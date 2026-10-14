#youtube_video.py
import json
import re
import sys
import time
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

from config import get_os, is_windows, is_mac, is_linux


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _open_url(url: str) -> None:
    try:
        if is_windows():
            try:
                subprocess.Popen(["cmd", "/c", "start", "msedge", url], shell=False)
                return
            except Exception:
                subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
                return
        elif is_mac():
            subprocess.Popen(["open", url])
        elif is_linux():
            subprocess.Popen(["xdg-open", url])
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception as e:
        print(f"[YouTube] ⚠️ open_url failed: {e}")

def _scrape_first_video_url(query: str) -> str | None:

    if not _REQUESTS_OK:
        return None

    search_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )

    try:
        r    = requests.get(search_url, headers=HEADERS, timeout=10)
        html = r.text

        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)

        seen = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)

            if f'/shorts/{vid}' in html:
                continue
            return f"https://www.youtube.com/watch?v={vid}"

    except Exception as e:
        print(f"[YouTube] ⚠️ scrape_first_video_url failed: {e}")

    return None

def _extract_video_id(url: str) -> str | None:
    match = re.search(
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url
    )
    return match.group(1) if match else None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _ask_for_url(prompt_text: str = "YouTube video URL:") -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()

        url = simpledialog.askstring("J.A.R.V.I.S", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception as e:
        print(f"[YouTube] ⚠️ URL dialog failed: {e}")
        return None


def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript      = None

        lang_priority = ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]

        try:
            transcript = transcript_list.find_manually_created_transcript(lang_priority)
        except Exception:
            pass

        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(lang_priority)
            except Exception:
                for t in transcript_list:
                    transcript = t
                    break

        if transcript is None:
            return None

        fetched = transcript.fetch()
        return " ".join(entry["text"] for entry in fetched)

    except Exception as e:
        print(f"[YouTube] ⚠️ Transcript fetch failed: {e}")
        return None


def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    from google.genai import types
    from core import gemini

    max_chars = 80000
    truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
    # A whole transcript can be 80k characters, hence the long deadline — but a
    # deadline there is, and the ladder in core/gemini.py picks the model.
    response = gemini.call(
        f"Please summarize this YouTube video transcript:\n\n{truncated}",
        tier=gemini.SMART,
        timeout_ms=60_000,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are JARVIS, an AI assistant. "
                "Summarize YouTube video transcripts clearly and concisely. "
                "Structure: 1-sentence overview, then 3-5 key points. "
                "Be direct. Address the user as 'sir'. "
                "Match the language of the transcript."
            )
        )
    )
    if response is None:
        return "I couldn't reach Gemini to summarise that transcript, sir."
    return (response.text or "").strip()


