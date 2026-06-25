from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy


TRACK_ICONS: dict[str, str] = {
    "V1": "\u25b6",
    "B1": "\u25a3",
    "A1": "\u266b",
    "A2": "\u266b",
    "S1": "T",
    "M1": "\u25a0",
}

AUDIO_PREFIXES = {"A1", "A2"}
BLUR_PREFIXES = {"B1"}
LOGO_PREFIXES = {"L1"}
MASK_PREFIXES = {"M1"}


class TrackLabelBar(QFrame):
    """Fixed left-side label strip showing track names. Pairs with EditorTimeline."""

    muteToggled = Signal(str, bool)  # track_name, is_muted
    blurToggled = Signal(str, bool)  # track_name, is_enabled
    logoToggled = Signal(str, bool)  # track_name, is_shown
    maskToggled = Signal(str, bool)  # track_name, is_shown

    TRACK_HEADER_W = 132
    RULER_HEIGHT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.TRACK_HEADER_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #142030; border: none;")
        self._track_names: list[str] = []
        self._track_heights: list[int] = []
        self._track_locked: list[bool] = []
        self._track_muted: list[bool] = []
        self._track_blur_on: list[bool] = []
        self._track_logo_shown: list[bool] = []
        self._track_mask_shown: list[bool] = []
        self._timeline_widget = None  # for vertical scroll sync

    def set_timeline(self, timeline):
        """Store a reference to the timeline so the labels can be
        scrolled in sync with the timeline's vertical scrollbar."""
        self._timeline_widget = timeline
        # Repaint the labels whenever the timeline scrolls or its
        # geometry changes so the track label positions follow the
        # layer content.
        try:
            sb = timeline.verticalScrollBar()
            if sb is not None:
                sb.valueChanged.connect(self.update)
        except Exception:
            pass
        try:
            # Repaint on horizontal scroll and viewport changes too
            timeline.horizontalScrollBar().valueChanged.connect(self.update)
        except Exception:
            pass

    def set_tracks(self, names: list, heights: list, locked: list = None, muted: list = None):
        self._track_names = names
        self._track_heights = heights
        self._track_locked = locked or [False] * len(names)
        self._track_muted = muted or [False] * len(names)
        # Default blur effect to ON for B1 tracks
        self._track_blur_on = [
            (n.split(" ")[0] in BLUR_PREFIXES) for n in names
        ]
        # Default logo visibility to ON for L1 tracks
        self._track_logo_shown = [
            (n.split(" ")[0] in LOGO_PREFIXES) for n in names
        ]
        # Default mask visibility to ON for M1 tracks
        self._track_mask_shown = [
            (n.split(" ")[0] in MASK_PREFIXES) for n in names
        ]
        self.update()

    def _get_track_heights(self) -> list:
        """Return the current track heights, preferring the timeline's
        live values so the labels stay in sync with dynamic heights."""
        if self._timeline_widget is not None and hasattr(
            self._timeline_widget, "_track_heights"
        ):
            tl_heights = self._timeline_widget._track_heights
            if self._track_names and tl_heights:
                # Use timeline's heights, falling back to our cached
                # values for any track not in the timeline's dict.
                return [tl_heights.get(n, h) for n, h in zip(self._track_names, self._track_heights)]
        return self._track_heights

    def set_muted(self, name: str, muted: bool):
        for i, n in enumerate(self._track_names):
            if n == name and i < len(self._track_muted):
                self._track_muted[i] = muted
                self.update()
                return

    def set_blur_on(self, name: str, on: bool):
        for i, n in enumerate(self._track_names):
            if n == name and i < len(self._track_blur_on):
                self._track_blur_on[i] = on
                self.update()
                return

    def set_logo_shown(self, name: str, shown: bool):
        for i, n in enumerate(self._track_names):
            if n == name and i < len(self._track_logo_shown):
                self._track_logo_shown[i] = shown
                self.update()
                return

    def set_mask_shown(self, name: str, shown: bool):
        for i, n in enumerate(self._track_names):
            if n == name and i < len(self._track_mask_shown):
                self._track_mask_shown[i] = shown
                self.update()
                return

    def mousePressEvent(self, event: QMouseEvent):
        # Click on an audio track label to toggle its mute state.
        # Click on a blur track label to toggle the blur effect.
        # Click on a logo track label to hide/show the logo.
        # Click on a mask track label to hide/show the mask.
        if event.button() == Qt.LeftButton:
            idx = self._track_index_at(event.position().y())
            if 0 <= idx < len(self._track_names):
                name = self._track_names[idx]
                prefix = name.split(" ")[0] if name else ""
                if prefix in AUDIO_PREFIXES:
                    new_muted = not self._track_muted[idx]
                    self._track_muted[idx] = new_muted
                    self.update()
                    self.muteToggled.emit(name, new_muted)
                    event.accept()
                    return
                if prefix in BLUR_PREFIXES:
                    new_state = not (
                        self._track_blur_on[idx]
                        if idx < len(self._track_blur_on)
                        else False
                    )
                    if idx < len(self._track_blur_on):
                        self._track_blur_on[idx] = new_state
                    self.update()
                    self.blurToggled.emit(name, new_state)
                    event.accept()
                    return
                if prefix in LOGO_PREFIXES:
                    new_state = not (
                        self._track_logo_shown[idx]
                        if idx < len(self._track_logo_shown)
                        else False
                    )
                    if idx < len(self._track_logo_shown):
                        self._track_logo_shown[idx] = new_state
                    self.update()
                    self.logoToggled.emit(name, new_state)
                    event.accept()
                    return
                if prefix in MASK_PREFIXES:
                    new_state = not (
                        self._track_mask_shown[idx]
                        if idx < len(self._track_mask_shown)
                        else False
                    )
                    if idx < len(self._track_mask_shown):
                        self._track_mask_shown[idx] = new_state
                    self.update()
                    self.maskToggled.emit(name, new_state)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Change cursor to a pointing hand when hovering over an audio,
        # blur, logo, or mask track label to signal it is clickable.
        idx = self._track_index_at(event.position().y())
        is_clickable = False
        if 0 <= idx < len(self._track_names):
            prefix = self._track_names[idx].split(" ")[0] if self._track_names[idx] else ""
            if (prefix in AUDIO_PREFIXES or prefix in BLUR_PREFIXES
                    or prefix in LOGO_PREFIXES or prefix in MASK_PREFIXES):
                is_clickable = True
        self.setCursor(Qt.PointingHandCursor if is_clickable else Qt.ArrowCursor)

    def leaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def _track_index_at(self, y: float) -> int:
        # Add the timeline's vertical scroll offset so the click
        # position is converted to the un-scrolled label space.
        scroll_y = 0
        if self._timeline_widget is not None:
            try:
                sb = self._timeline_widget.verticalScrollBar()
                if sb is not None:
                    scroll_y = int(sb.value())
            except Exception:
                pass
        yp = (y + scroll_y) - self.RULER_HEIGHT
        if yp < 0:
            return -1
        for i, h in enumerate(self._track_heights):
            if yp < h:
                return i
            yp -= h
        return -1

    def _label_lines(self, name: str, max_text_w: int, fm: QFontMetrics) -> list[str]:
        """Split the track label into lines that fit the available width.

        Strategy:
        - Keep the prefix token (V1, A1, A2, S1, B1) on the first line.
        - Remaining text is word-wrapped to fit the column.
        - If everything still fits on one line, no split is done.
        """
        parts = (name or "").split(" ", 1)
        prefix = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        if not rest:
            return [prefix]

        words = rest.split(" ")
        line1 = prefix
        first_line_words: list[str] = []
        for w in words:
            candidate = (line1 + " " + w).strip()
            if fm.horizontalAdvance(candidate) <= max_text_w:
                line1 = candidate
                first_line_words.append(w)
            else:
                break
        if not first_line_words:
            # First word after prefix alone is too wide; put it on line 2.
            first_line_words = []
            line1 = prefix
        remaining_words = words[len(first_line_words):]
        if not remaining_words:
            return [line1]

        # Word-wrap the remaining text.
        lines: list[str] = [line1]
        current = ""
        for w in remaining_words:
            candidate = (current + " " + w).strip() if current else w
            if fm.horizontalAdvance(candidate) <= max_text_w:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        return lines

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Apply the timeline's vertical scroll offset so the labels
        # scroll in sync with the layer content (stays aligned).
        scroll_y = 0
        if self._timeline_widget is not None:
            try:
                sb = self._timeline_widget.verticalScrollBar()
                if sb is not None:
                    scroll_y = int(sb.value())
            except Exception:
                pass

        y = self.RULER_HEIGHT - scroll_y

        # Use the timeline's live track heights so the labels expand
        # or shrink with the layer count.
        track_heights = self._get_track_heights()

        def _icon(name: str) -> str:
            prefix = name.split(" ")[0] if name else ""
            return TRACK_ICONS.get(prefix, "?")

        def _color(name: str) -> QColor:
            prefix = name.split(" ")[0] if name else ""
            palette = {"V1": QColor("#2a6bcf"), "B1": QColor("#6b5b7b"),
                       "A1": QColor("#2a9d3f"), "A2": QColor("#2a9d3f"),
                       "S1": QColor("#c96b2a"),
                       "M1": QColor("#8c5a2a")}
            return palette.get(prefix, QColor("#6b8cb8"))

        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)
        # Reserve space on the right for mute/lock icons on audio tracks.
        icon_col_w = 24
        text_x = 8
        text_w = self.TRACK_HEADER_W - text_x - icon_col_w - 4

        for i, name in enumerate(self._track_names):
            h = track_heights[i] if i < len(track_heights) else 60
            icon = _icon(name)
            c = _color(name)
            muted = self._track_muted[i] if i < len(self._track_muted) else False
            blur_on = self._track_blur_on[i] if i < len(self._track_blur_on) else False
            prefix = name.split(" ")[0] if name else ""

            logo_hidden = (prefix in LOGO_PREFIXES
                           and i < len(self._track_logo_shown)
                           and not self._track_logo_shown[i])
            mask_hidden = (prefix in MASK_PREFIXES
                           and i < len(self._track_mask_shown)
                           and not self._track_mask_shown[i])
            if muted or logo_hidden or mask_hidden:
                bg = QColor("#1a1a2e")
            elif prefix in BLUR_PREFIXES and not blur_on:
                bg = QColor("#1a1a2e")  # dimmed when blur is off
            else:
                bg = QColor("#142030")
            painter.fillRect(0, y, self.TRACK_HEADER_W, h, bg)
            painter.setPen(QPen(QColor("#1e2d42"), 1))
            painter.drawRect(0, y, self.TRACK_HEADER_W - 1, h - 1)

            painter.setPen(QPen(c, 0))
            painter.fillRect(0, y, 3, h, c)

            dim_text = (muted or logo_hidden or mask_hidden
                        or (prefix in BLUR_PREFIXES and not blur_on))
            text_color = QColor("#555") if dim_text else QColor("#ffffff")
            painter.setPen(text_color)
            lines = self._label_lines(name, text_w, fm)
            if not lines:
                lines = [name or ""]
            line_h = fm.height()
            total_h = line_h * len(lines)
            start_y = y + max(2, (h - total_h) // 2)
            for li, line in enumerate(lines):
                display = f"{icon} {line}" if li == 0 else line
                painter.drawText(text_x, start_y + li * line_h,
                                 text_w, line_h,
                                 Qt.AlignLeft | Qt.AlignVCenter, display)

            # (ON/OFF label removed - blur state is shown by track dimming)

            # Lock indicator for locked tracks
            if i < len(self._track_locked) and self._track_locked[i]:
                painter.setPen(QPen(QColor("#e04040"), 0))
                painter.drawText(self.TRACK_HEADER_W - 24, y + 4, 20, h - 8,
                                 Qt.AlignRight | Qt.AlignVCenter, "\U0001f512")

            y += h

        painter.end()
