"""
JARVIS — Netflix Control
------------------------
Controls Netflix search and playback on Windows and web.
Handles commands like:
    - "go to the netflix and search mandhadi and play it"
    - "open netflix and play stranger things"
    - "search on netflix for <title>"
    - "open netflix"
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
import urllib.parse
from typing import Optional

try:
    import pyautogui
    _PYAUTOGUI_OK = True
except ImportError:
    _PYAUTOGUI_OK = False

_SYSTEM = platform.system()


def _open_netflix_search_and_play(query: str, player=None) -> str:
    """Navigate to Netflix search page on Edge/browser and trigger playback of the top result."""
    clean_q = (query or "").strip()
    if not clean_q:
        return _open_netflix(player=player)

    encoded = urllib.parse.quote(clean_q)
    url = f"https://www.netflix.com/search?q={encoded}"

    if _SYSTEM == "Windows":
        try:
            # Open in Microsoft Edge with quoted URL
            subprocess.Popen(f'cmd /c start msedge "{url}"', shell=True)
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    elif _SYSTEM == "Darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url])

    # Allow the Netflix web UI and catalog search results to populate
    time.sleep(1.8)

    # Trigger playback of the focused top result card
    if _PYAUTOGUI_OK:
        old_failsafe = getattr(pyautogui, "FAILSAFE", True)
        try:
            pyautogui.FAILSAFE = False
            # Hit enter or space on the top search result card
            pyautogui.press("enter")
            time.sleep(0.3)
        except Exception as e:
            print(f"[Netflix] Play trigger error: {e}")
        finally:
            pyautogui.FAILSAFE = old_failsafe

    title_label = clean_q.title()
    if player and hasattr(player, "show_media"):
        try:
            player.show_media(f"{title_label} (Netflix)", "Netflix")
        except Exception:
            pass

    return f"Navigated to Netflix, searched for '{clean_q}', and initiated playback."


def _open_netflix(player=None) -> str:
    """Launch Netflix app or open Netflix home in browser."""
    if _SYSTEM == "Windows":
        # First try Windows Store Netflix app if installed
        try:
            p = subprocess.Popen(
                ["explorer.exe", "shell:AppsFolder\\4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.0)
            return "Netflix application launched."
        except Exception:
            pass

        # Fallback to browser
        try:
            subprocess.Popen('cmd /c start msedge "https://www.netflix.com"', shell=True)
            return "Opened Netflix in browser."
        except Exception:
            pass

    import webbrowser
    webbrowser.open("https://www.netflix.com")
    return "Opened Netflix."


def netflix_control(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Main handler for Netflix actions."""
    parameters = parameters or {}
    action = str(parameters.get("action", "play")).strip().lower()
    query = str(parameters.get("query", "")).strip()

    # Clean filler phrases if passed inside query
    for prefix in (
        "go to netflix and search",
        "search on netflix for",
        "search netflix for",
        "search on netflix",
        "search netflix",
        "watch on netflix",
        "play on netflix",
        "on netflix",
        "and play it",
        "and play",
        "play it",
    ):
        if query.lower().startswith(prefix):
            query = query[len(prefix):].strip()
        if query.lower().endswith(prefix):
            query = query[:-len(prefix)].strip()

    if action in {"open", "launch", "start"} and not query:
        return _open_netflix(player=player)

    if action in {"play", "search", "search_play", "watch"} or query:
        return _open_netflix_search_and_play(query, player=player)

    if action in {"pause", "stop"}:
        if _PYAUTOGUI_OK:
            pyautogui.press("space")
            return "Netflix playback paused."
        return "Paused Netflix."

    return _open_netflix(player=player)


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "netflix_control",
    "description": (
        "Controls Netflix navigation, movie/series search, and video playback. "
        "ALWAYS use this tool whenever the user asks to open Netflix, go to Netflix, search for a movie, series, show, "
        "drama, or film on Netflix, or play something on Netflix (e.g. 'go to the netflix and search mandhadi and play it', "
        "'watch Stranger Things on Netflix', 'search Netflix for Wednesday', 'open Netflix'). "
        "NEVER call spotify_control for Netflix requests — Spotify is strictly for music."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "'play' (search and play movie/show), 'search' (search catalog), 'open' (launch Netflix), or 'pause'",
            },
            "query": {
                "type": "STRING",
                "description": "The exact movie, show, or series title (e.g. 'mandhadi', 'Stranger Things', 'Squid Game')",
            },
        },
        "required": ["action"],
    },
    "handler": netflix_control,
}
