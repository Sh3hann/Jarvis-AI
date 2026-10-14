"""
Voice Activity Detection (VAD) and speech classification for JARVIS.

Distinguishes human speech/voice from ambient room sounds, typing, mouse
clicks, fans, air conditioning, thumps, and background noise.

Architecture:
  1. Primary: Silero Neural VAD via openwakeword or onnxruntime.
     Trained on tens of thousands of hours of speech and noise to output a
     calibrated probability of human speech in real-time (<0.5ms per block).
  2. Secondary: Acoustic formant, spectral distribution, and zero-crossing
     rate (ZCR) analysis as a robust zero-dependency fallback.
"""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Optional

import numpy as np


class VoiceDetector:
    """Detects whether an audio block is genuine human voice vs other sounds."""

    def __init__(self, min_speech_level: float = 0.0013, speech_threshold: float = 0.20):
        self.min_speech_level = min_speech_level
        self.speech_threshold = speech_threshold
        self._lock = threading.Lock()
        self._vad = None
        self._session = None
        self._last_prob = 0.0
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize Silero VAD backend (via openwakeword.vad or direct onnxruntime)."""
        # Strategy 1: openwakeword.vad.VAD
        try:
            from openwakeword.vad import VAD
            self._vad = VAD()
            return
        except Exception:
            pass

        # Strategy 2: Direct ONNX Runtime session with silero_vad.onnx
        try:
            import onnxruntime as ort
            vad_path = self._find_model_path()
            if vad_path and os.path.isfile(vad_path):
                opts = ort.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 1
                self._session = ort.InferenceSession(str(vad_path), sess_options=opts)
                self._h = np.zeros((2, 1, 64), dtype=np.float32)
                self._c = np.zeros((2, 1, 64), dtype=np.float32)
                self._sr = np.array(16000, dtype=np.int64)
        except Exception:
            self._session = None

    def _find_model_path(self) -> Optional[str]:
        """Look for silero_vad.onnx in known locations."""
        try:
            import openwakeword
            p = Path(openwakeword.__file__).resolve().parent / "resources" / "models" / "silero_vad.onnx"
            if p.is_file():
                return str(p)
        except Exception:
            pass

        local_path = Path(__file__).resolve().parent / "silero_vad.onnx"
        if local_path.is_file():
            return str(local_path)

        return None

    def reset(self) -> None:
        """Reset internal recurrent neural network states."""
        with self._lock:
            self._last_prob = 0.0
            if self._vad is not None:
                try:
                    self._vad.reset_states()
                except Exception:
                    pass
            elif self._session is not None and hasattr(self, "_h"):
                self._h.fill(0)
                self._c.fill(0)

    @property
    def last_probability(self) -> float:
        """Last predicted voice probability [0.0, 1.0]."""
        return self._last_prob

    def is_voice(self, pcm, sr: int = 16000, lvl: float = 0.0) -> bool:
        """
        True if the audio block contains human voice/speech.
        Returns False for room noise, typing, clicks, fans, or silence.
        """
        # Quick level check: intentional speech directed at the mic sits well
        # above the ambient baseline.
        if lvl < self.min_speech_level:
            self._last_prob = 0.0
            return False

        samples = np.asarray(pcm).flatten()
        if samples.size == 0:
            self._last_prob = 0.0
            return False

        # Ensure int16 for VAD models
        if samples.dtype.kind == "f":
            samples_i16 = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        else:
            samples_i16 = samples.astype(np.int16)

        with self._lock:
            # ── Strategy 1: openwakeword.vad ─────────────────────────────────
            if self._vad is not None:
                try:
                    pad_len = (512 - (len(samples_i16) % 512)) % 512
                    if pad_len > 0:
                        inp = np.pad(samples_i16, (0, pad_len))
                    else:
                        inp = samples_i16
                    score = float(self._vad.predict(inp, frame_size=512))
                    self._last_prob = score
                    if score >= self.speech_threshold:
                        return True
                    if score < 0.10:
                        return False
                except Exception:
                    pass

            # ── Strategy 2: Direct ONNX Silero ───────────────────────────────
            elif self._session is not None:
                try:
                    audio_f32 = samples_i16.astype(np.float32) / 32768.0
                    probs = []
                    for i in range(0, len(audio_f32), 512):
                        chunk = audio_f32[i : i + 512]
                        if len(chunk) < 512:
                            chunk = np.pad(chunk, (0, 512 - len(chunk)))
                        out, self._h, self._c = self._session.run(
                            None,
                            {
                                "input": chunk.reshape(1, -1),
                                "sr": self._sr,
                                "h": self._h,
                                "c": self._c,
                            },
                        )
                        probs.append(float(out[0][0]))
                    score = max(probs) if probs else 0.0
                    self._last_prob = score
                    if score >= self.speech_threshold:
                        return True
                    if score < 0.10:
                        return False
                except Exception:
                    pass

        # ── Strategy 3 / Borderline Acoustic Verification ────────────────────
        return self._acoustic_check(samples_i16, sr)

    def _acoustic_check(self, samples_i16: np.ndarray, sr: int) -> bool:
        """
        Frequency and waveform shape verification.
        Speech concentrates energy in formant bands (85-3400 Hz) with modest ZCR.
        Clicks, keyboard clatter, paper rustle, and fans have high ZCR and HF energy.
        """
        try:
            s_float = samples_i16.astype(np.float32)

            # 1. Zero crossing rate
            zcr = float(np.sum(np.abs(np.diff(np.signbit(s_float))))) / len(s_float)
            if zcr > 0.22:
                # High ZCR is typical of clicks, taps, hiss, or white noise
                return False

            # 2. Spectral energy distribution
            fft = np.abs(np.fft.rfft(s_float))
            freqs = np.fft.rfftfreq(len(s_float), d=1.0 / sr)
            tot_energy = float(np.sum(fft ** 2))
            if tot_energy < 1e-6:
                return False

            # High-frequency ratio (above 4000 Hz)
            hf_mask = freqs >= 4000
            hf_ratio = float(np.sum(fft[hf_mask] ** 2)) / tot_energy
            if hf_ratio > 0.30:
                # Too much high-frequency energy (keys, clatter, clicks)
                return False

            # Speech core band (50 Hz to 3400 Hz, supporting deep lower-Hz voices)
            voice_mask = (freqs >= 50) & (freqs <= 3400)
            voice_ratio = float(np.sum(fft[voice_mask] ** 2)) / tot_energy

            return voice_ratio >= 0.60
        except Exception:
            return False
