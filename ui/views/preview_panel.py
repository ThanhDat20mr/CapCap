import os

from PySide6 import QtCore
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from runtime_paths import asset_path
from widgets import MpvVideoView, TimelineWidget, VideoView
from utils.icon_utils import load_icon
from utils.media_backend import is_mpv_backend_available


def _set_preview_icon_button(button: QPushButton, icon_path: str, tooltip: str):
    button.setText("")
    button.setFixedSize(38, 38)
    button.setIcon(load_icon(icon_path, 18))
    button.setIconSize(QSize(18, 18))
    button.setStyleSheet("QPushButton { padding: 0; }")


class OcrRegionOverlay(QWidget):
    _HANDLE_SIZE = 10
    _MIN_W = 40
    _MIN_H = 10

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self._norm = QRectF(0.0, 0.75, 1.0, 0.25)
        self._load_rect()
        self._target_view = None
        self._main_window = None
        self._requested_visible = True
        self._editable = False
        self._drag_mode = ""
        self._drag_offset = QRectF()
        self._rect_on_press = QRectF()
        self._press_pos = QRectF()
        self.hide()

    def _load_rect(self):
        v = os.getenv("OCR_SUBTITLE_RECT", "")
        try:
            parts = [float(x) for x in v.split(",")]
            if len(parts) == 4:
                self._norm = QRectF(*parts)
        except Exception:
            pass

    def _save_rect(self):
        r = self._norm
        os.environ["OCR_SUBTITLE_RECT"] = f"{r.x():.4f},{r.y():.4f},{r.width():.4f},{r.height():.4f}"
        os.environ["OCR_CROP_RATIO"] = f"{r.height():.4f}"

    def attach_to_view(self, view):
        self._target_view = view
        if view and view.window():
            self._main_window = view.window()
            self._main_window.installEventFilter(self)

    def set_editable(self, editable: bool):
        self._editable = editable
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self._editable)
        if not editable:
            self._drag_mode = ""
            self.setCursor(Qt.ArrowCursor)
            try:
                self.releaseKeyboard()
            except Exception:
                pass
        else:
            self.setCursor(Qt.OpenHandCursor)
            self.grabKeyboard()
        self._update_button()
        self.update()

    def _update_button(self):
        w = self._main_window
        if w is None:
            return
        btn = getattr(w, "ocr_region_btn", None)
        if btn is None:
            return
        if not bool(getattr(w, "_ocr_overlay_visible", True)):
            btn.setStyleSheet("QPushButton { color: #7a8ea3; font-weight: bold; font-size: 10px; padding: 0; }")
        elif self._editable:
            btn.setStyleSheet("QPushButton { color: #ffb450; font-weight: bold; font-size: 10px; padding: 0; }")
        else:
            btn.setStyleSheet("QPushButton { color: #6ee7d6; font-weight: bold; font-size: 10px; padding: 0; }")

    def _is_requested_visible(self) -> bool:
        if hasattr(self, "_requested_visible"):
            return bool(self._requested_visible)
        w = self._main_window
        if w is None and self._target_view is not None:
            w = self._target_view.window()
            if w is not None:
                self._main_window = w
                self._main_window.installEventFilter(self)
        if w is None:
            return True
        return bool(getattr(w, "_ocr_overlay_visible", True))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._editable:
            self.set_editable(False)
            self.releaseKeyboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if obj is self._main_window:
            if event.type() == QtCore.QEvent.WindowDeactivate:
                self.hide()
            elif event.type() in (QtCore.QEvent.WindowActivate, QtCore.QEvent.Resize, QtCore.QEvent.Move, QtCore.QEvent.Show):
                if self._is_requested_visible():
                    self.sync_to_view()
                else:
                    self.hide()
        return False

    def sync_to_view(self):
        if not self._target_view:
            self.hide()
            return
        if self._main_window is None and self._target_view.window() is not None:
            self._main_window = self._target_view.window()
            self._main_window.installEventFilter(self)
        if self._main_window is not None and bool(getattr(self._main_window, "_suspend_ocr_overlay", False)):
            self.hide()
            return
        if not self._is_requested_visible():
            self.hide()
            return
        engine = os.getenv("TRANSCRIPTION_ENGINE", "whisper").strip().lower()
        if engine != "ocr":
            self.hide()
            return
        self._load_rect()
        top_left = self._target_view.mapToGlobal(QtCore.QPoint(0, 0))
        self.setGeometry(QtCore.QRect(top_left, self._target_view.size()))
        self.show()
        self.raise_()
        self.update()

    def _content_rect(self):
        if self._target_view and hasattr(self._target_view, "get_video_content_rect"):
            r = self._target_view.get_video_content_rect()
            if r.width() > 0 and r.height() > 0:
                return r
        return QRectF(0, 0, float(self.width()), float(self.height()))

    def _ocr_rect(self):
        c = self._content_rect()
        return QRectF(
            c.x() + self._norm.x() * c.width(),
            c.y() + self._norm.y() * c.height(),
            self._norm.width() * c.width(),
            self._norm.height() * c.height(),
        )

    def _set_ocr_rect(self, rect: QRectF):
        c = self._content_rect()
        w = max(1.0, float(c.width()))
        h = max(1.0, float(c.height()))
        bounded = QRectF(rect)
        bounded.setWidth(max(self._MIN_W, bounded.width()))
        bounded.setHeight(max(self._MIN_H, bounded.height()))
        if bounded.left() < c.left():
            bounded.moveLeft(c.left())
        if bounded.top() < c.top():
            bounded.moveTop(c.top())
        if bounded.right() > c.right():
            bounded.moveRight(c.right())
        if bounded.bottom() > c.bottom():
            bounded.moveBottom(c.bottom())
        self._norm = QRectF(
            max(0.0, (bounded.x() - c.x()) / w),
            max(0.0, (bounded.y() - c.y()) / h),
            min(1.0, bounded.width() / w),
            min(1.0, bounded.height() / h),
        )
        self._save_rect()
        self.update()

    def _handle_rects(self, rect: QRectF):
        s = float(self._HANDLE_SIZE)
        half = s / 2.0
        pts = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        return {k: QRectF(p.x() - half, p.y() - half, s, s) for k, p in pts.items()}

    def _hit_test(self, pos):
        r = self._ocr_rect()
        for name, hr in self._handle_rects(r).items():
            if hr.contains(pos):
                return name
        if r.contains(pos):
            return "move"
        return ""

    def mousePressEvent(self, event):
        if not self._editable or event.button() != Qt.LeftButton:
            if not self._editable and event.button() == Qt.LeftButton:
                self.set_editable(True)
                self.setCursor(Qt.OpenHandCursor)
                event.accept()
                return
            event.ignore()
            return
        pos = event.position()
        self._drag_mode = self._hit_test(pos)
        self._rect_on_press = QRectF(self._ocr_rect())
        self._press_pos = pos
        if self._drag_mode == "move":
            self._drag_offset = pos - self._rect_on_press.topLeft()
            self.setCursor(Qt.ClosedHandCursor)
        elif self._drag_mode:
            self.setCursor(Qt.SizeAllCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if not self._editable:
            event.ignore()
            return
        if not self._drag_mode:
            hit = self._hit_test(pos)
            if hit == "move":
                self.setCursor(Qt.OpenHandCursor)
            elif hit:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        rect = QRectF(self._rect_on_press)
        if self._drag_mode == "move":
            rect.moveTopLeft(pos - self._drag_offset)
        else:
            d = pos - self._press_pos
            if "left" in self._drag_mode:
                rect.setLeft(rect.left() + d.x())
            if "right" in self._drag_mode:
                rect.setRight(rect.right() + d.x())
            if "top" in self._drag_mode:
                rect.setTop(rect.top() + d.y())
            if "bottom" in self._drag_mode:
                rect.setBottom(rect.bottom() + d.y())
            if rect.width() < self._MIN_W:
                if "left" in self._drag_mode:
                    rect.setLeft(rect.right() - self._MIN_W)
                else:
                    rect.setRight(rect.left() + self._MIN_W)
            if rect.height() < self._MIN_H:
                if "top" in self._drag_mode:
                    rect.setTop(rect.bottom() - self._MIN_H)
                else:
                    rect.setBottom(rect.top() + self._MIN_H)
        self._set_ocr_rect(rect)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_mode = ""
        if self._editable:
            self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def paintEvent(self, event):
        if self._target_view is None:
            return
        rect = self._ocr_rect()
        if rect.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        color = QColor(110, 231, 214) if not self._editable else QColor(255, 180, 80)
        a = 120 if not self._editable else 180
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), a), 2))
        p.setBrush(QColor(color.red(), color.green(), color.blue(), a // 4))
        p.drawRoundedRect(rect, 8, 8)

        if self._editable:
            p.setBrush(QColor(255, 180, 80, 235))
            p.setPen(QPen(QColor(12, 24, 38, 220), 1))
            for hr in self._handle_rects(rect).values():
                p.drawEllipse(hr)

        p.setPen(QColor(color.red(), color.green(), color.blue(), 200))
        font = p.font()
        font.setPixelSize(11)
        p.setFont(font)
        label = f"OCR {self._norm.height()*100:.0f}%"
        p.drawText(int(rect.right() - 90), int(rect.bottom() - 6), label)
        p.end()


class FramePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.video_source_width = 0
        self.video_source_height = 0
        self.preview_aspect_key = "source"
        self.preview_scale_mode = "fit"
        self.preview_fill_focus_x = 0.5
        self.preview_fill_focus_y = 0.5
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.hide()

    def set_frame_image(self, image_path: str):
        self._pixmap = QPixmap(image_path)
        self.update()

    def clear_frame_image(self):
        self._pixmap = QPixmap()
        self.update()

    def set_video_dimensions(self, width: int, height: int):
        self.video_source_width = max(0, int(width or 0))
        self.video_source_height = max(0, int(height or 0))
        self.update()

    def set_preview_aspect_ratio(self, aspect_key: str):
        self.preview_aspect_key = str(aspect_key or "source").strip().lower() or "source"
        self.update()

    def set_preview_scale_mode(self, scale_mode: str):
        self.preview_scale_mode = str(scale_mode or "fit").strip().lower() or "fit"
        self.update()

    def set_preview_fill_focus(self, focus_x: float, focus_y: float):
        self.preview_fill_focus_x = max(0.0, min(1.0, float(focus_x)))
        self.preview_fill_focus_y = max(0.0, min(1.0, float(focus_y)))
        self.update()

    def _resolve_canvas_aspect_ratio(self) -> float | None:
        aspect_map = {
            "16:9": 16.0 / 9.0,
            "9:16": 9.0 / 16.0,
            "1:1": 1.0,
            "4:3": 4.0 / 3.0,
        }
        if self.preview_aspect_key in aspect_map:
            return aspect_map[self.preview_aspect_key]
        if self.video_source_width and self.video_source_height:
            return self.video_source_width / self.video_source_height
        if not self._pixmap.isNull() and self._pixmap.height() > 0:
            return self._pixmap.width() / self._pixmap.height()
        return None

    def get_preview_canvas_rect(self) -> QRectF:
        view_w, view_h = float(self.width()), float(self.height())
        if view_w <= 0 or view_h <= 0:
            return QRectF(0, 0, 0, 0)
        canvas_ratio = self._resolve_canvas_aspect_ratio()
        if not canvas_ratio:
            return QRectF(0, 0, view_w, view_h)
        view_ratio = view_w / view_h if view_h else canvas_ratio
        if canvas_ratio > view_ratio:
            content_w = view_w
            content_h = view_w / canvas_ratio
            offset_x = 0.0
            offset_y = (view_h - content_h) / 2.0
        else:
            content_h = view_h
            content_w = view_h * canvas_ratio
            offset_x = (view_w - content_w) / 2.0
            offset_y = 0.0
        return QRectF(offset_x, offset_y, content_w, content_h)

    def get_video_content_rect(self) -> QRectF:
        canvas_rect = self.get_preview_canvas_rect()
        if canvas_rect.width() <= 0 or canvas_rect.height() <= 0:
            return QRectF(0, 0, 0, 0)
        source_w = self.video_source_width or self._pixmap.width()
        source_h = self.video_source_height or self._pixmap.height()
        if not source_w or not source_h:
            return canvas_rect
        source_ratio = source_w / source_h
        canvas_ratio = canvas_rect.width() / canvas_rect.height() if canvas_rect.height() else source_ratio
        if self.preview_scale_mode == "fill":
            if source_ratio > canvas_ratio:
                content_h = canvas_rect.height()
                content_w = content_h * source_ratio
                overflow_w = max(0.0, content_w - canvas_rect.width())
                offset_x = canvas_rect.left() - overflow_w * self.preview_fill_focus_x
                offset_y = canvas_rect.top()
            else:
                content_w = canvas_rect.width()
                content_h = content_w / source_ratio
                offset_x = canvas_rect.left()
                overflow_h = max(0.0, content_h - canvas_rect.height())
                offset_y = canvas_rect.top() - overflow_h * self.preview_fill_focus_y
        else:
            if source_ratio > canvas_ratio:
                content_w = canvas_rect.width()
                content_h = content_w / source_ratio
                offset_x = canvas_rect.left()
                offset_y = canvas_rect.top() + (canvas_rect.height() - content_h) / 2.0
            else:
                content_h = canvas_rect.height()
                content_w = content_h * source_ratio
                offset_x = canvas_rect.left() + (canvas_rect.width() - content_w) / 2.0
                offset_y = canvas_rect.top()
        return QRectF(offset_x, offset_y, content_w, content_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if self._pixmap.isNull():
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        canvas_rect = self.get_preview_canvas_rect()
        target_rect = self.get_video_content_rect()
        painter.setClipRect(canvas_rect)
        painter.drawPixmap(target_rect, self._pixmap, QRectF(self._pixmap.rect()))


class TimelineTrackLabels(QFrame):
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self._timeline = timeline
        self.setObjectName("timelineTrackLabels")
        self.setFixedWidth(112)
        self._rows = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QLabel("Tracks")
        self.header.setFixedHeight(28)
        self.header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.header.setContentsMargins(14, 0, 0, 0)
        self.header.setObjectName("helperLabel")
        layout.addWidget(self.header)

        for key, title in (("video", "Video"), ("text", "Text"), ("audio", "Audio")):
            row = QFrame()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(14, 8, 10, 8)
            row_layout.setSpacing(1)
            title_label = QLabel(title)
            title_label.setObjectName("statusHeadline")
            title_label.setStyleSheet("font-size: 12px; font-weight: 700;")
            row_layout.addStretch()
            row_layout.addWidget(title_label)
            row_layout.addStretch()
            layout.addWidget(row)
            self._rows[key] = row
        layout.addStretch()
        self.sync_to_timeline()

    def sync_to_timeline(self):
        for key, row in self._rows.items():
            visible = self._timeline.is_track_visible(key)
            row.setVisible(visible)
            layout = getattr(self._timeline, "_layout", {})
            row_height = int(layout.get(key, {}).get("h", 0)) if visible else 0
            row.setFixedHeight(row_height)


def _build_timeline_track_labels(timeline):
    return TimelineTrackLabels(timeline)


def build_preview_panel(gui):
    right_panel = QWidget()
    right_panel.setObjectName("rightPanel")
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(10)

    gui.preview_context_label = QLabel("Choose a video to start previewing. Subtitle and voice status will appear here as you work.")
    gui.preview_context_label.setWordWrap(True)
    gui.preview_context_label.setObjectName("previewContextLabel")
    gui.preview_context_label.hide()
    gui.frame_preview_badge_label = QLabel("Frame Preview")
    gui.frame_preview_badge_label.setObjectName("helperLabel")
    gui.frame_preview_badge_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    gui.frame_preview_badge_label.setStyleSheet(
        "QLabel { background: rgba(8, 14, 24, 0.86); border: 1px solid #35506d; "
        "border-radius: 10px; padding: 4px 10px; color: #cfe6ff; font-weight: 700; }"
    )
    gui.frame_preview_badge_label.hide()
    gui.frame_preview_status_label = QLabel("Exact frame preview updates here when available.")
    gui.frame_preview_status_label.setWordWrap(True)
    gui.frame_preview_status_label.setObjectName("helperLabel")
    gui.frame_preview_status_label.hide()
    gui.frame_preview_image_label = FramePreviewWidget()
    gui.frame_preview_image_label.hide()

    gui.video_view = MpvVideoView() if is_mpv_backend_available() else VideoView()
    gui.video_view.setMinimumHeight(320)
    gui.video_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    gui.timeline = TimelineWidget()
    gui.timeline.seekRequested.connect(gui.set_position)
    gui.timeline.segmentSelected.connect(gui.on_timeline_segment_selected)
    gui.timeline.segmentTimingEditStarted.connect(gui.on_timeline_segment_timing_edit_started)
    gui.timeline.segmentTimingChanged.connect(gui.on_timeline_segment_timing_changed)
    gui.timeline.zoomChanged.connect(lambda value: gui.timeline_zoom_label.setText(f"{value}%"))
    gui.time_label = QLabel("00:00 / 00:00")
    gui.time_label.setStyleSheet("font-weight: bold; min-width: 100px; color: #6ee7d6;")

    preview_card = QFrame()
    preview_card.setObjectName("statusCard")
    preview_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    preview_card_layout = QVBoxLayout(preview_card)
    preview_card_layout.setContentsMargins(12, 12, 12, 10)
    preview_card_layout.setSpacing(8)
    preview_card_layout.addWidget(gui.preview_context_label)
    preview_card_layout.addWidget(gui.frame_preview_status_label)
    preview_card_layout.addWidget(gui.frame_preview_image_label, 1)
    preview_card_layout.addWidget(gui.video_view, 1)
    preview_card_layout.setStretchFactor(gui.frame_preview_image_label, 1)
    preview_card_layout.setStretchFactor(gui.video_view, 1)

    icons_dir = asset_path("icons")

    def _make_sep():
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setFixedWidth(2)
        sep.setStyleSheet("QFrame { color: #444; }")
        return sep

    gui.play_btn = QPushButton()
    gui.stop_btn = QPushButton()
    gui.preview_btn = QPushButton()
    gui.blur_area_btn = QPushButton()
    gui.blur_area_btn.setCheckable(True)
    gui.blur_add_btn = QPushButton()
    gui.ocr_region_btn = QPushButton()
    gui.ocr_region_btn.setCheckable(True)
    _set_preview_icon_button(gui.play_btn, os.path.join(icons_dir, "play.svg"), "Play or pause preview")
    _set_preview_icon_button(gui.stop_btn, os.path.join(icons_dir, "reset.svg"), "Reset preview to the beginning")
    _set_preview_icon_button(gui.preview_btn, os.path.join(icons_dir, "preview.svg"), "Render a fresh preview using current subtitle and audio")
    _set_preview_icon_button(gui.blur_area_btn, os.path.join(icons_dir, "blur.svg"), "Turn blur effect on or off")
    gui.blur_add_btn.setText("+")
    gui.blur_add_btn.setToolTip("Add another blur region")
    gui.blur_add_btn.setFixedSize(38, 38)
    gui.blur_add_btn.setStyleSheet("QPushButton { color: #ffc15e; font-weight: bold; font-size: 18px; padding: 0; }")
    gui.ocr_region_btn.setText("OCR")
    gui.ocr_region_btn.setToolTip("Edit OCR subtitle region")
    gui.ocr_region_btn.setFixedSize(38, 38)
    gui.ocr_region_btn.setStyleSheet("QPushButton { color: #6ee7d6; font-weight: bold; font-size: 10px; padding: 0; }")
    gui.ocr_region_btn.hide()

    gui.preview_volume_down_btn = QPushButton()
    gui.preview_mute_btn = QPushButton()
    gui.preview_volume_up_btn = QPushButton()
    _set_preview_icon_button(gui.preview_volume_down_btn, os.path.join(icons_dir, "volume_down.svg"), "Lower preview volume")
    _set_preview_icon_button(gui.preview_mute_btn, os.path.join(icons_dir, "volume_mute.svg"), "Mute preview")
    _set_preview_icon_button(gui.preview_volume_up_btn, os.path.join(icons_dir, "volume_up.svg"), "Raise preview volume")
    gui.preview_volume_label = QLabel("100%")
    gui.preview_volume_label.setObjectName("helperLabel")
    gui.preview_speed_combo = QComboBox()
    gui.preview_speed_combo.addItem("0.75x", 0.75)
    gui.preview_speed_combo.addItem("1.0x", 1.0)
    gui.preview_speed_combo.addItem("1.25x", 1.25)
    gui.preview_speed_combo.addItem("1.5x", 1.5)
    gui.preview_speed_combo.addItem("2.0x", 2.0)
    gui.preview_speed_combo.setCurrentIndex(1)
    gui.preview_audio_track_combo = QComboBox()
    gui.preview_audio_track_combo.setMinimumWidth(108)
    gui.preview_audio_track_combo.addItem("Original", "original")

    play_group = QHBoxLayout()
    play_group.setSpacing(6)
    play_group.addWidget(gui.play_btn)
    play_group.addWidget(gui.stop_btn)
    play_group.addWidget(gui.preview_btn)

    blur_group = QHBoxLayout()
    blur_group.setSpacing(6)
    blur_group.addWidget(gui.blur_area_btn)
    blur_group.addWidget(gui.blur_add_btn)
    blur_group.addWidget(gui.ocr_region_btn)

    volume_group = QHBoxLayout()
    volume_group.setSpacing(6)
    volume_group.addWidget(gui.preview_volume_down_btn)
    volume_group.addWidget(gui.preview_mute_btn)
    volume_group.addWidget(gui.preview_volume_up_btn)
    volume_group.addWidget(gui.preview_volume_label)
    volume_group.addStretch(0)
    volume_group.addWidget(QLabel("Audio"))
    volume_group.addWidget(gui.preview_audio_track_combo)
    volume_group.addWidget(QLabel("Speed"))
    volume_group.addWidget(gui.preview_speed_combo)

    transport_row = QHBoxLayout()
    transport_row.setContentsMargins(0, 0, 0, 0)
    transport_row.setSpacing(10)
    transport_row.addLayout(play_group)
    transport_row.addWidget(_make_sep())
    transport_row.addLayout(blur_group)
    transport_row.addWidget(_make_sep())
    transport_row.addLayout(volume_group, 1)
    preview_card_layout.addLayout(transport_row)
    gui.frame_preview_badge_label.setParent(preview_card)
    gui.frame_preview_badge_label.raise_()

    gui.ocr_region_overlay = OcrRegionOverlay()
    gui.ocr_region_overlay.attach_to_view(gui.video_view)

    def _sync_ocr_overlay():
        overlay = getattr(gui, "ocr_region_overlay", None)
        if overlay is None:
            return
        overlay.sync_to_view()

    gui._sync_ocr_overlay = _sync_ocr_overlay

    _ocr_video = gui.video_view
    _ocr_orig_resize = _ocr_video.resizeEvent
    def _ocr_resize_handler(event):
        _ocr_orig_resize(event)
        _sync_ocr_overlay()
    _ocr_video.resizeEvent = _ocr_resize_handler
    _ocr_orig_move = _ocr_video.moveEvent
    def _ocr_move_handler(event):
        _ocr_orig_move(event)
        _sync_ocr_overlay()
    _ocr_video.moveEvent = _ocr_move_handler
    _ocr_orig_show = _ocr_video.showEvent
    def _ocr_show_handler(event):
        _ocr_orig_show(event)
        _sync_ocr_overlay()
    _ocr_video.showEvent = _ocr_show_handler
    QtCore.QTimer.singleShot(0, _sync_ocr_overlay)

    timeline_card = QFrame()
    timeline_card.setObjectName("statusCard")
    timeline_layout = QVBoxLayout(timeline_card)
    timeline_layout.setContentsMargins(12, 10, 12, 10)
    timeline_layout.setSpacing(8)

    timeline_header_layout = QHBoxLayout()
    timeline_header_layout.setSpacing(10)
    timeline_copy_layout = QVBoxLayout()
    timeline_copy_layout.setSpacing(1)
    timeline_title = QLabel("Timeline")
    timeline_title.setObjectName("statusHeadline")
    timeline_meta = QLabel("Editor-first layout with dedicated video, audio, and subtitle lanes.")
    timeline_meta.setObjectName("helperLabel")
    timeline_copy_layout.addWidget(timeline_title)
    timeline_copy_layout.addWidget(timeline_meta)
    timeline_header_layout.addLayout(timeline_copy_layout, 1)
    gui.timeline_undo_btn = QPushButton("Undo")
    gui.timeline_undo_btn.setFixedWidth(58)
    gui.timeline_undo_btn.setEnabled(False)
    gui.timeline_redo_btn = QPushButton("Redo")
    gui.timeline_redo_btn.setFixedWidth(58)
    gui.timeline_redo_btn.setEnabled(False)
    gui.timeline_split_btn = QPushButton("Split")
    gui.timeline_split_btn.setFixedWidth(58)
    gui.timeline_split_btn.setEnabled(False)
    gui.timeline_delete_btn = QPushButton("Delete")
    gui.timeline_delete_btn.setFixedWidth(62)
    gui.timeline_delete_btn.setEnabled(False)
    gui.timeline_nudge_left_btn = QPushButton("<")
    gui.timeline_nudge_left_btn.setFixedWidth(34)
    gui.timeline_nudge_left_btn.setEnabled(False)
    gui.timeline_nudge_right_btn = QPushButton(">")
    gui.timeline_nudge_right_btn.setFixedWidth(34)
    gui.timeline_nudge_right_btn.setEnabled(False)
    gui.timeline_ripple_left_btn = QPushButton("<<")
    gui.timeline_ripple_left_btn.setFixedWidth(40)
    gui.timeline_ripple_left_btn.setEnabled(False)
    gui.timeline_ripple_right_btn = QPushButton(">>")
    gui.timeline_ripple_right_btn.setFixedWidth(40)
    gui.timeline_ripple_right_btn.setEnabled(False)
    gui.timeline_undo_btn.clicked.connect(gui.undo_last_timeline_timing_edit)
    gui.timeline_redo_btn.clicked.connect(gui.redo_last_timeline_timing_edit)
    gui.timeline_split_btn.clicked.connect(gui.split_selected_timeline_segment)
    gui.timeline_delete_btn.clicked.connect(gui.delete_selected_timeline_segment)
    gui.timeline_nudge_left_btn.clicked.connect(lambda: gui.nudge_selected_timeline_segment(-0.05))
    gui.timeline_nudge_right_btn.clicked.connect(lambda: gui.nudge_selected_timeline_segment(0.05))
    gui.timeline_ripple_left_btn.clicked.connect(lambda: gui.ripple_nudge_selected_timeline_segment(-0.05))
    gui.timeline_ripple_right_btn.clicked.connect(lambda: gui.ripple_nudge_selected_timeline_segment(0.05))
    gui.timeline_zoom_out_btn = QPushButton("-")
    gui.timeline_zoom_out_btn.setFixedWidth(34)
    gui.timeline_zoom_label = QLabel(f"{gui.timeline.zoom_percent()}%")
    gui.timeline_zoom_label.setObjectName("helperLabel")
    gui.timeline_zoom_label.setAlignment(Qt.AlignCenter)
    gui.timeline_zoom_label.setMinimumWidth(48)
    gui.timeline_zoom_in_btn = QPushButton("+")
    gui.timeline_zoom_in_btn.setFixedWidth(34)
    gui.timeline_zoom_reset_btn = QPushButton("Fit")
    gui.timeline_zoom_reset_btn.setFixedWidth(52)
    gui.timeline_zoom_out_btn.clicked.connect(gui.timeline.zoom_out)
    gui.timeline_zoom_in_btn.clicked.connect(gui.timeline.zoom_in)
    gui.timeline_zoom_reset_btn.clicked.connect(gui.timeline.reset_zoom)
    gui.voice_timing_sync_label = QLabel("Sync")
    gui.voice_timing_sync_label.setObjectName("helperLabel")

    edit_group = QHBoxLayout()
    edit_group.setSpacing(4)
    edit_group.addWidget(gui.timeline_undo_btn)
    edit_group.addWidget(gui.timeline_redo_btn)
    edit_group.addWidget(gui.timeline_split_btn)
    edit_group.addWidget(gui.timeline_delete_btn)

    nudge_group = QHBoxLayout()
    nudge_group.setSpacing(4)
    nudge_group.addWidget(gui.timeline_nudge_left_btn)
    nudge_group.addWidget(gui.timeline_nudge_right_btn)
    nudge_group.addWidget(gui.timeline_ripple_left_btn)
    nudge_group.addWidget(gui.timeline_ripple_right_btn)

    view_group = QHBoxLayout()
    view_group.setSpacing(4)
    view_group.addWidget(gui.timeline_zoom_out_btn)
    view_group.addWidget(gui.timeline_zoom_label)
    view_group.addWidget(gui.timeline_zoom_in_btn)
    view_group.addWidget(gui.timeline_zoom_reset_btn)
    view_group.addWidget(gui.voice_timing_sync_label)
    view_group.addWidget(gui.voice_timing_sync_combo)
    view_group.addWidget(gui.time_label)

    timeline_header_layout.addLayout(edit_group)
    timeline_header_layout.addWidget(_make_sep())
    timeline_header_layout.addLayout(nudge_group)
    timeline_header_layout.addWidget(_make_sep())
    timeline_header_layout.addLayout(view_group)
    timeline_layout.addLayout(timeline_header_layout)

    timeline_body_layout = QHBoxLayout()
    timeline_body_layout.setSpacing(0)
    gui.timeline_track_labels = _build_timeline_track_labels(gui.timeline)
    gui.timeline.layoutChanged.connect(gui.timeline_track_labels.sync_to_timeline)
    timeline_body_layout.addWidget(gui.timeline_track_labels)
    timeline_body_layout.addWidget(gui.timeline, 1)
    timeline_layout.addLayout(timeline_body_layout)

    gui.progress_bar = QProgressBar()
    gui.progress_bar.setFixedHeight(8)
    gui.progress_bar.setTextVisible(False)
    timeline_layout.addWidget(gui.progress_bar)

    gui.translated_text = QTextEdit()
    gui.translated_text.setPlaceholderText("Vietnamese subtitle text will appear here. You can edit it before export.")
    gui.translated_text.hide()
    gui.transcript_text = QTextEdit()
    gui.transcript_text.setPlaceholderText("The original subtitle transcript will appear here...")
    gui.transcript_text.hide()

    inspector_shell = QWidget()
    inspector_shell.setObjectName("subtitleInspectorShell")
    inspector_shell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    inspector_shell_layout = QHBoxLayout(inspector_shell)
    inspector_shell_layout.setContentsMargins(0, 0, 0, 0)
    inspector_shell_layout.setSpacing(0)

    inspector_card = QFrame()
    inspector_card.setObjectName("statusCard")
    inspector_card.setMinimumWidth(360)
    inspector_card.setMaximumWidth(560)
    gui.subtitle_inspector_card = inspector_card
    inspector_layout = QVBoxLayout(inspector_card)
    inspector_layout.setContentsMargins(14, 14, 14, 14)
    inspector_layout.setSpacing(10)

    inspector_header = QHBoxLayout()
    inspector_header.setSpacing(8)
    inspector_copy = QVBoxLayout()
    inspector_copy.setSpacing(2)
    inspector_title = QLabel("Subtitle Inspector")
    inspector_title.setObjectName("statusHeadline")
    inspector_copy.addWidget(inspector_title)
    gui.subtitle_inspector_summary_label = QLabel("Selected subtitle: none")
    gui.subtitle_inspector_summary_label.setObjectName("helperLabel")
    gui.subtitle_inspector_summary_label.setWordWrap(True)
    inspector_copy.addWidget(gui.subtitle_inspector_summary_label)
    inspector_header.addLayout(inspector_copy, 1)
    inspector_header.addStretch(0)
    inspector_layout.addLayout(inspector_header)

    gui.subtitle_inspector_details_widget = QWidget()
    gui.subtitle_inspector_details_widget.setObjectName("segmentInspectorDetails")
    inspector_details_layout = QVBoxLayout(gui.subtitle_inspector_details_widget)
    inspector_details_layout.setContentsMargins(0, 0, 0, 0)
    inspector_details_layout.setSpacing(10)

    inspector_actions_row = QHBoxLayout()
    inspector_actions_row.setSpacing(8)
    gui.rewrite_translation_btn = QPushButton("Rewrite")
    gui.rewrite_selected_segment_btn = QPushButton("Rewrite Selected Subtitle")
    gui.import_translation_btn = QPushButton("Import SRT")
    gui.rewrite_selected_segment_btn.clicked.connect(gui.run_rewrite_selected_segment)
    inspector_actions_row.addWidget(gui.rewrite_translation_btn)
    inspector_actions_row.addWidget(gui.rewrite_selected_segment_btn)
    inspector_actions_row.addWidget(gui.import_translation_btn)
    inspector_layout.addLayout(inspector_actions_row)

    gui.show_original_subtitle_cb = QCheckBox("Show original")
    gui.show_original_subtitle_cb.setChecked(True)
    inspector_toggle_row = QHBoxLayout()
    inspector_toggle_row.setSpacing(10)
    inspector_toggle_row.addWidget(gui.show_original_subtitle_cb)
    inspector_toggle_row.addStretch(1)
    inspector_layout.addLayout(inspector_toggle_row)

    inspector_nav_row = QHBoxLayout()
    inspector_nav_row.setSpacing(8)
    gui.segment_prev_btn = QPushButton("Prev")
    gui.segment_prev_btn.clicked.connect(lambda: gui.step_selected_segment(-1))
    gui.segment_next_btn = QPushButton("Next")
    gui.segment_next_btn.clicked.connect(lambda: gui.step_selected_segment(1))
    gui.segment_selection_label = QLabel("No subtitle selected")
    gui.segment_selection_label.setObjectName("helperLabel")
    inspector_nav_row.addWidget(gui.segment_prev_btn)
    inspector_nav_row.addWidget(gui.segment_next_btn)
    inspector_nav_row.addWidget(gui.segment_selection_label, 1)
    inspector_layout.addLayout(inspector_nav_row)

    gui.segment_editor_scroll = QScrollArea()
    gui.segment_editor_scroll.setObjectName("segmentEditorScroll")
    gui.segment_editor_scroll.setWidgetResizable(True)
    gui.segment_editor_scroll.setFrameShape(QFrame.NoFrame)
    gui.segment_editor_container = QWidget()
    gui.segment_editor_container.setObjectName("segmentEditorContainer")
    gui.segment_editor_layout = QVBoxLayout(gui.segment_editor_container)
    gui.segment_editor_layout.setContentsMargins(0, 0, 0, 0)
    gui.segment_editor_layout.setSpacing(10)
    gui.segment_editor_scroll.setWidget(gui.segment_editor_container)
    inspector_details_layout.addWidget(gui.segment_editor_scroll, 1)
    inspector_layout.addWidget(gui.subtitle_inspector_details_widget, 1)
    gui.subtitle_inspector_details_widget.setVisible(False)

    inspector_handle = QFrame()
    inspector_handle.setObjectName("subtitleInspectorHandle")
    inspector_handle.setFixedWidth(34)
    inspector_handle_layout = QVBoxLayout(inspector_handle)
    inspector_handle_layout.setContentsMargins(0, 0, 0, 0)
    inspector_handle_layout.setSpacing(0)
    inspector_handle_layout.addStretch(1)
    gui.subtitle_inspector_toggle_btn = QPushButton("◀")
    gui.subtitle_inspector_toggle_btn.setCheckable(True)
    gui.subtitle_inspector_toggle_btn.setChecked(False)
    gui.subtitle_inspector_toggle_btn.setObjectName("subtitleInspectorHandleBtn")
    gui.subtitle_inspector_toggle_btn.setFixedSize(28, 110)
    gui.subtitle_inspector_toggle_btn.clicked.connect(lambda checked: gui.toggle_subtitle_inspector_details(bool(checked)))
    inspector_handle_layout.addWidget(gui.subtitle_inspector_toggle_btn, 0, Qt.AlignHCenter)
    inspector_handle_layout.addStretch(1)

    inspector_shell_layout.addWidget(inspector_card, 1)
    inspector_shell_layout.addWidget(inspector_handle, 0)
    gui.subtitle_inspector_details_widget.setVisible(False)
    gui.subtitle_inspector_shell = inspector_shell
    gui.subtitle_inspector_handle = inspector_handle
    inspector_shell.setFixedWidth(max(34, inspector_handle.sizeHint().width() or inspector_handle.width() or 34))

    workspace_row = QHBoxLayout()
    workspace_row.setSpacing(10)
    workspace_row.addWidget(preview_card, 1)
    workspace_row.addWidget(inspector_shell, 0)

    right_layout.addLayout(workspace_row, 5)
    right_layout.addWidget(timeline_card, 3)
    return right_panel
