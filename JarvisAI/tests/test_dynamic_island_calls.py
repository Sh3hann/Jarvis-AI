import sys
import unittest
from PyQt6.QtWidgets import QApplication

class TestDynamicIslandCallsAndTimestamps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_whatsapp_call_and_message_accuracy(self):
        from core.dynamic_island import DynamicIslandOverlay
        island = DynamicIslandOverlay()

        # Test Case 1: WhatsApp Voice Call with 'from'
        island._on_incoming_windows_notification(
            "WhatsApp", "Incoming voice call from Dedaa ❤️", "", "#22c55e", msg_time="7:12 PM"
        )
        self.assertEqual(island._notif_title.text(), "Dedaa ❤️")
        self.assertEqual(island._notif_time.text(), "7:12 PM")
        self.assertIn("CALL", island._notif_badge.text())

        # Test Case 2: WhatsApp Video Call with 'from'
        island._on_incoming_windows_notification(
            "WhatsApp", "Incoming video call from John Doe", "", "#22c55e", msg_time="7:14 PM"
        )
        self.assertEqual(island._notif_title.text(), "John Doe")
        self.assertEqual(island._notif_time.text(), "7:14 PM")
        self.assertIn("VIDEO CALL", island._notif_badge.text())

        # Test Case 3: WhatsApp Voice Call with 2 elements (desc, name)
        island._on_incoming_windows_notification(
            "WhatsApp", "Incoming voice call", "Chamara Sir Swimming", "#22c55e", msg_time="7:15 PM"
        )
        self.assertEqual(island._notif_title.text(), "Chamara Sir Swimming")
        self.assertEqual(island._notif_time.text(), "7:15 PM")
        self.assertIn("CALL", island._notif_badge.text())

        # Test Case 4: WhatsApp Voice Call with 2 elements (name, desc)
        island._on_incoming_windows_notification(
            "WhatsApp", "Chamara Sir Swimming", "Incoming voice call", "#22c55e", msg_time="7:16 PM"
        )
        self.assertEqual(island._notif_title.text(), "Chamara Sir Swimming")
        self.assertEqual(island._notif_time.text(), "7:16 PM")
        self.assertIn("CALL", island._notif_badge.text())

        # Test Case 5: Normal WhatsApp message
        island._on_incoming_windows_notification(
            "WhatsApp", "CH SWIMMING SQUAD", "Chamara Sir: Practice tomorrow", "#22c55e", msg_time="7:18 PM"
        )
        self.assertEqual(island._notif_title.text(), "CH SWIMMING SQUAD")
        self.assertEqual(island._notif_time.text(), "7:18 PM")
        self.assertIn("WHATSAPP", island._notif_badge.text())

        island.close()

    def test_live_song_display_and_music_island(self):
        from core.dynamic_island import DynamicIslandOverlay
        island = DynamicIslandOverlay()

        # Initial state: media inactive, shows weather
        self.assertFalse(island._is_media_active)
        self.assertIn("°C", island._pill_weather_lbl.text())

        # Media update: live song playing
        data = {
            "active": True,
            "title": "Starboy",
            "artist": "The Weeknd",
            "album": "Starboy",
            "playing": True,
            "pos": 45.0,
            "end": 230.0,
            "thumb_bytes": b"",
        }
        island._on_live_media_update(data)

        self.assertTrue(island._is_media_active)
        self.assertTrue(island._is_playing)
        self.assertEqual(island._title_lbl.text(), "Starboy")
        self.assertEqual(island._artist_lbl.text(), "The Weeknd")
        # Pill bar now displays the live song!
        self.assertIn("Starboy", island._pill_weather_lbl.text())
        self.assertIn("🎵", island._pill_weather_lbl.text())
        self.assertFalse(island._compact_equalizer.isHidden())
        self.assertTrue(island._pill_trailing_lbl.isHidden())

        # When clicked or expanded, it automatically switches to Card 0 (Music Island)
        island.expand()
        self.assertEqual(island._card_stack.currentIndex(), 0)
        self.assertTrue(island._is_expanded)

        # Collapse back to pill bar
        island.collapse()
        self.assertFalse(island._is_expanded)

        # When transient notification ends, it restores the live song
        island._reset_bar_display()
        self.assertIn("Starboy", island._pill_weather_lbl.text())

        # When media stops
        stop_data = {
            "active": False,
            "title": "",
            "artist": "",
            "playing": False,
            "pos": 0.0,
            "end": 0.0,
            "thumb_bytes": b"",
        }
        island._on_live_media_update(stop_data)
        self.assertFalse(island._is_media_active)
        self.assertIn("°C", island._pill_weather_lbl.text())

        island.close()

    def test_copy_paste_loading_bar(self):
        from core.dynamic_island import DynamicIslandOverlay
        island = DynamicIslandOverlay()

        # Verify progress bar widget exists
        self.assertTrue(hasattr(island, "_pill_progress_bar"))
        self.assertIsNotNone(island._pill_progress_bar)

        # Trigger copy progress
        island.show_clipboard_progress("Sample text copied to clipboard", action="Copied")
        # Pill bar label should indicate copy action
        self.assertIn("Copied", island._pill_weather_lbl.text())
        self.assertFalse(island._pill_progress_bar.isHidden())

        # Trigger paste action
        island.show_paste("Sample pasted text")
        self.assertIn("Pasted", island._pill_weather_lbl.text())
        self.assertFalse(island._pill_progress_bar.isHidden())

        island.close()

    def test_new_song_small_bar_only_no_expanded_box(self):
        from core.dynamic_island import DynamicIslandOverlay
        island = DynamicIslandOverlay()

        # Start a brand new song
        data = {
            "active": True,
            "title": "Blinding Lights",
            "artist": "The Weeknd",
            "album": "After Hours",
            "playing": True,
            "pos": 10.0,
            "end": 200.0,
            "thumb_bytes": b"",
        }
        island._on_live_media_update(data)

        # Song name MUST appear on the small bar (compact pill)
        self.assertIn("Blinding Lights", island._pill_weather_lbl.text())
        self.assertIn("🎵", island._pill_weather_lbl.text())

        # But MUST NOT pop up the extended card box automatically!
        self.assertFalse(island._is_expanded)
        self.assertEqual(island.height(), island._COMPACT_H)

        island.close()

    def test_neural_immersive_overlay_theme_and_buttons(self):
        from ui import NeuralImmersiveOverlay
        overlay = NeuralImmersiveOverlay("", "J.A.R.V.I.S")

        # Verify Dynamic Island theme tokens
        self.assertEqual(overlay.styleSheet(), "QWidget#NeuralImmersiveOverlay { background-color: #000000; }")
        self.assertTrue(hasattr(overlay, "_top_frame"))
        self.assertTrue(hasattr(overlay, "_cmd_frame"))
        self.assertTrue(hasattr(overlay, "eq"))

        # Verify functional buttons
        clicked = {"mute": False, "interrupt": False, "wake": False, "style": False, "hand": False, "reset": False, "console": False}
        overlay.on_mute = lambda: clicked.__setitem__("mute", True)
        overlay.on_interrupt = lambda: clicked.__setitem__("interrupt", True)
        overlay.on_wake = lambda: clicked.__setitem__("wake", True)
        overlay.on_cycle_style = lambda: clicked.__setitem__("style", True)
        overlay.on_hand_control = lambda: clicked.__setitem__("hand", True)
        overlay.on_hand_reset = lambda: clicked.__setitem__("reset", True)
        overlay.on_console = lambda: clicked.__setitem__("console", True)

        overlay.mute_button.click()
        self.assertTrue(clicked["mute"])
        overlay.interrupt_button.click()
        self.assertTrue(clicked["interrupt"])
        overlay.wake_button.click()
        self.assertTrue(clicked["wake"])
        overlay.style_button.click()
        self.assertTrue(clicked["style"])
        overlay.hand_button.click()
        self.assertTrue(clicked["hand"])
        overlay.hand_reset_button.click()
        self.assertTrue(clicked["reset"])
        overlay.console_button.click()
        self.assertTrue(clicked["console"])

        # Test state change
        overlay.set_state("SPEAKING")
        self.assertEqual(overlay.state_label.text(), "SPEAKING")
        self.assertEqual(overlay.eq._mode, "jarvis")

        overlay.set_state("LISTENING")
        self.assertEqual(overlay.state_label.text(), "LISTENING")
        self.assertEqual(overlay.eq._mode, "user")

        overlay.close()

    def test_system_tray_and_taskbar_hiding(self):
        from ui import MainWindow, QSystemTrayIcon
        win = MainWindow("")

        # System tray icon exists and is initialized
        self.assertTrue(hasattr(win, "_tray_icon"))
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.assertIsNotNone(win._tray_icon)
            self.assertIn("JARVIS", win._tray_icon.toolTip())
            # Context menu actions
            menu = win._tray_icon.contextMenu()
            self.assertIsNotNone(menu)
            action_texts = [a.text() for a in menu.actions()]
            self.assertTrue(any("HUD" in t for t in action_texts))
            self.assertTrue(any("Console" in t for t in action_texts))
            self.assertTrue(any("Dynamic Island" in t for t in action_texts))
            self.assertTrue(any("Quit" in t for t in action_texts))

        # Test hide behavior (no taskbar presence)
        win._present_default_view()
        self.assertTrue(win.isHidden())

        # Cleanup
        win._force_quit = True
        win.close()

    def test_thread_safe_island_signals(self):
        from ui import MainWindow, JarvisUI
        ui = JarvisUI("")
        win = ui._win

        # Test show_message, show_call, show_media thread-safe methods
        ui.show_message("WhatsApp: Amma", "Hello, calling from worker")
        ui.show_call("Amma", call_type="Voice", app_name="WhatsApp")
        ui.show_media("Believer", "Imagine Dragons")

        # Dynamic island received and updated without crashes
        self.assertTrue(hasattr(win, "_island_message_sig"))
        self.assertTrue(hasattr(win, "_island_call_sig"))
        self.assertTrue(hasattr(win, "_island_media_sig"))

        win._force_quit = True
        win.close()

    def test_spotify_and_youtube_music_routing(self):
        from actions.spotify_control import spotify_control, GENERIC_MUSIC_TERMS
        from actions.youtube_video import _handle_play

        # 1. Verify generic play terms
        self.assertIn("this music", GENERIC_MUSIC_TERMS)
        self.assertIn("music", GENERIC_MUSIC_TERMS)
        self.assertIn("the music", GENERIC_MUSIC_TERMS)

        class MockPlayer:
            def __init__(self):
                self.media = None
                self.video_shown = False
            def show_media(self, title, artist=""):
                self.media = (title, artist)
            def show_video(self, source, title=""):
                self.video_shown = True

        player = MockPlayer()

        # 2. Test youtube_video redirecting music/song queries to spotify_control
        res = _handle_play({"query": "play this music"}, player)
        self.assertFalse(player.video_shown)  # HUD video player was NOT opened!
        self.assertTrue("Spotify" in res or "YouTube Music" in res)

        # 3. Test youtube_video redirecting specific song to spotify_control
        res2 = _handle_play({"query": "play Shape of You song"}, player)
        self.assertFalse(player.video_shown)  # HUD video player was NOT opened!
        self.assertTrue("Shape of You" in res2)

    def test_youtube_playback_opens_in_browser_not_hud(self):
        from unittest.mock import patch
        import actions.youtube_video as yv

        class MockPlayer:
            def __init__(self):
                self.video_shown = False
                self.webpage_shown = False
                self.logs = []
            def show_video(self, source, title=""):
                self.video_shown = True
            def show_webpage(self, url, title=""):
                self.webpage_shown = True
            def write_log(self, msg):
                self.logs.append(msg)

        player = MockPlayer()
        opened_urls = []

        with patch.object(yv, "_open_url", side_effect=lambda u: opened_urls.append(u)), \
             patch.object(yv, "_scrape_first_video_url", return_value="https://www.youtube.com/watch?v=mock123"):

            # When user says "play on youtube" (empty or generic)
            res = yv._handle_play({"query": "play on youtube"}, player)
            self.assertFalse(player.video_shown)
            self.assertFalse(player.webpage_shown)
            self.assertIn("https://www.youtube.com", opened_urls)
            self.assertIn("Opened YouTube", res)

            # When user asks for a video on youtube
            opened_urls.clear()
            res2 = yv._handle_play({"query": "play on youtube starboy"}, player)
            self.assertFalse(player.video_shown)
            self.assertFalse(player.webpage_shown)
            self.assertEqual(opened_urls, ["https://www.youtube.com/watch?v=mock123"])
            self.assertIn("Playing on YouTube", res2)

            # When direct YouTube URL is given
            opened_urls.clear()
            res3 = yv._handle_play({"url": "https://www.youtube.com/watch?v=direct999"}, player)
            self.assertFalse(player.video_shown)
            self.assertFalse(player.webpage_shown)
            self.assertEqual(opened_urls, ["https://www.youtube.com/watch?v=direct999"])
            self.assertIn("Playing on YouTube", res3)

    def test_web_search_opens_in_browser_not_hud(self):
        from unittest.mock import patch
        import actions.web_search as ws

        class MockPlayer:
            def __init__(self):
                self.news_cards_shown = False
                self.images_shown = False
                self.logs = []
            def show_news_cards(self, *args, **kwargs):
                self.news_cards_shown = True
            def show_images(self, *args, **kwargs):
                self.images_shown = True
            def write_log(self, msg):
                self.logs.append(msg)

        player = MockPlayer()
        opened_searches = []

        with patch.object(ws, "_open_search_in_browser", side_effect=lambda q, mode="search": opened_searches.append((q, mode))), \
             patch.object(ws, "_search", return_value="Search summary result"):

            res = ws.web_search({"query": "latest AI news"}, player=player)
            self.assertFalse(player.news_cards_shown)
            self.assertFalse(player.images_shown)
            self.assertEqual(opened_searches, [("latest AI news", "search")])
            self.assertIn("Search summary result", res)

    def test_spotify_play_music_and_youtube_play_that(self):
        from unittest.mock import patch
        import actions.spotify_control as sc
        import actions.youtube_video as yv

        class MockPlayer:
            def __init__(self):
                self.media = None
                self.video_shown = False
                self.webpage_shown = False
            def show_media(self, title, artist=""):
                self.media = (title, artist)
            def show_video(self, source, title=""):
                self.video_shown = True
            def show_webpage(self, url, title=""):
                self.webpage_shown = True

        player = MockPlayer()

        with patch.object(sc, "_ensure_spotify", return_value=True), \
             patch.object(sc, "_focus_spotify", return_value=True), \
             patch.object(sc, "_media_key", return_value=True):

            # 1. User says "play music": switches to Spotify and plays current track
            res = sc.spotify_control({"action": "play", "query": ""}, player=player)
            self.assertIn("Switched to Spotify and playing current track", res)
            self.assertEqual(player.media, ("Current Track", "Spotify"))

            # 2. User says a name of a song: plays that track on Spotify
            with patch.object(sc, "_search_and_play_spotify", return_value=True) as mock_search:
                res2 = sc.spotify_control({"action": "play", "query": "Starboy"}, player=player)
                self.assertIn("Playing Starboy on Spotify", res2)
                mock_search.assert_called_once_with("Starboy", player=player)
                self.assertEqual(sc.get_last_played_track(), "Starboy")

        # 3. User says "open in youtube and play" or "open in youtube and play that"
        opened_urls = []
        with patch.object(yv, "_open_url", side_effect=lambda u: opened_urls.append(u)), \
             patch.object(yv, "_scrape_first_video_url", return_value="https://www.youtube.com/watch?v=starboy123") as mock_scrape:

            res3 = yv.youtube_video({"action": "play", "query": "open in youtube and play that"}, player=player)
            self.assertFalse(player.video_shown)
            self.assertFalse(player.webpage_shown)
            # Scraped for the last track (Starboy)
            mock_scrape.assert_called_with("Starboy")
            self.assertEqual(opened_urls, ["https://www.youtube.com/watch?v=starboy123"])
            self.assertIn("Playing on YouTube in Microsoft Edge", res3)


    def test_news_channels_and_dynamic_island_bar_display(self):
        from unittest.mock import patch, MagicMock
        import actions.web_search as ws

        class MockPlayer:
            def __init__(self):
                self.news_items = None
                self.news_title = None
            def show_news_cards(self, items, title="HEADLINES"):
                self.news_items = items
                self.news_title = title

        player = MockPlayer()
        opened_searches = []

        # 1. General news request ("tell me news") -> fetches news, DOES NOT open browser, passes to player
        mock_headlines = "1. Global climate summit agrees on historic treaty [BBC News]\n2. Sri Lanka commissions massive clean energy grid [Newsfirst]"
        with patch.object(ws, "_open_search_in_browser", side_effect=lambda q, mode="search": opened_searches.append((q, mode))), \
             patch.object(ws, "_news", return_value=mock_headlines) as mock_news_fn:

            res = ws.web_search({"query": "tell me news", "mode": "news"}, player=player)
            # Browser must NEVER be opened for news!
            self.assertEqual(len(opened_searches), 0)
            mock_news_fn.assert_called_once_with("tell me news")
            self.assertEqual(player.news_items, mock_headlines)
            self.assertIn("BBC News", res)

        # 2. Specific channel request (e.g. "BBC news") -> routes to that channel
        with patch.object(ws, "_ddg_news", return_value=[{"title": "BBC Breaking: Major discovery", "source": "BBC News", "snippet": "Scientists report new finding.", "url": "https://bbc.com/1"}]):
            res_bbc = ws._news("tell me BBC news")
            self.assertIn("BBC News", res_bbc)
            self.assertIn("BBC Breaking", res_bbc)

        # 3. Dynamic Island show_news strictly on the bar (no popup cards/dialogs)
        from core.dynamic_island import DynamicIslandOverlay
        island = DynamicIslandOverlay.__new__(DynamicIslandOverlay)
        island._is_expanded = False
        island._news_sequence_queue = []
        island._news_sequence_idx = 0
        island._news_sequence_timer = MagicMock()
        island.show_island_pill_alert = MagicMock()
        island._reset_bar_display = MagicMock()

        island.show_news(mock_headlines)
        self.assertEqual(len(island._news_sequence_queue), 2)
        # First headline displayed immediately via show_island_pill_alert on the bar
        island.show_island_pill_alert.assert_called_with("◈", "BBC News", "News", "Global climate summit agrees on historic treaty", color="#38bdf8", duration_ms=7500)
        # Next headline queued via single-shot timer
        island._news_sequence_timer.start.assert_called_with(7000)

        # Advance to next headline
        island._advance_news_sequence()
        island.show_island_pill_alert.assert_called_with("◈", "Newsfirst", "News", "Sri Lanka commissions massive clean energy grid", color="#38bdf8", duration_ms=7500)

        # Stop news sequence
        island.stop_news_sequence()
        island._news_sequence_timer.stop.assert_called()
        self.assertEqual(len(island._news_sequence_queue), 0)
        island._reset_bar_display.assert_called_once()


if __name__ == "__main__":
    unittest.main()

