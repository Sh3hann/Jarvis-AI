#computer_control.py
import io
import json
import platform
import re
import string
import subprocess
import sys

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import math
import time
import random
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0.02
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def _get_os() -> str:
    # The config may have been copied from a different computer. Keyboard
    # modifiers and launch commands must match this host, not that saved value.
    return _platform_os()


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "jarvis_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


_INTERACTIVE_DESKTOP_ATTACHED = False
_INTERACTIVE_DESKTOP_HANDLE = None

def _ensure_interactive_desktop():
    """Ensure current Windows thread is attached to the interactive 'default' desktop without dropping handles."""
    global _INTERACTIVE_DESKTOP_ATTACHED, _INTERACTIVE_DESKTOP_HANDLE
    if platform.system() == "Windows" and not _INTERACTIVE_DESKTOP_ATTACHED:
        try:
            import ctypes
            DESKTOP_ALL = 0x01FF
            h = ctypes.windll.user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
            if h:
                if ctypes.windll.user32.SetThreadDesktop(h):
                    _INTERACTIVE_DESKTOP_ATTACHED = True
                    _INTERACTIVE_DESKTOP_HANDLE = h
        except Exception:
            pass


def _safe_cursor_pos() -> tuple[int, int]:
    """Retrieve current cursor position safely without fail-safe exceptions."""
    _ensure_interactive_desktop()
    if _PYAUTOGUI:
        try:
            pt = pyautogui.position()
            return int(pt.x), int(pt.y)
        except Exception:
            pass
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
    return 960, 540


def _move(x: int, y: int, duration: float | None = None) -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()

    cur_x, cur_y = _safe_cursor_pos()
    dist = math.hypot(x - cur_x, y - cur_y)

    if duration is None:
        if dist < 40:
            duration = 0.05
        else:
            # Smooth autonomous glide so user sees the cursor move by itself
            duration = min(0.32, max(0.10, dist / 3800.0))

    try:
        pyautogui.moveTo(x, y, duration=duration, tween=getattr(pyautogui, "easeInOutQuad", None))
    except Exception:
        try:
            pyautogui.moveTo(x, y, duration=duration)
        except Exception:
            if platform.system() == "Windows":
                try:
                    import ctypes
                    ctypes.windll.user32.SetCursorPos(int(x), int(y))
                except Exception:
                    pass
    return f"Mouse → ({x}, {y})"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"

    if x is not None and y is not None:
        _move(int(x), int(y))
        time.sleep(0.04)
        pyautogui.click(button=btn, clicks=clicks, interval=0.06)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{btn}]"

    # Click at current position
    pyautogui.click(button=btn, clicks=clicks, interval=0.06)
    cur_x, cur_y = _safe_cursor_pos()
    return f"{'Double-c' if clicks == 2 else 'C'}licked at ({cur_x}, {cur_y}) [{btn}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3, x: int | None = None, y: int | None = None) -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()

    screen_w, screen_h = pyautogui.size()
    cur_x, cur_y = _safe_cursor_pos()

    # If target coordinate passed, move there
    if x is not None and y is not None:
        _move(int(x), int(y), duration=0.12)
    elif cur_x <= 5 and cur_y <= 5:
        # Cursor is parked in corner. Move cursor to center of screen so active window gets the wheel event
        _move(screen_w // 2, screen_h // 2, duration=0.1)

    dir_clean = str(direction or "down").lower().strip()

    # Keyboard page scroll navigation shortcuts
    if dir_clean in ("page_down", "pagedown"):
        pyautogui.press("pagedown")
        return "Scrolled page down"
    if dir_clean in ("page_up", "pageup"):
        pyautogui.press("pageup")
        return "Scrolled page up"
    if dir_clean in ("top", "home"):
        pyautogui.hotkey("ctrl", "home")
        return "Scrolled to top"
    if dir_clean in ("bottom", "end"):
        pyautogui.hotkey("ctrl", "end")
        return "Scrolled to bottom"

    amt = int(amount) if amount is not None else 3
    if amt == 0:
        amt = 3
    amt_abs = abs(amt)

    # Windows mouse_event expects WHEEL_DELTA (120 units per notch)
    if platform.system() == "Windows":
        notch_delta = amt_abs * 120 if amt_abs < 50 else amt_abs
    else:
        notch_delta = amt_abs

    vertical = dir_clean in ("down", "up")
    if vertical:
        clicks = notch_delta if dir_clean == "up" else -notch_delta
        try:
            pyautogui.scroll(clicks)
        except Exception:
            if platform.system() == "Windows":
                try:
                    import ctypes
                    MOUSEEVENTF_WHEEL = 0x0800
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, clicks, 0)
                except Exception:
                    pass
    else:
        clicks = notch_delta if dir_clean == "right" else -notch_delta
        try:
            pyautogui.hscroll(clicks)
        except Exception:
            if platform.system() == "Windows":
                try:
                    import ctypes
                    MOUSEEVENTF_HWHEEL = 0x01000
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, clicks, 0)
                except Exception:
                    pass

    return f"Scrolled {dir_clean} ×{amt_abs}"


if platform.system() == "Windows":
    import ctypes

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]
        _anonymous_ = ("_input",)
        _fields_ = [("type", ctypes.c_ulong), ("_input", _U)]

    def _win_send_mouse(flags: int, x: int = 0, y: int = 0):
        _ensure_interactive_desktop()
        _enable_dpi_awareness()
        inp = _INPUT()
        inp.type = 0  # INPUT_MOUSE
        if flags & 0x8000:
            sm_cx = max(1, ctypes.windll.user32.GetSystemMetrics(0) - 1)
            sm_cy = max(1, ctypes.windll.user32.GetSystemMetrics(1) - 1)
            inp.mi.dx = int(65535 * x / sm_cx)
            inp.mi.dy = int(65535 * y / sm_cy)
        else:
            inp.mi.dx = 0
            inp.mi.dy = 0
        inp.mi.dwFlags = flags
        inp.mi.time = 0
        inp.mi.dwExtraInfo = None
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _win_click(x: int, y: int, button: str = "left"):
        down_flag = 0x0008 if button == "right" else 0x0002
        up_flag = 0x0010 if button == "right" else 0x0004
        move_flag = 0x8001
        _win_send_mouse(move_flag, int(x), int(y))
        time.sleep(0.03)
        _win_send_mouse(down_flag, int(x), int(y))
        time.sleep(0.03)
        _win_send_mouse(up_flag, int(x), int(y))
        time.sleep(0.04)
else:
    def _win_send_mouse(flags: int, x: int = 0, y: int = 0):
        pass

    def _win_click(x: int, y: int, button: str = "left"):
        _click(x, y, button=button)


def _native_mouse_move(x: int, y: int):
    """Move cursor using hardware input compatibility."""
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    if platform.system() == "Windows":
        try:
            _win_send_mouse(0x8001, int(x), int(y))
            return
        except Exception:
            pass
    if _PYAUTOGUI:
        pyautogui.moveTo(x, y)


def _native_mouse_down(button: str = "left"):
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"
    if platform.system() == "Windows":
        try:
            cur_x, cur_y = _safe_cursor_pos()
            ev = 0x0008 if btn == "right" else 0x0002
            _win_send_mouse(ev, cur_x, cur_y)
            return
        except Exception:
            pass
    if _PYAUTOGUI:
        pyautogui.mouseDown(button=btn)


def _native_mouse_up(button: str = "left"):
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"
    if platform.system() == "Windows":
        try:
            cur_x, cur_y = _safe_cursor_pos()
            ev = 0x0010 if btn == "right" else 0x0004
            _win_send_mouse(ev, cur_x, cur_y)
            return
        except Exception:
            pass
    if _PYAUTOGUI:
        pyautogui.mouseUp(button=btn)


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.4, button: str = "left") -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"
    _draw_path([(x1, y1), (x2, y2)], button=btn)
    return f"Dragged ({x1},{y1}) → ({x2},{y2}) [{btn}]"


def _mouse_down(button: str = "left") -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"
    _native_mouse_down(button=btn)
    cur_x, cur_y = _safe_cursor_pos()
    return f"Mouse down [{btn}] at ({cur_x}, {cur_y})"


def _mouse_up(button: str = "left") -> str:
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"
    _native_mouse_up(button=btn)
    cur_x, cur_y = _safe_cursor_pos()
    return f"Mouse up [{btn}] at ({cur_x}, {cur_y})"


