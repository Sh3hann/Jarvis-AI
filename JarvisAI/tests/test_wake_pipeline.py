import unittest
from unittest.mock import MagicMock
import numpy as np
import main
from core.wake_word import WakeWordDetector, DEFAULT_THRESHOLD
from core.word_interrupt import WordInterruptDetector


class TestWakePipeline(unittest.TestCase):
    def test_wake_word_threshold(self):
        self.assertEqual(DEFAULT_THRESHOLD, 0.03)

    def test_openwakeword_detection_flow(self):
        detected = []
        det = WakeWordDetector(
            on_detect=lambda: detected.append(True),
            threshold=0.06,
        )
        self.assertEqual(det._threshold, 0.06)

    def test_main_wake_from_word_interrupt(self):
        live = main.JarvisLive.__new__(main.JarvisLive)
        live.ui = MagicMock()
        live.session = MagicMock()
        live._loop = None
        live._speaking_lock = MagicMock()
        live._is_speaking = False
        live._assistant_turn_pending = False
        live._briefing_active = False
        live._awake = False
        live._last_spoken_language = "English"

        wake_calls = []
        def mock_wake(reason="wake word", announce=False):
            live._awake = True
            wake_calls.append((reason, announce))

        live.wake = mock_wake

        # Test English wake word: "wake up"
        live._on_word_interrupt_detected("wake up", [])
        self.assertTrue(live._awake)
        self.assertEqual(len(wake_calls), 1)
        self.assertIn("wake word (wake up)", wake_calls[0][0])
        self.assertEqual(live._last_spoken_language, "English")

        # Test Sinhala wake word: "ඇහැරෙන්න"
        live._awake = False
        wake_calls.clear()
        live._on_word_interrupt_detected("ඇහැරෙන්න", [])
        self.assertTrue(live._awake)
        self.assertEqual(len(wake_calls), 1)
        self.assertIn("wake word (ඇහැරෙන්න)", wake_calls[0][0])
        self.assertEqual(live._last_spoken_language, "Sinhala")

    def test_word_interrupt_audio_accumulation(self):
        detected = []
        detector = WordInterruptDetector(
            on_detect=lambda word, replay: detected.append(word)
        )
        detector._running = True

        # Feed 5 frames of speech (each frame 1024 samples)
        frame = np.ones(1024, dtype=np.int16) * 500
        for _ in range(5):
            detector.feed(frame, is_voice=True, lvl=0.02)

        # Confirm buffer was NOT prematurely cleared at 300ms
        self.assertGreaterEqual(len(detector._voice_buffer), 5)

        # Feed 3 frames of silence -> triggers dispatch
        silence_frame = np.zeros(1024, dtype=np.int16)
        for _ in range(3):
            detector.feed(silence_frame, is_voice=False, lvl=0.0)

        # Candidate clip should now be queued for recognition
        self.assertFalse(detector._queue.empty())
        item = detector._queue.get()
        clip, replay = item
        self.assertEqual(len(clip), 1024 * 5)


if __name__ == "__main__":
    unittest.main()
