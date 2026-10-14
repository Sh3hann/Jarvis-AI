import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, date
from pathlib import Path

_CNW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows" else {}
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    _sys = platform.system()
    if _sys == "Darwin":
        return "mac"
    if _sys == "Linux":
        return "linux"
    return "windows"


def _scripts_dir() -> Path:
    d = Path.home() / ".jarvis" / "reminders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _triggers_dir() -> Path:
    d = Path.home() / ".jarvis" / "reminders" / "triggers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_dir() -> Path:
    d = Path.home() / ".jarvis" / "reminders" / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


_ACTIVE_REMINDERS_FILE = Path.home() / ".jarvis" / "reminders" / "active_reminders.json"
_ACTIVE_REMINDERS: list[dict] = []
_SCHEDULER_THREAD: threading.Thread | None = None
_SCHEDULER_LOCK = threading.Lock()


def _synthesize_reminder_speech(spoken_text: str, target_wav: Path) -> bool:
    """Synthesize reminder text in JARVIS's actual neural Gemini voice."""
    try:
        from google import genai
        from google.genai import types
        import wave

        cfg_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        api_key = None
        voice_name = "Charon"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                api_key = cfg.get("gemini_api_key")
                voice_name = cfg.get("voice_name", "Charon") or "Charon"
            except Exception:
                pass

        if not api_key:
            import os
            api_key = os.environ.get("GEMINI_API_KEY")

        if not api_key:
            return False

        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=spoken_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    )
                ),
            ),
        )

        audio_bytes = None
        if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
            for part in resp.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    audio_bytes = part.inline_data.data
                    break

        if not audio_bytes:
            return False

        target_wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_bytes)
        return True
    except Exception as e:
        print(f"[Reminder] Neural speech synthesis notice: {e}")
        return False


def _speak_reminder(message: str, task_name: str | None = None) -> None:
    """Speak the reminder out loud using JARVIS's actual neural Gemini voice."""
    clean = str(message).strip()
    if clean.lower().startswith("to "):
        spoken_text = f"Sir, this is your reminder {clean}."
    elif clean.lower().startswith("that "):
        spoken_text = f"Sir, this is your reminder {clean}."
    else:
        spoken_text = f"Sir, you asked me to remind you to {clean}."

    def _tts_worker():
        time.sleep(0.3)
        wav_path = None
        if task_name:
            candidate = _audio_dir() / f"{task_name}.wav"
            if candidate.exists() and candidate.stat().st_size > 0:
                wav_path = candidate

        # If not already pre-cached, synthesize on-the-fly using Gemini neural TTS
        if not wav_path or not wav_path.exists():
            fallback_wav = _audio_dir() / f"live_{int(time.time())}.wav"
            if _synthesize_reminder_speech(spoken_text, fallback_wav):
                wav_path = fallback_wav

        played = False
        if wav_path and wav_path.exists():
            try:
                if platform.system() == "Windows":
                    import winsound
                    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
                    played = True
                else:
                    import subprocess
                    cmd = ["afplay", str(wav_path)] if platform.system() == "Darwin" else ["aplay", str(wav_path)]
                    subprocess.run(cmd, check=False)
                    played = True
            except Exception as exc:
                print(f"[Reminder] Neural audio playback notice: {exc}")

        # Fallback to local system voice only if Gemini neural TTS is completely unreachable
        if not played:
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.say(spoken_text)
                engine.runAndWait()
            except Exception:
                try:
                    import win32com.client
                    speaker = win32com.client.Dispatch("SAPI.SpVoice")
                    speaker.Speak(spoken_text)
                except Exception:
                    pass

    threading.Thread(target=_tts_worker, daemon=True).start()


def _fire_reminder(message: str, task_name: str | None = None) -> None:
    """Pop the reminder in Dynamic Island with audible alert and spoken voice."""
    print(f"[Reminder] ⏰ Firing reminder on Dynamic Island and speaking aloud: {message}")
    # 1. Pop notification box on Dynamic Island
    try:
        from core.dynamic_island import DynamicIslandOverlay
        DynamicIslandOverlay.post_notification(
            title="⏰ REMINDER",
            message=message,
            color="#ef4444",
            icon="⏰",
            duration_ms=12000,
        )
    except Exception as e:
        print(f"[Reminder] Dynamic Island display error: {e}")

    # 2. Play reminder sound
    try:
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        try:
            if platform.system() == "Windows":
                import winsound
                for freq in [800, 1000, 1200]:
                    winsound.Beep(freq, 180)
                    time.sleep(0.08)
        except Exception:
            pass

    # 3. JARVIS speaks the reminder out loud on time with the real talking JARVIS voice
    _speak_reminder(message, task_name=task_name)


