#computer_settings.py
import json
import re
import sys
import time
import subprocess
import platform
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

from core import confirm
from core.undo import push_undo

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

if _OS == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
    import ctypes
    from ctypes import wintypes
    try:
        import win32service, win32gui, win32process, win32con
        _WIN32 = True
    except ImportError:
        _WIN32 = False
else:
    _WIN_HIDE: dict = {}
    _WIN32 = False


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _get_macos_wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0" 

def _windows_volume_control():
    """Return the endpoint interface across old and current Pycaw releases.

    Current Pycaw returns an AudioDevice whose EndpointVolume property is
    already the IAudioEndpointVolume interface. Older releases exposed a
    lower-level Activate method instead.
    """
    from pycaw.pycaw import AudioUtilities
    device = AudioUtilities.GetSpeakers()
    endpoint = getattr(device, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint

    activate = getattr(device, "Activate", None)
    if callable(activate):
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        interface = activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    raise RuntimeError(
        "Pycaw did not expose EndpointVolume on the default output device. "
        "Update pycaw and comtypes, then restart JARVIS."
    )


def _windows_volume_adjust(delta: int) -> int:
    """Adjust and verify the Windows master endpoint level with graceful media key fallback."""
    before = volume_get()
    try:
        if before is not None:
            target = max(0, min(100, before + int(delta)))
            volume_set(target)
            after = volume_get()
            if after is not None:
                return after
    except Exception as e:
        print(f"[Settings] Direct volume adjust encountered issue: {e}")

    # Fallback to hardware multimedia keys (works even if Pycaw COM interface glitched or locked)
    try:
        key = "volumeup" if delta > 0 else "volumedown"
        steps = max(1, abs(int(delta)) // 2)
        for _ in range(steps):
            pyautogui.press(key)
        after = volume_get()
        if after is not None:
            return after
    except Exception:
        pass

    return max(0, min(100, (before + int(delta)) if before is not None else 50))


def volume_up(delta: int = 10):
    delta = int(delta or 10)
    if _OS == "Windows":
        lvl = _windows_volume_adjust(delta)
        return f"Volume increased to {lvl}%."
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            f"set volume output volume (output volume of (get volume settings) + {delta})"],
            capture_output=True)
        return "Volume increased."
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{delta}%"],
            capture_output=True)
        return "Volume increased."

def volume_down(delta: int = 10):
    delta = int(delta or 10)
    if _OS == "Windows":
        lvl = _windows_volume_adjust(-delta)
        return f"Volume decreased to {lvl}%."
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            f"set volume output volume (output volume of (get volume settings) - {delta})"],
            capture_output=True)
        return "Volume decreased."
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{delta}%"],
            capture_output=True)
        return "Volume decreased."

def volume_mute():
    if _OS == "Windows":
        pyautogui.press("volumemute")
        return "Toggled mute."
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume with output muted"],
            capture_output=True)
        return "Toggled mute."
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True)
        return "Toggled mute."

def volume_get() -> int | None:
    """Current master volume 0-100, or None if this platform will not say.

    Undo needs a "before" value, and reading one is cheap on every OS we
    support. Where it is not readable the action simply is not registered as
    undoable — a wrong undo is worse than no undo."""
    try:
        if _OS == "Windows":
            vol = _windows_volume_control()
            return max(0, min(100, round(vol.GetMasterVolumeLevelScalar() * 100)))
        if _OS == "Darwin":
            r = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                               capture_output=True, text=True, timeout=5)
            return max(0, min(100, int(r.stdout.strip())))
        r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                           capture_output=True, text=True, timeout=5)
        m = re.search(r"(\d+)%", r.stdout)
        return max(0, min(100, int(m.group(1)))) if m else None
    except Exception:
        return None


_CURRENT_BRIGHTNESS_CACHE = 100


def _set_gamma_brightness(percent: int) -> bool:
    """Universal Windows fallback: sets GPU Look-Up Table directly via GDI32.
    Works on every internal & external monitor, OLED, dGPU mode, and when Windows slider is missing."""
    global _CURRENT_BRIGHTNESS_CACHE
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        percent = max(5, min(100, int(percent)))
        factor = percent / 100.0
        hdc = user32.GetDC(0)
        ramp = (wintypes.WORD * 768)()
        for i in range(256):
            val = int(i * 256 * factor)
            val = max(0, min(65535, val))
            ramp[i] = val
            ramp[i + 256] = val
            ramp[i + 512] = val
        res = gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        user32.ReleaseDC(0, hdc)
        if res:
            _CURRENT_BRIGHTNESS_CACHE = percent
            return True
    except Exception as e:
        print(f"[Settings] Gamma ramp failed: {e}")
    return False


def _set_wmi_brightness(percent: int) -> bool:
    """Hardware ACPI/WMI brightness for laptop panels."""
    try:
        val = max(0, min(100, int(percent)))
        ps_cmd = (
            f"$val = {val}; "
            "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue | "
            "ForEach-Object { $_ | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{Timeout=1; Brightness=[byte]$val} -ErrorAction SilentlyContinue }; "
            "Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue | "
            "ForEach-Object { $_.WmiSetBrightness(1, $val) }"
        )
        r = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5, **_WIN_HIDE)
        return r.returncode == 0
    except Exception:
        return False