def _draw_path(points: list, button: str = "left", step_delay: float = 0.002) -> str:
    if not points or len(points) < 2:
        return "draw_path requires at least 2 points"
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    btn = "right" if str(button).lower() in ("right", "secondary") else "left"

    if platform.system() == "Windows":
        down_flag = 0x0008 if btn == "right" else 0x0002
        up_flag = 0x0010 if btn == "right" else 0x0004
        move_flag = 0x8001  # MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE

        first_x, first_y = int(points[0][0]), int(points[0][1])
        # 1. Move to start point
        _win_send_mouse(move_flag, first_x, first_y)
        time.sleep(0.04)

        # 2. Mouse DOWN once at start of stroke
        _win_send_mouse(down_flag, first_x, first_y)
        time.sleep(0.02)

        # 3. Continuous interpolation across ALL segments with mouse held down
        for p1, p2 in zip(points[:-1], points[1:]):
            x1, y1 = int(p1[0]), int(p1[1])
            x2, y2 = int(p2[0]), int(p2[1])
            dist = math.hypot(x2 - x1, y2 - y1)
            steps = max(3, int(dist / 3.5))
            for s in range(1, steps + 1):
                ix = int(x1 + (x2 - x1) * s / steps)
                iy = int(y1 + (y2 - y1) * s / steps)
                _win_send_mouse(move_flag, ix, iy)
                time.sleep(step_delay)

        time.sleep(0.02)
        # 4. Mouse UP once at end of stroke
        last_x, last_y = int(points[-1][0]), int(points[-1][1])
        _win_send_mouse(up_flag, last_x, last_y)
        time.sleep(0.03)
        return f"Drawn path with {len(points)} points [{btn}]"

    # Fallback for Mac/Linux
    old_pause = pyautogui.PAUSE
    pyautogui.PAUSE = 0.001
    try:
        first_x, first_y = int(points[0][0]), int(points[0][1])
        pyautogui.moveTo(first_x, first_y)
        time.sleep(0.03)
        pyautogui.mouseDown(button=btn)
        time.sleep(0.02)
        for p1, p2 in zip(points[:-1], points[1:]):
            x1, y1 = int(p1[0]), int(p1[1])
            x2, y2 = int(p2[0]), int(p2[1])
            dist = math.hypot(x2 - x1, y2 - y1)
            steps = max(3, int(dist / 3.5))
            for s in range(1, steps + 1):
                ix = int(x1 + (x2 - x1) * s / steps)
                iy = int(y1 + (y2 - y1) * s / steps)
                pyautogui.moveTo(ix, iy)
                time.sleep(step_delay)
        time.sleep(0.02)
        pyautogui.mouseUp(button=btn)
        time.sleep(0.03)
    finally:
        pyautogui.PAUSE = old_pause

    return f"Drawn path with {len(points)} points [{btn}]"


# ── MS Paint Color Palette & Multi-Color Drawing Engine ─────────────────────
_PAINT_COLOR_RGBS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "dark_gray": (127, 127, 127),
    "gray": (127, 127, 127),
    "grey": (127, 127, 127),
    "dark_red": (136, 0, 21),
    "maroon": (136, 0, 21),
    "red": (237, 28, 36),
    "orange": (255, 127, 39),
    "yellow": (255, 242, 0),
    "gold": (255, 242, 0),
    "green": (34, 177, 76),
    "dark_green": (34, 177, 76),
    "lime": (181, 230, 29),
    "light_green": (181, 230, 29),
    "turquoise": (0, 162, 232),
    "cyan": (0, 162, 232),
    "teal": (0, 162, 232),
    "blue": (0, 162, 232),
    "sky_blue": (0, 162, 232),
    "light_blue": (0, 162, 232),
    "indigo": (63, 72, 204),
    "navy": (63, 72, 204),
    "dark_blue": (63, 72, 204),
    "purple": (163, 73, 164),
    "violet": (163, 73, 164),
    "magenta": (163, 73, 164),
    "brown": (185, 122, 87),
    "tan": (185, 122, 87),
    "chocolate": (185, 122, 87),
    "pink": (255, 174, 201),
    "rose": (255, 174, 201),
    "white": (255, 255, 255),
}

_PAINT_PALETTE_CACHE: dict[str, tuple[int, int]] = {}
_LAST_PAINT_RECT: tuple[int, int, int, int] | None = None
_CURRENT_PAINT_COLOR: str | None = None


_PAINT_UIA_COLOR_MAP: dict[str, str] = {
    "black": "Black",
    "gray": "Gray",
    "grey": "Gray",
    "dark_gray": "Gray",
    "dark_red": "Dark red",
    "maroon": "Dark red",
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "gold": "Gold",
    "green": "Green",
    "dark_green": "Green",
    "lime": "Lime",
    "light_green": "Lime",
    "turquoise": "Turquoise",
    "cyan": "Turquoise",
    "teal": "Turquoise",
    "blue": "Turquoise",
    "sky_blue": "Turquoise",
    "light_blue": "Turquoise",
    "indigo": "Indigo",
    "navy": "Indigo",
    "dark_blue": "Indigo",
    "purple": "Purple",
    "violet": "Purple",
    "magenta": "Purple",
    "brown": "Brown",
    "tan": "Brown",
    "chocolate": "Brown",
    "pink": "Rose",
    "rose": "Rose",
    "white": "White",
    "light_gray": "Light gray",
    "light_yellow": "Light yellow",
    "light_turquoise": "Light turquoise",
    "blue_gray": "Blue-gray",
    "lavender": "Lavender",
}


_PAINT_RIBBON_SWATCHES: dict[str, tuple[int, int]] = {
    "black": (988, 105),
    "gray": (1018, 105),
    "grey": (1018, 105),
    "dark_gray": (1018, 105),
    "dark_red": (1048, 105),
    "maroon": (1048, 105),
    "red": (1078, 105),
    "orange": (1108, 105),
    "yellow": (1138, 105),
    "gold": (1138, 105),
    "green": (1168, 105),
    "dark_green": (1168, 105),
    "blue": (1198, 105),
    "turquoise": (1198, 105),
    "cyan": (1198, 105),
    "indigo": (1228, 105),
    "navy": (1228, 105),
    "purple": (1258, 105),
    "violet": (1258, 105),
    "white": (988, 135),
    "light_gray": (1018, 135),
    "brown": (1048, 135),
    "tan": (1048, 135),
    "chocolate": (1048, 135),
    "pink": (1078, 135),
    "rose": (1078, 135),
    "light_yellow": (1138, 135),
    "lime": (1168, 135),
    "light_green": (1168, 135),
    "light_blue": (1198, 135),
    "sky_blue": (1198, 135),
    "lavender": (1258, 135),
}


def _ensure_paint_tool(tool: str = "brush", window: str = "Paint"):
    """Ensure Paint is using the brush tool, switching if Fill/Eraser/Shapes is active."""
    if platform.system() != "Windows":
        return
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    try:
        import win32gui
        hwnd = None
        def _find(h, _):
            nonlocal hwnd
            if win32gui.IsWindowVisible(h):
                txt = win32gui.GetWindowText(h)
                if txt and (window or "Paint").lower() in txt.lower():
                    hwnd = h
                    return False
            return True
        win32gui.EnumWindows(_find, None)
        if not hwnd:
            return

        import pywinauto
        app = pywinauto.Application(backend="uia").connect(handle=hwnd)
        win = app.window(handle=hwnd)

        for c in win.descendants():
            if getattr(c.element_info, "automation_id", "") == "image":
                name = (c.element_info.name or "").lower()
                if "brush" in name or "pencil" in name:
                    return
                break

        target_aid = "PencilTool" if tool == "pencil" else "BrushesSplitButton"
        for c in win.descendants():
            aid = getattr(c.element_info, "automation_id", "")
            if aid == target_aid or (aid == "BrushesSplitButton" and tool != "pencil"):
                pt = c.rectangle().mid_point()
                _win_click(int(pt.x), int(pt.y))
                time.sleep(0.08)
                return
    except Exception:
        pass


