"""
Keyword-based interruption detector for JARVIS during speech.

Listens specifically for interruption words:
  - "hey jarvis", "jarvis"
  - "no", "wait", "stop", "cancel", "hold on", "quiet", "pause"

Runs faster-whisper-tiny in a dedicated background worker to ensure:
  - Zero latency on the real-time audio thread
  - No false triggers from ambient room noises, typing, or speaker echo
  - Immediate interruption and handoff to LISTENING when a target word is heard.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from typing import Callable, Optional

import numpy as np

INTERRUPT_KEYWORDS = (
    # English wake keywords
    "hey jarvis",
    "jarvis",
    "javis",
    "hello jarvis",
    "hi jarvis",
    "ok jarvis",
    "okay jarvis",
    "wake up",
    "wake up jarvis",
    "wake jarvis",
    "wake",
    "wake up please",
    "computer",
    "assistant",
    # English natural interrupt & stop keywords
    "stop",
    "stop talking",
    "stop it",
    "stop please",
    "please stop",
    "wait",
    "wait a second",
    "wait a minute",
    "wait wait",
    "just a second",
    "just a minute",
    "hold on",
    "hold on a second",
    "hold on a minute",
    "hold up",
    "hang on",
    "hang on a second",
    "hang on a minute",
    "excuse me",
    "no",
    "cancel",
    "quiet",
    "be quiet",
    "pause",
    "listen",
    "shut up",
    "shut it",
    "silence",
    "shush",
    "shh",
    "hush",
    "enough",
    "never mind",
    "cut it",
    "halt",
    # Sinhala wake keywords
    "ජාවිස්",
    "හේයි ජාවිස්",
    "ඇහැරෙන්න",
    "නැගිටින්න",
    "නැගිටින්න ජාවිස්",
    # Sinhala interrupt / stop keywords
    "නවත්වන්න",
    "නවත්තන්න",
    "ඉන්න",
    "පොඩ්ඩක් ඉන්න",
    "චුට්ටක් ඉන්න",
    "එපා",
    "කට වහගන්න",
    "කට වහන්න",
    "සද්ද නැතුව ඉන්න",
    "ඇති",
    # Singlish wake & stop
    "aharenna",
    "aherenna",
    "nagitinna",
    "nawaththanna",
    "poddak inna",
    "chuttak inna",
    "inna",
    "epa",
    "athi",
)


class WordInterruptDetector:
    """Detects spoken interrupt keywords ('hey jarvis', 'jarvis', 'no', 'wait', 'stop', etc.) during speech."""

    def __init__(
        self,
        on_detect: Callable[[str, list[bytes]], None],
        logger: Callable[[str], None] = print,
    ):
        self._on_detect = on_detect
        self._logger = logger
        self._queue: queue.Queue = queue.Queue(maxsize=4)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._model = None
        self._lock = threading.Lock()

        # Audio accumulation for voice segment
        self._voice_buffer: list[np.ndarray] = []
        self._voice_bytes: list[bytes] = []
        self._consecutive_silence = 0
        self._max_samples = 16000 * 2  # Max 2 seconds of voice

    def start(self) -> bool:
        """Spawn the background inference worker."""
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="WordInterruptThread"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop worker thread and free model."""
        self._running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self._model = None

    def reset(self) -> None:
        """Clear voice accumulation buffer."""
        with self._lock:
            self._voice_buffer.clear()
            self._voice_bytes.clear()
            self._consecutive_silence = 0

    def feed(self, frame_int16: np.ndarray, is_voice: bool, lvl: float = 0.0) -> None:
        """
        Feed an audio frame from the mic callback while JARVIS is speaking or asleep.
        Non-blocking: accumulates voice frames and queues candidate clips for transcription.
        """
        if not self._running:
            return

        with self._lock:
            frame_flat = (
                frame_int16[:, 0].copy()
                if getattr(frame_int16, "ndim", 1) > 1
                else frame_int16.copy()
            )

            # Accept confirmed human voice above the speech noise floor
            has_voice = bool(is_voice and lvl >= 0.012)

            if has_voice:
                self._consecutive_silence = 0
                self._voice_buffer.append(frame_flat)
                self._voice_bytes.append(frame_flat.tobytes())

                total_samples = sum(len(x) for x in self._voice_buffer)
                # Dispatch if continuous speech reaches maximum window (1.5 seconds)
                if total_samples >= 16000 * 1.5:
                    self._dispatch_clip()
            else:
                if self._voice_buffer:
                    self._consecutive_silence += 1
                    # After 3 frames of silence (~192ms), the speaker has finished saying the phrase.
                    if self._consecutive_silence >= 3:
                        self._dispatch_clip()

    def _dispatch_clip(self) -> None:
        """Queue accumulated voice clip for Whisper recognition."""
        if not self._voice_buffer:
            return
        audio_clip = np.concatenate(self._voice_buffer)
        replay = list(self._voice_bytes)
        self._voice_buffer.clear()
        self._voice_bytes.clear()
        self._consecutive_silence = 0

        # Skip noise bursts shorter than 200ms
        if len(audio_clip) < 16000 * 0.20:
            return

        try:
            self._queue.put_nowait((audio_clip, replay))
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((audio_clip, replay))
            except queue.Full:
                pass

    def _load_model(self):
        """Lazy load faster-whisper-tiny with warm-up."""
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel

            self._logger("Word interrupt: loading lightweight model…")
            self._model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=4)
            # Warm up kernels so the first real transcription has zero initialization delay
            try:
                silence_warmup = np.zeros(1600, dtype=np.float32)
                list(self._model.transcribe(silence_warmup, beam_size=1)[0])
            except Exception:
                pass
            self._logger("Word interrupt: ready.")
        except Exception as e:
            self._logger(f"Word interrupt: could not load model — {e}")
            self._model = None
        return self._model

    def _worker_loop(self) -> None:
        """Background transcription loop."""
        model = self._load_model()
        while self._running:
            try:
                item = self._queue.get()
                if item is None or not self._running:
                    break

                audio_clip, replay = item
                if model is None:
                    model = self._load_model()
                    if model is None:
                        continue

                # Convert int16 array to float32 normalized in [-1, 1]
                audio_f32 = audio_clip.astype(np.float32) / 32768.0
                max_val = float(np.max(np.abs(audio_f32))) if audio_f32.size > 0 else 0.0
                if max_val > 0.005:
                    # Normalize amplitude so quiet speech is clearly recognized
                    audio_f32 = audio_f32 * (0.7 / max(max_val, 0.05))

                t0 = time.monotonic()
                segments, _ = model.transcribe(
                    audio_f32,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    language=None,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    vad_filter=False,
                )
                text = " ".join(s.text for s in segments).strip()
                matched = self._match_keyword(text)

                if matched:
                    self._logger(
                        f"Word interrupt: '{matched}' detected in '{text}' ({round(time.monotonic() - t0, 2)}s)."
                    )
                    # Clear pending queue so we don't double fire
                    while not self._queue.empty():
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    try:
                        self._on_detect(matched, replay)
                    except Exception as exc:
                        self._logger(f"Word interrupt callback error: {exc}")
            except Exception as e:
                self._logger(f"Word interrupt error: {e}")

    @staticmethod
    def _match_keyword(text: str) -> Optional[str]:
        """Check if recognized text contains any interrupt keyword."""
        if not text:
            return None
        # Preserve alphanumeric and Sinhala characters (\u0D80-\u0DFF)
        clean = re.sub(r"[^\w\s\u0D80-\u0DFF]", " ", text, flags=re.UNICODE).lower()
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean:
            return None
        # Match longest phrases first ("wait a second" before "wait")
        sorted_kws = sorted(INTERRUPT_KEYWORDS, key=len, reverse=True)
        for kw in sorted_kws:
            if re.search(r"^[a-zA-Z0-9\s]+$", kw):
                pattern = rf"\b{re.escape(kw)}\b"
                if re.search(pattern, clean):
                    return kw
            else:
                # Sinhala keyword matching
                pattern = rf"(?:^|\s){re.escape(kw)}(?:$|\s)"
                if re.search(pattern, clean) or kw in text:
                    return kw
        return None
