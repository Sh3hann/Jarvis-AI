import unittest
import numpy as np

from core.voice_detector import VoiceDetector


class TestVoiceDetector(unittest.TestCase):
    def setUp(self):
        self.detector = VoiceDetector()

    def test_silence_below_speech_floor(self):
        silence = np.zeros(1024, dtype=np.int16)
        self.assertFalse(self.detector.is_voice(silence, lvl=0.05))

    def test_typing_clicks_rejected(self):
        clicks = np.zeros(1024, dtype=np.int16)
        clicks[::30] = 12000
        # Even if loud (lvl=0.25), clicks should be rejected by VAD & acoustics
        self.assertFalse(self.detector.is_voice(clicks, lvl=0.25))

    def test_fan_noise_rejected(self):
        np.random.seed(42)
        noise = (np.random.randn(1024) * 3500).astype(np.int16)
        self.assertFalse(self.detector.is_voice(noise, lvl=0.22))

    def test_low_rumble_rejected(self):
        t = np.linspace(0, 1024 / 16000, 1024)
        rumble = (np.sin(2 * np.pi * 45 * t) * 12000).astype(np.int16)
        self.assertFalse(self.detector.is_voice(rumble, lvl=0.30))

    def test_low_voice_level_gate(self):
        # Silence below 0.0012 is rejected immediately
        silence = np.zeros(1024, dtype=np.int16)
        self.assertFalse(self.detector.is_voice(silence, lvl=0.0010))

        # A low speech signal with lvl >= 0.0012 passes level gate to VAD/acoustics
        t = np.linspace(0, 1024 / 16000, 1024)
        # Formant frequencies typical of human voice (around 220Hz and 700Hz)
        voice_synth = ((np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 700 * t)) * 1000).astype(np.int16)
        # When lvl is 0.0013 (quiet voice), it should not be discarded by the min_speech_level gate
        self.assertGreaterEqual(0.0013, self.detector.min_speech_level)

    def test_reset_clears_state(self):
        self.detector.reset()
        self.assertEqual(self.detector.last_probability, 0.0)

    def test_sinhala_search_query_cleaning(self):
        from actions.web_search import _clean_search_query

        # Sinhala script with search command phrases stripped
        self.assertEqual(_clean_search_query("සිරි දළදා මාලිගාව ගැන search කරන්න"), "සිරි දළදා මාලිගාව")
        self.assertEqual(_clean_search_query("ශ්‍රී ලංකා කාලගුණය හොයන්න"), "ශ්‍රී ලංකා කාලගුණය")
        self.assertEqual(_clean_search_query("කොළඹ හෝටල් ගැන විස්තර හොයන්න"), "කොළඹ හෝටල් ගැන විස්තර")

        # Singlish phrases
        self.assertEqual(_clean_search_query("sigiriya gani hoyanna"), "sigiriya")
        self.assertEqual(_clean_search_query("google eke hoyanna roshan ranawana songs"), "roshan ranawana songs")
        self.assertEqual(_clean_search_query("mata hoyala denna python tutorials"), "python tutorials")

        # Pure Sinhala phrase preserved intact
        self.assertEqual(_clean_search_query("සිංහල නවකතා"), "සිංහල නවකතා")

    def test_spotify_play_dispatch(self):
        from actions.spotify_control import spotify_control
        res = spotify_control({"action": "play", "query": "Starboy"})
        self.assertIn("Starboy", res)

    def test_netflix_control_dispatch(self):
        from actions.netflix_control import netflix_control
        res = netflix_control({"action": "play", "query": "mandhadi"})
        self.assertIn("mandhadi", res.lower())
        self.assertIn("netflix", res.lower())

    def test_spotify_redirects_netflix(self):
        from actions.spotify_control import spotify_control
        res = spotify_control({"action": "play", "query": "mandhadi on netflix"})
        self.assertIn("netflix", res.lower())
        self.assertNotIn("spotify", res.lower())

    def test_open_app_antigravity_ide_normalization(self):
        from actions.open_app import _normalize
        norm_ide = _normalize("Antigravity IDE")
        self.assertIn("Antigravity", norm_ide)
        norm_simple = _normalize("antigravity")
        self.assertIn("Antigravity", norm_simple)

    def test_open_app_steam_library_normalization(self):
        from actions.open_app import _normalize
        norm_lib = _normalize("steam library")
        self.assertIn("steam://open/games", norm_lib)
        norm_phrase = _normalize("open steam and go to the library")
        self.assertIn("steam://open/games", norm_phrase)
        norm_games = _normalize("steam games")
        self.assertIn("steam://open/games", norm_games)

    def test_windows_settings_navigation(self):
        from unittest.mock import patch
        from actions.computer_settings import WINDOWS_SETTINGS_MAP, open_system_settings, computer_settings
        self.assertEqual(WINDOWS_SETTINGS_MAP["display"], "ms-settings:display")
        self.assertEqual(WINDOWS_SETTINGS_MAP["bluetooth"], "ms-settings:bluetooth")
        self.assertEqual(WINDOWS_SETTINGS_MAP["wifi"], "ms-settings:network-wifi")
        self.assertEqual(WINDOWS_SETTINGS_MAP["sound"], "ms-settings:sound")

        # Test settings dispatch without physically launching settings windows on desktop
        with patch("os.startfile", create=True) as mock_startfile, \
             patch("subprocess.Popen") as mock_popen:
            res = computer_settings({"action": "open_settings", "value": "display"})
            self.assertIn("display settings", res.lower())

            res_desc = computer_settings({"description": "go to bluetooth settings"})
            self.assertIn("bluetooth settings", res_desc.lower())
            self.assertTrue(mock_startfile.called or mock_popen.called)

    def test_reminder_12_am_parsing_and_rollover(self):
        from actions.reminder import _parse_time, _parse_date, reminder
        self.assertEqual(_parse_time("12 am"), (0, 0))
        self.assertEqual(_parse_time("12:00 am"), (0, 0))
        self.assertEqual(_parse_time("12 pm"), (12, 0))
        self.assertEqual(_parse_time("12:00 pm"), (12, 0))
        self.assertEqual(_parse_time("6:30 pm"), (18, 30))

        # Test setting a reminder for 12 am
        res = reminder({"time": "12 am", "message": "restart the laptop"})
        self.assertIn("reminder set for", res.lower())
        self.assertIn("12:00 am", res.lower())

    def test_spotify_protocol_and_close_app(self):
        from actions.open_app import _normalize
        import platform
        if platform.system() == "Windows":
            self.assertEqual(_normalize("spotify"), "spotify:")

        from actions.computer_settings import computer_settings
        res = computer_settings({"action": "close_app", "value": "spotify"})
        self.assertIn("closed", res.lower())

    def test_quick_settings_and_notification_bar(self):
        from actions.computer_settings import _detect_action, _IRREVERSIBLE, dnd_get_state

        # Voice intent detection for Notification Bar & Quick Settings
        self.assertEqual(_detect_action("turn off wifi")["action"], "wifi_off")
        self.assertEqual(_detect_action("turn on wifi")["action"], "wifi_on")
        self.assertEqual(_detect_action("turn off bluetooth")["action"], "bluetooth_off")
        self.assertEqual(_detect_action("turn on bluetooth")["action"], "bluetooth_on")
        self.assertIn(_detect_action("airplane mode on")["action"], ("airplane_mode_on", "flight_mode_on"))
        self.assertIn(_detect_action("flight mode off")["action"], ("airplane_mode_off", "flight_mode_off"))
        self.assertEqual(_detect_action("turn on dnd")["action"], "dnd_on")
        self.assertEqual(_detect_action("turn off dnd")["action"], "dnd_off")
        self.assertEqual(_detect_action("turn on focus")["action"], "focus_on")
        self.assertEqual(_detect_action("turn off focus")["action"], "focus_off")
        self.assertIn(_detect_action("stop focus")["action"], ("focus_off", "stop_focus"))
        self.assertEqual(_detect_action("turn on energy saver")["action"], "battery_saver_on")
        self.assertEqual(_detect_action("turn off battery saver")["action"], "battery_saver_off")
        self.assertIn(_detect_action("open quick settings")["action"], ("quick_settings", "open_quick_settings"))
        self.assertEqual(_detect_action("show notifications")["action"], "notifications")

        # Specific settings subpage vs radio toggles
        self.assertEqual(_detect_action("go to bluetooth settings"), {"action": "open_settings", "value": "bluetooth"})
        self.assertEqual(_detect_action("wifi settings"), {"action": "open_settings", "value": "wifi"})

        # Quick settings must execute immediately without confirmation modals
        self.assertNotIn("toggle_wifi", _IRREVERSIBLE)
        self.assertNotIn("wifi_on", _IRREVERSIBLE)
        self.assertNotIn("wifi_off", _IRREVERSIBLE)
        self.assertNotIn("bluetooth_on", _IRREVERSIBLE)
        self.assertNotIn("airplane_mode_on", _IRREVERSIBLE)
        self.assertNotIn("dnd_on", _IRREVERSIBLE)
        self.assertNotIn("battery_saver_on", _IRREVERSIBLE)

        # DND status read
        state = dnd_get_state()
        self.assertIsInstance(state, bool)

    def test_brightness_and_volume_control(self):
        from actions.computer_settings import (
            _detect_action, computer_settings, volume_get, brightness_get,
            volume_up, volume_down, brightness_up, brightness_down
        )

        # Voice detection for exact percentage
        self.assertEqual(_detect_action("set volume to 70%"), {"action": "volume_set", "value": 70})
        self.assertEqual(_detect_action("volume 45%"), {"action": "volume_set", "value": 45})
        self.assertEqual(_detect_action("set brightness to 80%"), {"action": "brightness_set", "value": 80})
        self.assertEqual(_detect_action("brightness 65%"), {"action": "brightness_set", "value": 65})

        # Voice detection for relative adjustments
        self.assertEqual(_detect_action("louder")["action"], "volume_up")
        self.assertEqual(_detect_action("turn up volume")["action"], "volume_up")
        self.assertEqual(_detect_action("quieter")["action"], "volume_down")
        self.assertEqual(_detect_action("turn down volume")["action"], "volume_down")
        self.assertEqual(_detect_action("brighter")["action"], "brightness_up")
        self.assertEqual(_detect_action("make screen brighter")["action"], "brightness_up")
        self.assertEqual(_detect_action("dimmer")["action"], "brightness_down")
        self.assertEqual(_detect_action("dim screen")["action"], "brightness_down")

        # Voice detection for mute / unmute
        self.assertEqual(_detect_action("mute")["action"], "mute")
        self.assertEqual(_detect_action("mute audio")["action"], "mute")
        self.assertEqual(_detect_action("unmute")["action"], "unmute")
        self.assertEqual(_detect_action("unmute audio")["action"], "unmute")

        # Voice detection for status queries
        self.assertEqual(_detect_action("what is the volume")["action"], "get_volume")
        self.assertEqual(_detect_action("what is the brightness")["action"], "get_brightness")

        # Dispatch via computer_settings
        res_vol = computer_settings({"action": "get_volume"})
        self.assertIn("volume is", res_vol.lower())

        res_br = computer_settings({"action": "get_brightness"})
        self.assertIn("brightness is", res_br.lower())

        # Direct readings
        v = volume_get()
        if v is not None:
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

        # Self-Heal Fix Actions
        self.assertEqual(_detect_action("fix brightness")["action"], "fix_brightness")
        self.assertEqual(_detect_action("brightness bug")["action"], "fix_brightness")
        self.assertEqual(_detect_action("cant adjust brightness")["action"], "fix_brightness")
        self.assertEqual(_detect_action("fix volume")["action"], "fix_volume")
        self.assertEqual(_detect_action("sound not working")["action"], "fix_volume")

        # Test fix dispatch
        res_fix_br = computer_settings({"action": "fix_brightness"})
        self.assertIn("refreshed", res_fix_br.lower())

        res_fix_vol = computer_settings({"action": "fix_volume"})
        self.assertIn("refreshed", res_fix_vol.lower())

    def test_windows_11_all_apps_normalization_and_discovery(self):
        from actions.open_app import _normalize, _get_start_apps_cache, _get_installed_shortcuts, _get_registry_app_paths
        import platform

        if platform.system() == "Windows":
            # Pre-installed Windows 11 system apps
            self.assertIn("ZuneMusic", _normalize("media player"))
            self.assertEqual(_normalize("windows media player"), "wmplayer.exe")
            self.assertEqual(_normalize("photos"), "ms-photos:")
            self.assertEqual(_normalize("calculator"), "calc.exe")
            self.assertEqual(_normalize("calc"), "calc.exe")
            self.assertEqual(_normalize("notepad"), "notepad.exe")
            self.assertEqual(_normalize("paint"), "mspaint.exe")
            self.assertEqual(_normalize("camera"), "microsoft.windows.camera:")
            self.assertEqual(_normalize("snipping tool"), "ms-screenclip:")
            self.assertEqual(_normalize("clock"), "ms-clock:")
            self.assertEqual(_normalize("weather"), "bingweather:")
            self.assertEqual(_normalize("microsoft store"), "ms-windows-store:")
            self.assertEqual(_normalize("control panel"), "control.exe")
            self.assertEqual(_normalize("task manager"), "taskmgr.exe")

            # Dynamic Discovery engines
            shortcuts = _get_installed_shortcuts()
            self.assertIsInstance(shortcuts, dict)
            self.assertGreater(len(shortcuts), 0)

            reg_paths = _get_registry_app_paths()
            self.assertIsInstance(reg_paths, dict)
            self.assertGreater(len(reg_paths), 0)

            cache = _get_start_apps_cache()
            self.assertIsInstance(cache, dict)
            self.assertGreater(len(cache), 0)

    def test_window_management_actions_and_intents(self):
        from actions.computer_settings import _detect_action, computer_settings

        # Voice intent detection for minimize, maximize, restore, and close
        self.assertEqual(_detect_action("minimize media player")["action"], "minimize")
        self.assertEqual(_detect_action("minimize media player")["value"], "media player")
        self.assertEqual(_detect_action("minimize spotify")["action"], "minimize")
        self.assertEqual(_detect_action("minimize spotify")["value"], "spotify")
        self.assertEqual(_detect_action("minimize all")["action"], "minimize")
        self.assertEqual(_detect_action("minimize all")["value"], "all")
        self.assertEqual(_detect_action("minimize")["action"], "minimize")

        self.assertEqual(_detect_action("maximize media player")["action"], "maximize")
        self.assertEqual(_detect_action("maximize media player")["value"], "media player")
        self.assertEqual(_detect_action("maximize chrome")["action"], "maximize")
        self.assertEqual(_detect_action("maximize chrome")["value"], "chrome")
        self.assertEqual(_detect_action("maximize all")["action"], "maximize")
        self.assertEqual(_detect_action("maximize")["action"], "maximize")

        self.assertEqual(_detect_action("restore media player")["action"], "restore")
        self.assertEqual(_detect_action("restore media player")["value"], "media player")
        self.assertEqual(_detect_action("unminimize spotify")["action"], "restore")
        self.assertEqual(_detect_action("restore")["action"], "restore")

        self.assertEqual(_detect_action("close media player")["action"], "close_app")
        self.assertEqual(_detect_action("close media player")["value"], "media player")
        self.assertEqual(_detect_action("close all")["action"], "close_app")
        self.assertEqual(_detect_action("close all")["value"], "all")

        # Dispatch via computer_settings
        res_min = computer_settings({"action": "minimize", "value": "media player"})
        self.assertIn("minimized", res_min.lower())

        res_max = computer_settings({"action": "maximize", "value": "media player"})
        self.assertIn("maximized", res_max.lower())

        res_res = computer_settings({"action": "restore", "value": "media player"})
        self.assertIn("restored", res_res.lower())

        res_close = computer_settings({"action": "close_app", "value": "media player"})
        self.assertIn("closed", res_close.lower())


if __name__ == "__main__":
    unittest.main()