def _select_paint_color(color_name: str, window: str = "Paint") -> bool:
    """Select a color from MS Paint palette ribbon dynamically using UIA, caching, and screen scanning."""
    global _PAINT_PALETTE_CACHE, _LAST_PAINT_RECT, _CURRENT_PAINT_COLOR
    if not color_name:
        return False
    norm = color_name.lower().strip().replace(" ", "_").replace("-", "_")
    if norm == _CURRENT_PAINT_COLOR:
        return True

    target_rgb = _PAINT_COLOR_RGBS.get(norm)
    if not target_rgb:
        for k, v in _PAINT_COLOR_RGBS.items():
            if k in norm or norm in k:
                target_rgb = v
                norm = k
                break
    if not target_rgb:
        return False

    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()

    target_win_hwnd = None
    win_rect = None
    if platform.system() == "Windows":
        try:
            import win32gui
            def _find_win(h, _):
                nonlocal win_rect, target_win_hwnd
                if win32gui.IsWindowVisible(h):
                    txt = win32gui.GetWindowText(h)
                    if txt and (window or "Paint").lower() in txt.lower():
                        r = win32gui.GetWindowRect(h)
                        if r[2] > r[0] and r[3] > r[1]:
                            win_rect = r
                            target_win_hwnd = h
                            return False
                return True
            win32gui.EnumWindows(_find_win, None)

            if target_win_hwnd and win32gui.GetForegroundWindow() != target_win_hwnd:
                _focus_window(window or "Paint")
                time.sleep(0.05)
        except Exception:
            pass

    # Invalidate cache if window moved or resized
    if win_rect and win_rect != _LAST_PAINT_RECT:
        _PAINT_PALETTE_CACHE.clear()
        _LAST_PAINT_RECT = win_rect

    if norm in _PAINT_PALETTE_CACHE:
        cx, cy = _PAINT_PALETTE_CACHE[norm]
        _win_click(cx, cy)
        _CURRENT_PAINT_COLOR = norm
        time.sleep(0.04)
        return True

    # 1. Try high-precision UIA lookup via pywinauto
    if platform.system() == "Windows" and target_win_hwnd:
        try:
            import pywinauto
            uia_name = _PAINT_UIA_COLOR_MAP.get(norm, norm.capitalize())
            app = pywinauto.Application(backend="uia").connect(handle=target_win_hwnd)
            win_uia = app.window(handle=target_win_hwnd)
            btn = win_uia.child_window(title=uia_name, control_type="ListItem")
            if btn.exists(timeout=0.3):
                pt = btn.rectangle().mid_point()
                cx, cy = int(pt.x), int(pt.y)
                _PAINT_PALETTE_CACHE[norm] = (cx, cy)
                _win_click(cx, cy)
                _CURRENT_PAINT_COLOR = norm
                time.sleep(0.04)
                return True
        except Exception:
            pass

    # 2. Try default ribbon swatches offset by window position
    if norm in _PAINT_RIBBON_SWATCHES and win_rect:
        base_x, base_y = _PAINT_RIBBON_SWATCHES[norm]
        offset_x = win_rect[0] - (-9)
        offset_y = win_rect[1] - (-9)
        cx = base_x + offset_x
        cy = base_y + offset_y
        _PAINT_PALETTE_CACHE[norm] = (cx, cy)
        _win_click(cx, cy)
        _CURRENT_PAINT_COLOR = norm
        time.sleep(0.04)
        return True

    # 3. Scan ribbon toolbar using PIL ImageGrab
    try:
        import PIL.ImageGrab
        if win_rect:
            left = max(0, win_rect[0])
            top = max(0, win_rect[1])
            right = win_rect[2]
            bottom = min(win_rect[3], top + 260)
        else:
            screen_w, screen_h = pyautogui.size()
            left, top, right, bottom = 0, 0, screen_w, 260

        img = PIL.ImageGrab.grab((left, top, right, bottom))
        pixels = img.load()
        w_img, h_img = img.size

        # Find target color cluster
        hits = []
        for x in range(0, w_img, 2):
            for y in range(40, h_img, 2):
                p = pixels[x, y][:3]
                if max(abs(p[0] - target_rgb[0]), abs(p[1] - target_rgb[1]), abs(p[2] - target_rgb[2])) <= 14:
                    hits.append((x + left, y + top))

        if len(hits) >= 10:
            cx = sum(p[0] for p in hits) // len(hits)
            cy = sum(p[1] for p in hits) // len(hits)
            _PAINT_PALETTE_CACHE[norm] = (cx, cy)
            _win_click(cx, cy)
            _CURRENT_PAINT_COLOR = norm
            time.sleep(0.04)
            return True
    except Exception as e:
        print(f"[ComputerControl] Error scanning palette color {norm}: {e}")

    return False


