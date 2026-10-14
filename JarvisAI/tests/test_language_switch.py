import unittest
from unittest.mock import MagicMock
import main


class TestLanguageSwitch(unittest.TestCase):
    def setUp(self):
        self.live = main.JarvisLive.__new__(main.JarvisLive)
        self.live.ui = MagicMock()
        self.live.session = MagicMock()
        self.live._loop = MagicMock()
        self.live._last_spoken_language = "English"

    def test_default_is_english(self):
        lang = self.live._load_last_spoken_language()
        self.assertEqual(lang, "English")

    def test_dynamic_switching(self):
        cases = [
            ("Hello Jarvis, how are you today?", "English"),
            ("කොහොමද ජාවිස්?", "Sinhala"),
            ("What is the weather in Colombo?", "English"),
            ("kohomada oyata?", "Sinhala"),
            ("ok", "Sinhala"),  # neutral confirmation, stays Sinhala
            ("Can you turn off the lights?", "English"),
            ("ok", "English"),  # neutral confirmation, stays English
            ("mata sinduwak danna puluwanda?", "Sinhala"),
            ("yes", "Sinhala"),
            ("speak in english now", "English"),
            ("sinhala walin katha karanna", "Sinhala"),
            ("switch to english please", "English"),
            ("ඇහැරෙන්න ජාවිස්", "Sinhala"),
            ("goodbye Jarvis", "English"),
        ]

        for text, expected in cases:
            with self.subTest(text=text, expected=expected):
                self.live._remember_spoken_language(text)
                self.assertEqual(self.live._last_spoken_language, expected)

    def test_on_text_command_routing(self):
        import threading
        self.live._awake = True
        self.live._voice_id_audio_lock = threading.Lock()
        self.live._voice_id_audio_chunks = []
        self.live._last_spoken_language = "English"

        sent_turns = []

        def mock_send(coro, loop):
            # Extract the turn text from the coroutine args
            # The coroutine is self.session.send_client_content(turns=..., turn_complete=True)
            pass

        self.live.session.send_client_content = MagicMock()
        import asyncio
        original_run_coroutine = asyncio.run_coroutine_threadsafe

        def fake_run_coroutine(coro, loop):
            # Close the coroutine to prevent warning
            coro.close()
            return MagicMock()

        asyncio.run_coroutine_threadsafe = fake_run_coroutine
        try:
            # 1. Type English command while default is English
            self.live._on_text_command("What time is it right now?")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "What time is it right now?")
            self.assertEqual(self.live._last_spoken_language, "English")

            # 2. Type Singlish command -> should switch to Sinhala and prepend prefix
            self.live._on_text_command("kohomada oyata?")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertIn("[Reply in fluent Sinhala / සිංහලෙන් පිළිතුරු දෙන්න]: kohomada oyata?", turn)
            self.assertEqual(self.live._last_spoken_language, "Sinhala")

            # 3. Type Sinhala script -> native Sinhala text without prefix
            self.live._on_text_command("අද කාලගුණය කොහොමද?")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "අද කාලගුණය කොහොමද?")
            self.assertEqual(self.live._last_spoken_language, "Sinhala")

            # 4. Type English command -> should switch BACK to English and NOT have Sinhala prefix!
            self.live._on_text_command("Who is the president of Sri Lanka?")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "Who is the president of Sri Lanka?")
            self.assertEqual(self.live._last_spoken_language, "English")

            # 5. Type translation to English containing Sinhala text -> target is English, no Sinhala prefix!
            self.live._on_text_command("Translate this text to English: කොහොමද ඔයාට")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "Translate this text to English: කොහොමද ඔයාට")
            self.assertEqual(self.live._last_spoken_language, "English")

            # 6. Type translation from English to Sinhala -> no Sinhala prefix prepended to command!
            self.live._on_text_command("Translate 'Good morning' to Sinhala")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "Translate 'Good morning' to Sinhala")
            self.assertEqual(self.live._last_spoken_language, "English")

            # 7. Type explanation request -> stays English and no prefix
            self.live._on_text_command("Explain how quantum computing works")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "Explain how quantum computing works")
            self.assertEqual(self.live._last_spoken_language, "English")

            # 8. Type meaning request -> stays English and no prefix
            self.live._on_text_command("What is the meaning of ephemeral?")
            call_args = self.live.session.send_client_content.call_args
            turn = call_args[1]["turns"]["parts"][0]["text"]
            self.assertEqual(turn, "What is the meaning of ephemeral?")
            self.assertEqual(self.live._last_spoken_language, "English")
        finally:
            asyncio.run_coroutine_threadsafe = original_run_coroutine


if __name__ == "__main__":
    unittest.main()

