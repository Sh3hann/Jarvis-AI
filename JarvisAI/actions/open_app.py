import os
import time
import subprocess
import platform
import shutil

try:
    import winreg
    _WINREG = True
except ImportError:
    _WINREG = False

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_SYSTEM = platform.system()

_APP_ALIASES: dict[str, dict[str, str]] = {

    # ── Modern IDEs & Development ──────────────────────────────────────────
    "antigravity":         {"Windows": "shell:AppsFolder\\Google.AntigravityIDE", "Darwin": "Antigravity",         "Linux": "antigravity"},
    "antigravity ide":     {"Windows": "shell:AppsFolder\\Google.AntigravityIDE", "Darwin": "Antigravity IDE",     "Linux": "antigravity"},
    "ide":                 {"Windows": "shell:AppsFolder\\Google.AntigravityIDE", "Darwin": "Visual Studio Code",  "Linux": "code"},
    "google antigravity":  {"Windows": "shell:AppsFolder\\Google.AntigravityIDE", "Darwin": "Antigravity",         "Linux": "antigravity"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "windows terminal":   {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "command prompt":     {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "git":                {"Windows": "git-bash",                "Darwin": "Terminal",             "Linux": "bash"},

    # ── Browsers ────────────────────────────────────────────────────────────
    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "microsoft edge":     {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "safari":             {"Windows": "msedge",                  "Darwin": "Safari",               "Linux": "firefox"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},

    # ── Communication & Social ──────────────────────────────────────────────
    "whatsapp":           {"Windows": "whatsapp:",               "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "microsoft teams":    {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "firefox"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "firefox"},

    # ── Windows 11 Pre-Installed & System Applications ──────────────────────
    "media player":       {"Windows": "shell:AppsFolder\\Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Darwin": "Music", "Linux": "vlc"},
    "windows media player": {"Windows": "wmplayer.exe",          "Darwin": "QuickTime Player",     "Linux": "vlc"},
    "music player":       {"Windows": "shell:AppsFolder\\Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Darwin": "Music", "Linux": "vlc"},
    "movies & tv":        {"Windows": "mswindowsvideo:",         "Darwin": "QuickTime Player",     "Linux": "vlc"},
    "movies and tv":      {"Windows": "mswindowsvideo:",         "Darwin": "QuickTime Player",     "Linux": "vlc"},
    "photos":             {"Windows": "ms-photos:",              "Darwin": "Photos",               "Linux": "eog"},
    "photo viewer":       {"Windows": "ms-photos:",              "Darwin": "Preview",              "Linux": "eog"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "calc":               {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "notes":              {"Windows": "notepad.exe",             "Darwin": "Notes",                "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "mspaint":            {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "camera":             {"Windows": "microsoft.windows.camera:", "Darwin": "Photo Booth",       "Linux": "cheese"},
    "webcam":             {"Windows": "microsoft.windows.camera:", "Darwin": "Photo Booth",       "Linux": "cheese"},
    "snipping tool":      {"Windows": "ms-screenclip:",          "Darwin": "Screenshot",           "Linux": "gnome-screenshot"},
    "snip":               {"Windows": "ms-screenclip:",          "Darwin": "Screenshot",           "Linux": "gnome-screenshot"},
    "snip & sketch":      {"Windows": "ms-screenclip:",          "Darwin": "Screenshot",           "Linux": "gnome-screenshot"},
    "clock":              {"Windows": "ms-clock:",               "Darwin": "Clock",                "Linux": "gnome-clocks"},
    "alarms":             {"Windows": "ms-clock:",               "Darwin": "Clock",                "Linux": "gnome-clocks"},
    "alarms & clock":     {"Windows": "ms-clock:",               "Darwin": "Clock",                "Linux": "gnome-clocks"},
    "timer":              {"Windows": "ms-clock:",               "Darwin": "Clock",                "Linux": "gnome-clocks"},
    "stopwatch":          {"Windows": "ms-clock:",               "Darwin": "Clock",                "Linux": "gnome-clocks"},
    "sound recorder":     {"Windows": "soundrecorder:",          "Darwin": "Voice Memos",          "Linux": "gnome-sound-recorder"},
    "voice recorder":     {"Windows": "soundrecorder:",          "Darwin": "Voice Memos",          "Linux": "gnome-sound-recorder"},
    "weather":            {"Windows": "bingweather:",            "Darwin": "Weather",              "Linux": "gnome-weather"},
    "microsoft store":    {"Windows": "ms-windows-store:",       "Darwin": "App Store",            "Linux": "gnome-software"},
    "store":              {"Windows": "ms-windows-store:",       "Darwin": "App Store",            "Linux": "gnome-software"},
    "windows store":      {"Windows": "ms-windows-store:",       "Darwin": "App Store",            "Linux": "gnome-software"},
    "sticky notes":       {"Windows": "shell:AppsFolder\\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App", "Darwin": "Stickies", "Linux": "xpad"},
    "maps":               {"Windows": "bingmaps:",               "Darwin": "Maps",                 "Linux": "gnome-maps"},
    "mail":               {"Windows": "outlookmail:",            "Darwin": "Mail",                 "Linux": "thunderbird"},
    "outlook":            {"Windows": "outlookmail:",            "Darwin": "Microsoft Outlook",    "Linux": "thunderbird"},
    "calendar":           {"Windows": "outlookcal:",             "Darwin": "Calendar",             "Linux": "gnome-calendar"},
    "phone link":         {"Windows": "ms-phone:",               "Darwin": "FaceTime",             "Linux": "kdeconnect"},
    "your phone":         {"Windows": "ms-phone:",               "Darwin": "FaceTime",             "Linux": "kdeconnect"},
    "xbox":               {"Windows": "xbox:",                   "Darwin": "Game Center",          "Linux": "steam"},
    "game bar":           {"Windows": "ms-gamebar:",             "Darwin": "Game Center",          "Linux": "steam"},
    "control panel":      {"Windows": "control.exe",             "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "device manager":     {"Windows": "devmgmt.msc",             "Darwin": "System Information",   "Linux": "hardinfo"},
    "disk management":    {"Windows": "diskmgmt.msc",            "Darwin": "Disk Utility",         "Linux": "gparted"},
    "event viewer":       {"Windows": "eventvwr.msc",            "Darwin": "Console",              "Linux": "gnome-logs"},
    "registry editor":    {"Windows": "regedit.exe",             "Darwin": "Terminal",             "Linux": "dconf-editor"},
    "regedit":            {"Windows": "regedit.exe",             "Darwin": "Terminal",             "Linux": "dconf-editor"},
    "resource monitor":   {"Windows": "resmon.exe",              "Darwin": "Activity Monitor",     "Linux": "htop"},
    "system information": {"Windows": "msinfo32.exe",            "Darwin": "System Information",   "Linux": "hardinfo"},
    "windows security":   {"Windows": "windowsdefender:",        "Darwin": "System Preferences",   "Linux": "clamtk"},
    "defender":           {"Windows": "windowsdefender:",        "Darwin": "System Preferences",   "Linux": "clamtk"},
    "quick assist":       {"Windows": "ms-quick-assist:",        "Darwin": "Screen Sharing",       "Linux": "remmina"},
    "tips":               {"Windows": "ms-get-started:",         "Darwin": "Tips",                 "Linux": "yelp"},
    "feedback hub":       {"Windows": "feedback-hub:",           "Darwin": "Feedback Assistant",   "Linux": "browser"},
    "copilot":            {"Windows": "microsoft-edge://?ux=copilot&tcp=1", "Darwin": "Google Chrome", "Linux": "firefox"},

    # ── Shell & Explorer ────────────────────────────────────────────────────
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "files":              {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file manager":       {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "my files":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},

    # ── Settings Subpages ───────────────────────────────────────────────────
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "display settings":   {"Windows": "ms-settings:display",     "Darwin": "System Preferences",   "Linux": "gnome-control-center display"},
    "sound settings":     {"Windows": "ms-settings:sound",       "Darwin": "System Preferences",   "Linux": "gnome-control-center sound"},
    "audio settings":     {"Windows": "ms-settings:sound",       "Darwin": "System Preferences",   "Linux": "gnome-control-center sound"},
    "volume settings":    {"Windows": "ms-settings:sound",       "Darwin": "System Preferences",   "Linux": "gnome-control-center sound"},
    "bluetooth settings": {"Windows": "ms-settings:bluetooth",   "Darwin": "System Preferences",   "Linux": "gnome-control-center bluetooth"},
    "wifi settings":      {"Windows": "ms-settings:network-wifi", "Darwin": "System Preferences",  "Linux": "gnome-control-center wifi"},
    "network settings":   {"Windows": "ms-settings:network",      "Darwin": "System Preferences",  "Linux": "gnome-control-center network"},
    "battery settings":   {"Windows": "ms-settings:batterysaver", "Darwin": "System Preferences",  "Linux": "gnome-control-center power"},
    "power settings":     {"Windows": "ms-settings:powersleep",   "Darwin": "System Preferences",  "Linux": "gnome-control-center power"},
    "windows update":     {"Windows": "ms-settings:windowsupdate", "Darwin": "System Preferences", "Linux": "gnome-control-center"},
    "apps settings":      {"Windows": "ms-settings:appsfeatures", "Darwin": "System Preferences",  "Linux": "gnome-control-center applications"},
    "installed apps":     {"Windows": "ms-settings:appsfeatures", "Darwin": "System Preferences",  "Linux": "gnome-control-center applications"},
    "notification settings": {"Windows": "ms-settings:notifications", "Darwin": "System Preferences", "Linux": "gnome-control-center notifications"},

    # ── Media, Games & Entertainment ────────────────────────────────────────
    "spotify":            {"Windows": "spotify:",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "netflix":            {"Windows": "shell:AppsFolder\\4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App", "Darwin": "Netflix", "Linux": "firefox"},
    "steam":              {"Windows": "steam://open/main",        "Darwin": "Steam",                "Linux": "steam"},
    "steam library":      {"Windows": "steam://open/games",       "Darwin": "steam://open/games",   "Linux": "steam steam://open/games"},
    "steam games":        {"Windows": "steam://open/games",       "Darwin": "steam://open/games",   "Linux": "steam steam://open/games"},
    "steam store":        {"Windows": "steam://open/store",       "Darwin": "steam://open/store",   "Linux": "steam steam://open/store"},
    "open steam and go to the library": {"Windows": "steam://open/games", "Darwin": "steam://open/games", "Linux": "steam steam://open/games"},
    "steam and go to the library": {"Windows": "steam://open/games", "Darwin": "steam://open/games", "Linux": "steam steam://open/games"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},

    # ── Creativity, Office & Tools ──────────────────────────────────────────
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "anydesk":            {"Windows": "AnyDesk",                 "Darwin": "AnyDesk",              "Linux": "anydesk"},
    "teamviewer":         {"Windows": "TeamViewer",              "Darwin": "TeamViewer",           "Linux": "teamviewer"},
    "obs":                {"Windows": "obs64.exe",               "Darwin": "OBS",                  "Linux": "obs"},
    "obs studio":         {"Windows": "obs64.exe",               "Darwin": "OBS",                  "Linux": "obs"},
    "davinci resolve":    {"Windows": "Resolve.exe",             "Darwin": "DaVinci Resolve",      "Linux": "resolve"},
    "photoshop":          {"Windows": "Photoshop.exe",           "Darwin": "Adobe Photoshop",      "Linux": "gimp"},
    "premiere":           {"Windows": "Adobe Premiere Pro.exe",  "Darwin": "Adobe Premiere Pro",   "Linux": "kdenlive"},
    "after effects":      {"Windows": "AfterFX.exe",             "Darwin": "Adobe After Effects",  "Linux": "blender"},
    "illustrator":        {"Windows": "Illustrator.exe",         "Darwin": "Adobe Illustrator",    "Linux": "inkscape"},
    "audacity":           {"Windows": "audacity.exe",            "Darwin": "Audacity",             "Linux": "audacity"},
}

_START_APPS_CACHE: dict[str, str] = {}
_LAST_START_APPS_QUERY: float = 0.0

def _get_start_apps_cache(force_refresh: bool = False) -> dict[str, str]:
    """Cache Windows Start Menu and Store app IDs for instant zero-latency launching, with auto-refresh."""
    global _START_APPS_CACHE, _LAST_START_APPS_QUERY
    now = time.time()
    if _START_APPS_CACHE and not force_refresh and (now - _LAST_START_APPS_QUERY < 300):
        return _START_APPS_CACHE
    try:
        import json
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Depth 2"],
            capture_output=True, text=True, timeout=8
        )
        if res.stdout.strip():
            data = json.loads(res.stdout)
            items = data if isinstance(data, list) else [data]
            refreshed = {}
            for item in items:
                name = str(item.get("Name", "")).lower().strip()
                appid = str(item.get("AppID", "")).strip()
                if name and appid:
                    refreshed[name] = appid
            if refreshed:
                _START_APPS_CACHE = refreshed
                _LAST_START_APPS_QUERY = now
    except Exception as e:
        print(f"[open_app] Start apps cache error: {e}")
    return _START_APPS_CACHE


def _get_installed_shortcuts() -> dict[str, str]:
    """Recursively discover .lnk shortcuts across user and system Start Menus."""
    dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    ]
    shortcuts = {}
    for d in dirs:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".lnk"):
                        name = f[:-4].lower().strip()
                        shortcuts[name] = os.path.join(root, f)
    return shortcuts


def _get_registry_app_paths() -> dict[str, str]:
    """Inspect Windows Registry App Paths for registered Win32/64 executables."""
    paths = {}
    if not _WINREG:
        return paths
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as k:
                num_subkeys, _, _ = winreg.QueryInfoKey(k)
                for i in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, subkey_name) as sk:
                            val, _ = winreg.QueryValueEx(sk, "")
                            if val and os.path.exists(val):
                                paths[subkey_name.lower().replace(".exe", "").strip()] = val
                    except Exception:
                        pass
        except Exception:
            pass
    return paths


def _normalize(raw: str) -> str:
    key = raw.lower().strip()

    # Steam library special phrasing
    if "steam" in key and any(w in key for w in ("library", "games", "game")):
        return "steam://open/games" if _SYSTEM in ("Windows", "Darwin") else "steam steam://open/games"

    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(_SYSTEM, raw)

    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(_SYSTEM, raw)

    return raw  


def _launch_windows(app_name: str) -> bool:
    import os

    # 1. Shell AppsFolder (universal UWP / packaged app launch)
    if app_name.lower().startswith("shell:"):
        try:
            subprocess.Popen(["explorer.exe", app_name])
            time.sleep(1.0)
            return True
        except Exception as e:
            print(f"[open_app] shell launch error: {e}")

    # 2. Explorer special handling
    if app_name.lower().strip() in ("explorer.exe", "explorer"):
        try:
            subprocess.Popen(["explorer.exe"])
            time.sleep(1.0)
            return True
        except Exception as e:
            print(f"[open_app] explorer launch failed: {e}")

    # 3. Direct Steam executable / URI handling
    if app_name.lower().startswith("steam://") or "steam" in app_name.lower():
        steam_paths = [
            r"C:\Program Files (x86)\Steam\steam.exe",
            r"C:\Program Files\Steam\steam.exe",
            os.path.expandvars(r"%ProgramFiles(x86)%\Steam\steam.exe"),
            os.path.expandvars(r"%ProgramFiles%\Steam\steam.exe"),
        ]
        steam_exe = next((p for p in steam_paths if os.path.isfile(p)), None)
        target_uri = app_name if app_name.lower().startswith("steam://") else (
            "steam://open/games" if any(w in app_name.lower() for w in ("library", "game")) else "steam://open/main"
        )
        if steam_exe:
            try:
                subprocess.Popen([steam_exe, target_uri])
                time.sleep(1.0)
                return True
            except Exception as e:
                print(f"[open_app] steam.exe launch failed: {e}")
        try:
            os.startfile(target_uri)
            time.sleep(1.0)
            return True
        except Exception:
            try:
                subprocess.Popen(f'start "" "{target_uri}"', shell=True)
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 4. Direct Spotify single-instance protocol handling
    if app_name.lower().strip() in ("spotify", "spotify.exe") or app_name.lower().startswith("spotify:"):
        try:
            os.startfile("spotify:")
            time.sleep(1.0)
            return True
        except Exception:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", "spotify:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 5. Direct executable path check (e.g. Antigravity IDE, LocalAppData, ProgramFiles)
    if "antigravity" in app_name.lower():
        antigravity_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity IDE\Antigravity IDE.exe")
        if os.path.isfile(antigravity_exe):
            try:
                subprocess.Popen([antigravity_exe])
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 6. Windows protocol URI (e.g. "whatsapp:", "ms-settings:", "mswindowsmusic:", "ms-photos:")
    if ":" in app_name and not app_name.startswith("shell:"):
        try:
            os.startfile(app_name)
            time.sleep(1.0)
            return True
        except Exception:
            try:
                subprocess.Popen(f'start "" "{app_name}"', shell=True)
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 7. Check Registry App Paths (covers installed desktop software, e.g. Chrome, Edge, VLC, Photoshop)
    reg_paths = _get_registry_app_paths()
    key = app_name.lower().strip()
    if key in reg_paths:
        try:
            subprocess.Popen([reg_paths[key]])
            time.sleep(1.0)
            return True
        except Exception:
            pass
    for r_name, r_path in reg_paths.items():
        if key in r_name or r_name in key:
            try:
                subprocess.Popen([r_path])
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 8. Check dynamic Windows Start Apps cache (with dynamic live refresh if not found)
    cache = _get_start_apps_cache()
    if key in cache:
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{cache[key]}"])
            time.sleep(1.0)
            return True
        except Exception:
            pass
    for name, appid in cache.items():
        if key in name or name in key:
            try:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # Live refresh cache once if not matched (catches future newly installed applications)
    cache = _get_start_apps_cache(force_refresh=True)
    if key in cache:
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{cache[key]}"])
            time.sleep(1.0)
            return True
        except Exception:
            pass
    for name, appid in cache.items():
        if key in name or name in key:
            try:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"])
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 9. Check Start Menu .lnk shortcuts (covers all user & system shortcuts)
    shortcuts = _get_installed_shortcuts()
    if key in shortcuts:
        try:
            os.startfile(shortcuts[key])
            time.sleep(1.0)
            return True
        except Exception:
            pass
    for s_name, s_path in shortcuts.items():
        if key in s_name or s_name in key:
            try:
                os.startfile(s_path)
                time.sleep(1.0)
                return True
            except Exception:
                pass

    # 10. Check system PATH
    clean_bin = app_name if app_name.endswith(".exe") else f"{app_name}.exe"
    if shutil.which(app_name) or shutil.which(clean_bin) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.2)
            return True
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    # 11. Fallback: Windows Start Menu search via PyAutoGUI
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.05
        pyautogui.press("win")
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.03)
        time.sleep(0.7)
        pyautogui.press("enter")
        time.sleep(2.0)
        return True
    except Exception as e:
        print(f"[open_app] Start Menu search failed: {e}")

    return False


def _launch_macos(app_name: str) -> bool:

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["open", "-a", f"{app_name}.app"],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] Spotlight failed: {e}")

    return False


_LINUX_TERMINAL_FALLBACKS = [
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
    "xterm", "lxterminal", "mate-terminal", "tilix", "alacritty", "kitty",
]

def _launch_linux(app_name: str) -> bool:

    # terminal emulators: try common ones in order
    if app_name in ("x-terminal-emulator", "gnome-terminal", "terminal"):
        for term in _LINUX_TERMINAL_FALLBACKS:
            if shutil.which(term):
                try:
                    subprocess.Popen([term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.0)
                    return True
                except Exception:
                    continue

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}

def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' -> '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        if launcher(normalized):
            return f"Opened {app_name}."
        if normalized.lower() != app_name.lower():
            if launcher(app_name):
                return f"Opened {app_name}."
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "open_app",
    "description": (
        "Opens any application, system app, or software program on the computer (including Windows 11 pre-installed apps like Media Player, Photos, Calculator, Camera, Snipping Tool, Notepad, and any currently or future installed third-party programs). "
        "Use this whenever the user asks to open, launch, or start ANY application, IDE, program, or desktop software "
        "(e.g. 'open Media Player', 'open Antigravity IDE', 'open Antigravity', 'open VS Code', 'open WhatsApp', 'open Chrome', 'open Spotify', 'open Netflix', 'open Calculator', 'open Photos'). "
        "ALWAYS call this tool — NEVER call web_search when the user asks to open an application or IDE."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "app_name": {
                "type": "STRING",
                "description": "Exact name of the application (e.g. 'Antigravity IDE', 'WhatsApp', 'Chrome', 'Spotify', 'Netflix', 'VS Code')"
            }
        },
        "required": [
            "app_name"
        ]
    },
    "handler": open_app,
}
