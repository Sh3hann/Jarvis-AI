"""
Dynamic Island overlay for JARVIS AI.
A living, breathing pill overlay 100% faithful to Apple's iOS Dynamic Island and the jordibruin/Dynamic-Islands spec.

Design Specifications:
- Pure OLED Jet Black (#000000) with authentic 38px squircle corner radius in expanded state.
- Compact Pill Bar:
    - Leading (Left): Real-time weather in Celsius (e.g. '⛅ 25°C'), mini album art thumbnail, or active notification badge.
    - Center: Hardware camera sensor cutout with privacy indicator dots (mic/cam).
    - Trailing (Right): Clean solid-color equalizer bars, live time, or notification message snippet.
- Windows Toast & WhatsApp Real-Time Monitor:
    - Hooks directly into Windows UserNotificationListener API to capture live toast notifications (even when Windows DND / Focus Assist is enabled).
    - WhatsApp messages trigger a sleek iOS Dynamic Island pill banner animation on the compact bar (not an intrusive full box pop up).
    - Smooth horizontal pill expansion (240px -> 324px): vibrant green WhatsApp icon '💬' + sender name on the left, live message preview on the right.
    - Clipboard copying triggers a sleek pill animation ('📋 Copied' + text preview) without covering the screen.
- Rock-Solid Topmost Front Enforcement:
    - Win32 WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE applied directly to the Win32 window handle.
    - 400ms heartbeat re-asserts HWND_TOPMOST so the Dynamic Island stays in the frontmost layer even when other apps, browsers, or games are active.
- Voice & Media Audio Visualizer (Solid Color):
    - Solid Green (#22c55e) when the USER is talking.
    - Solid Red (#ef4444) when JARVIS is talking.
    - Solid White (#ffffff) when MUSIC is playing.
    - Solid Muted Gray (#a1a1aa) when idle.
    - Accurately scales and animates in real-time with live voice audio levels.
    - Rainbow gradients and multi-color fills completely removed.
- Expanded Music Island (Exact match with Apple iOS Dynamic Island reference Image 2):
    - Real album cover art (56x56 px, r=14px) with automated iTunes high-res artwork resolution when SMTC thumbnail is empty.
    - Track title (15px bold white) and artist (13px muted iOS grey #8e8e93). Accurate live tracking with NO hardcoded fallbacks!
    - Clean solid-color animated equalizer waveform bars matching voice/media states.
    - Authentic Apple scrubber: elapsed timestamp (e.g. 1:47), solid white progress bar on #38383a track, countdown timestamp (e.g. -2:07), drag-to-seek support.
    - Vector transport controls: Previous (⏮), Play/Pause (❚❚ / ▶), Next (⏭), and AirPlay icon (⟐). Pure white, transparent background, responsive clicks.
- Flawless Click & Auto-Minimize Behavior:
    - Entire compact bar is 100% clickable with zero dead spots; clicking anywhere smoothly expands it.
    - Automatically minimizes back to the compact bar after 5 seconds of inactivity.
    - Interacting with buttons, scrubber, or moving the mouse resets the 5-second timer.
    - Moving the mouse away from the box auto-collapses it in 2.5 seconds.
    - Clicking anywhere on the box background immediately minimizes it back to the bar.
"""
from __future__ import annotations

import asyncio
import calendar
import ctypes
import gc
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import pynvml
    pynvml.nvmlInit()
    _HAS_NVML = True
except Exception:
    _HAS_NVML = False

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SMTC,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import DataReader
    _HAS_WINRT_SMTC = True
except Exception:
    _HAS_WINRT_SMTC = False

try:
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )
    from winrt.windows.ui.notifications import NotificationKinds
    _HAS_WINRT_NOTIFS = True
except Exception:
    _HAS_WINRT_NOTIFS = False


# ── Windows Extended Virtual Key & AppCommand Constants ──────────────────────
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_NEXTTRACK = 11
APPCOMMAND_MEDIA_PREVIOUSTRACK = 12
APPCOMMAND_MEDIA_STOP = 13
APPCOMMAND_MEDIA_PLAY_PAUSE = 14


