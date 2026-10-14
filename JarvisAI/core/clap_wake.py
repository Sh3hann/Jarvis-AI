"""Local, lightweight two-clap detector used while JARVIS is asleep.

Audio stays on-device. The microphone callback only copies a short frame into
this detector's bounded queue; level analysis and wake callbacks run on its
own worker thread.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable


class DoubleClapDetector:
    """Detect two sharp sound transients separated by a human clap interval.

    A clap is an impulse: energy jumps abruptly from the background and dies
    away within ~100 ms. Speech, music and JARVIS's own voice through the
    speakers also have loud peaks, but their energy is sustained across
    syllables. Each candidate therefore has to pass two checks:
      * onset — the 16 ms window is several times louder than the one before;
      * decay — energy falls back below a fraction of the onset level within
        DECAY_WINDOWS windows. Sustained sound is rejected as "not a clap".
    """

    MIN_PEAK = 3500         # Int16 peak must exceed 3500 (~11% of full scale, reliably catches room claps)
    MIN_RMS = 400           # Int16 RMS must exceed 400 (well above room noise floor ~50-100)
    MIN_CREST = 2.0         # Peak-to-RMS ratio for sharp impulsive transient
    ONSET_RATIO = 2.4       # Energy jump over previous window
    DECAY_RATIO = 0.45      # Must decay below 45% of peak RMS (allows realistic room reverb)
    DECAY_MAX_WINDOWS = 6   # Must decay within 6 windows (~96 ms)
    POST_QUIET_WINDOWS = 2  # Must stay quiet for 2 windows (~32 ms)
    MIN_ZCR = 16            # Zero crossings per 256 samples (> 500 Hz broadband noise)
    MIN_GAP = 0.15          # Min 150 ms between claps (human physical limit)
    MAX_GAP = 1.2           # Max 1.2s between claps (allows natural human clapping cadence)
    COOLDOWN = 1.2          # Cooldown after double clap detection
    REFRACTORY = 0.14       # Refractory period after a clap or sustained sound rejection

    def __init__(self, on_detect: Callable[[], None], logger: Callable[[str], None] = print):
        self._on_detect = on_detect
        self._logger = logger
        self._queue: queue.Queue = queue.Queue(maxsize=40)
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_clap = 0.0
        self._cooldown_until = 0.0
        self._noise_rms = 100.0
        self._prev_win_rms = 0.0
        # Pending candidate state dictionary
        self._candidate: dict | None = None
        self._refractory_until = 0.0

    @property
    def ready(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="DoubleClapWakeThread"
        )
        self._thread.start()
        self._logger("Two-clap wake: listening locally while JARVIS sleeps.")
        return True

    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def feed(self, frame_int16) -> None:
        """Non-blocking audio callback interface; dropped frames are harmless."""
        if not self._running:
            return
        try:
            data = frame_int16[:, 0].copy() if getattr(frame_int16, "ndim", 1) > 1 else frame_int16.copy()
            self._queue.put_nowait(data)
        except (queue.Full, AttributeError, TypeError):
            pass
        except Exception:
            pass

    def _loop(self) -> None:
        import numpy as np

        window_size = 256
        sample_rate = 16000

        while self._running:
            try:
                frame = self._queue.get()
                if frame is None or not self._running:
                    break
                samples = np.asarray(frame, dtype=np.int16).astype(np.int32, copy=False)
                if samples.size == 0:
                    continue
                now = time.monotonic()

                # Invalidate stale single claps older than MAX_GAP
                if self._last_clap and (now - self._last_clap > self.MAX_GAP):
                    self._last_clap = 0.0

                # Process in 16 ms (256-sample) windows
                for offset in range(0, samples.size, window_size):
                    window = samples[offset:offset + window_size]
                    if window.size < window_size:
                        continue
                    win_time = now + (offset / sample_rate)
                    win_peak = int(np.max(np.abs(window)))
                    win_rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))

                    # Zero crossing count in 16 ms (claps have broadband high freq noise)
                    signs = np.sign(window)
                    signs[signs == 0] = 1
                    zcr = int(np.sum(signs[:-1] != signs[1:]))

                    # Track background noise smoothly
                    if win_rms < 1000 and self._candidate is None:
                        self._noise_rms = max(40.0, min(2000.0, self._noise_rms * 0.98 + win_rms * 0.02))

                    dynamic_peak = max(self.MIN_PEAK, self._noise_rms * 5.0)
                    dynamic_rms = max(self.MIN_RMS, self._noise_rms * 2.5)

                    # Check pending candidate decay and post-decay quietness
                    if self._candidate is not None:
                        c = self._candidate
                        c["windows_seen"] += 1

                        if not c["decayed"]:
                            # Look for clap peak within first 2 windows (~32 ms)
                            if c["windows_seen"] <= 2 and win_rms > c["peak_rms"]:
                                c["peak_rms"] = win_rms

                            if win_rms <= c["peak_rms"] * self.DECAY_RATIO:
                                c["decayed"] = True
                                c["quiet_windows"] = 0
                            elif c["windows_seen"] > self.DECAY_MAX_WINDOWS:
                                # Failed to decay rapidly -> sustained sound (speech/music)
                                self._candidate = None
                                self._refractory_until = win_time + self.REFRACTORY
                        else:
                            # Candidate decayed; verify it STAYS quiet!
                            c["quiet_windows"] += 1
                            if win_rms > c["peak_rms"] * (self.DECAY_RATIO * 1.3):
                                # Sound bounced back up (speech formant / vowel / phrase)! Reject!
                                self._candidate = None
                                self._refractory_until = win_time + self.REFRACTORY
                            elif c["quiet_windows"] >= self.POST_QUIET_WINDOWS:
                                # Confirmed single clap transient!
                                cand_time = c["time"]
                                self._candidate = None
                                self._refractory_until = win_time + self.REFRACTORY

                                if win_time >= self._cooldown_until:
                                    if self._last_clap:
                                        gap = cand_time - self._last_clap
                                        if self.MIN_GAP <= gap <= self.MAX_GAP:
                                            self._last_clap = 0.0
                                            self._cooldown_until = win_time + self.COOLDOWN
                                            self._logger("Two-clap wake: double clap detected!")
                                            try:
                                                self._on_detect()
                                            except Exception as exc:
                                                self._logger(f"Two-clap wake: callback failed — {exc}")
                                        elif gap > self.MAX_GAP:
                                            self._last_clap = cand_time
                                            self._logger("Two-clap wake: first clap detected; clap once more.")
                                    else:
                                        self._last_clap = cand_time
                                        self._logger("Two-clap wake: first clap detected; clap once more.")

                    # Look for new onset if not refractory or cooling down
                    if (win_time >= self._refractory_until
                            and win_time >= self._cooldown_until
                            and self._candidate is None):
                        crest = win_peak / max(win_rms, 1.0)
                        is_onset = (
                            win_peak >= dynamic_peak
                            and win_rms >= dynamic_rms
                            and crest >= self.MIN_CREST
                            and win_rms >= self.ONSET_RATIO * max(self._prev_win_rms, self._noise_rms, 60.0)
                            and zcr >= self.MIN_ZCR
                        )
                        if is_onset:
                            self._candidate = {
                                "time": win_time,
                                "peak_rms": win_rms,
                                "windows_seen": 1,
                                "decayed": False,
                                "quiet_windows": 0,
                            }

                    self._prev_win_rms = win_rms

            except Exception as exc:
                self._logger(f"Two-clap wake: detector error — {exc}")