def _save_summary(content: str, video_url: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename

    header = (
        f"JARVIS — YouTube Summary\n"
        f"{'─' * 50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─' * 50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")

    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        print(f"[YouTube] ⚠️ Could not open text editor: {e}")

    return str(filepath)


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}

        for key, pattern in [
            ("title",    r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel",  r'"ownerChannelName":"([^"]+)"'),
            ("views",    r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
            ("likes",    r'"label":"([0-9,]+ likes)"'),
        ]:
            match = re.search(pattern, html)
            if match:
                raw = match.group(1)
                if key == "views":
                    info[key] = f"{int(raw):,}"
                elif key == "duration":
                    secs = int(raw)
                    info[key] = f"{secs // 60}:{secs % 60:02d}"
                else:
                    info[key] = raw

        return info
    except Exception as e:
        print(f"[YouTube] ⚠️ Info scrape failed: {e}")
        return {}


def _scrape_trending(region: str = "TR", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text

        titles   = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)

        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            channel = channels[i] if i < len(channels) else "Unknown"
            results.append({"rank": len(results) + 1, "title": title, "channel": channel})
            if len(results) >= max_results:
                break

        return results
    except Exception as e:
        print(f"[YouTube] ⚠️ Trending scrape failed: {e}")
        return []

def _clean_youtube_query(q: str) -> str:
    cleaned = (q or "").strip()
    cleaned = re.sub(r'^(?:open|play|watch|search)\s+(?:in|on)?\s*youtube\s*(?:and\s+play)?\s*(?:for|to)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^(?:open|play|watch)\s+youtube\s*(?:and\s+play)?\s*(?:for|to)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+(?:in|on)\s+youtube\s*(?:and\s+play)?\s*$', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\b(?:in|on)\s+youtube\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\byoutube\b', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'^(?:play|watch|open)\s+(?:this|that|the|a)?\s*', '', cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+(?:in|on)\s+edge\b', '', cleaned, flags=re.IGNORECASE).strip()
    if cleaned.lower() in ("that", "this", "music", "song", "video", "it"):
        return ""
    return cleaned.strip()


def _handle_play(parameters: dict, player) -> str:
    raw_query = parameters.get("query", "").strip()
    direct = str(parameters.get("url", "")).strip()
    candidate = direct or raw_query

    # If the user or model invoked youtube_video for music or a song (and not a video tutorial/clip or explicit on youtube),
    # route to spotify_control so music plays on Spotify/YouTube Music without opening the HUD!
    query_lower = (raw_query or direct).lower()
    is_explicit_youtube = "youtube" in query_lower or direct
    is_explicit_video = any(w in query_lower for w in ("video", "watch", "clip", "trailer", "movie", "tutorial", "hud", "youtube"))
    if not is_explicit_youtube and not is_explicit_video and any(w in query_lower for w in ("song", "music", "track", "album", "spotify")):
        try:
            from actions.spotify_control import spotify_control
            return spotify_control({"action": "play", "query": raw_query}, player=player)
        except Exception:
            pass

    # Direct local file paths play in the HUD player
    candidate_path = Path(candidate).expanduser()
    if candidate_path.is_file() or (
        candidate.lower().startswith(("https://", "http://"))
        and not _is_valid_youtube_url(candidate)
        and any(candidate.split("?", 1)[0].lower().endswith(ext) for ext in
                (".mp4", ".m4v", ".webm", ".mov", ".mkv", ".avi", ".ogv"))
    ):
        if player and hasattr(player, "show_video"):
            player.show_video(candidate, Path(candidate).name if candidate_path.is_file() else raw_query)
            return f"Playing in the HUD, muted: {raw_query}"

    # If candidate is a direct YouTube URL, open directly on youtube.com in Microsoft Edge / browser
    if _is_valid_youtube_url(candidate):
        _open_url(candidate)
        return f"Playing on YouTube in Microsoft Edge: {candidate}"

    # Clean the query of filler phrases like "open in youtube and play" or "on youtube"
    query = _clean_youtube_query(raw_query)

    # If query is empty and refers to "that" / "current track", check if there was a track playing
    is_referring_to_previous = any(w in raw_query.lower() for w in ("that", "this", "it", "current"))
    if not query and is_referring_to_previous:
        last_track = ""
        try:
            from actions.spotify_control import get_last_played_track
            last_track = get_last_played_track()
        except Exception:
            pass
        if not last_track and player and hasattr(player, "_current_media_title"):
            last_track = getattr(player, "_current_media_title", "")

        if last_track and last_track.lower() not in ("resumed track", "current track", "top hits", ""):
            query = last_track

    # If still no query remaining (e.g. user said "play on youtube" or "open in youtube and play"), open youtube.com directly
    if not query:
        youtube_home = "https://www.youtube.com"
        _open_url(youtube_home)
        return "Opened YouTube in Microsoft Edge."

    if player:
        try:
            player.write_log(f"[YouTube] Searching: {query}")
        except Exception:
            pass

    print(f"[YouTube] Scraping first non-Shorts video for: {query}")

    video_url = _scrape_first_video_url(query)

    if video_url:
        print(f"[YouTube] Opening on Edge: {video_url}")
        _open_url(video_url)
        return f"Playing on YouTube in Microsoft Edge: {query}"

    print(f"[YouTube] [Warning] Scrape failed, opening filtered search page on Edge")
    fallback_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}"
        f"&sp={_YT_VIDEO_FILTER}"
    )
    _open_url(fallback_url)
    return f"Opened YouTube search for: {query} on Microsoft Edge."


def _handle_pause(parameters: dict, player=None, speak=None) -> str:
    """Pause playback in the HUD or a confirmation-gated browser session."""
    routed = _browser_media_control(parameters, "pause")
    if routed is not None:
        return routed
    if player and hasattr(player, "pause_video"):
        player.pause_video()
        return "Paused the video in the JARVIS HUD."
    return "No YouTube video is active in the JARVIS HUD."


def _browser_media_control(parameters: dict, operation: str, seconds: int = 10):
    """Route only to the already-verified browser target from main.py."""
    target = str(parameters.get("_jarvis_playback_target", "hud")).lower()
    if target == "none":
        return "I don't see an active YouTube video in the HUD or JARVIS-controlled browser."
    if target != "browser":
        return None
    browser = str(parameters.get("_jarvis_playback_browser", ""))
    try:
        from actions.browser_control import control_youtube_media
        return control_youtube_media(browser, operation, seconds)
    except Exception as exc:
        return f"Could not control browser YouTube playback: {exc}"


def _handle_fast_forward(parameters: dict, player=None, speak=None) -> str:
    try:
        seconds = max(5, min(120, int(parameters.get("seconds", 10))))
    except (TypeError, ValueError):
        seconds = 10
    routed = _browser_media_control(parameters, "fast_forward", seconds)
    if routed is not None:
        return routed
    if not player or not hasattr(player, "seek_video"):
        return "No YouTube video is active in the JARVIS HUD."
    player.seek_video(seconds)
    return f"Skipped ahead {seconds} seconds in the JARVIS HUD video."


def _handle_stop(parameters: dict, player=None, speak=None) -> str:
    routed = _browser_media_control(parameters, "stop")
    if routed is not None:
        return routed
    if not player or not hasattr(player, "stop_video"):
        return "No YouTube video is active in the JARVIS HUD."
    player.stop_video()
    return "Stopped the video in the JARVIS HUD."


def _handle_sound(parameters: dict, player, muted: bool) -> str:
    routed = _browser_media_control(parameters, "mute" if muted else "unmute")
    if routed is not None:
        return routed
    if not player or not hasattr(player, "set_video_muted"):
        return "No YouTube video is active in the JARVIS HUD."
    player.set_video_muted(muted)
    return "Video sound enabled in the HUD." if not muted else "Video sound muted in the HUD."


def _handle_summarize(parameters: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"

    url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if parameters.get("save", False):
        saved_path = _save_summary(summary, url)
        return f"Summary complete and saved to Desktop: {saved_path}"

    return summary


def _handle_get_info(parameters: dict, player, speak) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] Getting info: {url}")

    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."

    lines = [
        f"{key.capitalize()}: {info[key]}"
        for key in ("title", "channel", "views", "duration", "likes")
        if key in info
    ]
    result = "\n".join(lines)

    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")

    return result


def _handle_trending(parameters: dict, player, speak) -> str:
    region = parameters.get("region", "TR").upper()

    if player:
        player.write_log(f"[YouTube] Trending: {region}")

    trending = _scrape_trending(region=region, max_results=8)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines  = [f"Top trending videos in {region}:"]
    lines += [f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending]
    result = "\n".join(lines)

    if speak:
        top3   = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result

_ACTION_MAP = {
    "play":      _handle_play,
    "pause":     _handle_pause,
    "play_pause": _handle_pause,
    "fast_forward": _handle_fast_forward,
    "seek":      _handle_fast_forward,
    "stop":      _handle_stop,
    "sound_on":  lambda parameters, player, speak=None: _handle_sound(parameters, player, False),
    "unmute":    lambda parameters, player, speak=None: _handle_sound(parameters, player, False),
    "sound_off": lambda parameters, player, speak=None: _handle_sound(parameters, player, True),
    "mute":      lambda parameters, player, speak=None: _handle_sound(parameters, player, True),
    "summarize": _handle_summarize,
    "get_info":  _handle_get_info,
    "trending":  _handle_trending,
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player and hasattr(player, "write_log"):
        player.write_log(f"[YouTube] Action: {action}")
    print(f"[YouTube] Action: {action}  Params: {params}")

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return (
            f"Unknown YouTube action: '{action}'. "
            "Available: play, pause, fast_forward, stop, sound_on, sound_off, "
            "summarize, get_info, trending."
        )

    try:
        if action == "play":
            return handler(params, player) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        print(f"[YouTube] [Error] in {action}: {e}")
        return f"YouTube {action} failed, sir: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "youtube_video",
    "description": (
        "Searches and plays videos on YouTube directly on Microsoft Edge / web browser. "
        "STRICTLY FOR VIDEOS, tutorials, trailers, and visual watching. Do NOT use this "
        "tool for music, songs, or audio playback (ALWAYS use spotify_control for music and songs). "
        "When user asks to play a video or play on YouTube, this tool opens and plays the video "
        "on youtube.com in Microsoft Edge, never on the HUD. Local video files can still be played "
        "in the HUD player. Voice controls can pause, fast-forward, stop, unmute, and mute "
        "browser/HUD playback. Summarize/get_info/trending remain available."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | pause | fast_forward | stop | unmute/sound_on | mute/sound_off | summarize | get_info | trending. Fast-forward skips 10 seconds by default."
            },
            "query": {
                "type": "STRING",
                "description": "Search query for play action"
            },
            "url": {
                "type": "STRING",
                "description": "Optional YouTube/direct video URL or full local video file path for HUD playback"
            },
            "save": {
                "type": "BOOLEAN",
                "description": "Save summary to Notepad (summarize only)"
            },
            "region": {
                "type": "STRING",
                "description": "Country code for trending e.g. TR, US"
            },
            "seconds": {
                "type": "INTEGER",
                "description": "Seconds to skip forward (5–120, default 10), used by fast_forward/seek"
            },
            "url": {
                "type": "STRING",
                "description": "Video URL for get_info action"
            }
        },
        "required": []
    },
    "handler": youtube_video,
}