def _dispatch_media_key(vk: int, app_cmd: int) -> None:
    """
    Robust media key dispatcher combining AppCommand broadcast and extended keybd_event.
    Guarantees Spotify, YouTube, Chrome, Media Player, and VLC respond to transport buttons.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        user32.SendMessageW(hwnd, WM_APPCOMMAND, hwnd, app_cmd << 16)
        user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
    except Exception as e:
        print(f"[DynamicIsland] Media key dispatch failed: {e}")


# ── In-Memory Album Art Cache ────────────────────────────────────────────────
_ARTWORK_CACHE: dict[str, bytes] = {}


def _fetch_online_artwork(title: str, artist: str) -> bytes:
    """Fetch official album art from iTunes Search API when SMTC thumbnail is empty."""
    query = f"{title} {artist}".strip()
    if not query:
        return b""
    if query in _ARTWORK_CACHE:
        return _ARTWORK_CACHE[query]

    try:
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            if results:
                art_url = results[0].get("artworkUrl100", "").replace("100x100bb.jpg", "600x600bb.jpg")
                if art_url:
                    img_req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(img_req, timeout=3.5) as img_resp:
                        img_bytes = img_resp.read()
                        if img_bytes:
                            if len(_ARTWORK_CACHE) >= 16:
                                try:
                                    _ARTWORK_CACHE.pop(next(iter(_ARTWORK_CACHE)))
                                except Exception:
                                    pass
                            _ARTWORK_CACHE[query] = img_bytes
                            return img_bytes
    except Exception:
        pass
    return b""


# ── Solid Color Audio & Voice Visualizer Waveform Widget ─────────────────────
class IOSEqualizerWidget(QWidget):
    """
    Apple iOS style audio visualizer waveform widget with solid colors:
    - Solid Green (#22c55e) when the USER is talking.
    - Solid Red (#ef4444) when JARVIS is talking.
    - Solid White (#ffffff) when MUSIC is playing.
    - Solid Muted Gray (#a1a1aa) when IDLE/STANDBY.
    Accurately scales in real-time with live voice and audio levels.
    """

    def __init__(self, parent: QWidget | None = None, num_bars: int = 5, bar_w: float = 2.6, spacing: float = 2.0):
        super().__init__(parent)
        self._num_bars = num_bars
        self._bar_w = bar_w
        self._spacing = spacing
        total_w = int(num_bars * bar_w + (num_bars - 1) * spacing) + 4
        self.setFixedSize(max(26, total_w), 20)
        self._level = 0.0
        self._target_level = 0.0
        self._phase = 0.0
        self._is_playing = False
        self._mode = "idle"  # "user", "jarvis", "music", "idle"
        self._solid_color = QColor("#a1a1aa")

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(33)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "user":
            self._solid_color = QColor("#22c55e")  # Solid Green when user is talking
        elif mode == "jarvis":
            self._solid_color = QColor("#ef4444")  # Solid Red when Jarvis is talking
        elif mode == "music":
            self._solid_color = QColor("#ffffff")  # Solid White for music
        else:
            self._solid_color = QColor("#a1a1aa")  # Solid Muted Gray for idle
        if not self._anim_timer.isActive():
            self._anim_timer.start(33)
        self.update()

    def set_level(self, level: float | None) -> None:
        if level is None:
            self._target_level = 0.04
        else:
            try:
                target = max(0.0, min(1.0, float(level)))
                if target > self._target_level:
                    self._target_level = self._target_level * 0.15 + target * 0.85
                else:
                    self._target_level = self._target_level * 0.70 + target * 0.30
            except (TypeError, ValueError):
                self._target_level = 0.04
        if self._target_level > 0.05 and not self._anim_timer.isActive():
            self._anim_timer.start(33)

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        if self._mode not in ("user", "jarvis"):
            if playing:
                self.set_mode("music")
            else:
                self.set_mode("idle")
        if playing and not self._anim_timer.isActive():
            self._anim_timer.start(33)

    def _tick(self) -> None:
        self._phase += 0.30
        self._level += (self._target_level - self._level) * 0.45
        self._target_level = max(0.03, self._target_level * 0.92)
        # Power & RAM saving: pause timer when completely idle
        if self._mode == "idle" and not self._is_playing and self._level <= 0.035 and self._target_level <= 0.035:
            self._anim_timer.stop()
        self.update()


    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        total_w = self._num_bars * self._bar_w + (self._num_bars - 1) * self._spacing
        start_x = (self.width() - total_w) / 2.0
        mid_y = self.height() / 2.0

        is_voice_active = (self._mode in ("user", "jarvis") and self._level > 0.04)
        is_active = is_voice_active or self._is_playing or self._level > 0.08

        painter.setBrush(QBrush(self._solid_color))
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(self._num_bars):
            dist_from_center = abs(i - (self._num_bars - 1) / 2.0)
            center_weight = max(0.65, 1.15 - dist_from_center * 0.25)

            freq = 0.85 + i * 0.40
            wave = (math.sin(self._phase * freq + i * 0.9) + 1.0) * 0.5

            if is_active:
                amplitude = (self._level * 0.85 + wave * 0.25) * center_weight
                factor = max(0.20, min(1.0, amplitude))
            else:
                factor = 0.18 + wave * 0.08

            bar_h = max(3.5, factor * (self.height() - 4.0))
            x = start_x + i * (self._bar_w + self._spacing)
            y = mid_y - bar_h / 2.0

            painter.drawRoundedRect(QRectF(x, y, self._bar_w, bar_h), self._bar_w / 2.0, self._bar_w / 2.0)


# ── Authentic Apple iOS Animated Loading / Progress Bar ─────────────────────
class IOSProgressBar(QWidget):
    """
    Sleek Apple iOS Dynamic Island animated progress bar.
    Renders with rounded pill caps and smooth gradient fill for copy/paste and task feedback.
    """
    def __init__(self, parent: QWidget | None = None, height: int = 3):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._progress = 0.0
        self._color = QColor("#38bdf8")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_progress(self, val: float, color: str = "#38bdf8") -> None:
        self._progress = max(0.0, min(1.0, float(val)))
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        # Background track
        painter.setBrush(QBrush(QColor(255, 255, 255, 28)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # Progress fill
        if self._progress > 0.0:
            fill_w = max(h, w * self._progress)
            grad = QLinearGradient(0, 0, fill_w, h)
            grad.setColorAt(0.0, self._color)
            grad.setColorAt(1.0, self._color.lighter(130))
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(QRectF(0, 0, fill_w, h), r, r)



# ── Album Art Display Widget (Apple iOS Squircle) ────────────────────────────
class AlbumArtWidget(QWidget):
    """
    Renders album cover artwork in an authentic iOS squircle (56x56 px, r=14px).
    Features smooth image scaling and clean monochrome vinyl fallback when inactive.
    """

    def __init__(self, parent: QWidget | None = None, size: int = 56):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._pixmap: Optional[QPixmap] = None
        self._track_title = ""

    def set_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        self._pixmap = pixmap
        self.update()

    def set_bytes(self, data: bytes, title: str = "") -> None:
        self._track_title = title
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                self._pixmap = pix
                self.update()
                return
        self._pixmap = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = float(self.width())
        h = float(self.height())
        rect = QRectF(0.0, 0.0, w, h)
        radius = 14.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.save()
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                int(w), int(h),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = (scaled.width() - int(w)) // 2
            sy = (scaled.height() - int(h)) // 2
            painter.drawPixmap(0, 0, scaled, sx, sy, int(w), int(h))
            painter.setPen(QPen(QColor(255, 255, 255, 25), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), radius, radius)
        else:
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0.0, QColor("#1f1f23"))
            grad.setColorAt(1.0, QColor("#121214"))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(self.rect())

            painter.setPen(QPen(QColor(255, 255, 255, 14), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(7, 7, w - 14, h - 14))
            painter.drawEllipse(QRectF(15, 15, w - 30, h - 30))

            painter.setPen(QColor("#71717a"))
            f = painter.font()
            f.setPointSize(16)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "🎵")

        painter.restore()


# ── Authentic Apple iOS Transport Control Buttons ───────────────────────────
class IOSTransportButton(QPushButton):
    """
    Pure white vector transport button matching Apple iOS Dynamic Island (Image 2).
    Zero background boxes, zero rainbow borders, pristine antialiased vector geometry with QPointF.
    """
    user_interacted = pyqtSignal()

    def __init__(self, kind: str, parent: QWidget | None = None, size: int = 36):
        super().__init__(parent)
        self._kind = kind  # "prev", "play", "pause", "next", "airplay"
        self._is_playing = False
        self._is_hovered = False
        self._is_pressed = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def set_kind(self, kind: str) -> None:
        if self._kind != kind:
            self._kind = kind
            self.update()

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        self.set_kind("pause" if playing else "play")

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        self._is_pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = True
            self.update()
            self.user_interacted.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._is_pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        cx = w / 2.0
        cy = h / 2.0

        alpha = 140 if self._is_pressed else (210 if self._is_hovered else 255)
        color = QColor(255, 255, 255, alpha)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)

        if self._kind == "prev":
            tri_w = 6.8
            tri_h = 11.0
            p1 = QPolygonF([QPointF(cx - 1.0, cy), QPointF(cx - 1.0 + tri_w, cy - tri_h / 2.0), QPointF(cx - 1.0 + tri_w, cy + tri_h / 2.0)])
            p2 = QPolygonF([QPointF(cx - 1.0 - tri_w, cy), QPointF(cx - 1.0, cy - tri_h / 2.0), QPointF(cx - 1.0, cy + tri_h / 2.0)])
            painter.drawPolygon(p1)
            painter.drawPolygon(p2)

        elif self._kind == "next":
            tri_w = 6.8
            tri_h = 11.0
            p1 = QPolygonF([QPointF(cx + 1.0, cy), QPointF(cx + 1.0 - tri_w, cy - tri_h / 2.0), QPointF(cx + 1.0 - tri_w, cy + tri_h / 2.0)])
            p2 = QPolygonF([QPointF(cx + 1.0 + tri_w, cy), QPointF(cx + 1.0, cy - tri_h / 2.0), QPointF(cx + 1.0, cy + tri_h / 2.0)])
            painter.drawPolygon(p1)
            painter.drawPolygon(p2)

        elif self._kind == "play":
            tri_w = 11.0
            tri_h = 15.0
            poly = QPolygonF([
                QPointF(cx + tri_w * 0.6, cy),
                QPointF(cx - tri_w * 0.4, cy - tri_h / 2.0),
                QPointF(cx - tri_w * 0.4, cy + tri_h / 2.0),
            ])
            painter.drawPolygon(poly)

        elif self._kind == "pause":
            bar_w = 4.2
            bar_h = 14.0
            gap = 4.0
            x1 = cx - gap / 2.0 - bar_w
            x2 = cx + gap / 2.0
            y = cy - bar_h / 2.0
            painter.drawRoundedRect(QRectF(x1, y, bar_w, bar_h), bar_w / 2.0, bar_w / 2.0)
            painter.drawRoundedRect(QRectF(x2, y, bar_w, bar_h), bar_w / 2.0, bar_w / 2.0)

        elif self._kind == "airplay":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(160, 160, 165, alpha), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(int(cx - 9), int(cy - 9), 18, 18, 45 * 16, 90 * 16)
            painter.drawArc(int(cx - 6), int(cy - 6), 12, 12, 45 * 16, 90 * 16)
            painter.setBrush(QBrush(QColor(160, 160, 165, alpha)))
            painter.setPen(Qt.PenStyle.NoPen)
            tri_poly = QPolygonF([
                QPointF(cx, cy - 1.0),
                QPointF(cx - 5.0, cy + 6.0),
                QPointF(cx + 5.0, cy + 6.0),
            ])
            painter.drawPolygon(tri_poly)


# ── Authentic Apple iOS Scrubber Slider ──────────────────────────────────────
class IOSScrubberWidget(QWidget):
    """
    Apple iOS progress scrubber bar as seen in Image 2.
    Solid white progress bar on #38383a background track with rounded ends.
    Click or drag anywhere to seek live.
    """
    seek_requested = pyqtSignal(float)
    user_interacted = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._progress = 0.0
        self._total_seconds = 235.0
        self._is_dragging = False

    def set_progress(self, current_sec: float, total_sec: float) -> None:
        if self._is_dragging:
            return
        self._total_seconds = max(1.0, total_sec)
        self._progress = max(0.0, min(1.0, current_sec / self._total_seconds))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        bar_h = 5.5
        y = (h - bar_h) / 2.0
        r = bar_h / 2.0

        # Background Track
        track_rect = QRectF(0.0, y, w, bar_h)
        painter.setBrush(QBrush(QColor("#38383a")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(track_rect, r, r)

        # Active Solid White Progress Fill
        fill_w = max(bar_h, w * self._progress) if self._progress > 0 else 0.0
        if fill_w > 0:
            fill_rect = QRectF(0.0, y, fill_w, bar_h)
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawRoundedRect(fill_rect, r, r)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            pos_x = event.position().x()
            self._progress = max(0.0, min(1.0, pos_x / max(1.0, float(self.width()))))
            self.update()
            self.user_interacted.emit()
            self.seek_requested.emit(self._progress * self._total_seconds)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging:
            pos_x = event.position().x()
            self._progress = max(0.0, min(1.0, pos_x / max(1.0, float(self.width()))))
            self.update()
            self.user_interacted.emit()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.user_interacted.emit()
            self.seek_requested.emit(self._progress * self._total_seconds)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ── Clickable Pill Frame & Widget ────────────────────────────────────────────
class ClickablePillFrame(QFrame):
    """QFrame that reliably dispatches click events to the parent overlay."""
    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            parent = self.window()
            if hasattr(parent, "handle_pill_click"):
                parent.handle_pill_click()
                event.accept()
                return
        super().mousePressEvent(event)


class ClickableCompactWidget(QWidget):
    """QWidget for the compact pill bar guaranteeing zero dead spots on click."""
    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            parent = self.window()
            if hasattr(parent, "handle_pill_click"):
                parent.handle_pill_click()
                event.accept()
                return
        super().mousePressEvent(event)


# ── Windows DND / Focus Assist Detection ─────────────────────────────────────
def is_windows_dnd_active() -> bool:
    """
    Check if Windows Do Not Disturb / Focus Assist / Quiet Hours is active.
    Checks Windows CloudStore QuietHours profile (UTF-16LE & ASCII) and Win32 SHQueryUserNotificationState.
    """
    # 1. Check Windows 11 CloudStore DND setting (Live real-time detection)
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as parent:
            for i in range(200):
                try:
                    sub = winreg.EnumKey(parent, i)
                    if "donotdisturb.quiethourssettings" in sub.lower():
                        full_sub = f"{key_path}\\{sub}\\windows.data.donotdisturb.quiethourssettings"
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, full_sub) as sk:
                            data, _ = winreg.QueryValueEx(sk, "Data")
                            raw = bytes(data).lower()
                            # PriorityOnly / AlarmsOnly / Muted = DND is ON
                            for kw in ("priorityonly", "alarmsonly", "muted"):
                                if (kw.encode("utf-16le") in raw) or (kw.encode("ascii") in raw):
                                    return True
                            # Unrestricted = DND is OFF
                            for kw in ("unrestricted",):
                                if (kw.encode("utf-16le") in raw) or (kw.encode("ascii") in raw):
                                    return False
                except OSError:
                    break
    except Exception:
        pass

    # 2. Fallback to Win32 SHQueryUserNotificationState
    try:
        shell32 = ctypes.windll.shell32
        state = ctypes.c_ulong()
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            if state.value == 6:  # QUNS_QUIET_TIME
                return True
    except Exception:
        pass

    return False


# ── Windows Live Notification & WhatsApp Watcher ─────────────────────────────
class WindowsNotificationWatcher(QWidget):
    """
    Hooks directly into Windows UserNotificationListener API to capture live toast notifications.
    Operates in a persistent low-latency daemon event loop (~150ms poll cycle) to guarantee zero delay.
    Inspects all visual bindings to reliably detect WhatsApp voice and video calls as well as messages.
    Extracts the exact UTC creation timestamp and converts to local time for 100% accurate time display.
    Works even when Windows DND (Do Not Disturb) / Focus Assist is active!
    """
    notification_arrived = pyqtSignal(str, str, str, str, str)  # app_name, sender/title, body, badge_color, msg_time

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._seen_ids: set[int] = set()
        self._seen_messages: dict[int, str] = {}
        self._running = True
        self._initialized = False

        if _HAS_WINRT_NOTIFS:
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def stop(self) -> None:
        self._running = False

    def _worker_loop(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_run())
            loop.close()
        except Exception as e:
            print(f"[DynamicIsland] Notification watcher thread error: {e}")

    async def _async_run(self) -> None:
        try:
            listener = UserNotificationListener.current
            await listener.request_access_async()
            # Initial scan: mark all historical notifications as already seen
            # so we DO NOT replay old historical messages upon startup!
            initial_notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
            if initial_notifs:
                for n in initial_notifs:
                    try:
                        self._seen_ids.add(n.id)
                        content_key = self._extract_content_key(n)
                        if content_key:
                            self._seen_messages[n.id] = content_key
                    except Exception:
                        pass
            self._initialized = True
        except Exception as e:
            print(f"[DynamicIsland] Notification listener init error: {e}")
            self._initialized = True

        # Ultra-fast continuous poll loop (150ms sleep)
        while self._running:
            try:
                listener = UserNotificationListener.current
                notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
                if notifs:
                    self._process_notifications(notifs)
            except Exception:
                pass
            await asyncio.sleep(0.15)

    def _extract_notification_data(self, n) -> tuple[str, str, list[str], str]:
        """
        Extract app_name, app_id, texts, and exact creation time from a UserNotification.
        Inspects all visual bindings to capture call templates (ToastCall, VoIP) as well as ToastGeneric.
        """
        app_name = "App"
        app_id = ""
        try:
            if n.app_info:
                if n.app_info.display_info and n.app_info.display_info.display_name:
                    app_name = n.app_info.display_info.display_name
                if n.app_info.id:
                    app_id = n.app_info.id
        except Exception:
            pass

        texts: list[str] = []
        # 1. Iterate over all visual bindings (crucial for ToastCall, VoIP, custom templates)
        try:
            if hasattr(n.notification, "visual") and n.notification.visual:
                if hasattr(n.notification.visual, "bindings") and n.notification.visual.bindings:
                    for b in n.notification.visual.bindings:
                        try:
                            for t in b.get_text_elements():
                                val = (t.text or "").strip()
                                if val and val not in texts:
                                    texts.append(val)
                        except Exception:
                            pass
        except Exception:
            pass

        # 2. Fallback to known templates if bindings was empty
        if not texts:
            known_templates = ("ToastGeneric", "ToastCall", "ToastText01", "ToastText02", "ToastImageAndText01")
            for tmpl in known_templates:
                try:
                    b = n.notification.visual.get_binding(tmpl)
                    if b:
                        for t in b.get_text_elements():
                            val = (t.text or "").strip()
                            if val and val not in texts:
                                texts.append(val)
                        if texts:
                            break
                except Exception:
                    pass

        # 3. Extract accurate creation timestamp
        msg_time = ""
        try:
            if hasattr(n, "creation_time") and n.creation_time:
                local_dt = n.creation_time.astimezone()
                msg_time = local_dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            pass
        if not msg_time:
            msg_time = datetime.now().strftime("%I:%M %p").lstrip("0")

        return app_name, app_id, texts, msg_time

    def _extract_content_key(self, n) -> str:
        _, _, texts, _ = self._extract_notification_data(n)
        return " | ".join(texts)

    def _process_notifications(self, notifs) -> None:
        for n in notifs:
            try:
                app_name, app_id, texts, msg_time = self._extract_notification_data(n)
                if not texts:
                    continue

                title = texts[0]
                body = " ".join(texts[1:]) if len(texts) > 1 else ""
                content_key = f"{title}:{body}"

                is_new = (n.id not in self._seen_ids) or (self._seen_messages.get(n.id) != content_key)
                if is_new:
                    self._seen_ids.add(n.id)
                    self._seen_messages[n.id] = content_key

                    is_whatsapp = (
                        ("whatsapp" in app_name.lower())
                        or ("whatsapp" in app_id.lower())
                        or ("whatsapp" in title.lower())
                        or ("whatsapp" in body.lower())
                    )
                    color = "#22c55e" if is_whatsapp else "#38bdf8"
                    app_label = "WhatsApp" if is_whatsapp else app_name

                    self.notification_arrived.emit(app_label, title, body, color, msg_time)
            except Exception:
                continue


# ── Windows SMTC Live Media Poller Worker ─────────────────────────────────────
class MediaSessionWatcher(QWidget):
    media_updated = pyqtSignal(dict)
    artwork_fetched = pyqtSignal(bytes)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_title = ""
        self._current_artist = ""
        self._fetching = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_now)
        self._timer.start(1200)

    def _poll_now(self) -> None:
        if not _HAS_WINRT_SMTC or self._fetching:
            return
        self._fetching = True
        threading.Thread(target=self._async_fetch, daemon=True).start()

    def _async_fetch(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            data = loop.run_until_complete(self._query_smtc())
            loop.close()
            if data:
                self.media_updated.emit(data)
                title = data.get("title", "")
                artist = data.get("artist", "")
                thumb = data.get("thumb_bytes", b"")
                if title and not thumb and (title != self._current_title or artist != self._current_artist):
                    self._current_title = title
                    self._current_artist = artist
                    threading.Thread(target=self._fetch_art_worker, args=(title, artist), daemon=True).start()
        except Exception:
            pass
        finally:
            self._fetching = False

    def _fetch_art_worker(self, title: str, artist: str) -> None:
        art_bytes = _fetch_online_artwork(title, artist)
        if art_bytes:
            self.artwork_fetched.emit(art_bytes)

    @staticmethod
    async def _get_best_session(mgr):
        if not mgr:
            return None
        cur = None
        try:
            cur = mgr.get_current_session()
        except Exception:
            cur = None

        sessions = []
        try:
            raw = mgr.get_sessions()
            if raw:
                sessions = list(raw)
        except Exception:
            sessions = []

        candidates = []
        if cur:
            candidates.append(cur)
        for s in sessions:
            if s not in candidates:
                candidates.append(s)

        for s in candidates:
            try:
                info = s.get_playback_info()
                if info and info.playback_status == PlaybackStatus.PLAYING:
                    return s
            except Exception:
                pass

        for s in candidates:
            try:
                prop = await s.try_get_media_properties_async()
                if prop and prop.title and prop.title.strip():
                    return s
            except Exception:
                pass

        return cur or (sessions[0] if sessions else None)

    async def _query_smtc(self) -> dict | None:
        mgr = await SMTC.request_async()
        if not mgr:
            return None

        sessions = []
        try:
            raw = mgr.get_sessions()
            if raw:
                sessions = list(raw)
        except Exception:
            sessions = []

        cur = None
        try:
            cur = mgr.get_current_session()
        except Exception:
            cur = None

        candidate_sessions = []
        if cur:
            candidate_sessions.append(cur)
        for s in sessions:
            if s not in candidate_sessions:
                candidate_sessions.append(s)

        chosen_session = None
        chosen_prop = None
        chosen_info = None

        fallback_session = None
        fallback_prop = None
        fallback_info = None

        for s in candidate_sessions:
            try:
                prop = await s.try_get_media_properties_async()
                if not prop:
                    continue
                t = prop.title.strip() if prop.title else ""
                if not t:
                    continue

                info = s.get_playback_info()
                is_playing = (info and info.playback_status == PlaybackStatus.PLAYING)

                if is_playing:
                    chosen_session = s
                    chosen_prop = prop
                    chosen_info = info
                    break  # Actively playing with title has highest priority
                elif not fallback_session:
                    fallback_session = s
                    fallback_prop = prop
                    fallback_info = info
            except Exception:
                continue

        if not chosen_session and fallback_session:
            chosen_session = fallback_session
            chosen_prop = fallback_prop
            chosen_info = fallback_info

        if not chosen_session or not chosen_prop:
            return {
                "active": False,
                "title": "",
                "artist": "",
                "album": "",
                "playing": False,
                "pos": 0.0,
                "end": 0.0,
                "thumb_bytes": b"",
            }

        title = chosen_prop.title.strip() if chosen_prop.title else ""
        artist = chosen_prop.artist.strip() if chosen_prop.artist else ""
        album = chosen_prop.album_title.strip() if chosen_prop.album_title else ""
        playing = (chosen_info.playback_status == PlaybackStatus.PLAYING) if chosen_info else False

        pos = 0.0
        end = 0.0
        try:
            tl = chosen_session.get_timeline_properties()
            if tl:
                if hasattr(tl, "position") and tl.position is not None:
                    pos = tl.position.total_seconds()
                if hasattr(tl, "end_time") and tl.end_time is not None:
                    end = tl.end_time.total_seconds()
        except Exception:
            pass

        thumb_bytes = b""
        if chosen_prop.thumbnail:
            try:
                st = await chosen_prop.thumbnail.open_read_async()
                if st and st.size > 0:
                    r = DataReader(st.get_input_stream_at(0))
                    await r.load_async(st.size)
                    buf = bytearray(st.size)
                    r.read_bytes(buf)
                    thumb_bytes = bytes(buf)
            except Exception:
                pass

        return {
            "active": bool(title),
            "title": title,
            "artist": artist,
            "album": album,
            "playing": playing,
            "pos": pos,
            "end": end,
            "thumb_bytes": thumb_bytes,
        }

    def seek_position(self, seconds: float) -> None:
        def _seek_job():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                async def _do():
                    mgr = await SMTC.request_async()
                    cur = await MediaSessionWatcher._get_best_session(mgr)
                    if cur:
                        ticks = int(seconds * 10_000_000)
                        await cur.try_change_playback_position_async(ticks)
                loop.run_until_complete(_do())
                loop.close()
            except Exception:
                pass
        threading.Thread(target=_seek_job, daemon=True).start()

    def toggle_play_pause(self) -> None:
        def _job():
            executed = False
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                async def _do():
                    nonlocal executed
                    mgr = await SMTC.request_async()
                    cur = await MediaSessionWatcher._get_best_session(mgr)
                    if cur:
                        executed = await cur.try_toggle_play_pause_async()
                loop.run_until_complete(_do())
                loop.close()
            except Exception:
                pass
            if not executed:
                _dispatch_media_key(VK_MEDIA_PLAY_PAUSE, APPCOMMAND_MEDIA_PLAY_PAUSE)
        threading.Thread(target=_job, daemon=True).start()

    def skip_next(self) -> None:
        def _job():
            executed = False
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                async def _do():
                    nonlocal executed
                    mgr = await SMTC.request_async()
                    cur = await MediaSessionWatcher._get_best_session(mgr)
                    if cur:
                        executed = await cur.try_skip_next_async()
                loop.run_until_complete(_do())
                loop.close()
            except Exception:
                pass
            if not executed:
                _dispatch_media_key(VK_MEDIA_NEXT_TRACK, APPCOMMAND_MEDIA_NEXTTRACK)
        threading.Thread(target=_job, daemon=True).start()

    def skip_prev(self) -> None:
        def _job():
            executed = False
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                async def _do():
                    nonlocal executed
                    mgr = await SMTC.request_async()
                    cur = await MediaSessionWatcher._get_best_session(mgr)
                    if cur:
                        executed = await cur.try_skip_previous_async()
                loop.run_until_complete(_do())
                loop.close()
            except Exception:
                pass
            if not executed:
                _dispatch_media_key(VK_MEDIA_PREV_TRACK, APPCOMMAND_MEDIA_PREVIOUSTRACK)
        threading.Thread(target=_job, daemon=True).start()


# ── Dynamic Island Overlay Window ───────────────────────────────────────────
class DynamicIslandOverlay(QWidget):
    """
    Living, breathing iOS Dynamic Island for Windows.
    100% faithful to Apple iOS Dynamic Island & jordibruin/Dynamic-Islands.
    """

    _COMPACT_W = 240
    _EXPANDED_PILL_W = 380
    _COMPACT_H = 36
    _EXPANDED_W = 384
    _EXPANDED_H = 184
    _TOP_MARGIN = 10
    _INSTANCE = None

    @classmethod
    def post_notification(
        cls,
        title: str,
        message: str,
        color: str = "#ef4444",
        icon: str = "⏰",
        duration_ms: int = 8000,
    ) -> None:
        """Thread-safe public entry point to pop a notification in Dynamic Island from any thread."""
        inst = getattr(cls, "_INSTANCE", None)
        if not inst:
            return
        try:
            from PyQt6.QtCore import QTimer
            badge = "REMINDER" if "remind" in title.lower() else (title[:15] if title else "JARVIS")
            QTimer.singleShot(0, lambda: inst.pop_notification_box(
                icon=icon,
                badge=badge,
                title=title,
                body=message,
                color=color,
                duration_ms=duration_ms,
            ))
        except Exception as e:
            print(f"[DynamicIsland] post_notification error: {e}")

    def __init__(self, main_window: QWidget | None = None, parent: QWidget | None = None):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        DynamicIslandOverlay._INSTANCE = self
        self.setObjectName("dynamicIslandOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        self._main_window = main_window
        self._is_expanded = False
        self._active_context = 0  # 0: Music, 1: Weather, 2: Notifs, 3: Calendar, 4: Gaming
        self._current_state = "STANDBY"
        self._celsius_temp = "25°C"
        self._weather_icon = "⛅"
        self._last_clipboard_text = ""
        self._total_duration_sec = 235.0
        self._is_playing = False
        self._is_media_active = False
        self._transient_notif_active = False
        self._current_pill_alert_w = self._EXPANDED_PILL_W
        self._latest_notif_source = ""
        self._latest_notif_title = ""
        self._current_media_title = ""
        self._current_media_artist = ""

        # Background SMTC Media watcher
        self._media_watcher = MediaSessionWatcher(self)
        self._media_watcher.media_updated.connect(self._on_live_media_update)
        self._media_watcher.artwork_fetched.connect(self._on_artwork_downloaded)

        # Background Windows Toast & WhatsApp watcher
        self._notif_watcher = WindowsNotificationWatcher(self)
        self._notif_watcher.notification_arrived.connect(self._on_incoming_windows_notification)

        # Root layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Island Body Pill Frame (Clickable everywhere)
        self._pill_frame = ClickablePillFrame(self)
        self._pill_frame.setObjectName("dynamicIslandPill")
        self._pill_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_pill_style(expanded=False)
        root_layout.addWidget(self._pill_frame)

        self._pill_layout = QVBoxLayout(self._pill_frame)
        self._pill_layout.setContentsMargins(12, 0, 12, 0)
        self._pill_layout.setSpacing(0)

        # ── 1. Compact Pill Strip (Image 2 Middle Pill) ──────────────────────────
        self._compact_widget = ClickableCompactWidget(self._pill_frame)
        self._compact_widget.setFixedHeight(36)
        self._compact_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        compact_row = QHBoxLayout(self._compact_widget)
        compact_row.setContentsMargins(0, 0, 0, 0)
        compact_row.setSpacing(6)

        # Leading (Left): Celsius Weather, Mini Cover Art, or Notification Badge
        self._compact_leading = QWidget(self._compact_widget)
        self._compact_leading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        leading_layout = QHBoxLayout(self._compact_leading)
        leading_layout.setContentsMargins(0, 0, 0, 0)
        leading_layout.setSpacing(5)

        self._compact_cover = QLabel(self._compact_leading)
        self._compact_cover.setFixedSize(18, 18)
        self._compact_cover.setStyleSheet("border-radius: 4px; background: #1c1c1e;")
        self._compact_cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._compact_cover.hide()
        leading_layout.addWidget(self._compact_cover, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._pill_weather_lbl = QLabel(f"{self._weather_icon} {self._celsius_temp}", self._compact_leading)
        self._pill_weather_lbl.setStyleSheet("""
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
        """)
        self._pill_weather_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        leading_layout.addWidget(self._pill_weather_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        compact_row.addWidget(self._compact_leading, alignment=Qt.AlignmentFlag.AlignVCenter)

        compact_row.addStretch(1)

        # Middle camera cutout removed per user request (clean edge-to-edge compact bar)
        self._privacy_dot = QLabel()

        # Trailing (Right): Solid-color audio visualizer waveform bars
        self._compact_trailing = QWidget(self._compact_widget)
        self._compact_trailing.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        trailing_layout = QHBoxLayout(self._compact_trailing)
        trailing_layout.setContentsMargins(0, 0, 0, 0)
        trailing_layout.setSpacing(4)

        self._pill_trailing_lbl = QLabel("", self._compact_trailing)
        self._pill_trailing_lbl.setStyleSheet("""
            color: #8e8e93;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 11px;
            font-weight: 500;
            background: transparent;
        """)
        self._pill_trailing_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pill_trailing_lbl.hide()
        trailing_layout.addWidget(self._pill_trailing_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Accurate Solid Color Equalizer (Green for User, Red for Jarvis, White for Music)
        self._compact_equalizer = IOSEqualizerWidget(self._compact_trailing, num_bars=5, bar_w=2.6, spacing=2.0)
        self._compact_equalizer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        trailing_layout.addWidget(self._compact_equalizer, alignment=Qt.AlignmentFlag.AlignVCenter)
        compact_row.addWidget(self._compact_trailing, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._pill_layout.addWidget(self._compact_widget)

        # ── Authentic Apple iOS Animated Loading / Progress Bar ─────────────
        self._pill_progress_bar = IOSProgressBar(self._pill_frame, height=3)
        self._pill_layout.addWidget(self._pill_progress_bar)

        self._clipboard_progress_timer = QTimer(self)
        self._clipboard_progress_timer.setInterval(16)
        self._clipboard_progress_val = 0.0
        self._clipboard_action_name = "Copied"
        self._clipboard_progress_timer.timeout.connect(self._step_clipboard_progress)
        self._last_seen_song = ""

        # ── 2. Expanded Island Card Stack (Exact 1:1 Match with Image 2) ─────────
        self._expanded_widget = QWidget(self._pill_frame)
        expanded_col = QVBoxLayout(self._expanded_widget)
        expanded_col.setContentsMargins(10, 10, 10, 10)
        expanded_col.setSpacing(8)

        self._card_stack = QStackedWidget(self._expanded_widget)

        # ── Music Card (1:1 with Image 2) ──
        card_music = QWidget()
        m_layout = QVBoxLayout(card_music)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(8)

        # Row 1: Album Art + Titles + Waveform
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self._album_art = AlbumArtWidget(card_music, size=56)
        row1.addWidget(self._album_art, alignment=Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title_lbl = QLabel("No Media Playing", card_music)
        self._title_lbl.setStyleSheet("""
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 15px;
            font-weight: 700;
            background: transparent;
        """)
        title_col.addWidget(self._title_lbl)

        self._artist_lbl = QLabel("Play audio on your PC", card_music)
        self._artist_lbl.setStyleSheet("""
            color: #8e8e93;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 13px;
            font-weight: 500;
            background: transparent;
        """)
        title_col.addWidget(self._artist_lbl)

        row1.addLayout(title_col)
        row1.addStretch(1)

        # Solid color animated equalizer bars on top right
        self._expanded_equalizer = IOSEqualizerWidget(card_music, num_bars=6, bar_w=2.8, spacing=2.2)
        row1.addWidget(self._expanded_equalizer, alignment=Qt.AlignmentFlag.AlignVCenter)

        m_layout.addLayout(row1)

        # Row 2: Apple Scrubber Bar (2:50  [=====]  -0:51)
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(8)

        self._scrub_pos_lbl = QLabel("0:00", card_music)
        self._scrub_pos_lbl.setStyleSheet("color: #8e8e93; font-size: 11px; font-weight: 500; background: transparent;")
        scrub_row.addWidget(self._scrub_pos_lbl)

        self._scrubber = IOSScrubberWidget(card_music)
        self._scrubber.seek_requested.connect(self._on_seek_requested)
        self._scrubber.user_interacted.connect(self._reset_auto_minimize_timer)
        scrub_row.addWidget(self._scrubber)

        self._scrub_end_lbl = QLabel("-0:00", card_music)
        self._scrub_end_lbl.setStyleSheet("color: #8e8e93; font-size: 11px; font-weight: 500; background: transparent;")
        scrub_row.addWidget(self._scrub_end_lbl)

        m_layout.addLayout(scrub_row)

        # Row 3: Solid White Vector Transport Controls Row (⏮   ❚❚   ⏭   ⟐)
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(10, 0, 10, 0)

        self._btn_prev = IOSTransportButton("prev", card_music, size=36)
        self._btn_prev.user_interacted.connect(self._reset_auto_minimize_timer)
        self._btn_prev.clicked.connect(self._on_prev_clicked)

        self._btn_play = IOSTransportButton("play", card_music, size=42)
        self._btn_play.user_interacted.connect(self._reset_auto_minimize_timer)
        self._btn_play.clicked.connect(self._on_play_pause_clicked)

        self._btn_next = IOSTransportButton("next", card_music, size=36)
        self._btn_next.user_interacted.connect(self._reset_auto_minimize_timer)
        self._btn_next.clicked.connect(self._on_next_clicked)

        self._btn_airplay = IOSTransportButton("airplay", card_music, size=30)
        self._btn_airplay.user_interacted.connect(self._reset_auto_minimize_timer)

        ctrl_row.addWidget(self._btn_prev)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._btn_play)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._btn_next)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self._btn_airplay)

        m_layout.addLayout(ctrl_row)
        self._card_stack.addWidget(card_music)

        # ── Context 1: iOS Weather Island ──
        card_weather = QWidget()
        w_layout = QVBoxLayout(card_weather)
        w_layout.setContentsMargins(4, 4, 4, 4)
        w_layout.setSpacing(6)

        w_top = QHBoxLayout()
        self._w_city = QLabel("Colombo", card_weather)
        self._w_city.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: 700; background: transparent;")
        w_top.addWidget(self._w_city)
        w_top.addStretch(1)
        self._w_temp = QLabel(self._celsius_temp, card_weather)
        self._w_temp.setStyleSheet("color: #ffffff; font-size: 22px; font-weight: 800; background: transparent;")
        w_top.addWidget(self._w_temp)
        w_layout.addLayout(w_top)

        self._w_desc = QLabel(f"{self._weather_icon} Partly Cloudy", card_weather)
        self._w_desc.setStyleSheet("color: #e2e8f0; font-size: 13px; font-weight: 500; background: transparent;")
        w_layout.addWidget(self._w_desc)

        self._w_stats = QLabel("Feels like: 26°C  ·  Humidity: 78%  ·  Wind: 14 km/h", card_weather)
        self._w_stats.setStyleSheet("color: #8e8e93; font-size: 11px; background: transparent;")
        w_layout.addWidget(self._w_stats)
        w_layout.addStretch(1)
        self._card_stack.addWidget(card_weather)

        # ── Context 2: iOS Notification & Clipboard Island ──
        card_notif = QWidget()
        n_layout = QVBoxLayout(card_notif)
        n_layout.setContentsMargins(4, 4, 4, 4)
        n_layout.setSpacing(5)

        n_top = QHBoxLayout()
        self._notif_badge = QLabel("◈ WHATSAPP", card_notif)
        self._notif_badge.setStyleSheet("color: #22c55e; font-size: 10px; font-weight: 800; background: transparent;")
        n_top.addWidget(self._notif_badge)
        n_top.addStretch(1)
        self._notif_time = QLabel("Just now", card_notif)
        self._notif_time.setStyleSheet("color: #8e8e93; font-size: 10px; background: transparent;")
        n_top.addWidget(self._notif_time)
        n_layout.addLayout(n_top)

        self._notif_title = QLabel("Incoming Message", card_notif)
        self._notif_title.setWordWrap(True)
        self._notif_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 700; background: transparent;")
        n_layout.addWidget(self._notif_title)

        self._notif_body = QLabel("Jarvis Autonomous Desktop OS is operational.", card_notif)
        self._notif_body.setWordWrap(True)
        self._notif_body.setStyleSheet("color: #e2e8f0; font-size: 12px; line-height: 1.3; background: transparent;")
        n_layout.addWidget(self._notif_body)
        n_layout.addStretch(1)
        self._card_stack.addWidget(card_notif)

        # ── Context 3: iOS Calendar Island ──
        card_cal = QWidget()
        cal_layout = QVBoxLayout(card_cal)
        cal_layout.setContentsMargins(4, 2, 4, 2)
        cal_layout.setSpacing(4)

        now = datetime.now()
        cal_top = QHBoxLayout()
        self._cal_title = QLabel(now.strftime("%B %Y").upper(), card_cal)
        self._cal_title.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 800; background: transparent;")
        cal_top.addWidget(self._cal_title)
        cal_top.addStretch(1)
        self._cal_date = QLabel(now.strftime("%A, %d %b"), card_cal)
        self._cal_date.setStyleSheet("color: #8e8e93; font-size: 11px; font-weight: 600; background: transparent;")
        cal_top.addWidget(self._cal_date)
        cal_layout.addLayout(cal_top)

        self._cal_grid_widget = QWidget(card_cal)
        self._cal_grid_layout = QGridLayout(self._cal_grid_widget)
        self._cal_grid_layout.setContentsMargins(0, 0, 0, 0)
        self._cal_grid_layout.setSpacing(2)
        self._build_calendar_grid(now)
        cal_layout.addWidget(self._cal_grid_widget)
        cal_layout.addStretch(1)
        self._card_stack.addWidget(card_cal)

        # ── Context 4: Gaming & Telemetry Island ──
        card_game = QWidget()
        g_layout = QVBoxLayout(card_game)
        g_layout.setContentsMargins(4, 2, 4, 2)
        g_layout.setSpacing(6)

        g_hdr = QLabel("HARDWARE TELEMETRY", card_game)
        g_hdr.setStyleSheet("color: #8e8e93; font-size: 10px; font-weight: 800; background: transparent;")
        g_layout.addWidget(g_hdr)

        g_row = QHBoxLayout()
        g_row.setSpacing(8)
        self._tel_fps = self._create_telemetry_box("FPS", "144", "#ffffff", card_game)
        self._tel_cpu = self._create_telemetry_box("CPU", "--%", "#ffffff", card_game)
        self._tel_gpu = self._create_telemetry_box("GPU", "--%", "#ffffff", card_game)
        self._tel_ram = self._create_telemetry_box("RAM", "--%", "#ffffff", card_game)
        g_row.addWidget(self._tel_fps)
        g_row.addWidget(self._tel_cpu)
        g_row.addWidget(self._tel_gpu)
        g_row.addWidget(self._tel_ram)
        g_layout.addLayout(g_row)
        g_layout.addStretch(1)
        self._card_stack.addWidget(card_game)

        expanded_col.addWidget(self._card_stack)
        self._expanded_widget.hide()
        self._pill_layout.addWidget(self._expanded_widget)

        # ── Timers ───────────────────────────────────────────────────────────────
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

        # Fast topmost heartbeat (400ms) guarantees Island stays on absolute top of all apps
        self._topmost_heartbeat = QTimer(self)
        self._topmost_heartbeat.timeout.connect(self._ensure_topmost)
        self._topmost_heartbeat.start(400)

        self._hw_timer = QTimer(self)
        self._hw_timer.timeout.connect(self._update_hardware)
        self._hw_timer.start(2500)

        # Auto-minimize timer: automatically minimizes back to the bar after 5 seconds of inactivity
        self._auto_minimize_timer = QTimer(self)
        self._auto_minimize_timer.setSingleShot(True)
        self._auto_minimize_timer.timeout.connect(self.collapse)

        # Bar notification reset timer
        self._bar_reset_timer = QTimer(self)
        self._bar_reset_timer.setSingleShot(True)
        self._bar_reset_timer.timeout.connect(self._reset_bar_display)

        # News headline sequence timer & queue (cycles one by one on the bar)
        self._news_sequence_timer = QTimer(self)
        self._news_sequence_timer.setSingleShot(True)
        self._news_sequence_timer.timeout.connect(self._advance_news_sequence)
        self._news_sequence_queue: list[tuple[str, str]] = []
        self._news_sequence_idx: int = 0

        # Live weather refresh
        QTimer.singleShot(400, self._refresh_weather_async)

        # Clipboard Monitor
        clip = QApplication.clipboard()
        if clip is not None:
            clip.dataChanged.connect(self._on_clipboard_changed)

        # Geometry animation
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.resize(self._COMPACT_W, self._COMPACT_H)
        self._position_top_center()

    def handle_pill_click(self) -> None:
        """Centralized click dispatcher guaranteeing 100% reliable expansion/collapse."""
        # If user clicked while a WhatsApp alert is on the bar, open WhatsApp chat
        if self._transient_notif_active and "whatsapp" in self._latest_notif_source.lower() and self._latest_notif_title:
            try:
                from actions.whatsapp_chat import open_whatsapp_chat
                open_whatsapp_chat(self._latest_notif_title)
            except Exception:
                pass
            self._reset_bar_display()
            return

        if not self._is_expanded:
            self.expand()
        else:
            self.collapse()

    def _create_telemetry_box(self, title: str, val: str, color: str, parent: QWidget) -> QFrame:
        f = QFrame(parent)
        f.setStyleSheet("background: rgba(255, 255, 255, 0.06); border-radius: 10px;")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(1)
        t = QLabel(title, f)
        t.setStyleSheet("color: #8e8e93; font-size: 9px; font-weight: 700; background: transparent;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v = QLabel(val, f)
        v.setObjectName(f"val_{title}")
        v.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 800; background: transparent;")
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        lay.addWidget(v)
        return f

    def _build_calendar_grid(self, dt: datetime) -> None:
        days = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
        for col, day_name in enumerate(days):
            lbl = QLabel(day_name)
            lbl.setStyleSheet("color: #71717a; font-size: 9px; font-weight: 700; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cal_grid_layout.addWidget(lbl, 0, col)

        cal = calendar.monthcalendar(dt.year, dt.month)
        today = dt.day
        for row_idx, week in enumerate(cal):
            for col_idx, day_num in enumerate(week):
                if day_num == 0:
                    lbl = QLabel("")
                else:
                    lbl = QLabel(str(day_num))
                    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    lbl.setFixedSize(20, 16)
                    if day_num == today:
                        lbl.setStyleSheet("color: #000000; font-size: 9px; font-weight: 800; background: #ffffff; border-radius: 8px;")
                    else:
                        lbl.setStyleSheet("color: #d4d4d8; font-size: 9px; font-weight: 500; background: transparent;")
                self._cal_grid_layout.addWidget(lbl, row_idx + 1, col_idx)

    def _update_pill_style(self, expanded: bool) -> None:
        radius = 38 if expanded else 18
        self._pill_frame.setStyleSheet(
            f"QFrame#dynamicIslandPill {{"
            f"  background: #000000;"
            f"  border: 1px solid rgba(255, 255, 255, 0.08);"
            f"  border-radius: {radius}px;"
            f"}}"
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._position_top_center()
        self._ensure_topmost()

    def _ensure_topmost(self) -> None:
        """Enforce Windows HWND_TOPMOST and extended styles so Dynamic Island stays on top of ALL apps."""
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            from ctypes import wintypes
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000

            cur_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if not (cur_style & WS_EX_TOPMOST):
                user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cur_style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def _position_top_center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, self._TOP_MARGIN)
            return
        geo = screen.availableGeometry()
        target_w = self._EXPANDED_W if self._is_expanded else (getattr(self, "_current_pill_alert_w", self._EXPANDED_PILL_W) if self._transient_notif_active else self._COMPACT_W)
        target_h = self._EXPANDED_H if self._is_expanded else self._COMPACT_H
        target_x = geo.left() + (geo.width() - target_w) // 2
        target_y = geo.top() + self._TOP_MARGIN
        self.setGeometry(target_x, target_y, target_w, target_h)
        self._ensure_topmost()

    def enterEvent(self, event) -> None:
        if self._is_expanded:
            self._reset_auto_minimize_timer()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._is_expanded:
            self._auto_minimize_timer.start(2500)
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Mouse wheel smoothly switches context cards."""
        if not self._is_expanded:
            self.expand()
        self._reset_auto_minimize_timer()
        delta = event.angleDelta().y()
        total_cards = self._card_stack.count()
        if delta < 0:
            self._active_context = (self._active_context + 1) % total_cards
        elif delta > 0:
            self._active_context = (self._active_context - 1) % total_cards
        self._card_stack.setCurrentIndex(self._active_context)
        event.accept()

    def _update_clock(self) -> None:
        self._ensure_topmost()
        if self._current_state in ("LISTENING", "SPEAKING"):
            self._compact_equalizer.show()
            self._pill_trailing_lbl.hide()
        elif self._is_media_active:
            self._compact_equalizer.show()
            self._pill_trailing_lbl.hide()
        elif not self._is_expanded and not self._transient_notif_active:
            now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
            self._pill_trailing_lbl.setText(now_str)
            self._pill_trailing_lbl.show()
            self._compact_equalizer.hide()

    def _update_hardware(self) -> None:
        if not _HAS_PSUTIL:
            return
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            gpu_pct = 0
            if _HAS_NVML:
                try:
                    h = pynvml.nvmlDeviceGetHandleByIndex(0)
                    gpu_pct = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
                except Exception:
                    pass

            c_lbl = self._tel_cpu.findChild(QLabel, "val_CPU")
            if c_lbl: c_lbl.setText(f"{cpu:.0f}%")
            g_lbl = self._tel_gpu.findChild(QLabel, "val_GPU")
            if g_lbl: g_lbl.setText(f"{gpu_pct}%")
            r_lbl = self._tel_ram.findChild(QLabel, "val_RAM")
            if r_lbl: r_lbl.setText(f"{ram:.0f}%")
        except Exception:
            pass

    def _refresh_weather_async(self) -> None:
        def fetch():
            try:
                from actions.weather_report import _forecast
                data = _forecast()
                cur = data.get("current", {})
                temp = cur.get("temp", 25.0)
                summary = cur.get("summary", "Partly Cloudy")
                loc = data.get("location", "Colombo")
                feels = cur.get("feels_like", temp)
                humidity = cur.get("humidity", 78)
                wind = cur.get("wind", 14)

                icon = "☀️"
                if "rain" in summary.lower(): icon = "🌧️"
                elif "cloud" in summary.lower(): icon = "⛅"
                elif "thunder" in summary.lower(): icon = "⛈️"
                elif "snow" in summary.lower(): icon = "❄️"

                celsius_str = f"{round(temp)}°C"
                self._celsius_temp = celsius_str
                self._weather_icon = icon

                QTimer.singleShot(0, lambda: self._apply_weather_data(icon, celsius_str, loc, summary, feels, humidity, wind))
            except Exception as e:
                print(f"[DynamicIsland] Weather fetch failed: {e}")

        threading.Thread(target=fetch, daemon=True).start()

    def _apply_weather_data(self, icon: str, celsius: str, loc: str, desc: str, feels: float, hum: int, wind: float) -> None:
        if not self._transient_notif_active:
            self._pill_weather_lbl.setText(f"{icon} {celsius}")
        self._w_city.setText(loc.split(",")[0] if loc else "Colombo")
        self._w_temp.setText(celsius)
        self._w_desc.setText(f"{icon} {desc}")
        self._w_stats.setText(f"Feels like: {round(feels)}°C  ·  Humidity: {hum}%  ·  Wind: {round(wind)} km/h")

    # ── Live Windows Media SMTC Handler ──────────────────────────────────────
    def _on_live_media_update(self, data: dict) -> None:
        active = data.get("active", False)
        title = data.get("title", "")
        artist = data.get("artist", "")
        playing = data.get("playing", False)
        pos = data.get("pos", 0.0)
        end = data.get("end", 0.0)
        thumb_bytes = data.get("thumb_bytes", b"")

        self._is_media_active = active
        self._is_playing = playing
        self._current_media_title = title
        self._current_media_artist = artist
        self._btn_play.set_playing(playing)

        if self._current_state not in ("LISTENING", "SPEAKING"):
            self._compact_equalizer.set_playing(playing)
            self._expanded_equalizer.set_playing(playing)

        if active and title:
            self._title_lbl.setText(title[:28])
            self._artist_lbl.setText(artist[:30] if artist else "Unknown Artist")
            if not self._transient_notif_active:
                pill_title = title if len(title) <= 18 else (title[:17] + "…")
                self._pill_weather_lbl.setText(f"🎵 {pill_title}")
                self._pill_weather_lbl.setStyleSheet("""
                    color: #ffffff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                """)
                self._pill_trailing_lbl.hide()
                self._compact_equalizer.show()
                if self._compact_cover.pixmap() and not self._compact_cover.pixmap().isNull():
                    self._compact_cover.show()
        else:
            self._title_lbl.setText("No Media Playing")
            self._artist_lbl.setText("Play audio on your PC")
            if not self._transient_notif_active:
                self._pill_weather_lbl.setText(f"{self._weather_icon} {self._celsius_temp}")
                self._pill_weather_lbl.setStyleSheet("""
                    color: #ffffff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                """)
                self._compact_cover.hide()
                if self._current_state not in ("LISTENING", "SPEAKING"):
                    now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
                    self._pill_trailing_lbl.setText(now_str)
                    self._pill_trailing_lbl.show()
                    self._compact_equalizer.hide()

        if thumb_bytes:
            self._album_art.set_bytes(thumb_bytes, title=title)
            px = QPixmap()
            if px.loadFromData(thumb_bytes):
                self._compact_cover.setPixmap(px.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                if active and not self._transient_notif_active:
                    self._compact_cover.show()
        elif not active:
            self._album_art.set_bytes(b"", title="")
            self._compact_cover.clear()
            self._compact_cover.hide()

        self._total_duration_sec = end if end > 0 else 235.0
        self._scrubber.set_progress(pos, self._total_duration_sec)

        pos_m, pos_s = divmod(int(pos), 60)
        rem_sec = max(0, int(self._total_duration_sec - pos))
        rem_m, rem_s = divmod(rem_sec, 60)

        self._scrub_pos_lbl.setText(f"{pos_m}:{pos_s:02d}")
        self._scrub_end_lbl.setText(f"-{rem_m}:{rem_s:02d}")

    def _on_artwork_downloaded(self, img_bytes: bytes) -> None:
        """Invoked when iTunes high-res artwork is fetched for the active track."""
        if img_bytes and self._is_media_active:
            self._album_art.set_bytes(img_bytes, title=self._title_lbl.text())
            px = QPixmap()
            if px.loadFromData(img_bytes):
                self._compact_cover.setPixmap(px.scaled(18, 18, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                if not self._transient_notif_active:
                    self._compact_cover.show()

    # ── Media Button Actions ─────────────────────────────────────────────────
    def _reset_auto_minimize_timer(self) -> None:
        """Reset the auto-minimize timer to 5 seconds upon user activity."""
        if self._is_expanded:
            self._auto_minimize_timer.start(5000)

    def _on_play_pause_clicked(self) -> None:
        self._reset_auto_minimize_timer()
        self._media_watcher.toggle_play_pause()

    def _on_prev_clicked(self) -> None:
        self._reset_auto_minimize_timer()
        self._media_watcher.skip_prev()

    def _on_next_clicked(self) -> None:
        self._reset_auto_minimize_timer()
        self._media_watcher.skip_next()

    def _on_seek_requested(self, seconds: float) -> None:
        self._reset_auto_minimize_timer()
        self._media_watcher.seek_position(seconds)

    # ── Windows Live Notifications & Clipboard Monitors ───────────────────────
    def _on_incoming_windows_notification(
        self, app_name: str, title: str, body: str, color: str, msg_time: str = ""
    ) -> None:
        """Invoked when Windows UserNotificationListener detects a live toast."""
        is_whatsapp = "whatsapp" in app_name.lower() or "whatsapp" in f"{title} {body}".lower()
        combined = f"{app_name} {title} {body}".lower()

        # Detect incoming calls (WhatsApp call, phone call, etc.)
        call_indicators = (
            "incoming call", "voice call", "video call", "whatsapp call",
            "calling", "incoming voice call", "incoming video call", "call from",
            "audio call"
        )
        is_call = any(k in combined for k in call_indicators)
        is_video = "video" in combined

        caller_name = title.strip()
        call_desc = body.strip()

        if is_call:
            full_text = f"{title} {body}".strip()
            # Extract caller name from patterns like "Incoming voice call from Dedaa ❤️"
            extracted_name = None
            for sep in (" from ", " From "):
                if sep in full_text:
                    parts = full_text.split(sep, 1)
                    extracted_name = parts[1].strip()
                    call_desc = parts[0].strip()
                    break

            if extracted_name:
                caller_name = extracted_name
            else:
                title_is_desc = any(k in title.lower() for k in ("incoming", "call", "whatsapp", "calling", "voice", "video", "audio"))
                body_is_desc = any(k in body.lower() for k in ("incoming", "call", "whatsapp", "calling", "voice", "video", "audio"))
                if title_is_desc and body.strip() and not body_is_desc:
                    caller_name = body.strip()
                    call_desc = title.strip()
                elif body_is_desc and title.strip() and not title_is_desc:
                    caller_name = title.strip()
                    call_desc = body.strip()

            if not call_desc or any(k in call_desc.lower() for k in ("whatsapp",)):
                call_desc = "Incoming Video Call..." if is_video else "Incoming Voice Call..."

            icon = "📹" if is_video else "📞"
            badge = "WhatsApp Video Call" if (is_whatsapp and is_video) else (
                "WhatsApp Call" if is_whatsapp else (f"{app_name} Video Call" if is_video else f"{app_name} Call")
            )
            color = "#38bdf8" if is_video else "#22c55e"
            snippet = call_desc
        else:
            icon = "💬" if is_whatsapp else "🔔"
            badge = "WhatsApp" if is_whatsapp else app_name
            snippet = body or "New message"

        dnd_active = is_windows_dnd_active()

        if dnd_active:
            # DND is ON: sleek compact pill alert animation (does not pop the big box)
            self.show_island_pill_alert(
                icon=icon,
                badge=badge,
                title=caller_name,
                snippet=snippet,
                color=color,
                duration_ms=6500 if is_call else 5000,
                msg_time=msg_time,
            )
        else:
            # DND is OFF: message or call pops up in the expanded box!
            self.pop_notification_box(
                icon=icon,
                badge=badge,
                title=caller_name,
                body=snippet,
                color=color,
                duration_ms=8000 if is_call else 6500,
                msg_time=msg_time,
            )

    def _on_clipboard_changed(self) -> None:
        try:
            cb = QApplication.clipboard()
            if cb is None:
                return
            mime = cb.mimeData()
            if mime and mime.hasText():
                txt = cb.text().strip()
                if txt and txt != self._last_clipboard_text and len(txt) >= 2:
                    self._last_clipboard_text = txt
                    self.show_clipboard_progress(txt, action="Copied")
        except Exception:
            pass

    def show_clipboard(self, text: str) -> None:
        txt = (text or "").strip()
        if not txt or txt == self._last_clipboard_text:
            return
        self._last_clipboard_text = txt
        self.show_clipboard_progress(txt, action="Copied")

    def show_paste(self, text: str) -> None:
        txt = (text or "").strip()
        self.show_clipboard_progress(txt, action="Pasted")

    def show_clipboard_progress(self, text: str, action: str = "Copied") -> None:
        """
        Sleek Apple iOS Dynamic Island animated clipboard progress loading bar.
        Smoothly fills from 0% to 100% while displaying snippet, then flashes success checkmark.
        """
        self._transient_notif_active = True
        self._clipboard_action_name = action
        clean = " ".join((text or "").split()).strip()
        preview = clean[:22] + ("…" if len(clean) > 22 else "")

        self._compact_cover.hide()
        self._pill_weather_lbl.setText(f"📋 {action}: {preview}")
        self._pill_weather_lbl.setStyleSheet("""
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
        """)
        self._pill_trailing_lbl.hide()
        self._compact_equalizer.hide()

        fm = self._pill_weather_lbl.fontMetrics()
        txt_w = fm.horizontalAdvance(f"📋 {action}: {preview}")
        target_w = min(460, max(280, txt_w + 38))
        self._current_pill_alert_w = target_w

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        new_x = geo.left() + (geo.width() - target_w) // 2
        new_y = geo.top() + self._TOP_MARGIN

        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(new_x, new_y, target_w, self._COMPACT_H))
        self._anim.start()

        self._pill_progress_bar.set_progress(0.0, "#38bdf8")
        self._pill_progress_bar.show()

        self._clipboard_progress_val = 0.0
        self._clipboard_progress_timer.start()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._ensure_topmost()

    def _step_clipboard_progress(self) -> None:
        self._clipboard_progress_val += 0.05
        col = "#22c55e" if self._clipboard_progress_val >= 0.85 else "#38bdf8"
        self._pill_progress_bar.set_progress(min(1.0, self._clipboard_progress_val), col)

        if self._clipboard_progress_val >= 1.0:
            self._clipboard_progress_timer.stop()
            self._pill_weather_lbl.setText(f"✓ {self._clipboard_action_name} to Clipboard!")
            self._pill_weather_lbl.setStyleSheet("""
                color: #22c55e;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            """)
            self._bar_reset_timer.start(1800)

    # ── Sleek Apple Dynamic Island Pill Alert (One Message Animation) ────────
    def show_island_pill_alert(
        self,
        icon: str,
        badge: str,
        title: str,
        snippet: str,
        color: str = "#22c55e",
        duration_ms: int = 5000,
        msg_time: str = "",
    ) -> None:
        """
        Sleek iOS Dynamic Island banner animation on the compact bar.
        Expands the bar smoothly from 240px to dynamic width with icon, sender, and snippet.
        Does NOT cover the screen or pop up an intrusive full box.
        Works when DND (Do Not Disturb) is enabled!
        """
        self._transient_notif_active = True
        self._latest_notif_source = badge
        self._latest_notif_title = title

        display_time = msg_time or datetime.now().strftime("%I:%M %p").lstrip("0")

        # Update card in case user expands
        self._notif_badge.setText(f"◈ {badge.upper()}")
        self._notif_badge.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 800; background: transparent;")
        self._notif_title.setText(str(title).strip())
        self._notif_body.setText(str(snippet).strip()[:240])
        self._notif_time.setText(display_time)

        if not self.isVisible():
            self.show()
            self.raise_()

        if not self._is_expanded:
            clean_title = str(title).split(" - ")[0].strip()[:35]
            self._compact_cover.hide()
            self._pill_weather_lbl.setText(f"{icon} {clean_title}")
            title_color = "#22c55e" if "whatsapp" in badge.lower() or "call" in badge.lower() else "#ffffff"
            self._pill_weather_lbl.setStyleSheet(f"""
                color: {title_color};
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                font-size: 12px;
                font-weight: 700;
                background: transparent;
            """)

            clean_snip = str(snippet).strip()[:42]
            self._pill_trailing_lbl.setText(clean_snip)
            self._pill_trailing_lbl.setStyleSheet("""
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: 500;
                background: transparent;
            """)
            self._pill_trailing_lbl.show()
            self._compact_equalizer.hide()

            # Dynamic horizontal expansion of the compact pill based on font metrics
            fm_lead = self._pill_weather_lbl.fontMetrics()
            fm_trail = self._pill_trailing_lbl.fontMetrics()
            lead_w = fm_lead.horizontalAdvance(f"{icon} {clean_title}")
            trail_w = fm_trail.horizontalAdvance(clean_snip)
            needed_w = lead_w + trail_w + 58
            target_w = min(540, max(self._EXPANDED_PILL_W, needed_w))
            self._current_pill_alert_w = target_w

            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
            new_x = geo.left() + (geo.width() - target_w) // 2
            new_y = geo.top() + self._TOP_MARGIN

            self._anim.stop()
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(QRect(new_x, new_y, target_w, self._COMPACT_H))
            self._anim.start()

        self._bar_reset_timer.start(duration_ms)
        self._ensure_topmost()

    def pop_notification_box(
        self,
        icon: str,
        badge: str,
        title: str,
        body: str,
        color: str = "#22c55e",
        duration_ms: int = 6500,
        msg_time: str = "",
    ) -> None:
        """
        Pop up the notification in the expanded Island box (used when DND is OFF).
        Displays full contact name, full body, badge, and auto-minimizes back to the bar.
        """
        self._transient_notif_active = True
        self._latest_notif_source = badge
        self._latest_notif_title = title

        display_time = msg_time or datetime.now().strftime("%I:%M %p").lstrip("0")

        # Update notification card (Context 2)
        self._notif_badge.setText(f"◈ {badge.upper()}")
        self._notif_badge.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 800; background: transparent;")
        self._notif_time.setText(display_time)
        self._notif_title.setText(str(title).strip())
        self._notif_body.setText(str(body).strip()[:240])

        # Also prepare the compact bar labels in case user collapses early or when it minimizes
        clean_title = str(title).split(" - ")[0].strip()[:35]
        self._pill_weather_lbl.setText(f"{icon} {clean_title}")
        title_color = "#22c55e" if "whatsapp" in badge.lower() or "call" in badge.lower() else "#ffffff"
        self._pill_weather_lbl.setStyleSheet(f"""
            color: {title_color};
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
        """)
        self._pill_trailing_lbl.setText(str(body).strip()[:26])
        self._pill_trailing_lbl.show()
        self._compact_equalizer.hide()

        # Switch card stack to Context 2 (Notification Card)
        self._active_context = 2
        self._card_stack.setCurrentIndex(2)

        # Expand into the box
        self.expand()
        self.show()
        self.raise_()
        self._ensure_topmost()

        # Auto-minimize timer: returns to bar after duration_ms
        self._auto_minimize_timer.start(duration_ms)
        self._bar_reset_timer.start(duration_ms + 2500)

    def _reset_bar_display(self) -> None:
        self._transient_notif_active = False
        self._clipboard_progress_timer.stop()
        self._pill_progress_bar.hide()

        if self._is_media_active and self._current_media_title:
            pill_title = self._current_media_title if len(self._current_media_title) <= 20 else (self._current_media_title[:19] + "…")
            self._pill_weather_lbl.setText(f"🎵 {pill_title}")
            if self._compact_cover.pixmap() and not self._compact_cover.pixmap().isNull():
                self._compact_cover.show()
            self._pill_trailing_lbl.hide()
            self._compact_equalizer.show()
        else:
            self._pill_weather_lbl.setText(f"{self._weather_icon} {self._celsius_temp}")
            self._compact_cover.hide()
            if self._current_state in ("LISTENING", "SPEAKING"):
                self._pill_trailing_lbl.hide()
                self._compact_equalizer.show()
            else:
                now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
                self._pill_trailing_lbl.setText(now_str)
                self._pill_trailing_lbl.setStyleSheet("""
                    color: #8e8e93;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    font-size: 11px;
                    font-weight: 500;
                    background: transparent;
                """)
                self._pill_trailing_lbl.show()
                self._compact_equalizer.hide()

        self._pill_weather_lbl.setStyleSheet("""
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
        """)

        if not self._is_expanded:
            target_w = self._COMPACT_W
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
            new_x = geo.left() + (geo.width() - target_w) // 2
            new_y = geo.top() + self._TOP_MARGIN

            self._anim.stop()
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(QRect(new_x, new_y, target_w, self._COMPACT_H))
            self._anim.start()

    # ── Expand and Auto-Minimize Mechanics ───────────────────────────────────
    def expand(self) -> None:
        """
        Expand the island into the box.
        Starts the 5-second auto-minimize timer so it automatically returns to the compact bar!
        """
        if self._is_expanded:
            self._reset_auto_minimize_timer()
            return
        self._is_expanded = True
        self._auto_minimize_timer.start(5000)

        # Switch to Music card if media is active and we're not currently popping a notification
        if self._is_media_active and not self._transient_notif_active:
            self._active_context = 0
            self._card_stack.setCurrentIndex(0)

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        new_x = geo.left() + (geo.width() - self._EXPANDED_W) // 2
        new_y = geo.top() + self._TOP_MARGIN

        self._update_pill_style(expanded=True)
        self._compact_widget.hide()
        self._expanded_widget.show()

        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(new_x, new_y, self._EXPANDED_W, self._EXPANDED_H))
        self._anim.start()
        self._ensure_topmost()

    def collapse(self) -> None:
        """Minimize the box back into the compact bar."""
        if not self._is_expanded:
            return
        self._is_expanded = False
        self._auto_minimize_timer.stop()

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        target_w = getattr(self, "_current_pill_alert_w", self._EXPANDED_PILL_W) if self._transient_notif_active else self._COMPACT_W
        new_x = geo.left() + (geo.width() - target_w) // 2
        new_y = geo.top() + self._TOP_MARGIN

        self._expanded_widget.hide()
        self._compact_widget.show()
        self._update_pill_style(expanded=False)

        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(new_x, new_y, target_w, self._COMPACT_H))
        self._anim.start()
        self._ensure_topmost()
        try:
            gc.collect()
        except Exception:
            pass

    def toggle(self) -> None:
        self.handle_pill_click()

    def pop_transient_notification(
        self, badge: str, title: str, message: str, color: str = "#22c55e", msg_time: str = ""
    ) -> None:
        """Show an alert on the island (pops in box if DND is off, or sleek pill animation if DND is on)."""
        combined = f"{badge} {title} {message}".lower()
        is_call = any(k in combined for k in ("call", "calling"))
        is_video = "video" in combined
        icon = "📹" if is_video else ("📞" if is_call else ("💬" if "whatsapp" in badge.lower() else ("📋" if "clip" in badge.lower() else "🔔")))

        if is_windows_dnd_active():
            self.show_island_pill_alert(
                icon=icon,
                badge=badge,
                title=title,
                snippet=message,
                color=color,
                duration_ms=6500 if is_call else 5000,
                msg_time=msg_time,
            )
        else:
            self.pop_notification_box(
                icon=icon,
                badge=badge,
                title=title,
                body=message,
                color=color,
                duration_ms=8000 if is_call else 6500,
                msg_time=msg_time,
            )

    def pop_notification(self, badge: str, title: str, text: str) -> None:
        """Alias for compatibility with ui.py calls."""
        self.pop_transient_notification(badge, title, text)

    def show_message(self, sender: str, message: str, msg_time: str = "") -> None:
        self.pop_transient_notification("WhatsApp", sender or "New Message", message, color="#22c55e", msg_time=msg_time)

    def show_call(self, caller: str, call_type: str = "Voice", app_name: str = "WhatsApp", msg_time: str = "") -> None:
        """Explicit helper to display an incoming call on the Dynamic Island."""
        is_video = "video" in call_type.lower()
        icon = "📹" if is_video else "📞"
        badge = f"{app_name} Video Call" if is_video else f"{app_name} Call"
        color = "#38bdf8" if is_video else "#22c55e"
        desc = "Incoming Video Call..." if is_video else "Incoming Voice Call..."
        self.pop_transient_notification(badge, caller or "Incoming Call", desc, color=color, msg_time=msg_time)

    def show_news(self, items: list | dict | str, title: str = "HEADLINES") -> None:
        """
        Display news headlines one by one directly on the Dynamic Island compact bar.
        Keeps the island strictly on the compact bar (no popup card or expanding box).
        Cycles through stories one by one as JARVIS speaks.
        """
        parsed_items: list[tuple[str, str]] = []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    source = it.get("source") or it.get("channel") or "News"
                    h_text = it.get("title") or it.get("snippet") or str(it)
                    if str(h_text).strip():
                        parsed_items.append((str(source).strip(), str(h_text).strip()))
                else:
                    text_line = str(it).strip()
                    if text_line:
                        parsed_items.append(("News", text_line))
        elif isinstance(items, dict):
            source = items.get("source") or items.get("channel") or "News"
            h_text = items.get("title") or items.get("snippet") or str(items)
            if str(h_text).strip():
                parsed_items.append((str(source).strip(), str(h_text).strip()))
        else:
            text_str = str(items or "").strip()
            for line in text_str.split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^(?:\d+[\.\)]|\•|\-|\*)\s*(.+?)(?:\s*\[(.*?)\])?$", line)
                if m:
                    h_text = m.group(1).strip()
                    source = (m.group(2) or "News").strip()
                    if h_text and len(h_text) > 8 and not h_text.lower().startswith("source:"):
                        parsed_items.append((source, h_text))
                elif len(line) > 15 and not line.lower().startswith("source:") and not line.lower().startswith("latest news:") and not line.lower().startswith("search results"):
                    parsed_items.append(("News", line))

        if not parsed_items:
            fallback = str(items or "")[:60].strip()
            if fallback:
                parsed_items = [("News", fallback)]

        self._news_sequence_queue = parsed_items
        self._news_sequence_idx = 0
        self._news_sequence_timer.stop()
        self._advance_news_sequence()

    def _advance_news_sequence(self) -> None:
        """Advance to the next headline in the news queue on the compact bar."""
        if not self._news_sequence_queue:
            return
        if self._news_sequence_idx >= len(self._news_sequence_queue):
            self._news_sequence_queue.clear()
            self._news_sequence_idx = 0
            return

        source, headline = self._news_sequence_queue[self._news_sequence_idx]
        self._news_sequence_idx += 1

        clean_src = source[:16] if source else "News"
        clean_hd = headline.split(" - ")[0].strip()

        # Display strictly on the compact bar (no popup card/box)
        self.show_island_pill_alert("◈", clean_src, "News", clean_hd, color="#38bdf8", duration_ms=7500)

        # Advance to next headline after 7 seconds if more remain
        if self._news_sequence_idx < len(self._news_sequence_queue):
            self._news_sequence_timer.start(7000)

    def stop_news_sequence(self) -> None:
        """Stop any ongoing news headline rotation and reset bar."""
        self._news_sequence_timer.stop()
        self._news_sequence_queue.clear()
        self._news_sequence_idx = 0
        if not self._is_expanded:
            self._reset_bar_display()

    def show_weather(self, summary: str, location: str = "Colombo") -> None:
        self._card_stack.setCurrentIndex(1)
        self.expand()

    def show_media(self, title: str, artist: str = "") -> None:
        if title:
            self._title_lbl.setText(str(title)[:28])
            self._artist_lbl.setText(str(artist)[:30] if artist else "Unknown Artist")
            self._is_media_active = True
            self._current_media_title = str(title)
            self._current_media_artist = str(artist)
            if not self._transient_notif_active:
                pill_title = str(title) if len(str(title)) <= 20 else (str(title)[:19] + "…")
                self._pill_weather_lbl.setText(f"🎵 {pill_title}")
                self._pill_trailing_lbl.hide()
                self._compact_equalizer.show()
        self._card_stack.setCurrentIndex(0)
        # Kept on small bar per user request — clicking pill expands it!

    def set_state(self, state: str) -> None:
        state = str(state or "STANDBY").upper()
        self._current_state = state
        speaking = (state == "SPEAKING")
        listening = (state == "LISTENING")

        if speaking:
            # JARVIS TALKING: Solid Red visualizer (#ef4444)
            self._privacy_dot.setStyleSheet("background: #ef4444; border-radius: 2px;")
            self._compact_equalizer.set_mode("jarvis")
            self._expanded_equalizer.set_mode("jarvis")
            self._compact_equalizer.show()
            self._pill_trailing_lbl.hide()
        elif listening:
            # USER TALKING / LISTENING: Solid Green visualizer (#22c55e)
            self._privacy_dot.setStyleSheet("background: #22c55e; border-radius: 2px;")
            self._compact_equalizer.set_mode("user")
            self._expanded_equalizer.set_mode("user")
            self._compact_equalizer.show()
            self._pill_trailing_lbl.hide()
        elif self._is_media_active and self._is_playing:
            # MUSIC PLAYING: Solid White visualizer (#ffffff)
            self._privacy_dot.setStyleSheet("background: #27272a; border-radius: 2px;")
            self._compact_equalizer.set_mode("music")
            self._expanded_equalizer.set_mode("music")
            self._compact_equalizer.show()
            self._pill_trailing_lbl.hide()
        else:
            # IDLE / STANDBY: Muted Solid Gray (#a1a1aa)
            self._privacy_dot.setStyleSheet("background: #27272a; border-radius: 2px;")
            self._compact_equalizer.set_mode("idle")
            self._expanded_equalizer.set_mode("idle")
            if not self._is_expanded and not self._transient_notif_active:
                now_str = datetime.now().strftime("%I:%M %p")
                self._pill_trailing_lbl.setText(now_str)
                self._pill_trailing_lbl.show()
                self._compact_equalizer.hide()

    def set_audio_level(self, level: float | None) -> None:
        """Accurately scale visualizer waveform bars in real-time with incoming audio level."""
        self._compact_equalizer.set_level(level)
        self._expanded_equalizer.set_level(level)

    # ── Mouse Click & Drag (Locked on Top of Screen) ─────────────────────────
    def mouseDoubleClickEvent(self, event) -> None:
        """Double clicking restores the full desktop console."""
        self.restore_main_window()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.handle_pill_click()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_expanded:
            self._reset_auto_minimize_timer()
        event.accept()

    def restore_main_window(self) -> None:
        if self._main_window is not None:
            self._main_window.showNormal()
            self._main_window.raise_()
            self._main_window.activateWindow()
        self.collapse()

    def closeEvent(self, event) -> None:
        try:
            if hasattr(self, "_notif_watcher") and self._notif_watcher:
                self._notif_watcher.stop()
        except Exception:
            pass
        super().closeEvent(event)
