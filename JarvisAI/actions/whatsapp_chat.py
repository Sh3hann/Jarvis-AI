"""WhatsApp contact search and chat opener for JARVIS."""
from __future__ import annotations

import platform
import re
import subprocess
import time
import webbrowser

try:
    import pyautogui
    import pyperclip
    _AUTOMATION_READY = True
except ImportError:
    _AUTOMATION_READY = False

_OS = platform.system()


def _focus_whatsapp_window() -> bool:
    """Bring WhatsApp Desktop window to foreground on Windows."""
    if _OS != "Windows":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        matches = []

        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    if "whatsapp" in title.lower():
                        matches.append(hwnd)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        if matches:
            hwnd = matches[0]
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def open_whatsapp_chat(contact: str, message: str = "") -> str:
    """Open WhatsApp Desktop, search for contact/group, and open the chat."""
    contact_clean = str(contact or "").strip()
    if not contact_clean:
        return "Please specify a contact or group name to search in WhatsApp."

    msg_clean = str(message or "").strip()

    # 1. Direct phone number deep link if digits only or international format
    phone_digits = re.sub(r"[^\d+]", "", contact_clean)
    if len(phone_digits) >= 9 and (phone_digits.startswith("+") or phone_digits.isdigit()):
        target_phone = phone_digits.lstrip("+")
        url = f"whatsapp://send?phone={target_phone}"
        if msg_clean:
            import urllib.parse
            url += f"&text={urllib.parse.quote(msg_clean)}"
        try:
            if _OS == "Windows":
                subprocess.Popen(f'explorer.exe "{url}"', shell=True)
            elif _OS == "Darwin":
                subprocess.run(["open", url], check=False)
            else:
                webbrowser.open(url)
            time.sleep(2.0)
            if msg_clean and _AUTOMATION_READY:
                time.sleep(1.0)
                pyautogui.press("enter")
            return f"Opened WhatsApp chat with {contact_clean}."
        except Exception:
            pass

    # 2. Launch / focus WhatsApp Desktop app
    try:
        if _OS == "Windows":
            subprocess.Popen("explorer.exe whatsapp:", shell=True)
            time.sleep(1.8)
            _focus_whatsapp_window()
        elif _OS == "Darwin":
            subprocess.run(["open", "-a", "WhatsApp"], check=False)
            time.sleep(1.8)
        else:
            subprocess.Popen(["whatsapp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.8)
    except Exception as e:
        print(f"[WhatsApp] App launch note: {e}")

    # 3. Perform in-app search via desktop automation
    if _AUTOMATION_READY:
        try:
            if _OS == "Windows":
                _focus_whatsapp_window()
                time.sleep(0.3)

            # Focus search bar in WhatsApp Desktop
            search_key = ("command", "f") if _OS == "Darwin" else ("ctrl", "f")
            select_all = ("command", "a") if _OS == "Darwin" else ("ctrl", "a")
            paste_key = ("command", "v") if _OS == "Darwin" else ("ctrl", "v")

            # Press search hotkey
            pyautogui.hotkey(*search_key)
            time.sleep(0.35)

            # Clear previous search
            pyautogui.hotkey(*select_all)
            time.sleep(0.1)
            pyautogui.press("backspace")
            time.sleep(0.1)

            # Paste contact name via clipboard for exact unicode handling
            pyperclip.copy(contact_clean)
            pyautogui.hotkey(*paste_key)
            time.sleep(1.0)

            # Navigate down into results and open the chat
            pyautogui.press("down")
            time.sleep(0.25)
            pyautogui.press("enter")
            time.sleep(0.5)

            # If user wanted to send a message immediately
            if msg_clean:
                pyperclip.copy(msg_clean)
                pyautogui.hotkey(*paste_key)
                time.sleep(0.25)
                pyautogui.press("enter")
                time.sleep(0.2)
                return f"Opened WhatsApp, found '{contact_clean}', and sent your message."

            return f"Opened WhatsApp and opened the chat conversation with '{contact_clean}'."
        except Exception as exc:
            print(f"[WhatsApp] Automation note: {exc}")
        finally:
            # Crucial: release all modifier keys so the system and app never become unresponsive
            for mod in ("ctrl", "alt", "shift", "command"):
                try:
                    pyautogui.keyUp(mod)
                except Exception:
                    pass

    # 4. Fallback to WhatsApp Web
    try:
        webbrowser.open("https://web.whatsapp.com/")
        return f"Opened WhatsApp Web. Please select '{contact_clean}' from your chats."
    except Exception as e:
        return f"Could not open WhatsApp: {e}"


def whatsapp_action(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    contact = params.get("contact", "")
    message = params.get("message", "")
    result = open_whatsapp_chat(contact, message)
    if player:
        if hasattr(player, "write_log"):
            player.write_log(f"💬 [WhatsApp] {result}")
        if hasattr(player, "show_message"):
            player.show_message(f"WhatsApp: {contact}", message or result)
    return result


TOOL = {
    "name": "open_whatsapp_chat",
    "description": (
        "Opens WhatsApp Desktop, searches for a specific contact or group name, "
        "and opens their chat window. Can also optionally send a message if provided. "
        "MUST be called when the user asks to open WhatsApp, search for a contact on WhatsApp, "
        "open a chat with someone on WhatsApp, or start a conversation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "contact": {
                "type": "STRING",
                "description": "Name or phone number of the contact or group to search for and open (e.g. 'Amma', 'John', 'Family', '+94771234567')."
            },
            "message": {
                "type": "STRING",
                "description": "Optional message text to type and send. Leave empty if the user only wants to search and open the chat."
            }
        },
        "required": ["contact"]
    },
    "handler": whatsapp_action,
}
