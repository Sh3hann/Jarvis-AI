import unittest
from core.word_interrupt import WordInterruptDetector, INTERRUPT_KEYWORDS


class TestWordInterrupt(unittest.TestCase):
    def test_keywords_presence(self):
        expected = ["hey jarvis", "jarvis", "no", "wait", "stop", "cancel", "hold on", "quiet", "pause"]
        for kw in expected:
            self.assertIn(kw, INTERRUPT_KEYWORDS)

    def test_match_keyword_positive(self):
        cases = [
            ("hey jarvis", "hey jarvis"),
            ("Hey Jarvis!", "hey jarvis"),
            ("Jarvis", "jarvis"),
            ("no", "no"),
            ("No, wait!", "no"),
            ("wait please", "wait"),
            ("stop talking", "stop"),
            ("cancel that", "cancel"),
            ("hold on a second", "hold on"),
            ("be quiet", "quiet"),
            ("pause", "pause"),
            ("silence please", "silence"),
            ("hold up", "hold up"),
            ("shush", "shush"),
            ("enough!", "enough"),
            ("hello jarvis", "hello jarvis"),
            ("hi jarvis", "hi jarvis"),
            ("wake up", "wake up"),
            ("Wake up!", "wake up"),
            ("wake up jarvis", "wake up jarvis"),
            ("wake", "wake"),
            ("ජාවිස්", "ජාවිස්"),
            ("හේයි ජාවිස්", "හේයි ජාවිස්"),
            ("ඇහැරෙන්න", "ඇහැරෙන්න"),
            ("නැගිටින්න", "නැගිටින්න"),
            ("aharenna", "aharenna"),
            ("නවත්වන්න", "නවත්වන්න"),
            ("නවත්තන්න", "නවත්තන්න"),
            ("ඉන්න", "ඉන්න"),
            ("එපා", "එපා"),
            ("wait a second", "wait a second"),
            ("wait a minute please", "wait a minute"),
            ("just a second", "just a second"),
            ("hang on", "hang on"),
            ("excuse me", "excuse me"),
            ("poddak inna", "poddak inna"),
            ("චුට්ටක් ඉන්න", "චුට්ටක් ඉන්න"),
            ("ඇති", "ඇති"),
            ("shh", "shh"),
        ]
        for text, expected in cases:
            res = WordInterruptDetector._match_keyword(text)
            self.assertIsNotNone(res, f"Expected match for '{text}'")

    def test_match_keyword_negative(self):
        # Must not falsely match subwords or ordinary conversational phrases
        cases = [
            "knowledge is power",      # "no" in "knowledge"
            "nobody was there",         # "no" in "nobody"
            "notice the sign",          # "no" in "notice"
            "the weather is nice today",
            "what time is it",
            "play some jazz music",
        ]
        for text in cases:
            res = WordInterruptDetector._match_keyword(text)
            self.assertIsNone(res, f"Unexpected match for '{text}': got {res}")

    def test_detector_lifecycle(self):
        detected = []
        det = WordInterruptDetector(on_detect=lambda word, replay: detected.append(word))
        self.assertTrue(det.start())
        det.reset()
        det.stop()

    def test_noise_rejected_by_feed(self):
        import numpy as np
        det = WordInterruptDetector(on_detect=lambda word, replay: None)
        det._running = True
        frame = np.ones(1024, dtype=np.int16) * 1000

        # When is_voice is False, noise or speaker sound with lvl 0.05 is rejected
        det.feed(frame, is_voice=False, lvl=0.05)
        self.assertEqual(len(det._voice_buffer), 0)

        # When is_voice is True and lvl >= 0.012, voice is accumulated
        det.feed(frame, is_voice=True, lvl=0.03)
        self.assertEqual(len(det._voice_buffer), 1)


if __name__ == "__main__":
    unittest.main()