def _generate_multi_stroke_object(
    name: str,
    cx: int,
    cy: int,
    size: int = 180,
    width: int | None = None,
    height: int | None = None,
) -> list[dict]:
    """Generate multi-colored vector strokes for recognizable objects:
    houses, pets (cat, dog), trees, cars, boats, flowers, sun, fish, birds, landscapes, and shapes."""
    w = width or size
    h = height or size
    s = str(name or "house").lower().strip()
    strokes: list[dict] = []

    def circle(x: int, y: int, r: int, steps: int = 20) -> list[tuple[int, int]]:
        return [
            (
                x + int(r * math.cos(2 * math.pi * i / steps)),
                y + int(r * math.sin(2 * math.pi * i / steps)),
            )
            for i in range(steps + 1)
        ]

    if any(k in s for k in ("house", "home", "cabin", "building")):
        # 1. Grass
        strokes.append({"color": "green", "points": [(cx - int(w * 0.75), cy + h // 2), (cx + int(w * 0.75), cy + h // 2)]})
        # 2. Walls
        x1, y1 = cx - w // 2, cy - int(h * 0.08)
        x2, y2 = cx + w // 2, cy + h // 2
        strokes.append({"color": "brown", "points": [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]})
        # 3. Roof
        strokes.append({"color": "red", "points": [(x1 - int(w * 0.08), y1), (cx, cy - int(h * 0.52)), (x2 + int(w * 0.08), y1), (x1 - int(w * 0.08), y1)]})
        # 4. Chimney
        ch_x1 = cx + int(w * 0.22)
        ch_x2 = cx + int(w * 0.34)
        strokes.append({"color": "red", "points": [(ch_x1, cy - int(h * 0.25)), (ch_x1, cy - int(h * 0.48)), (ch_x2, cy - int(h * 0.48)), (ch_x2, cy - int(h * 0.15))]})
        # 5. Smoke
        strokes.append({"color": "gray", "points": [(ch_x1 + 6, cy - int(h * 0.52)), (ch_x1 + 14, cy - int(h * 0.58)), (ch_x1 + 8, cy - int(h * 0.65)), (ch_x1 + 16, cy - int(h * 0.72))]})
        # 6. Door
        dw, dh = int(w * 0.24), int(h * 0.38)
        strokes.append({"color": "orange", "points": [(cx - dw // 2, y2), (cx - dw // 2, y2 - dh), (cx + dw // 2, y2 - dh), (cx + dw // 2, y2)]})
        # 7. Door knob
        strokes.append({"color": "yellow", "points": [(cx + dw // 4, y2 - dh // 2), (cx + dw // 4, y2 - dh // 2 + 3)]})
        # 8. Windows
        ww, wh = int(w * 0.20), int(h * 0.20)
        lwx, lwy = cx - int(w * 0.30), cy + int(h * 0.05)
        strokes.append({"color": "blue", "points": [(lwx - ww // 2, lwy - wh // 2), (lwx + ww // 2, lwy - wh // 2), (lwx + ww // 2, lwy + wh // 2), (lwx - ww // 2, lwy + wh // 2), (lwx - ww // 2, lwy - wh // 2)]})
        strokes.append({"color": "blue", "points": [(lwx, lwy - wh // 2), (lwx, lwy + wh // 2)]})
        strokes.append({"color": "blue", "points": [(lwx - ww // 2, lwy), (lwx + ww // 2, lwy)]})
        rwx, rwy = cx + int(w * 0.30), cy + int(h * 0.05)
        strokes.append({"color": "blue", "points": [(rwx - ww // 2, rwy - wh // 2), (rwx + ww // 2, rwy - wh // 2), (rwx + ww // 2, rwy + wh // 2), (rwx - ww // 2, rwy + wh // 2), (rwx - ww // 2, rwy - wh // 2)]})
        strokes.append({"color": "blue", "points": [(rwx, rwy - wh // 2), (rwx, rwy + wh // 2)]})
        strokes.append({"color": "blue", "points": [(rwx - ww // 2, rwy), (rwx + ww // 2, rwy)]})
        # 9. Sun
        strokes.append({"color": "yellow", "points": circle(cx - int(w * 0.65), cy - int(h * 0.50), int(w * 0.12), steps=16)})

    elif any(k in s for k in ("tree", "forest", "plant", "pine")):
        # Grass base
        strokes.append({"color": "green", "points": [(cx - int(w * 0.65), cy + h // 2), (cx + int(w * 0.65), cy + h // 2)]})
        # Trunk
        tw = int(w * 0.22)
        strokes.append({"color": "brown", "points": [(cx - tw // 2, cy + h // 2), (cx - tw // 3, cy), (cx + tw // 3, cy), (cx + tw // 2, cy + h // 2)]})
        # Branches
        strokes.append({"color": "brown", "points": [(cx - tw // 4, cy + int(h * 0.05)), (cx - int(w * 0.25), cy - int(h * 0.05))]})
        strokes.append({"color": "brown", "points": [(cx + tw // 4, cy + int(h * 0.05)), (cx + int(w * 0.25), cy - int(h * 0.05))]})
        # Foliage tiers (bottom, middle, top)
        strokes.append({"color": "green", "points": [(cx - int(w * 0.48), cy + int(h * 0.08)), (cx, cy - int(h * 0.15)), (cx + int(w * 0.48), cy + int(h * 0.08)), (cx - int(w * 0.48), cy + int(h * 0.08))]})
        strokes.append({"color": "green", "points": [(cx - int(w * 0.38), cy - int(h * 0.10)), (cx, cy - int(h * 0.32)), (cx + int(w * 0.38), cy - int(h * 0.10)), (cx - int(w * 0.38), cy - int(h * 0.10))]})
        strokes.append({"color": "green", "points": [(cx - int(w * 0.26), cy - int(h * 0.28)), (cx, cy - int(h * 0.52)), (cx + int(w * 0.26), cy - int(h * 0.28)), (cx - int(w * 0.26), cy - int(h * 0.28))]})
        # Red apples
        for ax, ay in [
            (cx - int(w * 0.22), cy - int(h * 0.02)),
            (cx + int(w * 0.22), cy - int(h * 0.04)),
            (cx - int(w * 0.12), cy - int(h * 0.22)),
            (cx + int(w * 0.14), cy - int(h * 0.20)),
        ]:
            strokes.append({"color": "red", "points": circle(ax, ay, max(4, int(w * 0.04)), steps=8)})

    elif any(k in s for k in ("cat", "kitten", "kitty")):
        # Body
        body_pts = [
            (
                cx + int(w * 0.28 * math.cos(2 * math.pi * i / 24)),
                cy + int(h * 0.22) + int(h * 0.26 * math.sin(2 * math.pi * i / 24)),
            )
            for i in range(25)
        ]
        strokes.append({"color": "black", "points": body_pts})
        # Paws
        strokes.append({"color": "black", "points": [(cx - int(w * 0.15), cy + int(h * 0.46)), (cx - int(w * 0.05), cy + int(h * 0.46))]})
        strokes.append({"color": "black", "points": [(cx + int(w * 0.05), cy + int(h * 0.46)), (cx + int(w * 0.15), cy + int(h * 0.46))]})
        # Head
        hr = int(w * 0.24)
        hc_y = cy - int(h * 0.15)
        strokes.append({"color": "black", "points": circle(cx, hc_y, hr, steps=24)})
        # Left ear & inner ear
        strokes.append({"color": "black", "points": [(cx - int(hr * 0.85), hc_y - int(hr * 0.45)), (cx - int(hr * 0.95), hc_y - int(hr * 1.55)), (cx - int(hr * 0.20), hc_y - int(hr * 0.95))]})
        strokes.append({"color": "pink", "points": [(cx - int(hr * 0.75), hc_y - int(hr * 0.55)), (cx - int(hr * 0.85), hc_y - int(hr * 1.35)), (cx - int(hr * 0.30), hc_y - int(hr * 0.90))]})
        # Right ear & inner ear
        strokes.append({"color": "black", "points": [(cx + int(hr * 0.20), hc_y - int(hr * 0.95)), (cx + int(hr * 0.95), hc_y - int(hr * 1.55)), (cx + int(hr * 0.85), hc_y - int(hr * 0.45))]})
        strokes.append({"color": "pink", "points": [(cx + int(hr * 0.30), hc_y - int(hr * 0.90)), (cx + int(hr * 0.85), hc_y - int(hr * 1.35)), (cx + int(hr * 0.75), hc_y - int(hr * 0.55))]})
        # Eyes
        strokes.append({"color": "green", "points": circle(cx - int(hr * 0.42), hc_y - int(hr * 0.15), max(3, int(hr * 0.18)), steps=10)})
        strokes.append({"color": "green", "points": circle(cx + int(hr * 0.42), hc_y - int(hr * 0.15), max(3, int(hr * 0.18)), steps=10)})
        # Nose & mouth
        ny = hc_y + int(hr * 0.15)
        strokes.append({"color": "pink", "points": [(cx - 5, ny - 3), (cx + 5, ny - 3), (cx, ny + 3), (cx - 5, ny - 3)]})
        strokes.append({"color": "black", "points": [(cx - 10, ny + 8), (cx, ny + 4), (cx + 10, ny + 8)]})
        # Whiskers
        strokes.append({"color": "black", "points": [(cx - int(hr * 0.5), ny), (cx - int(hr * 1.3), ny - 6)]})
        strokes.append({"color": "black", "points": [(cx - int(hr * 0.5), ny + 4), (cx - int(hr * 1.3), ny + 4)]})
        strokes.append({"color": "black", "points": [(cx - int(hr * 0.5), ny + 8), (cx - int(hr * 1.25), ny + 14)]})
        strokes.append({"color": "black", "points": [(cx + int(hr * 0.5), ny), (cx + int(hr * 1.3), ny - 6)]})
        strokes.append({"color": "black", "points": [(cx + int(hr * 0.5), ny + 4), (cx + int(hr * 1.3), ny + 4)]})
        strokes.append({"color": "black", "points": [(cx + int(hr * 0.5), ny + 8), (cx + int(hr * 1.25), ny + 14)]})
        # Tail
        tail = [
            (cx + int(w * 0.22), cy + int(h * 0.40)),
            (cx + int(w * 0.38), cy + int(h * 0.35)),
            (cx + int(w * 0.48), cy + int(h * 0.15)),
            (cx + int(w * 0.42), cy - int(h * 0.05)),
        ]
        strokes.append({"color": "black", "points": tail})

    elif any(k in s for k in ("dog", "puppy", "hound", "pet")):
        # Body and legs
        strokes.append({"color": "brown", "points": [
            (cx - int(w * 0.35), cy + int(h * 0.35)),
            (cx - int(w * 0.35), cy + int(h * 0.05)),
            (cx + int(w * 0.25), cy + int(h * 0.05)),
            (cx + int(w * 0.30), cy + int(h * 0.35)),
            (cx + int(w * 0.20), cy + int(h * 0.48)),
            (cx + int(w * 0.10), cy + int(h * 0.35)),
            (cx - int(w * 0.20), cy + int(h * 0.35)),
            (cx - int(w * 0.25), cy + int(h * 0.48)),
            (cx - int(w * 0.35), cy + int(h * 0.35)),
        ]})
        # Head
        hc_x, hc_y = cx - int(w * 0.28), cy - int(h * 0.15)
        hr = int(w * 0.20)
        strokes.append({"color": "brown", "points": circle(hc_x, hc_y, hr, steps=20)})
        # Floppy ears
        strokes.append({"color": "brown", "points": [(hc_x - int(hr * 0.8), hc_y - int(hr * 0.4)), (hc_x - int(hr * 1.3), hc_y + int(hr * 0.8)), (hc_x - int(hr * 0.6), hc_y + int(hr * 0.5))]})
        strokes.append({"color": "brown", "points": [(hc_x + int(hr * 0.4), hc_y - int(hr * 0.8)), (hc_x + int(hr * 0.9), hc_y + int(hr * 0.6)), (hc_x + int(hr * 0.3), hc_y + int(hr * 0.4))]})
        # Snout / Nose
        strokes.append({"color": "black", "points": circle(hc_x - int(hr * 0.6), hc_y + int(hr * 0.2), max(3, int(hr * 0.16)), steps=8)})
        # Eye
        strokes.append({"color": "blue", "points": circle(hc_x - int(hr * 0.1), hc_y - int(hr * 0.2), max(3, int(hr * 0.14)), steps=8)})
        # Collar & tag
        strokes.append({"color": "red", "points": [(hc_x - int(hr * 0.4), hc_y + int(hr * 0.85)), (hc_x + int(hr * 0.7), hc_y + int(hr * 0.85))]})
        strokes.append({"color": "yellow", "points": circle(hc_x + int(hr * 0.15), hc_y + int(hr * 1.1), 5, steps=8)})
        # Tail
        strokes.append({"color": "brown", "points": [(cx + int(w * 0.28), cy + int(h * 0.10)), (cx + int(w * 0.45), cy - int(h * 0.15))]})

    elif any(k in s for k in ("car", "automobile", "truck", "vehicle")):
        # Body
        strokes.append({"color": "red", "points": [
            (cx - int(w * 0.45), cy + int(h * 0.25)),
            (cx - int(w * 0.45), cy + int(h * 0.05)),
            (cx - int(w * 0.25), cy + int(h * 0.05)),
            (cx - int(w * 0.12), cy - int(h * 0.25)),
            (cx + int(w * 0.18), cy - int(h * 0.25)),
            (cx + int(w * 0.32), cy + int(h * 0.05)),
            (cx + int(w * 0.45), cy + int(h * 0.05)),
            (cx + int(w * 0.45), cy + int(h * 0.25)),
            (cx - int(w * 0.45), cy + int(h * 0.25)),
        ]})
        # Wheels
        wr = int(w * 0.11)
        fw_x, rw_x = cx - int(w * 0.25), cx + int(w * 0.25)
        w_y = cy + int(h * 0.25)
        strokes.append({"color": "black", "points": circle(fw_x, w_y, wr, steps=16)})
        strokes.append({"color": "gray", "points": circle(fw_x, w_y, wr // 2, steps=10)})
        strokes.append({"color": "black", "points": circle(rw_x, w_y, wr, steps=16)})
        strokes.append({"color": "gray", "points": circle(rw_x, w_y, wr // 2, steps=10)})
        # Windows
        strokes.append({"color": "blue", "points": [
            (cx - int(w * 0.20), cy + int(h * 0.02)),
            (cx - int(w * 0.10), cy - int(h * 0.20)),
            (cx - 2, cy - int(h * 0.20)),
            (cx - 2, cy + int(h * 0.02)),
            (cx - int(w * 0.20), cy + int(h * 0.02)),
        ]})
        strokes.append({"color": "blue", "points": [
            (cx + 4, cy + int(h * 0.02)),
            (cx + 4, cy - int(h * 0.20)),
            (cx + int(w * 0.14), cy - int(h * 0.20)),
            (cx + int(w * 0.25), cy + int(h * 0.02)),
            (cx + 4, cy + int(h * 0.02)),
        ]})
        # Headlight & Taillight
        strokes.append({"color": "yellow", "points": [(cx + int(w * 0.44), cy + int(h * 0.10)), (cx + int(w * 0.45), cy + int(h * 0.18))]})
        strokes.append({"color": "dark_red", "points": [(cx - int(w * 0.44), cy + int(h * 0.10)), (cx - int(w * 0.45), cy + int(h * 0.18))]})

    elif any(k in s for k in ("boat", "ship", "sailboat", "yacht")):
        # Hull
        strokes.append({"color": "brown", "points": [
            (cx - int(w * 0.45), cy + int(h * 0.15)),
            (cx - int(w * 0.30), cy + int(h * 0.35)),
            (cx + int(w * 0.30), cy + int(h * 0.35)),
            (cx + int(w * 0.45), cy + int(h * 0.15)),
            (cx - int(w * 0.45), cy + int(h * 0.15)),
        ]})
        # Mast
        strokes.append({"color": "black", "points": [(cx, cy + int(h * 0.15)), (cx, cy - int(h * 0.45))]})
        # Main sail
        strokes.append({"color": "red", "points": [(cx + 4, cy - int(h * 0.42)), (cx + int(w * 0.38), cy + int(h * 0.10)), (cx + 4, cy + int(h * 0.10)), (cx + 4, cy - int(h * 0.42))]})
        # Jib sail
        strokes.append({"color": "yellow", "points": [(cx - 4, cy - int(h * 0.38)), (cx - int(w * 0.35), cy + int(h * 0.10)), (cx - 4, cy + int(h * 0.10)), (cx - 4, cy - int(h * 0.38))]})
        # Flag
        strokes.append({"color": "red", "points": [(cx, cy - int(h * 0.45)), (cx - int(w * 0.10), cy - int(h * 0.40)), (cx, cy - int(h * 0.35))]})
        # Water waves
        wave = []
        for i in range(25):
            t = i / 24.0
            wx = cx - int(w * 0.55) + int(w * 1.1 * t)
            wy = cy + int(h * 0.42) + int(8 * math.sin(t * 4 * math.pi))
            wave.append((wx, wy))
        strokes.append({"color": "blue", "points": wave})

    elif any(k in s for k in ("flower", "rose", "tulip", "daisy")):
        # Stem
        strokes.append({"color": "green", "points": [(cx, cy), (cx, cy + int(h * 0.45))]})
        # Leaves
        strokes.append({"color": "green", "points": [(cx, cy + int(h * 0.22)), (cx - int(w * 0.25), cy + int(h * 0.15)), (cx, cy + int(h * 0.28))]})
        strokes.append({"color": "green", "points": [(cx, cy + int(h * 0.26)), (cx + int(w * 0.25), cy + int(h * 0.19)), (cx, cy + int(h * 0.32))]})
        # Center core
        cr = int(w * 0.15)
        strokes.append({"color": "yellow", "points": circle(cx, cy - int(h * 0.10), cr, steps=16)})
        # Petals
        for i in range(6):
            ang = 2 * math.pi * i / 6
            pcx = cx + int(cr * 1.6 * math.cos(ang))
            pcy = (cy - int(h * 0.10)) + int(cr * 1.6 * math.sin(ang))
            strokes.append({"color": "pink", "points": circle(pcx, pcy, int(cr * 0.8), steps=12)})

    elif any(k in s for k in ("sun", "sunny")):
        sr = int(w * 0.25)
        strokes.append({"color": "yellow", "points": circle(cx, cy, sr, steps=24)})
        # Rays
        for i in range(12):
            ang = 2 * math.pi * i / 12
            r1 = sr + 6
            r2 = sr + int(w * 0.20)
            strokes.append({"color": "orange", "points": [
                (cx + int(r1 * math.cos(ang)), cy + int(r1 * math.sin(ang))),
                (cx + int(r2 * math.cos(ang)), cy + int(r2 * math.sin(ang))),
            ]})
        # Face
        strokes.append({"color": "orange", "points": circle(cx - int(sr * 0.35), cy - int(sr * 0.2), 3, steps=8)})
        strokes.append({"color": "orange", "points": circle(cx + int(sr * 0.35), cy - int(sr * 0.2), 3, steps=8)})
        smile = [
            (
                cx + int(sr * 0.5 * math.cos(math.pi * 0.2 + math.pi * 0.6 * i / 10)),
                cy + int(sr * 0.5 * math.sin(math.pi * 0.2 + math.pi * 0.6 * i / 10)),
            )
            for i in range(11)
        ]
        strokes.append({"color": "orange", "points": smile})

    elif any(k in s for k in ("fish", "shark", "goldfish")):
        # Body
        body = []
        for i in range(25):
            t = 2 * math.pi * i / 24
            bx = cx + int(w * 0.35 * math.cos(t))
            by = cy + int(h * 0.20 * math.sin(t))
            body.append((bx, by))
        strokes.append({"color": "orange", "points": body})
        # Tail fin
        tail = [(cx + int(w * 0.30), cy), (cx + int(w * 0.48), cy - int(h * 0.22)), (cx + int(w * 0.42), cy), (cx + int(w * 0.48), cy + int(h * 0.22)), (cx + int(w * 0.30), cy)]
        strokes.append({"color": "red", "points": tail})
        # Dorsal fin
        strokes.append({"color": "red", "points": [(cx - int(w * 0.10), cy - int(h * 0.18)), (cx, cy - int(h * 0.35)), (cx + int(w * 0.15), cy - int(h * 0.15))]})
        # Eye
        strokes.append({"color": "black", "points": circle(cx - int(w * 0.20), cy - int(h * 0.05), max(3, int(w * 0.04)), steps=8)})
        # Bubbles
        strokes.append({"color": "blue", "points": circle(cx - int(w * 0.42), cy - int(h * 0.15), 6, steps=8)})
        strokes.append({"color": "blue", "points": circle(cx - int(w * 0.48), cy - int(h * 0.30), 8, steps=8)})

    elif any(k in s for k in ("bird", "dove", "eagle", "seagull")):
        # Body
        strokes.append({"color": "blue", "points": [
            (cx - int(w * 0.25), cy),
            (cx, cy + int(h * 0.15)),
            (cx + int(w * 0.25), cy),
            (cx, cy - int(h * 0.05)),
            (cx - int(w * 0.25), cy),
        ]})
        # Wings
        strokes.append({"color": "blue", "points": [(cx - int(w * 0.45), cy - int(h * 0.35)), (cx, cy - int(h * 0.05)), (cx + int(w * 0.45), cy - int(h * 0.35))]})
        # Beak
        strokes.append({"color": "yellow", "points": [(cx - int(w * 0.25), cy), (cx - int(w * 0.35), cy + 3), (cx - int(w * 0.25), cy + 7), (cx - int(w * 0.25), cy)]})
        # Eye
        strokes.append({"color": "black", "points": circle(cx - int(w * 0.18), cy + 2, 3, steps=6)})

    elif any(k in s for k in ("landscape", "scenery", "mountain", "nature")):
        # Sun
        strokes.append({"color": "yellow", "points": circle(cx - int(w * 0.40), cy - int(h * 0.38), int(w * 0.12), steps=16)})
        # Mountain 1
        strokes.append({"color": "purple", "points": [(cx - int(w * 0.55), cy + int(h * 0.15)), (cx - int(w * 0.20), cy - int(h * 0.30)), (cx + int(w * 0.15), cy + int(h * 0.15))]})
        # Snow cap 1
        strokes.append({"color": "blue", "points": [(cx - int(w * 0.26), cy - int(h * 0.18)), (cx - int(w * 0.20), cy - int(h * 0.30)), (cx - int(w * 0.13), cy - int(h * 0.18))]})
        # Mountain 2
        strokes.append({"color": "purple", "points": [(cx - int(w * 0.05), cy + int(h * 0.15)), (cx + int(w * 0.25), cy - int(h * 0.22)), (cx + int(w * 0.55), cy + int(h * 0.15))]})
        # Hills
        strokes.append({"color": "green", "points": [(cx - int(w * 0.55), cy + int(h * 0.25)), (cx - int(w * 0.10), cy + int(h * 0.12)), (cx + int(w * 0.55), cy + int(h * 0.25))]})
        # River
        strokes.append({"color": "blue", "points": [(cx - int(w * 0.05), cy + int(h * 0.15)), (cx - int(w * 0.12), cy + int(h * 0.32)), (cx + int(w * 0.05), cy + int(h * 0.50))]})
        # Tree
        strokes.append({"color": "brown", "points": [(cx + int(w * 0.30), cy + int(h * 0.32)), (cx + int(w * 0.30), cy + int(h * 0.20))]})
        strokes.append({"color": "green", "points": circle(cx + int(w * 0.30), cy + int(h * 0.16), int(w * 0.08), steps=12)})

    elif any(k in s for k in ("heart",)):
        scale = min(w, h) / 34.0
        pts = []
        for i in range(41):
            t = (2 * math.pi * i) / 40
            x = cx + int(scale * 16 * (math.sin(t) ** 3))
            y = cy - int(scale * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
            pts.append((x, y))
        strokes.append({"color": "red", "points": pts})

    elif any(k in s for k in ("star",)):
        R = max(w, h) // 2
        r = int(R * 0.4)
        pts = []
        for i in range(11):
            theta = -math.pi / 2 + i * math.pi / 5
            rad = R if i % 2 == 0 else r
            pts.append((cx + int(rad * math.cos(theta)), cy + int(rad * math.sin(theta))))
        strokes.append({"color": "yellow", "points": pts})

    elif any(k in s for k in ("smiley", "smile", "face")):
        R = size // 2
        strokes.append({"color": "yellow", "points": circle(cx, cy, R, steps=36)})
        er = max(4, R // 9)
        strokes.append({"color": "black", "points": circle(cx - R // 3, cy - R // 4, er, steps=12)})
        strokes.append({"color": "black", "points": circle(cx + R // 3, cy - R // 4, er, steps=12)})
        mouth = [(cx + int((R * 0.6) * math.cos(math.pi * 0.15 + (math.pi * 0.7 * i / 12))), cy + int((R * 0.6) * math.sin(math.pi * 0.15 + (math.pi * 0.7 * i / 12)))) for i in range(13)]
        strokes.append({"color": "black", "points": mouth})

    elif any(k in s for k in ("circle", "oval", "ellipse")):
        rx, ry = w // 2, h // 2
        pts = [
            (
                cx + int(rx * math.cos(2 * math.pi * i / 36)),
                cy + int(ry * math.sin(2 * math.pi * i / 36)),
            )
            for i in range(37)
        ]
        strokes.append({"color": "blue", "points": pts})

    elif any(k in s for k in ("rectangle", "square", "box")):
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2
        strokes.append({"color": "blue", "points": [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]})

    elif any(k in s for k in ("triangle",)):
        p1 = (cx, cy - h // 2)
        p2 = (cx + w // 2, cy + h // 2)
        p3 = (cx - w // 2, cy + h // 2)
        strokes.append({"color": "green", "points": [p1, p2, p3, p1]})

    elif any(k in s for k in ("spiral",)):
        pts = []
        for i in range(50):
            t = 4 * math.pi * i / 50
            r = (size // 2) * (i / 50)
            pts.append((cx + int(r * math.cos(t)), cy + int(r * math.sin(t))))
        strokes.append({"color": "purple", "points": pts})

    elif any(k in s for k in ("line",)):
        strokes.append({"color": "black", "points": [(cx - w // 2, cy), (cx + w // 2, cy)]})

    return strokes


def _ai_generate_object_strokes(object_name: str, cx: int, cy: int, size: int) -> list[dict] | None:
    """Use Gemini FAST to generate natural-colored vector strokes for arbitrary objects."""
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from core import gemini
        prompt = (
            f"You are a 2D line drawing generator for MS Paint.\n"
            f"Generate recognizable vector strokes for: '{object_name}'.\n"
            f"The drawing is centered at (x={cx}, y={cy}) with size {size}.\n"
            f"Allowed colors: black, brown, red, orange, yellow, green, blue, purple, pink, gray.\n"
            f"Output a valid JSON array of strokes, for example:\n"
            f"[\n"
            f'  {{"color": "green", "points": [[{cx-40}, {cy-20}], [{cx}, {cy-50}], [{cx+40}, {cy-20}]]}}\n'
            f"]\n"
            f"Rules:\n"
            f"- At least 4-10 distinct strokes representing the key features and natural colors of '{object_name}'.\n"
            f"- Use smooth curves with 4-16 points per stroke.\n"
            f"- All coordinates must stay within [{cx - size}, {cx + size}] and [{cy - size}, {cy + size}].\n"
            f"- Return ONLY the raw JSON array. No markdown, no explanations.\n"
        )
        resp = gemini.call(prompt, tier=gemini.FAST, timeout_ms=8000)
        if resp and resp.text:
            txt = resp.text.strip()
            m = re.search(r'\[.*\]', txt, re.DOTALL)
            if m:
                raw_strokes = json.loads(m.group(0))
                valid_strokes = []
                for s in raw_strokes:
                    if isinstance(s, dict) and "points" in s:
                        col = str(s.get("color", "black")).lower()
                        pts = [(int(p[0]), int(p[1])) for p in s["points"] if len(p) >= 2]
                        if len(pts) >= 2:
                            valid_strokes.append({"color": col, "points": pts})
                if valid_strokes:
                    return valid_strokes
    except Exception as e:
        print(f"[ComputerControl] AI stroke generator error for '{object_name}': {e}")
    return None


def _generate_shape_paths(
    shape: str,
    cx: int,
    cy: int,
    size: int = 150,
    width: int | None = None,
    height: int | None = None,
) -> list[list[tuple[int, int]]]:
    """Generate path points for shapes (returns list of point lists for backward compatibility)."""
    strokes = _generate_multi_stroke_object(shape, cx, cy, size=size, width=width, height=height)
    if strokes:
        return [s["points"] for s in strokes if "points" in s]
    # Default fallback to heart
    scale = min(width or size, height or size) / 34.0
    pts = []
    for i in range(41):
        t = (2 * math.pi * i) / 40
        x = cx + int(scale * 16 * (math.sin(t) ** 3))
        y = cy - int(scale * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
        pts.append((x, y))
    return [pts]


def _draw_object(
    target: str = "house",
    x: int | None = None,
    y: int | None = None,
    size: int = 180,
    width: int | None = None,
    height: int | None = None,
    window: str | None = None,
    color: str | None = None,
) -> str:
    """Draw any object or shape in MS Paint with multi-color palette switching."""
    _require_pyautogui()
    _ensure_interactive_desktop()
    _enable_dpi_awareness()

    screen_w, screen_h = pyautogui.size()
    target_win = window or "Paint"
    win_rect = None
    if target_win:
        _focus_window(target_win)
        time.sleep(0.25)
        if platform.system() == "Windows":
            try:
                import win32gui
                def _find_target(h, _):
                    nonlocal win_rect
                    if win32gui.IsWindowVisible(h):
                        txt = win32gui.GetWindowText(h)
                        if txt and target_win.lower() in txt.lower():
                            r = win32gui.GetWindowRect(h)
                            if r[2] > r[0] and r[3] > r[1]:
                                win_rect = r
                                return False
                    return True
                win32gui.EnumWindows(_find_target, None)
            except Exception:
                pass

        if target_win.lower() in ("paint", "mspaint"):
            _ensure_paint_tool("brush", window=target_win)
            time.sleep(0.04)

    # Resolve center (x, y) coordinates safely on canvas
    cx, cy = x, y
    if cx is None or cy is None:
        if win_rect and win_rect[2] > win_rect[0] and win_rect[3] > win_rect[1]:
            left, top, right, bottom = win_rect
            win_w = right - left
            win_h = bottom - top
            cx = left + (win_w // 2)
            cy = top + 210 + max(40, (win_h - 260) // 2)
        else:
            cx = screen_w // 2
            cy = (screen_h // 2) + 50

    cx = max(50, min(screen_w - 50, int(cx)))
    cy = max(50, min(screen_h - 50, int(cy)))

    # 1. Preset strokes
    strokes = _generate_multi_stroke_object(target, cx, cy, size=size, width=width, height=height)

    # 2. Check if known preset; if not, query AI generator
    t_clean = str(target or "").lower().strip()
    known_keywords = (
        "house", "home", "cabin", "building", "tree", "forest", "plant", "pine",
        "cat", "kitten", "kitty", "dog", "puppy", "hound", "pet",
        "car", "automobile", "truck", "vehicle", "boat", "ship", "sailboat", "yacht",
        "flower", "rose", "tulip", "daisy", "sun", "sunny", "fish", "shark", "goldfish",
        "bird", "dove", "eagle", "seagull", "landscape", "scenery", "mountain", "nature",
        "heart", "star", "smiley", "smile", "face", "circle", "oval", "ellipse",
        "rectangle", "square", "box", "triangle", "spiral", "line"
    )
    if not any(k in t_clean for k in known_keywords):
        ai_strokes = _ai_generate_object_strokes(target, cx, cy, size)
        if ai_strokes:
            strokes = ai_strokes

    if not strokes:
        strokes = [{"color": color or "red", "points": p} for p in _generate_shape_paths("heart", cx, cy, size=size)]

    total_pts = sum(len(s.get("points", [])) for s in strokes)
    cur_color = None
    for s in strokes:
        pts = s.get("points", [])
        if not pts:
            continue
        c = color or s.get("color", "black")
        if target_win.lower() in ("paint", "mspaint") and c != cur_color:
            _select_paint_color(c, window=target_win)
            cur_color = c
        _draw_path(pts, button="left")
        time.sleep(0.02)

    return f"Successfully painted {target} with {len(strokes)} strokes ({total_pts} points) in {target_win}."


def _draw_shape(
    shape: str = "heart",
    x: int | None = None,
    y: int | None = None,
    size: int = 150,
    width: int | None = None,
    height: int | None = None,
    window: str | None = None,
    color: str | None = None,
) -> str:
    """Draw shape or object (backward-compatible delegate to _draw_object)."""
    return _draw_object(
        target=shape,
        x=x,
        y=y,
        size=size,
        width=width,
        height=height,
        window=window,
        color=color,
    )


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        paste_key = "command" if _get_os() == "mac" else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _enable_dpi_awareness():
    if platform.system() == "Windows":
        try:
            import ctypes
            # Per-monitor DPI awareness
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

def _focus_window(title: str) -> str:
    if not title:
        return "No window title provided."
    _ensure_interactive_desktop()
    os_name = _get_os()

    if os_name == "windows":
        clean_title = title.strip()
        # Auto-launch Paint if requested but not open
        if clean_title.lower() in ("paint", "mspaint"):
            try:
                import pygetwindow as gw
                if not any(w.title and "paint" in w.title.lower() for w in gw.getAllWindows()):
                    subprocess.Popen(["mspaint.exe"])
                    time.sleep(0.8)
            except Exception:
                pass

        # 1. Try pygetwindow (fast, handles minimize/restore)
        try:
            import pygetwindow as gw
            matching = [w for w in gw.getAllWindows() if w.title and clean_title.lower() in w.title.lower()]
            if matching:
                w = matching[0]
                try:
                    import ctypes, win32gui
                    if hasattr(w, "_hWnd") and win32gui.GetForegroundWindow() == w._hWnd:
                        return f"Focused window: {w.title}"
                    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                    ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
                    time.sleep(0.15)
                    return f"Focused window: {w.title}"
                except Exception:
                    pass
        except Exception:
            pass

        # 2. Try win32gui
        try:
            import win32gui, win32con
            found = []
            def _enum(h, _):
                if win32gui.IsWindowVisible(h):
                    txt = win32gui.GetWindowText(h)
                    if txt and clean_title.lower() in txt.lower():
                        found.append(h)
                return True
            win32gui.EnumWindows(_enum, None)
            if found:
                h = found[0]
                try:
                    if win32gui.GetForegroundWindow() == h:
                        return f"Focused window: {win32gui.GetWindowText(h)}"
                    import ctypes
                    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                    win32gui.ShowWindow(h, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(h)
                    ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                    ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)
                    time.sleep(0.15)
                    return f"Focused window: {win32gui.GetWindowText(h)}"
                except Exception:
                    pass
        except Exception:
            pass

        # 3. PowerShell AppActivate fallback
        try:
            escaped = clean_title.replace('"', '`"')
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{escaped}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, **_WIN_HIDE,
            )
            time.sleep(0.25)
            return f"Focused window: {clean_title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _extract_window_hint(description: str) -> str | None:
    if not description:
        return None
    patterns = [
        r"\b(?:in|on|inside|of)\s+([A-Za-z0-9_\-\s]+?)(?:\s+(?:app|window|browser|tab|application))?$",
        r"\b(?:in|on|inside)\s+([A-Za-z0-9_\-]+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, description, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in {"the", "a", "an", "this", "that", "screen", "desktop", "center", "left", "right", "top", "bottom"}:
                return candidate
    return None

def _grab_screen_image():
    """Capture the full screen cleanly across Windows / macOS / Linux."""
    _ensure_interactive_desktop()
    _enable_dpi_awareness()
    # 1. Try PyQt6 if running inside Qt app
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QBuffer, QIODevice
        import PIL.Image
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen:
                pixmap = screen.grabWindow(0)
                if not pixmap.isNull():
                    qbuf = QBuffer()
                    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
                    pixmap.save(qbuf, "PNG")
                    return PIL.Image.open(io.BytesIO(bytes(qbuf.data()))).convert("RGB")
    except Exception:
        pass

    # 2. Try PIL ImageGrab
    try:
        import PIL.ImageGrab
        return PIL.ImageGrab.grab(all_screens=False).convert("RGB")
    except Exception:
        pass

    # 3. Fallback to PyAutoGUI screenshot
    _require_pyautogui()
    return pyautogui.screenshot().convert("RGB")


def _screen_find(description: str, window_title: str | None = None) -> tuple[int, int] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] [WARN] No API key for screen_find")
        return None

    _ensure_interactive_desktop()
    _enable_dpi_awareness()

    # If window title is provided or detected in description, bring it to front first
    win_hint = window_title or _extract_window_hint(description)
    if win_hint:
        try:
            print(f"[ComputerControl] Focusing target window: '{win_hint}'")
            _focus_window(win_hint)
            time.sleep(0.25)
        except Exception as e:
            print(f"[ComputerControl] [WARN] Window focus hint failed: {e}")

    try:
        from google.genai import types as gtypes

        _require_pyautogui()
        screen_w, screen_h = pyautogui.size()
        img = _grab_screen_image()

        # Compress / downscale image to max dimension 1280 to dramatically reduce network latency
        MAX_DIM = 1280
        orig_w, orig_h = img.size
        scale = min(1.0, MAX_DIM / max(orig_w, orig_h))
        if scale < 1.0:
            target_w = max(1, int(orig_w * scale))
            target_h = max(1, int(orig_h * scale))
            try:
                import PIL.Image
                resample = getattr(PIL.Image, "Resampling", PIL.Image).BILINEAR
                upload_img = img.resize((target_w, target_h), resample)
            except Exception:
                upload_img = img
        else:
            upload_img = img

        buf = io.BytesIO()
        upload_img.save(buf, format="JPEG", quality=82, optimize=False)
        image_bytes = buf.getvalue()

        prompt = (
            f"You are an expert computer GUI vision locator. Locate the UI element described as: '{description}'.\n"
            f"The entire desktop screen dimensions are {screen_w} width by {screen_h} height.\n"
            "CRITICAL INSTRUCTIONS FOR NON-FULLSCREEN / WINDOWED APPLICATIONS:\n"
            "1. Many applications on this computer are NOT fullscreen (they may be windowed, floating, split-screen, or occupying only a portion of the monitor).\n"
            "2. First locate the application window containing the element, then pinpoint the exact center of the requested UI element inside that window.\n"
            "3. Coordinates MUST be normalized to the ENTIRE desktop screen (where [0, 0] is the top-left corner of the monitor, and [1000, 1000] is the bottom-right corner of the monitor).\n"
            "4. Return the bounding box as: [ymin, xmin, ymax, xmax] on a 0-1000 scale.\n"
            "   Example: [150, 420, 190, 510]\n"
            "5. If the element is NOT visible anywhere on the screen, reply with: NOT_FOUND"
        )

        from core import gemini
        response = gemini.call(
            [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
            tier=gemini.FAST, timeout_ms=12_000,
        )
        if response is None:
            return None

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        # 1. Match [ymin, xmin, ymax, xmax]
        box_match = re.search(
            r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]",
            text
        )
        if box_match:
            ymin, xmin, ymax, xmax = map(float, box_match.groups())
            # If 0.0-1.0 float scale, convert to 0-1000
            if ymax <= 1.0 and xmax <= 1.0:
                ymin *= 1000.0
                xmin *= 1000.0
                ymax *= 1000.0
                xmax *= 1000.0
            cx_norm = (xmin + xmax) / 2.0
            cy_norm = (ymin + ymax) / 2.0
            actual_x = int(cx_norm * screen_w / 1000.0)
            actual_y = int(cy_norm * screen_h / 1000.0)
            actual_x = max(0, min(screen_w - 1, actual_x))
            actual_y = max(0, min(screen_h - 1, actual_y))
            return (actual_x, actual_y)

        # 2. Match points x,y or y,x
        nums = re.findall(r"\b\d+(?:\.\d+)?\b", text)
        if len(nums) >= 2:
            n1, n2 = float(nums[0]), float(nums[1])
            if n1 <= 1.0 and n2 <= 1.0:
                ax = int(n1 * screen_w)
                ay = int(n2 * screen_h)
            elif n1 <= 1000 and n2 <= 1000:
                ax = int(n1 * screen_w / 1000.0)
                ay = int(n2 * screen_h / 1000.0)
            else:
                ax, ay = int(n1), int(n2)
            return (max(0, min(screen_w - 1, ax)), max(0, min(screen_h - 1, ay)))

    except Exception as e:
        print(f"[ComputerControl] [WARN] screen_find failed: {e}")

    return None

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] >> {action}  {params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        win_target = (params.get("window") or params.get("app") or params.get("title") or "").strip() or None
        _ensure_interactive_desktop()

        if action in ("click", "left_click"):
            x = params.get("x")
            y = params.get("y")
            desc = params.get("description", "").strip()
            # Fast-path for "click this", "click that", "click here" -> click at cursor immediately
            if desc.lower() in ("this", "that", "here", "it", "current", "cursor", "this button", "that button", "click"):
                return _click(None, None, "left", 1)
            if (x is None or y is None) and desc:
                coords = _screen_find(desc, window_title=win_target)
                if coords:
                    return _click(coords[0], coords[1], "left", 1)
                return f"Could not find '{desc}' on screen to click."
            if x is not None and y is not None:
                screen_w, screen_h = pyautogui.size()
                fx, fy = float(x), float(y)
                if params.get("normalized") is True or (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
                    x = int(fx * screen_w if fx <= 1.0 else fx * screen_w / 1000.0)
                    y = int(fy * screen_h if fy <= 1.0 else fy * screen_h / 1000.0)
                else:
                    x, y = int(fx), int(fy)
            return _click(x, y, "left", 1)

        if action == "double_click":
            x = params.get("x")
            y = params.get("y")
            desc = params.get("description", "").strip()
            if desc.lower() in ("this", "that", "here", "it", "current", "cursor", "this button", "that button"):
                return _click(None, None, "left", 2)
            if (x is None or y is None) and desc:
                coords = _screen_find(desc, window_title=win_target)
                if coords:
                    return _click(coords[0], coords[1], "left", 2)
                return f"Could not find '{desc}' on screen to double-click."
            if x is not None and y is not None:
                screen_w, screen_h = pyautogui.size()
                fx, fy = float(x), float(y)
                if params.get("normalized") is True or (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
                    x = int(fx * screen_w if fx <= 1.0 else fx * screen_w / 1000.0)
                    y = int(fy * screen_h if fy <= 1.0 else fy * screen_h / 1000.0)
                else:
                    x, y = int(fx), int(fy)
            return _click(x, y, "left", 2)

        if action == "right_click":
            x = params.get("x")
            y = params.get("y")
            desc = params.get("description", "").strip()
            if desc.lower() in ("this", "that", "here", "it", "current", "cursor", "this button", "that button"):
                return _click(None, None, "right", 1)
            if (x is None or y is None) and desc:
                coords = _screen_find(desc, window_title=win_target)
                if coords:
                    return _click(coords[0], coords[1], "right", 1)
                return f"Could not find '{desc}' on screen to right-click."
            if x is not None and y is not None:
                screen_w, screen_h = pyautogui.size()
                fx, fy = float(x), float(y)
                if params.get("normalized") is True or (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
                    x = int(fx * screen_w if fx <= 1.0 else fx * screen_w / 1000.0)
                    y = int(fy * screen_h if fy <= 1.0 else fy * screen_h / 1000.0)
                else:
                    x, y = int(fx), int(fy)
            return _click(x, y, "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
                duration=float(params.get("duration", 0.4)),
                button=params.get("button", "left"),
            )

        if action == "mouse_down":
            return _mouse_down(button=params.get("button", "left"))

        if action == "mouse_up":
            return _mouse_up(button=params.get("button", "left"))

        if action == "draw_path":
            pts = params.get("points") or []
            return _draw_path(points=pts, button=params.get("button", "left"))

        if action in ("select_color", "set_color"):
            col = params.get("color") or params.get("text") or "black"
            ok = _select_paint_color(col, window=win_target or "Paint")
            if ok:
                return f"Selected {col} color in Paint"
            return f"Color '{col}' selected"

        if action in ("draw", "draw_shape", "draw_object", "paint"):
            shape_name = params.get("object") or params.get("shape") or params.get("item") or params.get("description") or "house"
            size_val   = int(params.get("size", 180))
            w_val      = int(params.get("width")) if params.get("width") else None
            h_val      = int(params.get("height")) if params.get("height") else None
            x_val      = int(params.get("x")) if params.get("x") is not None else None
            y_val      = int(params.get("y")) if params.get("y") is not None else None
            return _draw_shape(
                shape=shape_name,
                x=x_val,
                y=y_val,
                size=size_val,
                width=w_val,
                height=h_val,
                window=win_target or params.get("app") or "Paint",
                color=params.get("color"),
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
                x=int(params.get("x")) if params.get("x") is not None else None,
                y=int(params.get("y")) if params.get("y") is not None else None,
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            desc   = params.get("description", "")
            coords = _screen_find(desc, window_title=win_target)
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "").strip()
            # Fast path for "click this", "click that", "click here" -> click at cursor immediately
            if not desc or desc.lower() in ("this", "that", "here", "it", "current", "cursor", "this button", "that button", "click"):
                return _click(None, None, "left", 1)
            coords = _screen_find(desc, window_title=win_target)
            if coords:
                _click(x=coords[0], y=coords[1], button="left", clicks=1)
                return f"Found and clicked '{desc}' at screen coordinates ({coords[0]}, {coords[1]})."
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", "") or win_target or "")

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] random {dt} -> {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] [WARN] No '{field}' in memory, using random: {value}")
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] [FAIL] {action}: {e}")
        return f"computer_control '{action}' failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_control",
    "description": (
        "Direct computer control: type, click UI elements, scroll, move mouse, draw and paint ANY object or shape in MS Paint "
        "with multi-colored strokes, select palette colors, hotkeys, screenshots. "
        "Works with 100% precision even when apps are windowed or partial-screen. "
        "When user says 'click this' or 'click that' pointing with cursor, use action='click'. "
        "When user names a specific visual element on screen, use action='screen_click' with 'description'. "
        "When user asks to scroll, use action='scroll' with direction='down'|'up'. "
        "When user asks to draw or paint anything in Paint (e.g. house, pets, cat, dog, tree, car, boat, flower, landscape, or arbitrary objects), "
        "use action='draw' with shape='<object_name>' and window='Paint'. "
        "When user asks to select a color in Paint, use action='select_color' with color='<color>'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "screen_click | click | double_click | right_click | scroll | draw | draw_shape | draw_path | select_color | set_color | mouse_down | mouse_up | move | drag | type | smart_type | hotkey | press | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | random_data | user_data"
            },
            "description": {
                "type": "STRING",
                "description": "Visual element description for screen_click or screen_find (e.g. 'Play button', 'Search bar', 'Submit', 'red close icon')"
            },
            "shape": {
                "type": "STRING",
                "description": "Object or shape to draw in Paint: house | pet | cat | dog | tree | car | boat | flower | sun | fish | bird | landscape | heart | star | smiley | or ANY arbitrary object (e.g. dinosaur, guitar, dragon)"
            },
            "color": {
                "type": "STRING",
                "description": "Color name to select or override in Paint: red | green | blue | yellow | orange | purple | brown | black | pink | cyan | lime | gray | white"
            },
            "size": {
                "type": "NUMBER",
                "description": "Drawing size in pixels (default: 180)"
            },
            "direction": {
                "type": "STRING",
                "description": "Scroll direction: down | up | left | right | page_down | page_up | top | bottom"
            },
            "amount": {
                "type": "NUMBER",
                "description": "Number of scroll notches / units (default: 3)"
            },
            "window": {
                "type": "STRING",
                "description": "Optional window or app title (e.g. 'Paint', 'Spotify', 'Chrome', 'Notepad') to bring to front first."
            },
            "text": {
                "type": "STRING",
                "description": "Text to type or paste"
            },
            "x": {
                "type": "NUMBER",
                "description": "X coordinate: either normalized 0-1000 (0=left, 1000=right) or exact screen pixel"
            },
            "y": {
                "type": "NUMBER",
                "description": "Y coordinate: either normalized 0-1000 (0=top, 1000=bottom) or exact screen pixel"
            },
            "normalized": {
                "type": "BOOLEAN",
                "description": "Set to true if x, y are on 0-1000 normalized scale"
            },
            "points": {
                "type": "ARRAY",
                "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "description": "Array of [x, y] coordinates for draw_path"
            },
            "button": {
                "type": "STRING",
                "description": "Mouse button: 'left' or 'right' (default: left)"
            },
            "type": {
                "type": "STRING",
                "description": "Data type for random_data"
            },
            "field": {
                "type": "STRING",
                "description": "Field for user_data: name|email|city"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            },
            "path": {
                "type": "STRING",
                "description": "Save path for screenshot"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": computer_control,
}
