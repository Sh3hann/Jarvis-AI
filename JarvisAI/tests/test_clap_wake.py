import unittest
import numpy as np
import time
from core.clap_wake import DoubleClapDetector


class TestDoubleClapDetector(unittest.TestCase):
    def test_double_clap_detection(self):
        detected = []
        detector = DoubleClapDetector(on_detect=lambda: detected.append(True), logger=lambda _: None)
        self.assertTrue(detector.start())

        def make_clap():
            t = np.linspace(0, 0.05, int(16000 * 0.05), endpoint=False)
            noise = np.random.uniform(-1, 1, len(t))
            clap = (noise * np.exp(-t / 0.02) * 12000).astype(np.int16)
            return clap

        silence = np.zeros(1024, dtype=np.int16)
        # Establish noise floor
        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        # Clap 1
        f1 = np.zeros(1024, dtype=np.int16)
        c = make_clap()
        f1[:len(c)] = c
        detector.feed(f1)
        time.sleep(0.02)

        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        # Gap (~300ms)
        time.sleep(0.3)

        # Clap 2
        f2 = np.zeros(1024, dtype=np.int16)
        f2[:len(c)] = c
        detector.feed(f2)
        time.sleep(0.02)

        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        time.sleep(0.2)
        detector.stop()

        self.assertEqual(len(detected), 1, "Double clap should be detected once")

    def test_moderate_room_clap_detection(self):
        detected = []
        detector = DoubleClapDetector(on_detect=lambda: detected.append(True), logger=lambda _: None)
        self.assertTrue(detector.start())

        def make_moderate_clap():
            t = np.linspace(0, 0.05, int(16000 * 0.05), endpoint=False)
            noise = np.random.uniform(-1, 1, len(t))
            return (noise * np.exp(-t / 0.02) * 4500).astype(np.int16)

        silence = np.zeros(1024, dtype=np.int16)
        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        f1 = np.zeros(1024, dtype=np.int16)
        c = make_moderate_clap()
        f1[:len(c)] = c
        detector.feed(f1)
        time.sleep(0.02)

        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        time.sleep(0.4)

        f2 = np.zeros(1024, dtype=np.int16)
        c2 = make_moderate_clap()
        f2[:len(c2)] = c2
        detector.feed(f2)
        time.sleep(0.02)

        for _ in range(5):
            detector.feed(silence)
            time.sleep(0.01)

        time.sleep(0.2)
        detector.stop()

        self.assertEqual(len(detected), 1, "Moderate double clap in room should be detected")

    def test_sustained_sound_rejected(self):
        detected = []
        detector = DoubleClapDetector(on_detect=lambda: detected.append(True), logger=lambda _: None)
        detector.start()

        silence = np.zeros(1024, dtype=np.int16)
        for _ in range(3):
            detector.feed(silence)
            time.sleep(0.01)

        # Sustained tone (speech/music simulation)
        t = np.linspace(0, 0.25, int(16000 * 0.25), endpoint=False)
        tone = (np.sin(2 * np.pi * 300 * t) * 8000).astype(np.int16)
        for i in range(0, len(tone), 1024):
            buf = np.zeros(1024, dtype=np.int16)
            chunk = tone[i:i + 1024]
            buf[:len(chunk)] = chunk
            detector.feed(buf)
            time.sleep(0.01)

    def test_speech_syllables_rejected(self):
        detected = []
        detector = DoubleClapDetector(on_detect=lambda: detected.append(True), logger=lambda _: None)
        detector.start()

        silence = np.zeros(1024, dtype=np.int16)
        for _ in range(3):
            detector.feed(silence)
            time.sleep(0.01)

        # Multi-syllable speech simulation ("hello jarvis")
        sr = 16000
        def make_syllable(duration=0.08, amp=5000, freq=500):
            t = np.linspace(0, duration, int(sr * duration), endpoint=False)
            noise = np.random.uniform(-1, 1, len(t)) * np.exp(-t / 0.03)
            tone = np.sin(2 * np.pi * freq * t) * (1 - np.exp(-t / 0.01)) * np.exp(-t / 0.05)
            return ((noise * 0.7 + tone * 0.3) * amp).astype(np.int16)

        s1 = make_syllable(0.06, amp=5000, freq=500)
        f1 = np.zeros(1024, dtype=np.int16)
        f1[:len(s1)] = s1
        detector.feed(f1)
        time.sleep(0.2)

        s2 = make_syllable(0.06, amp=5000, freq=400)
        f2 = np.zeros(1024, dtype=np.int16)
        f2[:len(s2)] = s2
        detector.feed(f2)
        time.sleep(0.2)

        detector.stop()
        self.assertEqual(len(detected), 0, "Speech syllables must not trigger clap wake")

    def test_clicks_and_typing_rejected(self):
        detected = []
        detector = DoubleClapDetector(on_detect=lambda: detected.append(True), logger=lambda _: None)
        detector.start()

        silence = np.zeros(1024, dtype=np.int16)
        for _ in range(3):
            detector.feed(silence)
            time.sleep(0.01)

        # Keyboard / mouse clicks simulation (< 4000 amp)
        sr = 16000
        t = np.linspace(0, 0.015, int(sr * 0.015), endpoint=False)
        click = (np.random.uniform(-1, 1, len(t)) * np.exp(-t / 0.003) * 3000).astype(np.int16)

        f1 = np.zeros(1024, dtype=np.int16)
        f1[:len(click)] = click
        detector.feed(f1)
        time.sleep(0.25)

        f2 = np.zeros(1024, dtype=np.int16)
        f2[:len(click)] = click
        detector.feed(f2)
        time.sleep(0.2)

        detector.stop()
        self.assertEqual(len(detected), 0, "Typing / mouse clicks must not trigger clap wake")


if __name__ == "__main__":
    unittest.main()