def _load_active_reminders() -> list[dict]:
    if not _ACTIVE_REMINDERS_FILE.exists():
        return []
    try:
        data = json.loads(_ACTIVE_REMINDERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_active_reminders(items: list[dict]) -> None:
    try:
        _ACTIVE_REMINDERS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Reminder] Failed to save active reminders: {e}")


def _reminder_monitor_loop():
    global _ACTIVE_REMINDERS
    while True:
        try:
            # 1. Check triggers dropped by external scripts / schtasks
            trig_dir = _triggers_dir()
            for trig_file in list(trig_dir.glob("*.trigger")):
                try:
                    content = json.loads(trig_file.read_text(encoding="utf-8"))
                    msg = content.get("message", "Reminder")
                    t_name = content.get("task_name") or trig_file.stem
                    _fire_reminder(msg, task_name=t_name)
                    trig_file.unlink(missing_ok=True)
                except Exception:
                    try:
                        trig_file.unlink(missing_ok=True)
                    except Exception:
                        pass

            # 2. Check in-process active reminders
            now = datetime.now()
            with _SCHEDULER_LOCK:
                remaining = []
                for item in _ACTIVE_REMINDERS:
                    try:
                        target_dt = datetime.fromisoformat(item["target_iso"])
                        if now >= target_dt:
                            _fire_reminder(item.get("message", "Reminder"), task_name=item.get("task_name"))
                        else:
                            remaining.append(item)
                    except Exception:
                        pass
                if len(remaining) != len(_ACTIVE_REMINDERS):
                    _ACTIVE_REMINDERS = remaining
                    _save_active_reminders(_ACTIVE_REMINDERS)
        except Exception:
            pass
        time.sleep(1.5)


def _ensure_scheduler_running():
    global _SCHEDULER_THREAD, _ACTIVE_REMINDERS
    with _SCHEDULER_LOCK:
        if not _ACTIVE_REMINDERS:
            _ACTIVE_REMINDERS = _load_active_reminders()
        if _SCHEDULER_THREAD is None or not _SCHEDULER_THREAD.is_alive():
            _SCHEDULER_THREAD = threading.Thread(target=_reminder_monitor_loop, daemon=True)
            _SCHEDULER_THREAD.start()


def _sanitise(text: str, max_len: int = 200) -> str:
    return (
        text.replace("\\", "")
            .replace('"', "")
            .replace("'", "")
            .replace("\n", " ")
            .replace("\r", "")
            .strip()
    )[:max_len]


