"""
JARVIS — Spotify Control
-------------------------
Controls the Spotify desktop application on Windows using
system media keys and Windows application launching.

Supported commands:
    - Open Spotify
    - Play / pause
    - Next track
    - Previous track
    - Volume up / down
    - Mute / unmute
    - Search Spotify
    - Like current song
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
from pathlib import Path

try:
    import pyautogui
    _PYAUTOGUI_OK = True
except ImportError:
    _PYAUTOGUI_OK = False


# ---------------------------------------------------------------------------
# Spotify paths
# ---------------------------------------------------------------------------

SPOTIFY_EXE_PATHS = [
    Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Spotify" / "Spotify.exe",
    Path(os.environ.get("PROGRAMFILES", "")) / "Spotify" / "Spotify.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Spotify" / "Spotify.exe",
]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _find_spotify() -> Path | None:
    """Find the Spotify desktop executable (standard and WindowsApps)."""

    for path in SPOTIFY_EXE_PATHS:
        try:
            if path.exists():
                return path
        except Exception:
            pass

    # Detect WindowsApps Spotify (Microsoft Store edition)
    try:
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        win_apps = Path(prog_files) / "WindowsApps"
        if win_apps.exists():
            for folder in win_apps.glob("SpotifyAB.SpotifyMusic*"):
                exe = folder / "Spotify.exe"
                if exe.exists():
                    return exe
    except Exception:
        pass

    return None


def _focus_spotify() -> bool:
    """Bring the Spotify application window to the foreground."""
    try:
        os.startfile("spotify:")
        time.sleep(0.3)
    except Exception:
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", "spotify:"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.3)
        except Exception:
            pass

    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            t = (w.title or "").strip()
            if t and "spotify" in t.lower() and not any(x in t.lower() for x in ("visual studio", "code", "terminal", "powershell", "cmd", "antigravity")):
                try:
                    w.restore()
                    w.activate()
                    time.sleep(0.2)
                    return True
                except Exception:
                    pass
    except Exception:
        pass

    try:
        import ctypes
        import psutil
        user32 = ctypes.windll.user32
        matches = []

        def enum_cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True  # Skip headless helper windows with no title!
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()
            if not title:
                return True

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc_name = ""
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except Exception:
                pass

            # Only match top-level visible window with title containing Spotify or belonging to spotify.exe
            if ("spotify" in proc_name or "spotify" in title.lower()) and not any(x in title.lower() for x in ("visual studio", "code", "terminal", "powershell", "cmd", "antigravity")):
                matches.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        if matches:
            hwnd = matches[0]
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            return True
    except Exception:
        pass
    return True


def _launch_spotify() -> bool:
    """Launch Spotify if it is not already running."""
    try:
        os.startfile("spotify:")
        time.sleep(1.5)
        if _is_spotify_running():
            return True
    except Exception:
        pass

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "spotify:"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)
        if _is_spotify_running():
            return True
    except Exception:
        pass

    # Fall back to executable paths if protocol fails
    spotify = _find_spotify()
    if spotify:
        try:
            subprocess.Popen([str(spotify)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[Spotify] Failed to launch executable: {e}")

    return False


def _is_spotify_running() -> bool:
    """Check whether Spotify.exe is running."""

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Spotify.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        return "Spotify.exe" in result.stdout

    except Exception:
        return False


def _ensure_spotify() -> bool:
    """Make sure Spotify is running."""

    if _is_spotify_running():
        return True

    return _launch_spotify()


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3


def _send_media_key_win32(vk: int) -> bool:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        return True
    except Exception:
        return False


def _media_key(key: str) -> bool:
    """Send a Windows media key with win32 keybd_event and pyautogui fallback."""
    key_map = {
        "playpause": 0xB3,
        "nexttrack": 0xB0,
        "prevtrack": 0xB1,
        "stop": 0xB2,
    }
    vk = key_map.get(key.lower())
    if vk is not None and _send_media_key_win32(vk):
        return True

    if _PYAUTOGUI_OK:
        try:
            pyautogui.press(key)
            return True
        except Exception as e:
            print(f"[Spotify] Media key error: {e}")
    return False


def _open_spotify_search(query: str) -> bool:
    """Open Spotify directly to a search query."""

    if not query.strip():
        return False

    encoded = urllib.parse.quote(query.strip())

    url = f"spotify:search:{encoded}"

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )

        return True

    except Exception as e:
        print(f"[Spotify] Search error: {e}")
        return False


GENERIC_MUSIC_TERMS = {
    "", "music", "this music", "the music", "some music", "a song",
    "song", "songs", "current", "resume", "paused", "playback", "unpause",
    "track", "a track", "play", "play music", "play something", "my music",
}

_LAST_PLAYED_TRACK: str = ""


def get_last_played_track() -> str:
    global _LAST_PLAYED_TRACK
    return _LAST_PLAYED_TRACK


def set_last_played_track(track: str) -> None:
    global _LAST_PLAYED_TRACK
    clean = (track or "").strip()
    if clean and clean.lower() not in GENERIC_MUSIC_TERMS:
        _LAST_PLAYED_TRACK = clean


def _play_youtube_music(query: str, player=None) -> str:
    """Fallback: open YouTube Music directly in default browser without opening HUD."""
    import webbrowser
    clean = (query or "").strip()
    if clean and clean.lower() not in GENERIC_MUSIC_TERMS:
        encoded = urllib.parse.quote_plus(clean)
        url = f"https://music.youtube.com/search?q={encoded}"
        label = clean
    else:
        url = "https://music.youtube.com/"
        label = "Top Tracks"
    try:
        webbrowser.open(url)
        if player and hasattr(player, "show_media"):
            player.show_media(label, "YouTube Music")
        return f"Playing {label} on YouTube Music."
    except Exception as e:
        return f"Could not launch YouTube Music: {e}"


def _search_and_play_spotify(query: str, player=None) -> bool:
    """Search Spotify for the requested song/artist and initiate playback."""
    clean_query = query.strip()
    if not clean_query:
        return False

    if clean_query.lower() in GENERIC_MUSIC_TERMS:
        clean_query = "top hits"

    set_last_played_track(clean_query)

    if not _ensure_spotify():
        return False
    time.sleep(0.8)

    _focus_spotify()
    time.sleep(0.3)

    if _PYAUTOGUI_OK:
        old_failsafe = getattr(pyautogui, "FAILSAFE", True)
        try:
            pyautogui.FAILSAFE = False
            import pyperclip

            # Tier 1: Spotify Quick Search (Command Palette) via Ctrl + K
            # In Spotify desktop, Ctrl+K opens the quick search modal overlay.
            # Typing/pasting the query and hitting Enter directly initiates playback of top result!
            pyautogui.hotkey("ctrl", "k")
            time.sleep(0.35)
            pyperclip.copy(clean_query)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.65)  # wait for results to populate
            pyautogui.press("enter")
            time.sleep(0.3)
            # Send space / media key to ensure playback starts
            _send_media_key_win32(VK_MEDIA_PLAY_PAUSE)
        except Exception as e:
            print(f"[Spotify] Quick search play attempt: {e}")
        finally:
            pyautogui.FAILSAFE = old_failsafe
            for mod in ("ctrl", "alt", "shift", "command"):
                try:
                    pyautogui.keyUp(mod)
                except Exception:
                    pass

    # Tier 2: Search page navigation and tab-to-play fallback
    _open_spotify_search(clean_query)
    time.sleep(0.8)
    _focus_spotify()
    time.sleep(0.25)

    if _PYAUTOGUI_OK:
        old_failsafe = getattr(pyautogui, "FAILSAFE", True)
        try:
            pyautogui.FAILSAFE = False
            # From search bar, tab to top result and trigger play
            pyautogui.press("enter")
            time.sleep(0.2)
            pyautogui.press("tab")
            time.sleep(0.15)
            pyautogui.press("tab")
            time.sleep(0.15)
            pyautogui.press("enter")
            time.sleep(0.2)
            pyautogui.press("space")
            time.sleep(0.2)
            _send_media_key_win32(VK_MEDIA_PLAY_PAUSE)
        except Exception as e:
            print(f"[Spotify] Search page play attempt: {e}")
        finally:
            pyautogui.FAILSAFE = old_failsafe
            for mod in ("ctrl", "alt", "shift", "command"):
                try:
                    pyautogui.keyUp(mod)
                except Exception:
                    pass

    if player and hasattr(player, "show_media"):
        player.show_media(clean_query, "Spotify")

    return True


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def spotify_control(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:

    parameters = parameters or {}

    action = str(
        parameters.get("action", "")
    ).strip().lower()

    query = str(
        parameters.get("query", "")
    ).strip()

    # ---------------------------------------------------------------
    # OPEN
    # ---------------------------------------------------------------

    if action in {
        "open",
        "launch",
        "start",
    }:

        if _ensure_spotify():
            _focus_spotify()
            return "Spotify is open and ready."

        # If Spotify not installed, open YouTube Music
        return _play_youtube_music("", player=player)

    # ---------------------------------------------------------------
    # PLAY / PAUSE / SEARCH & PLAY
    # ---------------------------------------------------------------

    if action == "play":
        # Check if the query specifically asked for Netflix or movie/show streaming
        if "netflix" in query.lower() or "netflix" in action:
            try:
                from actions.netflix_control import netflix_control
                return netflix_control(parameters, response=response, player=player, session_memory=session_memory)
            except Exception:
                pass

        # Check if the query specifically asked for YouTube
        if "youtube" in query.lower():
            try:
                from actions.youtube_video import youtube_video
                return youtube_video(parameters, response=response, player=player, session_memory=session_memory)
            except Exception:
                return _play_youtube_music(query, player=player)

        # 1. "when i say play music it must go to spotify and play the current track"
        if query.lower() in GENERIC_MUSIC_TERMS or not query:
            _ensure_spotify()
            _focus_spotify()
            time.sleep(0.35)
            _media_key("playpause")
            if player and hasattr(player, "show_media"):
                player.show_media("Current Track", "Spotify")
            return "Switched to Spotify and playing current track."

        # 2. "if i say a name of a song then play that track on spotify"
        set_last_played_track(query)
        if _ensure_spotify():
            if _search_and_play_spotify(query, player=player):
                return f"Playing {query} on Spotify."

        # Fallback to YouTube Music if Spotify unavailable
        return _play_youtube_music(query, player=player)

    if action in {"pause", "stop"}:
        if _is_spotify_running():
            time.sleep(0.2)
            if _media_key("playpause"):
                return "Spotify playback paused."
        return "Music paused."

    if action in {"play_pause", "toggle"}:
        if _ensure_spotify():
            time.sleep(0.2)
            if _media_key("playpause"):
                return "Spotify playback toggled."
        return "Playback toggled."

    # ---------------------------------------------------------------
    # NEXT
    # ---------------------------------------------------------------

    if action in {
        "next",
        "next_track",
        "skip",
    }:

        if not _ensure_spotify():
            return "Spotify is not available."

        if _media_key("nexttrack"):
            return "Skipped to the next track."

        return "I couldn't skip the track."

    # ---------------------------------------------------------------
    # PREVIOUS
    # ---------------------------------------------------------------

    if action in {
        "previous",
        "previous_track",
        "back",
    }:

        if not _ensure_spotify():
            return "Spotify is not available."

        if _media_key("prevtrack"):
            return "Went back to the previous track."

        return "I couldn't go to the previous track."

    # ---------------------------------------------------------------
    # VOLUME UP
    # ---------------------------------------------------------------

    if action in {
        "volume_up",
        "increase_volume",
        "louder",
    }:

        if _media_key("volumeup"):
            return "Spotify volume increased."

        return "I couldn't increase the volume."

    # ---------------------------------------------------------------
    # VOLUME DOWN
    # ---------------------------------------------------------------

    if action in {
        "volume_down",
        "decrease_volume",
        "quieter",
    }:

        if _media_key("volumedown"):
            return "Spotify volume decreased."

        return "I couldn't decrease the volume."

    # ---------------------------------------------------------------
    # MUTE
    # ---------------------------------------------------------------

    if action in {
        "mute",
        "unmute",
        "toggle_mute",
    }:

        if _media_key("volumemute"):
            return "System audio mute toggled."

        return "I couldn't toggle mute."

    # ---------------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------------

    if action in {
        "search",
        "find",
        "search_spotify",
    }:

        if not query:
            return "What should I search for on Spotify?"

        if not _ensure_spotify():
            return "Spotify is not available."

        if _search_and_play_spotify(query):
            return f"Searching and playing {query} on Spotify."

        return "I couldn't open Spotify search."

    # ---------------------------------------------------------------
    # LIKE
    # ---------------------------------------------------------------

    if action in {
        "like",
        "save",
        "save_song",
    }:

        if not _ensure_spotify():
            return "Spotify is not available."

        # Spotify desktop shortcut for saving the current track.
        if _media_key("ctrl"):

            # We don't rely on this branch for the actual action.
            pass

        try:
            pyautogui.hotkey("alt", "shift", "b")
            return "I attempted to save the current Spotify track."

        except Exception:
            return (
                "I couldn't save the current track automatically. "
                "The Spotify Web API can provide reliable like/save control."
            )

    # ---------------------------------------------------------------
    # UNKNOWN ACTION
    # ---------------------------------------------------------------

    return (
        "I don't know that Spotify command yet. "
        "Try play, pause, next, previous, volume up, volume down, "
        "mute, open, or search."
    )


# ---------------------------------------------------------------------------
# Gemini / Jarvis tool declaration
# ---------------------------------------------------------------------------

TOOL = {
    "name": "spotify_control",

    "description": (
        "Controls the Spotify desktop application. "
        "Use this tool whenever the user asks Jarvis to play music, play a song, or control Spotify, "
        "including playing a requested track, searching and playing artists or albums, "
        "opening Spotify, pausing or resuming music, skipping tracks, "
        "going to the previous track, increasing or decreasing volume, or muting audio. "
        "Whenever the user asks to play a song (e.g. 'play Believer', 'play a song by Queen', 'play a song'), "
        "call with action='play' and specify the song/artist in 'query'."
    ),

    "parameters": {
        "type": "OBJECT",

        "properties": {

            "action": {
                "type": "STRING",

                "description": (
                    "Spotify operation to perform. "
                    "Allowed values: play (plays requested song or resumes if query is empty), "
                    "pause, play_pause, search, open, next, previous, "
                    "volume_up, volume_down, mute, like."
                )
            },

            "query": {
                "type": "STRING",

                "description": (
                    "Song title, artist, playlist, or search keywords to play or search on Spotify. "
                    "Always provide this when the user asks to play a song."
                )
            },
        },

        "required": [
            "action"
        ],
    },

    "handler": spotify_control,
}