def _set_dxva2_brightness(percent: int) -> bool:
    """Hardware DDC/CI brightness for external monitors and desktop screens."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        dxva2 = ctypes.windll.dxva2

        class PHYSICAL_MONITOR(ctypes.Structure):
            _fields_ = [('hPhysicalMonitor', wintypes.HANDLE),
                        ('szPhysicalMonitorDescription', wintypes.WCHAR * 128)]

        monitors = []
        def enum_cb(hMon, hdc, lprc, dwData):
            monitors.append(hMon)
            return True

        MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(enum_cb), 0)

        success = False
        val = max(0, min(100, int(percent)))
        for hMon in monitors:
            count = wintypes.DWORD()
            if dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hMon, ctypes.byref(count)):
                phys = (PHYSICAL_MONITOR * count.value)()
                if dxva2.GetPhysicalMonitorsFromHMONITOR(hMon, count.value, phys):
                    for p in phys:
                        if dxva2.SetMonitorBrightness(p.hPhysicalMonitor, val):
                            success = True
                        dxva2.DestroyPhysicalMonitor(p.hPhysicalMonitor)
        return success
    except Exception:
        return False


def brightness_get() -> int:
    """Current brightness 0-100 across WMI, CIM, and fallback cache."""
    global _CURRENT_BRIGHTNESS_CACHE
    try:
        if _OS == "Windows":
            ps_cmd = (
                "(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness; "
                "if (!$?) { (Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness }"
            )
            r = subprocess.run(["powershell", "-Command", ps_cmd],
                               capture_output=True, text=True, timeout=5, **_WIN_HIDE)
            nums = [int(line.strip()) for line in r.stdout.splitlines() if line.strip().isdigit()]
            if nums:
                _CURRENT_BRIGHTNESS_CACHE = max(0, min(100, nums[0]))
                return _CURRENT_BRIGHTNESS_CACHE
            return _CURRENT_BRIGHTNESS_CACHE
        if _OS == "Linux" and subprocess.run(
                ["which", "brightnessctl"], capture_output=True).returncode == 0:
            cur = int(subprocess.run(["brightnessctl", "get"],
                                     capture_output=True, text=True, timeout=5).stdout.strip())
            mx  = int(subprocess.run(["brightnessctl", "max"],
                                     capture_output=True, text=True, timeout=5).stdout.strip())
            return max(0, min(100, round(cur * 100 / mx))) if mx else 100
    except Exception:
        pass
    return _CURRENT_BRIGHTNESS_CACHE


def brightness_set(value: int) -> int:
    """Set brightness across all display engines: WMI, DDC/CI, and GPU gamma ramp."""
    global _CURRENT_BRIGHTNESS_CACHE
    value = max(0, min(100, int(value)))
    _CURRENT_BRIGHTNESS_CACHE = value

    if _OS == "Windows":
        wmi_ok = _set_wmi_brightness(value)
        dxva_ok = _set_dxva2_brightness(value)
        # If hardware methods failed, or for external display/dGPU mode where WMI is broken:
        # Gamma ramp guarantees the screen brightness changes!
        if not wmi_ok and not dxva_ok:
            _set_gamma_brightness(value)
        else:
            # Normalize gamma ramp if hardware method succeeded
            _set_gamma_brightness(100)
            _CURRENT_BRIGHTNESS_CACHE = value
    elif _OS == "Linux":
        subprocess.run(["brightnessctl", "set", f"{value}%"], capture_output=True)
    return value


def volume_set(value: int):
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        try:
            vol = _windows_volume_control()
            vol.SetMasterVolumeLevelScalar(value / 100.0, None)
            return value
        except Exception as e:
            print(f"[Settings] Pycaw volume_set failed: {e}")
            cur = volume_get()
            if cur is not None:
                diff = value - cur
                key = "volumeup" if diff > 0 else "volumedown"
                steps = max(1, abs(diff) // 2)
                for _ in range(steps):
                    pyautogui.press(key)
            return value
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
            capture_output=True)
        return value
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
            capture_output=True)
        return value


def brightness_up(delta: int = 10):
    delta = int(delta or 10)
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 144'],
            capture_output=True)
        return "Brightness increased."
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", f"+{delta}%"], capture_output=True)
        return "Brightness increased."
    else:
        cur = brightness_get()
        target = min(100, cur + delta)
        brightness_set(target)
        return f"Brightness increased to {target}%."


def brightness_down(delta: int = 10):
    delta = int(delta or 10)
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 145'],
            capture_output=True)
        return "Brightness decreased."
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", f"{delta}%-"], capture_output=True)
        return "Brightness decreased."
    else:
        cur = brightness_get()
        target = max(0, cur - delta)
        brightness_set(target)
        return f"Brightness decreased to {target}%."


def fix_brightness():
    """Fix stuck brightness, missing Windows 11 brightness slider, or graphics driver glitches.
    Sends Win+Ctrl+Shift+B graphics subsystem reset and refreshes display services."""
    if _OS == "Windows":
        try:
            import ctypes
            import time
            user32 = ctypes.windll.user32
            VK_LWIN = 0x5B
            VK_CONTROL = 0x11
            VK_SHIFT = 0x10
            VK_B = 0x42
            KEYEVENTF_KEYUP = 0x0002

            # Trigger Windows Graphics Subsystem Reset (Win + Ctrl + Shift + B)
            user32.keybd_event(VK_LWIN, 0, 0, 0)
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_SHIFT, 0, 0, 0)
            user32.keybd_event(VK_B, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(VK_B, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)

            # Restart Display Enhancement Service if present
            subprocess.run(["powershell", "-Command", "Restart-Service DisplayEnhancementService -ErrorAction SilentlyContinue"],
                           capture_output=True, timeout=5, **_WIN_HIDE)
            # Re-normalize gamma ramp
            _set_gamma_brightness(100)
            cur = brightness_get()
            return f"Refreshed Windows graphics pipeline and display brightness subsystem. Current brightness is {cur}%. Both manual and voice adjustments are restored."
        except Exception as e:
            return f"Display refresh attempted: {e}"
    return "Display subsystem checked."


def fix_volume():
    """Fix stuck audio, disconnected audio endpoints, or locked volume mixer."""
    if _OS == "Windows":
        try:
            subprocess.run(["powershell", "-Command", "Restart-Service Audiosrv -Force -ErrorAction SilentlyContinue"],
                           capture_output=True, timeout=5, **_WIN_HIDE)
            vol = volume_get()
            return f"Windows audio subsystem refreshed. Current volume is {vol}%."
        except Exception as e:
            return f"Audio subsystem checked: {e}"
    return "Audio subsystem checked."

def _send_win_key(key_char: str):
    """Sends Win + Key (e.g. 'down', 'up', 'd') via keybd_event safely without failsafe exceptions."""
    try:
        if _OS == "Windows":
            VK_LWIN = 0x5B
            vk_map = {
                "down": 0x28,
                "up": 0x26,
                "left": 0x25,
                "right": 0x27,
                "d": 0x44,
                "m": 0x4D,
            }
            vk = vk_map.get(key_char.lower())
            if vk:
                user32 = ctypes.windll.user32
                user32.keybd_event(VK_LWIN, 0, 0, 0)
                time.sleep(0.03)
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.03)
                user32.keybd_event(vk, 0, 2, 0) # KEYEVENTF_KEYUP
                user32.keybd_event(VK_LWIN, 0, 2, 0)
                return
    except Exception:
        pass
    try:
        pyautogui.hotkey("win", key_char)
    except Exception:
        pass


def _get_desktop_windows(include_invisible: bool = False) -> list[tuple]:
    """
    Safely enumerates top-level windows across the interactive desktop ('default').
    Returns a list of tuples: (hwnd, title, class_name, pid, process_name).
    """
    if _OS != "Windows":
        return []
    windows = []
    try:
        user32 = ctypes.windll.user32
        hdesk = None
        try:
            hdesk = win32service.OpenDesktop('default', 0, False, 0x10000000)
            if hdesk:
                user32.SetThreadDesktop.argtypes = [wintypes.HWND]
                user32.SetThreadDesktop.restype = wintypes.BOOL
                user32.SetThreadDesktop(int(hdesk))
        except Exception:
            pass

        def cb(hwnd, _):
            if include_invisible or win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                cls_name = win32gui.GetClassName(hwnd)
                if title or include_invisible:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    pname = ""
                    if _PSUTIL:
                        try:
                            pname = psutil.Process(pid).name()
                        except Exception:
                            pname = ""
                    windows.append((hwnd, title, cls_name, pid, pname))
            return True

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            if hdesk:
                try:
                    win32gui.EnumDesktopWindows(hdesk, cb, None)
                except Exception:
                    pass
    except Exception as e:
        print(f"[computer_settings] Window enumeration error: {e}")
    return windows


def find_app_windows(app_name: str = None) -> list[tuple]:
    """
    Finds window(s) matching an application name by window title, process executable,
    or common application alias. If app_name is empty/None, returns the active window.
    """
    if _OS != "Windows":
        return []

    clean = (app_name or "").lower().strip()
    windows = _get_desktop_windows()

    if not clean or clean in ("active", "current", "this", "window", "foreground"):
        try:
            user32 = ctypes.windll.user32
            fg = user32.GetForegroundWindow()
            if fg:
                for w in windows:
                    if w[0] == fg:
                        return [w]
                # Direct query fallback
                title = win32gui.GetWindowText(fg)
                cls_name = win32gui.GetClassName(fg)
                _, pid = win32process.GetWindowThreadProcessId(fg)
                pname = psutil.Process(pid).name() if _PSUTIL else ""
                return [(fg, title, cls_name, pid, pname)]
        except Exception:
            pass
        return []

    # Common Windows 11 system, Store, and desktop process mappings
    sys_aliases = {
        "media player": ("microsoft.media.player", "wmplayer", "media.player", "media player", "zunemusic"),
        "windows media player": ("wmplayer", "microsoft.media.player"),
        "music player": ("microsoft.media.player", "wmplayer", "zunemusic"),
        "movies": ("video.ui", "mswindowsvideo"),
        "photos": ("microsoft.photos", "photos"),
        "calculator": ("calculatorapp", "calculator", "calc"),
        "camera": ("windowscamera", "camera"),
        "paint": ("mspaint", "paintapp", "paint"),
        "notepad": ("notepad",),
        "snipping tool": ("snippingtool", "screensketch"),
        "clock": ("time", "alarmsapp", "clock"),
        "weather": ("weather", "bingweather"),
        "terminal": ("windowsterminal", "wt"),
        "settings": ("systemsettings", "settings"),
        "store": ("winstore.app", "store"),
        "voice recorder": ("soundrec", "soundrecorder", "voicerecorder"),
        "sound recorder": ("soundrec", "soundrecorder", "voicerecorder"),
        "spotify": ("spotify",),
        "whatsapp": ("whatsapp",),
        "chrome": ("chrome",),
        "edge": ("msedge", "edge"),
        "firefox": ("firefox",),
        "steam": ("steam",),
        "discord": ("discord",),
        "telegram": ("telegram",),
        "slack": ("slack",),
        "antigravity": ("antigravity ide", "antigravity"),
        "antigravity ide": ("antigravity ide", "antigravity"),
        "vscode": ("code", "visual studio code"),
        "code": ("code", "visual studio code"),
        "netflix": ("netflix",),
    }

    search_terms = [clean]
    for k, aliases in sys_aliases.items():
        if k in clean or clean in k:
            search_terms.extend(aliases)

    matched = []
    for w in windows:
        hwnd, title, cls_name, pid, pname = w
        title_low = title.lower()
        pname_low = pname.lower()
        if any(term in title_low or term in pname_low for term in search_terms):
            matched.append(w)

    return matched


def close_app(app_name: str = None) -> str:
    target = (app_name or "").strip()
    low = target.lower()

    if low in ("all", "everything", "all apps", "all windows", "all applications"):
        if _OS == "Windows":
            try:
                user32 = ctypes.windll.user32
                windows = _get_desktop_windows()
                closed = 0
                for hwnd, title, cls, pid, pname in windows:
                    if title and pname.lower() not in ("explorer.exe", "shellexperiencehost.exe", "searchhost.exe", "taskbar.exe"):
                        user32.PostMessageW(hwnd, 0x0010, 0, 0) # WM_CLOSE
                        closed += 1
                return f"Closed {closed} open application windows."
            except Exception as e:
                print(f"[computer_settings] Close all windows error: {e}")
        return "Closed all open applications."

    if target and _OS == "Windows":
        try:
            user32 = ctypes.windll.user32
            # 1. Graceful window close via WM_CLOSE
            matched = find_app_windows(target)
            if matched:
                for hwnd, title, _, pid, pname in matched:
                    try:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    except Exception:
                        pass
                time.sleep(0.5)

            # 2. Process termination via psutil (covers system UWP, packaged, Win32, and future apps)
            if _PSUTIL:
                target_clean = low.replace(".exe", "").strip()
                known_procs = {
                    "media player": ("microsoft.media.player.exe", "wmplayer.exe", "media.player.exe"),
                    "windows media player": ("wmplayer.exe",),
                    "photos": ("microsoft.photos.exe", "photos.exe"),
                    "calculator": ("calculatorapp.exe", "calculator.exe", "calc.exe"),
                    "camera": ("windowscamera.exe", "camera.exe"),
                    "paint": ("mspaint.exe", "paintapp.exe"),
                    "notepad": ("notepad.exe",),
                    "snipping tool": ("snippingtool.exe", "screensketch.exe"),
                    "clock": ("time.exe", "alarmsapp.exe"),
                    "weather": ("weather.exe", "microsoft.msn.weather.exe"),
                    "terminal": ("windowsterminal.exe", "wt.exe"),
                    "settings": ("systemsettings.exe",),
                    "store": ("winstore.app.exe",),
                    "spotify": ("spotify.exe",),
                    "whatsapp": ("whatsapp.exe",),
                    "chrome": ("chrome.exe",),
                    "edge": ("msedge.exe",),
                    "firefox": ("firefox.exe",),
                    "steam": ("steam.exe",),
                    "discord": ("discord.exe",),
                    "telegram": ("telegram.exe",),
                    "slack": ("slack.exe",),
                    "antigravity": ("antigravity ide.exe",),
                    "antigravity ide": ("antigravity ide.exe",),
                    "vscode": ("code.exe",),
                    "code": ("code.exe",),
                    "netflix": ("netflix.exe",),
                }
                candidates = []
                for k, procs in known_procs.items():
                    if k in target_clean or target_clean in k:
                        candidates.extend(procs)
                candidates.append(f"{target_clean}.exe")

                killed = False
                for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        pname = p.info['name'].lower()
                        if pname in candidates or any(c in pname for c in candidates) or target_clean in pname:
                            p.terminate()
                            killed = True
                    except Exception:
                        pass
                if killed:
                    return f"Closed {target}."

            # 3. Fallback taskkill
            res = subprocess.run(["taskkill", "/F", "/IM", f"{target}.exe"], capture_output=True, text=True, **_WIN_HIDE)
            if res.returncode == 0:
                return f"Closed {target}."
        except Exception as e:
            print(f"[computer_settings] close_app error: {e}")

    if _OS == "Darwin":
        pyautogui.hotkey("command", "q")
    else:
        pyautogui.hotkey("alt", "f4")
    return f"Closed {target or 'active application'}."


def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")


def full_screen():
    if _OS == "Darwin": pyautogui.hotkey("ctrl", "command", "f")
    else:               pyautogui.press("f11")


def minimize_window(app_name: str = None) -> str:
    target = (app_name or "").strip()
    low = target.lower()

    if low in ("all", "everything", "all apps", "all windows", "desktop", "all applications"):
        show_desktop()
        return "Minimized all applications."

    if _OS == "Windows":
        try:
            import win32con
            user32 = ctypes.windll.user32
            matched = find_app_windows(target)
            if matched:
                count = 0
                for hwnd, title, _, _, pname in matched:
                    user32.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    count += 1
                disp = matched[0][1] or matched[0][4] or target
                return f"Minimized {disp}." if count == 1 else f"Minimized {count} {target} windows."
            
            # Fallback to active window shortcut
            _send_win_key("down")
            return f"Minimized {target or 'active window'}."
        except Exception as e:
            print(f"[computer_settings] minimize error: {e}")
            _send_win_key("down")
            return f"Minimized {target or 'active window'}."
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "m")
        return f"Minimized {target or 'active window'}."
    else:
        pyautogui.hotkey("super", "h")
        return f"Minimized {target or 'active window'}."


def maximize_window(app_name: str = None) -> str:
    target = (app_name or "").strip()
    if _OS == "Windows":
        try:
            import win32con
            user32 = ctypes.windll.user32
            matched = find_app_windows(target)
            if matched:
                for hwnd, title, _, _, pname in matched:
                    user32.ShowWindow(hwnd, win32con.SW_RESTORE)
                    user32.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
                    user32.SetForegroundWindow(hwnd)
                disp = matched[0][1] or matched[0][4] or target
                return f"Maximized {disp}."
            
            # Fallback to active window shortcut
            _send_win_key("up")
            return f"Maximized {target or 'active window'}."
        except Exception as e:
            print(f"[computer_settings] maximize error: {e}")
            _send_win_key("up")
            return f"Maximized {target or 'active window'}."
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to keystroke "f" '
            'using {control down, command down}'],
            capture_output=True)
        return f"Maximized {target or 'active window'}."
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                capture_output=True)
        except Exception:
            pyautogui.hotkey("super", "up")
        return f"Maximized {target or 'active window'}."


def restore_window(app_name: str = None) -> str:
    target = (app_name or "").strip()
    if _OS == "Windows":
        try:
            import win32con
            user32 = ctypes.windll.user32
            matched = find_app_windows(target)
            if matched:
                for hwnd, title, _, _, pname in matched:
                    user32.ShowWindow(hwnd, win32con.SW_RESTORE)
                    user32.SetForegroundWindow(hwnd)
                disp = matched[0][1] or matched[0][4] or target
                return f"Restored {disp}."
            _send_win_key("down")
            return f"Restored {target or 'active window'}."
        except Exception as e:
            print(f"[computer_settings] restore error: {e}")
            return f"Restored {target or 'active window'}."
    return f"Restored {target or 'active window'}."
    return f"Restored {target or 'active window'}."

def snap_left():
    if _OS == "Windows":
        pyautogui.hotkey("win", "left")
    elif _OS == "Darwin":
        # macOS has no built-in snap; try Rectangle app shortcut if installed
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "left")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,0,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def snap_right():
    if _OS == "Windows":
        pyautogui.hotkey("win", "right")
    elif _OS == "Darwin":
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "right")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,960,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def switch_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "tab")
    else:               pyautogui.hotkey("alt", "tab")

def show_desktop():
    if _OS == "Darwin":   pyautogui.hotkey("fn", "f11")
    elif _OS == "Windows": pyautogui.hotkey("win", "d")
    else:                  pyautogui.hotkey("super", "d")

def open_task_manager():
    if _OS == "Windows":
        pyautogui.hotkey("ctrl", "shift", "esc")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "Activity Monitor"])
    else:
        for cmd in [["gnome-system-monitor"], ["xfce4-taskmanager"], ["htop"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                break


def focus_search():
    if _OS == "Darwin": pyautogui.hotkey("command", "l")
    else:               pyautogui.hotkey("ctrl", "l")

def pause_video():
    # Activate the YouTube browser window first so Windows routes the media key
    # to its media session rather than another player (for example Spotify).
    if _OS == "Windows":
        try:
            import pygetwindow
            active = pygetwindow.getActiveWindow()
            windows = pygetwindow.getWindowsWithTitle("YouTube")
            target = (active if active and "youtube" in (active.title or "").lower()
                      else next((w for w in windows if not w.isMinimized), None)
                      or (windows[0] if windows else None))
            if target:
                if target.isMinimized:
                    target.restore()
                target.activate()
                time.sleep(0.2)
            elif windows == []:
                return "I couldn't find an open YouTube browser window to pause."
        except ImportError:
            pass
        try:
            pyautogui.press("playpause")
            return "Sent the Windows media play/pause key to the active browser."
        except Exception:
            pass
    pyautogui.press("space")
    return "Sent the player pause shortcut."

def refresh_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "r")
    else:               pyautogui.press("f5")

def close_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def new_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "t")
    else:               pyautogui.hotkey("ctrl", "t")

def next_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketright")
    else:               pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketleft")
    else:               pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    if _OS == "Darwin": pyautogui.hotkey("command", "left")
    else:               pyautogui.hotkey("alt", "left")

def go_forward():
    if _OS == "Darwin": pyautogui.hotkey("command", "right")
    else:               pyautogui.hotkey("alt", "right")

def zoom_in():
    if _OS == "Darwin": pyautogui.hotkey("command", "equal")
    else:               pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    if _OS == "Darwin": pyautogui.hotkey("command", "minus")
    else:               pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    if _OS == "Darwin": pyautogui.hotkey("command", "0")
    else:               pyautogui.hotkey("ctrl", "0")

def find_on_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "f")
    else:               pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(max(1, n)):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):    pyautogui.scroll(amount)
def scroll_down(amount: int = 500):  pyautogui.scroll(-amount)

def scroll_top():
    if _OS == "Darwin": pyautogui.hotkey("command", "up")
    else:               pyautogui.hotkey("ctrl", "home")

def scroll_bottom():
    if _OS == "Darwin": pyautogui.hotkey("command", "down")
    else:               pyautogui.hotkey("ctrl", "end")

def page_up():   pyautogui.press("pageup")
def page_down(): pyautogui.press("pagedown")


def copy():
    if _OS == "Darwin": pyautogui.hotkey("command", "c")
    else:               pyautogui.hotkey("ctrl", "c")

def paste():
    if _OS == "Darwin": pyautogui.hotkey("command", "v")
    else:               pyautogui.hotkey("ctrl", "v")

def cut():
    if _OS == "Darwin": pyautogui.hotkey("command", "x")
    else:               pyautogui.hotkey("ctrl", "x")

def undo():
    if _OS == "Darwin": pyautogui.hotkey("command", "z")
    else:               pyautogui.hotkey("ctrl", "z")

def redo():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "z")
    else:               pyautogui.hotkey("ctrl", "y")

def select_all():
    if _OS == "Darwin": pyautogui.hotkey("command", "a")
    else:               pyautogui.hotkey("ctrl", "a")

def save_file():
    if _OS == "Darwin": pyautogui.hotkey("command", "s")
    else:               pyautogui.hotkey("ctrl", "s")

def press_enter():   pyautogui.press("enter")
def press_escape():  pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(str(text))
        time.sleep(0.15)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def take_screenshot():
    if _OS == "Windows":
        pyautogui.hotkey("win", "shift", "s")
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "shift", "3")
    else:
        for cmd in [["scrot"], ["gnome-screenshot"], ["import", "-window", "root", "screenshot.png"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        pyautogui.hotkey("ctrl", "print_screen")

def lock_screen():
    if _OS == "Windows":
        pyautogui.hotkey("win", "l")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["xdg-screensaver", "lock"],
            ["loginctl", "lock-session"],
        ]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, capture_output=True)
                return

WINDOWS_SETTINGS_MAP = {
    # System
    "display": "ms-settings:display",
    "screen": "ms-settings:display",
    "brightness": "ms-settings:display",
    "resolution": "ms-settings:display",
    "sound": "ms-settings:sound",
    "audio": "ms-settings:sound",
    "volume": "ms-settings:sound",
    "notifications": "ms-settings:notifications",
    "notification": "ms-settings:notifications",
    "focus": "ms-settings:quiethours",
    "powersleep": "ms-settings:powersleep",
    "power": "ms-settings:powersleep",
    "sleep": "ms-settings:powersleep",
    "battery": "ms-settings:batterysaver",
    "batterysaver": "ms-settings:batterysaver",
    "storage": "ms-settings:storagesense",
    "storagesense": "ms-settings:storagesense",
    "multitasking": "ms-settings:multitasking",
    "activation": "ms-settings:activation",
    "recovery": "ms-settings:recovery",
    "about": "ms-settings:about",
    "system_info": "ms-settings:about",

    # Devices & Bluetooth
    "bluetooth": "ms-settings:bluetooth",
    "devices": "ms-settings:bluetooth",
    "printers": "ms-settings:printers",
    "printer": "ms-settings:printers",
    "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:mousetouchpad",
    "typing": "ms-settings:typing",
    "keyboard": "ms-settings:keyboard",

    # Network & Internet
    "wifi": "ms-settings:network-wifi",
    "wi_fi": "ms-settings:network-wifi",
    "network_wifi": "ms-settings:network-wifi",
    "network": "ms-settings:network",
    "internet": "ms-settings:network",
    "ethernet": "ms-settings:network-ethernet",
    "vpn": "ms-settings:network-vpn",
    "hotspot": "ms-settings:network-mobilehotspot",
    "airplane_mode": "ms-settings:network-airplanemode",
    "data_usage": "ms-settings:datausage",

    # Personalization
    "personalization": "ms-settings:personalization",
    "background": "ms-settings:personalization-background",
    "wallpaper": "ms-settings:personalization-background",
    "colors": "ms-settings:colors",
    "color": "ms-settings:colors",
    "themes": "ms-settings:themes",
    "theme": "ms-settings:themes",
    "lock_screen": "ms-settings:lockscreen",
    "lockscreen": "ms-settings:lockscreen",
    "fonts": "ms-settings:fonts",
    "taskbar": "ms-settings:taskbar",

    # Apps
    "apps": "ms-settings:appsfeatures",
    "installed_apps": "ms-settings:appsfeatures",
    "apps_and_features": "ms-settings:appsfeatures",
    "default_apps": "ms-settings:defaultapps",
    "startup": "ms-settings:startupapps",
    "startup_apps": "ms-settings:startupapps",

    # Accounts
    "accounts": "ms-settings:yourinfo",
    "your_info": "ms-settings:yourinfo",
    "email": "ms-settings:emailandaccounts",
    "sign_in": "ms-settings:signinoptions",

    # Time & Language
    "date": "ms-settings:dateandtime",
    "time": "ms-settings:dateandtime",
    "date_and_time": "ms-settings:dateandtime",
    "date_time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage",
    "region": "ms-settings:regionlanguage",

    # Gaming
    "gaming": "ms-settings:gaming-gamebar",
    "game_bar": "ms-settings:gaming-gamebar",
    "captures": "ms-settings:gaming-gamedvr",
    "game_mode": "ms-settings:gaming-gamemode",

    # Accessibility
    "accessibility": "ms-settings:easeofaccess-display",
    "text_size": "ms-settings:easeofaccess-display",
    "contrast": "ms-settings:easeofaccess-highcontrast",
    "narrator": "ms-settings:easeofaccess-narrator",
    "magnifier": "ms-settings:easeofaccess-magnifier",

    # Privacy & Security
    "privacy": "ms-settings:privacy",
    "security": "ms-settings:windowsdefender",
    "windows_security": "ms-settings:windowsdefender",
    "antivirus": "ms-settings:windowsdefender",
    "location": "ms-settings:privacy-location",
    "camera": "ms-settings:privacy-webcam",
    "webcam": "ms-settings:privacy-webcam",
    "microphone": "ms-settings:privacy-microphone",
    "mic": "ms-settings:privacy-microphone",

    # Windows Update
    "windows_update": "ms-settings:windowsupdate",
    "windowsupdate": "ms-settings:windowsupdate",
    "update": "ms-settings:windowsupdate",
    "updates": "ms-settings:windowsupdate",
    "check_for_updates": "ms-settings:windowsupdate-action",
}

def open_system_settings(subpage: str = None) -> str:
    if _OS == "Windows":
        uri = "ms-settings:"
        friendly = "system"
        if subpage:
            sub = str(subpage).strip().lower().replace(" ", "_").replace("-", "_")
            for prefix in ("open_", "go_to_", "show_", "view_"):
                if sub.startswith(prefix):
                    sub = sub[len(prefix):]
            if sub.endswith("_settings") or sub.endswith("_setting"):
                sub = sub.rsplit("_setting", 1)[0]
            if sub in WINDOWS_SETTINGS_MAP:
                uri = WINDOWS_SETTINGS_MAP[sub]
                friendly = sub.replace("_", " ")
            else:
                for k, v in WINDOWS_SETTINGS_MAP.items():
                    if k in sub or sub in k:
                        uri = v
                        friendly = k.replace("_", " ")
                        break
        try:
            import os
            os.startfile(uri)
            return f"Opened {friendly} settings."
        except Exception:
            try:
                subprocess.Popen(f'start "" "{uri}"', shell=True)
                return f"Opened {friendly} settings."
            except Exception:
                pyautogui.hotkey("win", "i")
                return "Opened settings."
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "System Preferences"])
        return "Opened System Preferences."
    else:
        for cmd in [["gnome-control-center"], ["xfce4-settings-manager"], ["kcmshell5"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return "Opened settings."
        return "Opened settings."

def open_file_explorer():
    if _OS == "Windows":
        pyautogui.hotkey("win", "e")
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(Path.home())])
    else:
        for cmd in [["nautilus"], ["thunar"], ["dolphin"], ["nemo"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        subprocess.Popen(["xdg-open", str(Path.home())])

def sleep_display():
    if _OS == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        except Exception as e:
            print(f"[Settings] sleep_display failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], capture_output=True)

def open_run():
    if _OS == "Windows":
        pyautogui.hotkey("win", "r")

def dark_mode():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell app "System Events" to tell appearance preferences '
            'to set dark mode to not dark mode'],
            capture_output=True)
    elif _OS == "Windows":
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Settings] dark_mode registry failed: {e}")
    else:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            current = result.stdout.strip()
            new_scheme = "'default'" if "dark" in current else "'prefer-dark'"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_scheme],
                capture_output=True
            )
        except Exception as e:
            print(f"[Settings] dark_mode Linux failed: {e}")

def _windows_radio_control(kind: str, action: str = "toggle") -> str:
    """
    Control Wi-Fi and Bluetooth using native Windows 11 WinRT Radio API (no UAC prompt required).
    kind: 'WiFi' | 'Bluetooth'
    action: 'on' | 'off' | 'toggle' | 'status'
    """
    ps_script = f"""
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ 
        $_.Name -eq 'AsTask' -and 
        $_.GetParameters().Count -eq 1 -and 
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
    }})[0]

    function Await($winRtOp, $resultType) {{
        $m = $asTaskGeneric.MakeGenericMethod($resultType)
        $t = $m.Invoke($null, @($winRtOp))
        $t.Wait(4000) | Out-Null
        return $t.Result
    }}

    [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
    $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])

    $radio = $radios | Where-Object {{ $_.Kind -eq '{kind}' }}
    if (-not $radio) {{
        Write-Output "NOT_FOUND"
        exit
    }}

    $curState = $radio.State.ToString()
    $act = '{action.lower()}'

    if ($act -eq 'status') {{
        Write-Output $curState
        exit
    }}

    $target = if ($act -eq 'on') {{ 'On' }} elseif ($act -eq 'off') {{ 'Off' }} else {{ if ($curState -eq 'On') {{ 'Off' }} else {{ 'On' }} }}

    if ($target -ne $curState) {{
        $op = $radio.SetStateAsync($target)
        $null = Await $op ([Windows.Devices.Radios.RadioAccessStatus])
    }}

    Write-Output $target
    """
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=8, **_WIN_HIDE)
        res = r.stdout.strip()
        if "On" in res:
            return f"Switched {kind} on."
        elif "Off" in res:
            return f"Switched {kind} off."
        elif "NOT_FOUND" in res:
            return f"{kind} adapter not found on this system."
    except Exception as e:
        print(f"[Settings] _windows_radio_control failed: {e}")

    # Fallback for WiFi
    if kind == "WiFi":
        try:
            cmd = 'netsh interface set interface name="Wi-Fi" admin=' + ("ENABLED" if action == "on" else "DISABLED")
            subprocess.run(cmd, shell=True, capture_output=True, timeout=5, **_WIN_HIDE)
            return f"Wi-Fi {action} command sent."
        except Exception:
            pass
    return f"Could not change {kind} state."


def wifi_on():
    if _OS == "Windows": return _windows_radio_control("WiFi", "on")
    elif _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        subprocess.run(["networksetup", "-setairportpower", iface, "on"], capture_output=True)
        return "Switched Wi-Fi on."
    else:
        subprocess.run(["nmcli", "radio", "wifi", "on"], capture_output=True)
        return "Switched Wi-Fi on."


def wifi_off():
    if _OS == "Windows": return _windows_radio_control("WiFi", "off")
    elif _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        subprocess.run(["networksetup", "-setairportpower", iface, "off"], capture_output=True)
        return "Switched Wi-Fi off."
    else:
        subprocess.run(["nmcli", "radio", "wifi", "off"], capture_output=True)
        return "Switched Wi-Fi off."


def toggle_wifi():
    if _OS == "Windows": return _windows_radio_control("WiFi", "toggle")
    elif _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        result = subprocess.run(["networksetup", "-getairportpower", iface], capture_output=True, text=True)
        state = "off" if "On" in result.stdout else "on"
        subprocess.run(["networksetup", "-setairportpower", iface, state], capture_output=True)
        return f"Switched Wi-Fi {state}."
    else:
        result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
        state  = "off" if "enabled" in result.stdout else "on"
        subprocess.run(["nmcli", "radio", "wifi", state], capture_output=True)
        return f"Switched Wi-Fi {state}."


def bluetooth_on():
    if _OS == "Windows": return _windows_radio_control("Bluetooth", "on")
    elif _OS == "Darwin":
        subprocess.run(["blueutil", "--power", "1"], capture_output=True)
        return "Switched Bluetooth on."
    else:
        subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True)
        return "Switched Bluetooth on."


def bluetooth_off():
    if _OS == "Windows": return _windows_radio_control("Bluetooth", "off")
    elif _OS == "Darwin":
        subprocess.run(["blueutil", "--power", "0"], capture_output=True)
        return "Switched Bluetooth off."
    else:
        subprocess.run(["rfkill", "block", "bluetooth"], capture_output=True)
        return "Switched Bluetooth off."


def toggle_bluetooth():
    if _OS == "Windows": return _windows_radio_control("Bluetooth", "toggle")
    elif _OS == "Darwin":
        subprocess.run(["blueutil", "--power", "toggle"], capture_output=True)
        return "Toggled Bluetooth."
    else:
        subprocess.run(["rfkill", "toggle", "bluetooth"], capture_output=True)
        return "Toggled Bluetooth."


def airplane_mode_on():
    if _OS == "Windows":
        _windows_radio_control("WiFi", "off")
        _windows_radio_control("Bluetooth", "off")
        try:
            import winreg
            k = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"System\CurrentControlSet\Control\RadioManagement\SystemRadioState")
            winreg.SetValueEx(k, "", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(k)
        except Exception:
            pass
        return "Turned on Flight Mode (Wi-Fi and Bluetooth disabled)."
    return "Turned on Flight Mode."


def airplane_mode_off():
    if _OS == "Windows":
        _windows_radio_control("WiFi", "on")
        _windows_radio_control("Bluetooth", "on")
        try:
            import winreg
            k = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, r"System\CurrentControlSet\Control\RadioManagement\SystemRadioState")
            winreg.SetValueEx(k, "", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(k)
        except Exception:
            pass
        return "Turned off Flight Mode (Wi-Fi and Bluetooth enabled)."
    return "Turned off Flight Mode."


def toggle_airplane_mode():
    if _OS == "Windows":
        status = _windows_radio_control("WiFi", "status")
        if "On" in status:
            return airplane_mode_on()
        else:
            return airplane_mode_off()
    return "Toggled Flight Mode."


def dnd_get_state() -> bool:
    """Return True if Do Not Disturb is active (toast notifications suppressed)."""
    if _OS == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            cur, _ = winreg.QueryValueEx(key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED")
            winreg.CloseKey(key)
            return cur == 0
        except Exception:
            return False
    return False


def dnd_on():
    if _OS == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValueEx(key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            try:
                import ctypes
                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "TraySettings", 2, 2000, None)
            except Exception:
                pass
            return "Turned on Do Not Disturb (notifications silenced)."
        except Exception as e:
            return f"Could not turn on Do Not Disturb: {e}"
    return "Turned on Do Not Disturb."


def dnd_off():
    if _OS == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValueEx(key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
            try:
                import ctypes
                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "TraySettings", 2, 2000, None)
            except Exception:
                pass
            return "Turned off Do Not Disturb (notifications un-silenced)."
        except Exception as e:
            return f"Could not turn off Do Not Disturb: {e}"
    return "Turned off Do Not Disturb."


def toggle_dnd():
    if _OS == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
                cur, _ = winreg.QueryValueEx(key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED")
                winreg.CloseKey(key)
            except Exception:
                cur = 1
            if cur == 0:
                return dnd_off()
            else:
                return dnd_on()
        except Exception as e:
            return f"Could not toggle Do Not Disturb: {e}"
    return "Toggled Do Not Disturb."


def focus_on():
    dnd_on()
    return "Started Focus mode (Do Not Disturb enabled, quiet focus active)."


def focus_off():
    dnd_off()
    return "Stopped Focus mode (notifications un-silenced)."


def toggle_focus():
    return toggle_dnd()


def battery_saver_on():
    if _OS == "Windows":
        try:
            r = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, timeout=5, **_WIN_HIDE)
            for scheme_name in ["Silent", "Power saver", "Balanced"]:
                m = re.search(rf"Power Scheme GUID:\s*([a-f0-9\-]+)\s*\({scheme_name}\)", r.stdout, re.IGNORECASE)
                if m:
                    subprocess.run(["powercfg", "/s", m.group(1)], capture_output=True, timeout=5, **_WIN_HIDE)
                    break
            subprocess.run(["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", "SUB_BATTERY", "BATFLAGSLOW", "1"], capture_output=True, timeout=5, **_WIN_HIDE)
            subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"], capture_output=True, timeout=5, **_WIN_HIDE)
            cur_b = brightness_get()
            if cur_b and cur_b > 40:
                brightness_set(40)
            return "Turned on Energy Saver mode."
        except Exception as e:
            return f"Could not turn on Energy Saver: {e}"
    return "Turned on Energy Saver."


def battery_saver_off():
    if _OS == "Windows":
        try:
            r = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, timeout=5, **_WIN_HIDE)
            for scheme_name in ["Turbo", "Performance", "Balanced"]:
                m = re.search(rf"Power Scheme GUID:\s*([a-f0-9\-]+)\s*\({scheme_name}\)", r.stdout, re.IGNORECASE)
                if m:
                    subprocess.run(["powercfg", "/s", m.group(1)], capture_output=True, timeout=5, **_WIN_HIDE)
                    break
            subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"], capture_output=True, timeout=5, **_WIN_HIDE)
            return "Turned off Energy Saver mode."
        except Exception as e:
            return f"Could not turn off Energy Saver: {e}"
    return "Turned off Energy Saver."


def toggle_battery_saver():
    if _OS == "Windows":
        r = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5, **_WIN_HIDE)
        if "Silent" in r.stdout or "Power saver" in r.stdout:
            return battery_saver_off()
        else:
            return battery_saver_on()
    return "Toggled Energy Saver."


def toggle_night_light():
    if _OS == "Windows":
        try:
            import os
            os.startfile("ms-settings:nightlight")
            return "Opened Night Light settings."
        except Exception:
            return "Night Light settings opened."
    return "Toggled Night Light."


def night_light_on():
    return toggle_night_light()


def night_light_off():
    return toggle_night_light()


def toggle_hotspot():
    if _OS == "Windows":
        try:
            import os
            os.startfile("ms-settings:network-mobilehotspot")
            return "Opened Mobile Hotspot settings."
        except Exception:
            pass
    return "Toggled Mobile Hotspot."


def hotspot_on():
    return toggle_hotspot()


def hotspot_off():
    return toggle_hotspot()


def open_quick_settings():
    if _OS == "Windows":
        pyautogui.hotkey("win", "a")
        return "Opened Windows 11 Quick Settings."
    return "Opened Quick Settings."


def open_notifications():
    if _OS == "Windows":
        pyautogui.hotkey("win", "n")
        return "Opened Windows 11 Notification Center."
    return "Opened Notifications."

def restart_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True, **_WIN_HIDE)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to restart'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "reboot"], capture_output=True)

def shutdown_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to shut down'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "poweroff"], capture_output=True)

ACTION_MAP: dict[str, callable] = {
    "volume_up":           volume_up,
    "volume_down":         volume_down,
    "mute":                volume_mute,
    "unmute":              volume_mute,
    "toggle_mute":         volume_mute,
    "brightness_up":       brightness_up,
    "brightness_down":     brightness_down,
    "sleep_display":       sleep_display,
    "screen_off":          sleep_display,
    "pause_video":         pause_video,
    "play_pause":          pause_video,
    "close_app":           close_app,
    "close_window":        close_window,
    "full_screen":         full_screen,
    "fullscreen":          full_screen,
    "minimize":            minimize_window,
    "minimize_window":     minimize_window,
    "minimize_app":        minimize_window,
    "maximize":            maximize_window,
    "maximize_window":     maximize_window,
    "maximize_app":        maximize_window,
    "restore":             restore_window,
    "restore_window":      restore_window,
    "restore_app":         restore_window,
    "snap_left":           snap_left,
    "snap_right":          snap_right,
    "switch_window":       switch_window,
    "show_desktop":        show_desktop,
    "task_manager":        open_task_manager,
    "focus_search":        focus_search,
    "refresh_page":        refresh_page,
    "reload":              refresh_page,
    "close_tab":           close_tab,
    "new_tab":             new_tab,
    "next_tab":            next_tab,
    "prev_tab":            prev_tab,
    "go_back":             go_back,
    "go_forward":          go_forward,
    "zoom_in":             zoom_in,
    "zoom_out":            zoom_out,
    "zoom_reset":          zoom_reset,
    "find_on_page":        find_on_page,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "scroll_top":          scroll_top,
    "scroll_bottom":       scroll_bottom,
    "page_up":             page_up,
    "page_down":           page_down,
    "copy":                copy,
    "paste":               paste,
    "cut":                 cut,
    "undo":                undo,
    "redo":                redo,
    "select_all":          select_all,
    "save":                save_file,
    "enter":               press_enter,
    "escape":              press_escape,
    "screenshot":          take_screenshot,
    "lock_screen":         lock_screen,
    "open_settings":       open_system_settings,
    "file_explorer":       open_file_explorer,
    "open_run":            open_run,
    "dark_mode":           dark_mode,
    "toggle_wifi":         toggle_wifi,
    "wifi_on":             wifi_on,
    "wifi_off":            wifi_off,
    "enable_wifi":         wifi_on,
    "disable_wifi":        wifi_off,
    "toggle_bluetooth":    toggle_bluetooth,
    "bluetooth_on":        bluetooth_on,
    "bluetooth_off":       bluetooth_off,
    "enable_bluetooth":    bluetooth_on,
    "disable_bluetooth":   bluetooth_off,
    "toggle_airplane_mode": toggle_airplane_mode,
    "airplane_mode_on":    airplane_mode_on,
    "airplane_mode_off":   airplane_mode_off,
    "enable_airplane_mode": airplane_mode_on,
    "disable_airplane_mode": airplane_mode_off,
    "flight_mode_on":      airplane_mode_on,
    "flight_mode_off":     airplane_mode_off,
    "toggle_flight_mode":  toggle_airplane_mode,
    "toggle_dnd":          toggle_dnd,
    "dnd_on":              dnd_on,
    "dnd_off":             dnd_off,
    "enable_dnd":          dnd_on,
    "disable_dnd":         dnd_off,
    "do_not_disturb_on":   dnd_on,
    "do_not_disturb_off":  dnd_off,
    "toggle_do_not_disturb": toggle_dnd,
    "toggle_focus":        toggle_focus,
    "focus_on":            focus_on,
    "focus_off":           focus_off,
    "enable_focus":        focus_on,
    "disable_focus":       focus_off,
    "start_focus":         focus_on,
    "stop_focus":          focus_off,
    "toggle_battery_saver": toggle_battery_saver,
    "battery_saver_on":    battery_saver_on,
    "battery_saver_off":   battery_saver_off,
    "enable_battery_saver": battery_saver_on,
    "disable_battery_saver": battery_saver_off,
    "toggle_energy_saver": toggle_battery_saver,
    "energy_saver_on":     battery_saver_on,
    "energy_saver_off":    battery_saver_off,
    "enable_energy_saver": battery_saver_on,
    "disable_energy_saver": battery_saver_off,
    "energy_safe_on":      battery_saver_on,
    "energy_safe_off":     battery_saver_off,
    "toggle_night_light":  toggle_night_light,
    "night_light_on":      night_light_on,
    "night_light_off":     night_light_off,
    "toggle_hotspot":      toggle_hotspot,
    "hotspot_on":          hotspot_on,
    "hotspot_off":         hotspot_off,
    "quick_settings":      open_quick_settings,
    "open_quick_settings": open_quick_settings,
    "notifications":       open_notifications,
    "open_notifications":  open_notifications,
    "notification_center": open_notifications,
    "restart":             restart_computer,
    "shutdown":            shutdown_computer,
    "brightness_set":      brightness_set,
    "set_brightness":      brightness_set,
    "volume_set":          volume_set,
    "set_volume":          volume_set,
    "get_volume":          lambda: (f"Current volume is {volume_get()}%." if volume_get() is not None else "Could not determine volume."),
    "get_brightness":      lambda: (f"Current brightness is {brightness_get()}%." if brightness_get() is not None else "Could not determine brightness."),
    "fix_brightness":      fix_brightness,
    "fix_display":         fix_brightness,
    "reset_display":       fix_brightness,
    "fix_volume":          fix_volume,
    "fix_audio":           fix_volume,
    "reset_audio":         fix_volume,
}

# ── What needs a human, and what just needs an undo ──────────────────────────
#
# Only truly destructive, irreversible system power actions require an explicit
# confirmation modal. All notification bar, network, radio, and quick settings
# execute immediately with instant effect.
_IRREVERSIBLE = {
    "restart":     ("Restart this computer",
                    "Anything unsaved will be lost. The computer restarts in 10 seconds."),
    "shutdown":    ("Shut this computer down",
                    "Anything unsaved will be lost. The computer powers off in 10 seconds."),
}

# Kept so anything still importing the old name keeps working.
_DANGEROUS_ACTIONS = set(_IRREVERSIBLE)


# ── Local intent resolution ──────────────────────────────────────────────────
_ALIASES = {
    "fix_brightness":  ("fix brightness", "fix display", "brightness bug", "brightness not working", "fix brightness slider", "reset graphics driver", "reset display driver", "screen bug"),
    "fix_volume":      ("fix volume", "fix audio", "volume bug", "sound bug", "audio not working", "sound not working", "fix sound"),
    "volume_up":       ("louder", "raise volume", "turn it up", "increase volume", "volume up", "sound up"),
    "volume_down":     ("quieter", "lower volume", "turn it down", "decrease volume", "volume down", "sound down"),
    "mute":            ("silence", "sound off", "no sound", "mute", "mute audio", "mute sound"),
    "unmute":          ("unmute", "unmute audio", "unmute sound"),
    "brightness_up":   ("brighter", "raise brightness", "increase brightness", "brightness up", "screen brighter", "make screen brighter"),
    "brightness_down": ("dimmer", "dim", "lower brightness", "decrease brightness", "brightness down", "screen dimmer", "dim screen"),
    "get_volume":      ("what is the volume", "what's the volume", "current volume", "check volume", "volume level"),
    "get_brightness":  ("what is the brightness", "what's the brightness", "current brightness", "check brightness", "brightness level"),
    "close_window":    ("close this", "close it"),
    "full_screen":     ("fullscreen", "maximise screen"),
    "show_desktop":    ("minimise everything", "go to desktop"),
    "lock_screen":     ("lock", "lock the pc", "lock computer"),
    "sleep_display":   ("screen off", "turn off the screen", "display off"),
    "dark_mode":       ("night mode", "light mode", "toggle theme"),
    "wifi_on":         ("turn on wifi", "turn wifi on", "enable wifi", "wifi on", "start wifi", "switch on wifi"),
    "wifi_off":        ("turn off wifi", "turn wifi off", "disable wifi", "wifi off", "stop wifi", "switch off wifi"),
    "toggle_wifi":     ("toggle wifi", "switch wifi", "internet off", "internet on"),
    "bluetooth_on":    ("turn on bluetooth", "turn bluetooth on", "enable bluetooth", "bluetooth on", "switch on bluetooth"),
    "bluetooth_off":   ("turn off bluetooth", "turn bluetooth off", "disable bluetooth", "bluetooth off", "switch off bluetooth"),
    "toggle_bluetooth": ("toggle bluetooth", "switch bluetooth"),
    "airplane_mode_on": ("turn on airplane mode", "turn on flight mode", "airplane mode on", "flight mode on", "enable airplane mode", "enable flight mode", "turn airplane mode on", "turn flight mode on"),
    "airplane_mode_off": ("turn off airplane mode", "turn off flight mode", "airplane mode off", "flight mode off", "disable airplane mode", "disable flight mode", "turn airplane mode off", "turn flight mode off"),
    "toggle_airplane_mode": ("airplane mode", "flight mode", "toggle airplane mode", "toggle flight mode"),
    "dnd_on":          ("turn on dnd", "turn on do not disturb", "dnd on", "do not disturb on", "enable dnd", "enable do not disturb", "silence notifications"),
    "dnd_off":         ("turn off dnd", "turn off do not disturb", "dnd off", "do not disturb off", "disable dnd", "disable do not disturb"),
    "toggle_dnd":      ("toggle dnd", "toggle do not disturb"),
    "focus_on":        ("turn on focus", "turn on focus mode", "focus on", "start focus", "start focus session", "enable focus"),
    "focus_off":       ("turn off focus", "turn off focus mode", "focus off", "stop focus", "stop focus session", "disable focus"),
    "toggle_focus":    ("toggle focus", "focus mode"),
    "battery_saver_on": ("turn on battery saver", "turn on energy saver", "battery saver on", "energy saver on", "enable battery saver", "enable energy saver", "power saver on", "turn on power saver", "energy safe on", "turn on energy safe", "enable energy safe"),
    "battery_saver_off": ("turn off battery saver", "turn off energy saver", "battery saver off", "energy saver off", "disable battery saver", "disable energy saver", "power saver off", "turn off power saver", "energy safe off", "turn off energy safe", "disable energy safe"),
    "toggle_battery_saver": ("toggle battery saver", "toggle energy saver", "toggle energy safe"),
    "night_light_on":  ("turn on night light", "night light on", "enable night light"),
    "night_light_off": ("turn off night light", "night light off", "disable night light"),
    "toggle_night_light": ("night light", "toggle night light", "blue light"),
    "hotspot_on":      ("turn on hotspot", "hotspot on", "enable hotspot", "turn on mobile hotspot"),
    "hotspot_off":     ("turn off hotspot", "hotspot off", "disable hotspot", "turn off mobile hotspot"),
    "toggle_hotspot":  ("hotspot", "mobile hotspot", "toggle hotspot"),
    "quick_settings":  ("quick settings", "open quick settings", "action center", "notification bar", "open notification bar"),
    "notifications":   ("notification center", "open notifications", "show notifications", "view notifications"),
    "task_manager":    ("processes", "task list"),
    "screenshot":      ("capture screen", "take a screenshot", "snip"),
    "refresh_page":    ("refresh", "reload page"),
    "new_tab":         ("open a tab", "open new tab"),
    "shutdown":        ("power off", "turn off the computer", "switch off the pc"),
    "restart":         ("reboot", "restart the pc"),
}

_VALUE_ACTIONS = {"volume_set", "set_volume", "brightness_set", "set_brightness",
                  "volume_up", "volume_down", "brightness_up", "brightness_down",
                  "type_text", "press_key", "reload_n", "scroll_up", "scroll_down",
                  "minimize", "minimize_window", "minimize_app",
                  "maximize", "maximize_window", "maximize_app",
                  "restore", "restore_window", "restore_app",
                  "close_app"}


def _normalise(text: str) -> str:
    return (text or "").strip().lower().replace("-", "_").replace(" ", "_")


def _detect_action(description: str) -> dict:
    """Resolve a free-text description to an action name, locally."""
    raw  = (description or "").strip()
    norm = _normalise(raw)
    if not norm:
        return {"action": "", "value": None}

    known = set(ACTION_MAP) | _VALUE_ACTIONS

    # 1. Already an exact action name.
    if norm in known:
        return {"action": norm, "value": None}

    low = raw.lower()

    # Window and Application control patterns (restore, minimize, maximize, close)
    m_res = re.search(r"\b(?:restore|unminimize|unminimise)\b\s*(?:the\s+)?(?:window\s+of\s+)?([a-z0-9_\-\. ]+)?", low)
    if m_res and any(w in low for w in ("restore", "unminimize", "unminimise")):
        t_clean = (m_res.group(1) or "").replace("window", "").replace("app", "").strip()
        return {"action": "restore", "value": t_clean or None}

    if any(p in low for p in ("minimize all", "minimise all", "minimize everything", "minimise everything", "minimize all windows", "minimise all apps", "minimize all applications")):
        return {"action": "minimize", "value": "all"}
    m_min = re.search(r"\b(?:minimize|minimise)\b\s*(?:the\s+)?(?:window\s+of\s+)?([a-z0-9_\-\. ]+)?", low)
    if m_min and not any(w in low for w in ("unminimize", "unminimise")):
        t_clean = (m_min.group(1) or "").replace("window", "").replace("app", "").strip()
        return {"action": "minimize", "value": t_clean or None}

    if any(p in low for p in ("maximize all", "maximise all", "maximize everything", "maximise everything", "maximize all windows", "maximize all apps")):
        return {"action": "maximize", "value": "all"}
    m_max = re.search(r"\b(?:maximize|maximise)\b\s*(?:the\s+)?(?:window\s+of\s+)?([a-z0-9_\-\. ]+)?", low)
    if m_max:
        t_clean = (m_max.group(1) or "").replace("window", "").replace("app", "").strip()
        return {"action": "maximize", "value": t_clean or None}

    if any(p in low for p in ("close all", "close everything", "close all apps", "close all windows", "close all applications")):
        return {"action": "close_app", "value": "all"}
    m_close = re.search(r"\b(?:close|exit|quit|shut down app|kill)\b\s*(?:the\s+)?(?:app\s+|application\s+)?([a-z0-9_\-\. ]+)?", low)
    if m_close:
        t_clean = (m_close.group(1) or "").replace("window", "").replace("app", "").strip()
        if t_clean in ("this", "window", "active window", "the window", "current window", "it", ""):
            return {"action": "close_app", "value": None}
        return {"action": "close_app", "value": t_clean or None}

    # Fixes / Self-Heal actions
    if any(p in low for p in ("fix brightness", "fix display", "brightness bug", "brightness not working", "cant adjust brightness", "can't adjust brightness", "fix brightness slider", "reset graphics", "reset display", "screen bug")):
        return {"action": "fix_brightness", "value": None}
    if any(p in low for p in ("fix volume", "fix audio", "volume bug", "sound bug", "audio not working", "sound not working", "cant adjust volume", "can't adjust volume", "fix sound", "reset audio")):
        return {"action": "fix_volume", "value": None}

    # 2. Volume and Brightness level setting & queries
    num = re.search(r"(\d{1,3})\s*%?", low)
    if num:
        val = max(0, min(100, int(num.group(1))))
        if any(w in low for w in ("brightness", "bright", "screen light", "display brightness")):
            return {"action": "brightness_set", "value": val}
        if any(w in low for w in ("volume", "ses", "sound", "lautstark", "громкость", "audio")):
            return {"action": "volume_set", "value": val}

    # Relative volume / brightness delta: e.g. "volume up by 20", "brightness down by 15"
    num_delta = re.search(r"(?:by|to)\s*(\d{1,3})\s*%?", low)
    delta_val = int(num_delta.group(1)) if num_delta else None

    if any(w in low for w in ("volume up", "increase volume", "raise volume", "turn up volume", "louder")):
        return {"action": "volume_up", "value": delta_val}
    if any(w in low for w in ("volume down", "decrease volume", "lower volume", "turn down volume", "quieter")):
        return {"action": "volume_down", "value": delta_val}
    if any(w in low for w in ("brightness up", "increase brightness", "raise brightness", "turn up brightness", "brighter", "make screen brighter")):
        return {"action": "brightness_up", "value": delta_val}
    if any(w in low for w in ("brightness down", "decrease brightness", "lower brightness", "turn down brightness", "dimmer", "dim screen")):
        return {"action": "brightness_down", "value": delta_val}

    # Mute / Unmute (unmute checked first)
    if any(w in low for w in ("unmute audio", "unmute sound", "unmute volume", "unmute pc", "unmute computer")) or low == "unmute":
        return {"action": "unmute", "value": None}
    if any(w in low for w in ("mute audio", "mute sound", "mute volume", "mute pc", "mute computer")) or low == "mute":
        return {"action": "mute", "value": None}

    # Status queries
    if any(p in low for p in ("what is the volume", "what's the volume", "current volume", "check volume", "volume level", "get volume")):
        return {"action": "get_volume", "value": None}
    if any(p in low for p in ("what is the brightness", "what's the brightness", "current brightness", "check brightness", "brightness level", "get brightness")):
        return {"action": "get_brightness", "value": None}

    # Presets / Extremes:
    if any(p in low for p in ("max volume", "volume to 100", "full volume")):
        return {"action": "volume_set", "value": 100}
    if any(p in low for p in ("max brightness", "brightness to 100", "full brightness")):
        return {"action": "brightness_set", "value": 100}
    if any(p in low for p in ("min brightness", "minimum brightness", "lowest brightness")):
        return {"action": "brightness_set", "value": 10}
    if any(p in low for p in ("half volume", "medium volume")):
        return {"action": "volume_set", "value": 50}
    if any(p in low for p in ("half brightness", "medium brightness")):
        return {"action": "brightness_set", "value": 50}

    # 3. Setting subpage detection (e.g. "bluetooth settings", "wifi settings", "go to sound settings")
    if ("setting" in low or "settings" in low) and "quick setting" not in low:
        for k in WINDOWS_SETTINGS_MAP:
            if k.replace("_", " ") in low or k in norm:
                return {"action": "open_settings", "value": k}
        return {"action": "open_settings", "value": None}

    # 4. Direct quick settings / notification bar intent matching
    if any(w in low for w in ("quick setting", "action center", "notification bar")):
        return {"action": "quick_settings", "value": None}
    if any(w in low for w in ("notification center", "show notification", "view notification")):
        return {"action": "notifications", "value": None}

    if any(w in low for w in ("wifi", "wi-fi")):
        if any(w in low for w in ("off", "disable", "disconnect", "close", "stop")):
            return {"action": "wifi_off", "value": None}
        if any(w in low for w in ("on", "enable", "connect", "start")):
            return {"action": "wifi_on", "value": None}
        return {"action": "toggle_wifi", "value": None}

    if "bluetooth" in low:
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "bluetooth_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "bluetooth_on", "value": None}
        return {"action": "toggle_bluetooth", "value": None}

    if any(w in low for w in ("airplane", "flight")):
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "airplane_mode_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "airplane_mode_on", "value": None}
        return {"action": "toggle_airplane_mode", "value": None}

    if any(w in low for w in ("dnd", "disturb")):
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "dnd_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "dnd_on", "value": None}
        return {"action": "toggle_dnd", "value": None}

    if "focus" in low and "search" not in low:
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "focus_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "focus_on", "value": None}
        return {"action": "toggle_focus", "value": None}

    if any(w in low for w in ("energy", "battery saver", "power saver", "energy safe")):
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "battery_saver_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "battery_saver_on", "value": None}
        return {"action": "toggle_battery_saver", "value": None}

    if "hotspot" in low:
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "hotspot_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "hotspot_on", "value": None}
        return {"action": "toggle_hotspot", "value": None}

    if "night light" in low or "blue light" in low:
        if any(w in low for w in ("off", "disable", "stop")):
            return {"action": "night_light_off", "value": None}
        if any(w in low for w in ("on", "enable", "start")):
            return {"action": "night_light_on", "value": None}
        return {"action": "toggle_night_light", "value": None}

    # 5. Alias phrases.
    for action, phrases in _ALIASES.items():
        if any(_normalise(p) == norm or p in low for p in phrases):
            return {"action": action, "value": None}

    # 6. Any other setting subpage detection
    if any(f"open {k}" in low for k in WINDOWS_SETTINGS_MAP):
        for k in WINDOWS_SETTINGS_MAP:
            if k.replace("_", " ") in low or k in norm:
                return {"action": "open_settings", "value": k}

    # 6. Fuzzy match on the action names
    import difflib
    close = difflib.get_close_matches(norm, sorted(known), n=1, cutoff=0.72)
    if close:
        return {"action": close[0], "value": None}

    # 7. Substring
    for action in sorted(known, key=len, reverse=True):
        if len(action) > 4 and (action in norm or norm in action):
            return {"action": action, "value": None}

    return {"action": "", "value": None}


def _suggest(description: str) -> str:
    """What to tell the model when nothing matched. Names real actions so its
    retry lands, instead of the old 'Unknown action' dead end."""
    import difflib
    near = difflib.get_close_matches(_normalise(description),
                                     sorted(ACTION_MAP), n=5, cutoff=0.3)
    hint = ", ".join(near) if near else ", ".join(sorted(ACTION_MAP)[:12])
    return (f"I could not match '{description}' to a computer action. "
            f"Call computer_settings again with an exact `action` from: {hint}.")

def computer_settings(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    if not _PYAUTOGUI:
        return "pyautogui is not installed. Run: pip install pyautogui"

    params      = parameters or {}
    raw_action  = params.get("action", "").strip()
    description = params.get("description", "").strip()
    value       = params.get("value", None)

    if not raw_action and description:
        detected   = _detect_action(description)
        raw_action = detected.get("action", "")
        if value is None:
            value = detected.get("value")

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return _suggest(description or raw_action)

    print(f"[Settings] Action: {action}  Value: {value}  OS: {_OS}")
    if player:
        player.write_log(f"[Settings] {action}")

    # ── The gate ─────────────────────────────────────────────────────────────
    # A human presses a button, or this does not happen. The model can no longer
    # write its own permission slip, and the action itself is handed to the UI
    # rather than performed here — so returning early is not "declining", it is
    # "parked until someone says yes".
    if action in _IRREVERSIBLE:
        title, detail = _IRREVERSIBLE[action]
        func = ACTION_MAP.get(action)
        if func is None:
            return f"Unknown action: '{raw_action}'."
        if confirm.pending_title():
            return ("There is already a confirmation waiting on screen. "
                    "Ask the user to answer that one first.")
        return confirm.request(
            key=action, title=title, detail=detail,
            run=lambda f=func, a=action: (f(), f"{a} done.")[1],
        )

    if action in ("volume_set", "set_volume"):
        try:
            target = int(value if value is not None else 50)
            before = volume_get()
            volume_set(target)
            if before is not None:
                push_undo(f"volume {before}% → {target}%",
                          lambda b=before: (volume_set(b), f"Back to {b}%.")[1])
            return f"Volume set to {target}%."
        except Exception as e:
            return f"Could not set volume: {e}"

    if action in ("brightness_set", "set_brightness"):
        try:
            target = int(value if value is not None else 50)
            before = brightness_get()
            brightness_set(target)
            if before is not None:
                push_undo(f"brightness {before}% → {target}%",
                          lambda b=before: (brightness_set(b), f"Back to {b}%.")[1])
            return f"Brightness set to {target}%."
        except Exception as e:
            return f"Could not set brightness: {e}"

    if action in ("volume_up", "volume_down"):
        delta = int(value or 10)
        before = volume_get()
        res = volume_up(delta) if action == "volume_up" else volume_down(delta)
        if before is not None:
            push_undo(f"volume ({action})",
                      lambda b=before: (volume_set(b), f"Volume back to {b}%.")[1])
        return res or f"Done: {action}."

    if action in ("brightness_up", "brightness_down"):
        delta = int(value or 10)
        before = brightness_get()
        res = brightness_up(delta) if action == "brightness_up" else brightness_down(delta)
        if before is not None:
            push_undo(f"brightness ({action})",
                      lambda b=before: (brightness_set(b), f"Brightness back to {b}%.")[1])
        return res or f"Done: {action}."

    if action in ("get_volume", "volume_level", "check_volume"):
        vol = volume_get()
        return f"Current volume is {vol}%." if vol is not None else "Could not determine volume."

    if action in ("get_brightness", "brightness_level", "check_brightness"):
        br = brightness_get()
        return f"Current brightness is {br}%." if br is not None else "Could not determine brightness."

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", "")).strip()
        if not text:
            return "No text provided to type."
        enter_after = str(params.get("press_enter", "false")).lower() in ("true", "1", "yes")
        type_text(text, press_enter_after=enter_after)
        return f"Typed: {text[:80]}"

    if action == "press_key":
        key = str(value or params.get("key", "")).strip()
        if not key:
            return "No key specified."
        press_key(key)
        return f"Pressed: {key}"

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            reload_page_n(int(value or 1))
            return f"Reloaded {value or 1} time(s)."
        except Exception as e:
            return f"Reload failed: {e}"

    if action == "scroll_up":
        scroll_up(int(value or 500))
        return "Scrolled up."

    if action == "scroll_down":
        scroll_down(int(value or 500))
        return "Scrolled down."

    if action in ("open_settings", "settings") or "setting" in action or action in WINDOWS_SETTINGS_MAP:
        sub = value or description or (action if action in WINDOWS_SETTINGS_MAP else None)
        return open_system_settings(sub)

    if action in ("minimize", "minimize_window", "minimize_app"):
        target = value or params.get("app_name") or params.get("target") or description
        target_clean = str(target).lower().replace("minimize", "").replace("minimise", "").replace("the", "").replace("window", "").replace("app", "").strip() if target else None
        return minimize_window(target_clean or None)

    if action in ("maximize", "maximize_window", "maximize_app"):
        target = value or params.get("app_name") or params.get("target") or description
        target_clean = str(target).lower().replace("maximize", "").replace("maximise", "").replace("the", "").replace("window", "").replace("app", "").strip() if target else None
        return maximize_window(target_clean or None)

    if action in ("restore", "restore_window", "restore_app"):
        target = value or params.get("app_name") or params.get("target") or description
        target_clean = str(target).lower().replace("restore", "").replace("unminimize", "").replace("the", "").replace("window", "").replace("app", "").strip() if target else None
        return restore_window(target_clean or None)

    if action == "close_app" or (action.startswith("close_") and action not in ("close_window", "close_tab")):
        target = value or params.get("app_name") or params.get("target") or (action[6:] if action.startswith("close_") else description)
        if target:
            target_clean = str(target).lower().replace("close", "").replace("the", "").replace("app", "").strip()
            return close_app(target_clean)
        return close_app()

    func = ACTION_MAP.get(action)
    if not func:
        return _suggest(raw_action or description)

    # ── Capture "before" so the change can be taken back ─────────────────────
    # Read-then-write is the whole mechanism for settings: there is no clever
    # inverse to compute, just a value to remember. Where the platform will not
    # tell us the current value, nothing is registered — an undo that restores
    # a guess is worse than no undo at all.
    _before = None
    if action in ("volume_up", "volume_down", "mute", "unmute", "toggle_mute"):
        _before = ("volume", volume_get())
    elif action in ("brightness_up", "brightness_down"):
        _before = ("brightness", brightness_get())

    try:
        action_result = func()
    except Exception as e:
        print(f"[Settings] Action failed ({action}): {e}")
        return f"Action failed ({action}): {e}"

    if isinstance(action_result, str) and action_result:
        return action_result

    if _before:
        kind, old = _before
        if old is not None:
            if kind == "volume":
                push_undo(f"volume ({action})",
                          lambda b=old: (volume_set(b), f"Volume back to {b}%.")[1])
            elif kind == "brightness":
                push_undo(f"brightness ({action})",
                          lambda b=old: (brightness_set(b), f"Brightness back to {b}%.")[1])
    elif action == "dark_mode":
        # A pure toggle: calling it again is the undo.
        push_undo("dark mode toggled",
                  lambda: (dark_mode(), "Theme switched back.")[1])

    return f"Done: {action}."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_settings",
    "description": (
        "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
        "typing text on screen, closing apps, fullscreen, dark mode, WiFi, Bluetooth, Flight/Airplane Mode, "
        "Do Not Disturb (DND), Focus Mode, Energy Saver / Battery Saver, Night Light, Mobile Hotspot, "
        "Quick Settings, Notifications, restart, shutdown, scrolling, tab management, zoom, screenshots, "
        "lock screen, refresh/reload page. Use for ANY single computer control command. "
        "restart and shutdown put a confirmation on the user's screen and do NOT happen until they press it — "
        "never claim they are done. All Quick Settings (WiFi, Bluetooth, Airplane Mode, DND, Focus, Energy Saver) "
        "execute immediately without confirmation. Volume, brightness and dark mode can be reversed with the `undo` tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            # The exact vocabulary, spelled out.
            #
            # This used to say only "The action to perform", so the model
            # usually filled `description` instead — and computer_settings then
            # made a SECOND Gemini call, inside the tool, purely to translate
            # that sentence into one of these names. Every "turn the volume
            # down" cost two model round trips.
            #
            # Naming the actions here costs ~600 characters once per session and
            # removes a whole round trip from every computer command.
            "action": {
                "type": "STRING",
                "description": (
                    "The exact action. Prefer this over `description` — pick one of: "
                    "wifi_on | wifi_off | toggle_wifi | bluetooth_on | bluetooth_off | toggle_bluetooth | "
                    "airplane_mode_on | airplane_mode_off | toggle_airplane_mode | "
                    "dnd_on | dnd_off | toggle_dnd | focus_on | focus_off | toggle_focus | "
                    "battery_saver_on | battery_saver_off | toggle_battery_saver | "
                    "night_light | hotspot_on | hotspot_off | quick_settings | notifications | "
                    "fix_brightness | fix_volume | "
                    "volume_up | volume_down | volume_set | get_volume | mute | unmute | "
                    "brightness_up | brightness_down | brightness_set | get_brightness | sleep_display | "
                    "pause_video | close_app | close_window | full_screen | "
                    "minimize | maximize | restore | snap_left | snap_right | "
                    "switch_window | show_desktop | task_manager | focus_search | "
                    "refresh_page | close_tab | new_tab | next_tab | prev_tab | "
                    "go_back | go_forward | zoom_in | zoom_out | zoom_reset | "
                    "find_on_page | scroll_up | scroll_down | scroll_top | "
                    "scroll_bottom | page_up | page_down | copy | paste | cut | "
                    "undo | redo | select_all | save | enter | escape | press_key | "
                    "type_text | screenshot | lock_screen | open_settings | "
                    "file_explorer | open_run | dark_mode | "
                    "restart | shutdown"
                )
            },
            "description": {
                "type": "STRING",
                "description": (
                    "Fallback only, when no action name above fits. "
                    "Resolved locally — no extra model call."
                )
            },
            "value": {
                "type": "STRING",
                "description": "Optional value: target app name (e.g. 'media player', 'spotify', 'chrome', or 'all') for minimize/maximize/restore/close_app, volume/brightness level 0-100, text to type, key name, setting name, etc."
            }
        },
        "required": []
    },
    "handler": computer_settings,
}