def _write_notify_script(task_name: str, message: str, os_name: str) -> Path:
    script_path = _scripts_dir() / f"{task_name}.py"
    msg_literal = json.dumps(message)
    task_name_literal = json.dumps(task_name)
    api_cfg_path_literal = json.dumps(str(Path(__file__).resolve().parent.parent / "config" / "api_keys.json"))

    if os_name == "windows":
        notify_block = f"""
message = {msg_literal}
task_name = {task_name_literal}
cfg_path = {api_cfg_path_literal}
notified = False

# 1. Signal running JARVIS Dynamic Island
try:
    _td = pathlib.Path.home() / ".jarvis" / "reminders" / "triggers"
    _td.mkdir(parents=True, exist_ok=True)
    _tf = _td / f"{{task_name}}.trigger"
    _tf.write_text(json.dumps({{"title": "⏰ REMINDER", "message": message, "task_name": task_name}}), encoding="utf-8")
except Exception:
    pass

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast("J.A.R.V.I.S Reminder", message, duration=15, threaded=False)
        notified = True
    except Exception:
        pass

if not notified:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", message], check=False)
    except Exception:
        pass

try:
    import winsound
    winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)
except Exception:
    try:
        import winsound
        for freq in [800, 1000, 1200]:
            winsound.Beep(freq, 180)
            import time; time.sleep(0.08)
    except Exception:
        pass

# 2. Spoken voice: Play pre-cached real JARVIS voice audio (Charon) or synthesize via Gemini
played = False
try:
    _af = pathlib.Path.home() / ".jarvis" / "reminders" / "audio" / f"{{task_name}}.wav"
    if _af.exists() and _af.stat().st_size > 0:
        import winsound
        winsound.PlaySound(str(_af), winsound.SND_FILENAME)
        played = True
except Exception:
    pass

if not played:
    try:
        from google import genai
        from google.genai import types
        import wave, json

        _p = pathlib.Path(cfg_path)
        _key = None
        _vname = "Charon"
        if _p.exists():
            _c = json.loads(_p.read_text(encoding="utf-8"))
            _key = _c.get("gemini_api_key")
            _vname = _c.get("voice_name", "Charon") or "Charon"
        if not _key:
            _key = os.environ.get("GEMINI_API_KEY")

        if _key:
            _cl = genai.Client(api_key=_key)
            _clean = str(message).strip()
            _txt = f"Sir, you asked me to remind you to {{_clean}}." if not _clean.lower().startswith("to ") else f"Sir, this is your reminder {{_clean}}."
            _resp = _cl.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=_txt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=_vname)
                        )
                    ),
                ),
            )
            for _part in _resp.candidates[0].content.parts:
                if _part.inline_data and _part.inline_data.data:
                    _tmp_wav = pathlib.Path.home() / ".jarvis" / "reminders" / "audio" / f"dyn_{{task_name}}.wav"
                    _tmp_wav.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(_tmp_wav), "wb") as _wf:
                        _wf.setnchannels(1)
                        _wf.setsampwidth(2)
                        _wf.setframerate(24000)
                        _wf.writeframes(_part.inline_data.data)
                    import winsound
                    winsound.PlaySound(str(_tmp_wav), winsound.SND_FILENAME)
                    _tmp_wav.unlink(missing_ok=True)
                    played = True
                    break
    except Exception:
        pass

if not played:
    try:
        import pyttsx3
        _e = pyttsx3.init()
        _e.say(f"Sir, you asked me to remind you to {message}.")
        _e.runAndWait()
    except Exception:
        try:
            import win32com.client
            _sp = win32com.client.Dispatch("SAPI.SpVoice")
            _sp.Speak(f"Sir, you asked me to remind you to {message}.")
        except Exception:
            pass
"""

    elif os_name == "mac":
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        script = 'display notification "{{}}" with title "J.A.R.V.I.S Reminder"'.format(
            message.replace('"', '')
        )
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass
"""

    else:  # linux
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "--urgency=normal", "--expire-time=15000",
             "J.A.R.V.I.S Reminder", message],
            check=False
        )
    except Exception:
        pass
"""

    script_body = f"""# Auto-generated by J.A.R.V.I.S reminder — do not edit
import sys, os, pathlib
{notify_block}
# Self-delete after firing
try:
    pathlib.Path(__file__).unlink(missing_ok=True)
except Exception:
    pass
"""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o600)   # owner read/write only
    return script_path

def _schedule_windows(target_dt: datetime, task_name: str,
                      script_path: Path, message: str) -> str:
    python_exe = Path(sys.executable)
    pythonw = python_exe.parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = pythonw

    xml_path = _scripts_dir() / f"{task_name}.xml"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo><Description>J.A.R.V.I.S Reminder</Description></RegistrationInfo>\n'
        '  <Triggers><TimeTrigger>\n'
        f'    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>\n'
        '    <Enabled>true</Enabled>\n'
        '  </TimeTrigger></Triggers>\n'
        '  <Actions><Exec>\n'
        f'    <Command>{python_exe}</Command>\n'
        f'    <Arguments>"{script_path}"</Arguments>\n'
        '  </Exec></Actions>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>\n'
        '    <Enabled>true</Enabled>\n'
        '  </Settings>\n'
        '  <Principals><Principal>\n'
        '    <LogonType>InteractiveToken</LogonType>\n'
        '    <RunLevel>LeastPrivilege</RunLevel>\n'
        '  </Principal></Principals>\n'
        '</Task>'
    )

    xml_path.write_text(xml_content, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
        capture_output=True, text=True, **_CNW,
    )

    try:
        xml_path.unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode != 0:
        script_path.unlink(missing_ok=True)
        err = (result.stderr or result.stdout).strip()
        print(f"[Reminder] ❌ schtasks: {err}")
        return ""  

    return task_name


def _schedule_mac(target_dt: datetime, task_name: str,
                  script_path: Path) -> str:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    label     = f"com.jarvis.reminder.{task_name}"
    plist_path = agents_dir / f"{label}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{script_path}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Year</key>   <integer>{target_dt.year}</integer>
    <key>Month</key>  <integer>{target_dt.month}</integer>
    <key>Day</key>    <integer>{target_dt.day}</integer>
    <key>Hour</key>   <integer>{target_dt.hour}</integer>
    <key>Minute</key> <integer>{target_dt.minute}</integer>
  </dict>
  <key>RunAtLoad</key>         <false/>
  <key>StandardOutPath</key>   <string>/dev/null</string>
  <key>StandardErrorPath</key> <string>/dev/null</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")
    plist_path.chmod(0o644)

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        plist_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ launchctl: {result.stderr.strip()}")
        return ""

    return label


def _schedule_linux(target_dt: datetime, task_name: str,
                    script_path: Path) -> str:

    if shutil.which("systemd-run"):
        on_calendar = target_dt.strftime("%Y-%m-%d %H:%M:00")
        result = subprocess.run(
            [
                "systemd-run",
                "--user",
                f"--on-calendar={on_calendar}",
                f"--unit={task_name}",
                "--",
                sys.executable, str(script_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ⚠️ systemd-run failed: {result.stderr.strip()}, trying 'at'")

    if shutil.which("at"):
        at_time = target_dt.strftime("%H:%M %Y-%m-%d")
        cmd_str = f"{sys.executable} {script_path}\n"
        result  = subprocess.run(
            ["at", at_time],
            input=cmd_str, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ❌ at: {result.stderr.strip()}")
        return ""

    print("[Reminder] ❌ Neither systemd-run nor at found on this Linux system.")
    return ""

def _parse_time(time_raw: str) -> tuple[int, int] | None:
    t = (time_raw or "").strip().lower()
    if not t:
        return None

    # Check for AM / PM pattern: e.g. "12:30 pm", "12 am", "12am", "6:15am"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        hr = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "am":
            hr = 0 if hr == 12 else hr
        elif meridiem == "pm":
            hr = 12 if hr == 12 else hr + 12
        return (hr, mn)

    # Check for 24-hour pattern: "14:30", "00:00", "0:00", "12:00"
    m2 = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
    if m2:
        hr = int(m2.group(1))
        mn = int(m2.group(2))
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            return (hr, mn)

    # Check for single integer: e.g. "12", "5"
    m3 = re.search(r"\b(\d{1,2})\b", t)
    if m3:
        hr = int(m3.group(1))
        if 0 <= hr <= 23:
            return (hr, 0)

    return None


def _parse_date(date_raw: str, default_date: date) -> tuple[date, bool]:
    d = (date_raw or "").strip().lower()
    if not d or d in ("today", "now", "tonight"):
        return (default_date, True)
    if d == "tomorrow":
        return (default_date + timedelta(days=1), False)

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(d, fmt).date()
            if "%Y" not in fmt:
                parsed = parsed.replace(year=default_date.year)
            is_today = (parsed == default_date)
            return (parsed, is_today)
        except ValueError:
            pass

    return (default_date, True)


def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:

    action = str(parameters.get("action", "reminder")).strip().lower()
    if action in {"timer", "countdown", "pomodoro"}:
        try:
            minutes = int(parameters.get("duration_minutes") or (25 if action == "pomodoro" else 1))
        except Exception:
            minutes = 25 if action == "pomodoro" else 1
        minutes = max(1, min(24 * 60, minutes))
        if player and hasattr(player, "start_timer"):
            player.start_timer(minutes, "POMODORO / FOCUS" if action == "pomodoro" else "COUNTDOWN")
            return f"{('Pomodoro focus' if action == 'pomodoro' else 'Countdown timer')} started for {minutes} minutes in the HUD."
        return "The HUD timer is unavailable in this session."

    date_str = str(parameters.get("date") or "").strip()
    time_str = str(parameters.get("time") or "").strip()
    message  = str(parameters.get("message") or "Reminder").strip()

    # If time was given in date_str or message:
    if not time_str and date_str:
        t_match = _parse_time(date_str)
        if t_match:
            time_str = date_str
            date_str = ""

    if not time_str and message:
        t_match = _parse_time(message)
        if t_match:
            time_str = message

    if not time_str:
        return "I need a time (e.g. 12 am, 6:30 pm, 14:00) to set a reminder."

    parsed_time = _parse_time(time_str)
    if not parsed_time:
        return f"I couldn't parse the time '{time_str}'. Please specify like '12 am' or '14:30'."

    now = datetime.now()
    parsed_date, is_today_or_default = _parse_date(date_str, now.date())
    target_dt = datetime.combine(parsed_date, datetime.min.time()).replace(
        hour=parsed_time[0], minute=parsed_time[1], second=0, microsecond=0
    )

    # Next occurrence rollover: if date was today or not specified and target has passed today, roll over to tomorrow!
    if is_today_or_default and target_dt <= now:
        target_dt += timedelta(days=1)

    if target_dt <= now:
        return "That time has already passed — I can't set a reminder in the past."

    os_name    = _get_os()
    safe_msg   = _sanitise(message)
    task_name  = f"JARVISReminder_{target_dt.strftime('%Y%m%d_%H%M%S')}"

    # Pre-synthesize the exact neural JARVIS voice (Charon) in background for instant trigger
    audio_wav = _audio_dir() / f"{task_name}.wav"
    clean_msg = safe_msg
    if clean_msg.lower().startswith("to "):
        spoken_text = f"Sir, this is your reminder {clean_msg}."
    elif clean_msg.lower().startswith("that "):
        spoken_text = f"Sir, this is your reminder {clean_msg}."
    else:
        spoken_text = f"Sir, you asked me to remind you to {clean_msg}."

    threading.Thread(
        target=_synthesize_reminder_speech,
        args=(spoken_text, audio_wav),
        daemon=True,
    ).start()

    # 1. Register in-process scheduler so Dynamic Island is guaranteed to show it on time!
    _ensure_scheduler_running()
    with _SCHEDULER_LOCK:
        _ACTIVE_REMINDERS.append({
            "task_name": task_name,
            "target_iso": target_dt.isoformat(),
            "message": safe_msg,
        })
        _save_active_reminders(_ACTIVE_REMINDERS)

    # 2. Also register OS scheduler fallback
    try:
        script_path = _write_notify_script(task_name, safe_msg, os_name)
        if os_name == "windows":
            _schedule_windows(target_dt, task_name, script_path, safe_msg)
        elif os_name == "mac":
            _schedule_mac(target_dt, task_name, script_path)
        else:
            _schedule_linux(target_dt, task_name, script_path)
    except Exception as e:
        print(f"[Reminder] OS scheduling notice: {e}")

    if player:
        player.write_log(f"[Reminder] ✅ {target_dt.strftime('%Y-%m-%d %H:%M')} — {safe_msg[:40]}")
        if hasattr(player, "add_reminder_card"):
            try:
                player.add_reminder_card(safe_msg, target_dt)
            except Exception as exc:
                print(f"[Reminder] HUD countdown registration notice: {exc}")

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    return f"Reminder set for {friendly_time}."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "reminder",
    "description": "Sets a dated reminder or starts a visible HUD countdown/Pomodoro timer. Use action='timer' with duration_minutes for a countdown or action='pomodoro' for a 25-minute focus timer. For a scheduled reminder use action='reminder' with date, time, message.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "reminder (default) | timer | countdown | pomodoro"},
            "duration_minutes": {"type": "INTEGER", "description": "Countdown length in minutes; for timer/countdown actions"},
            "date": {
                "type": "STRING",
                "description": "Date in YYYY-MM-DD format"
            },
            "time": {
                "type": "STRING",
                "description": "Time in HH:MM format (24h)"
            },
            "message": {
                "type": "STRING",
                "description": "Reminder message text"
            }
        },
        "required": []
    },
    "handler": reminder,
}
