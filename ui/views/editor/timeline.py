import os
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView


from app.layers.base import BaseLayer, LayerType
from app.layers.timeline import Timeline, Track, Clip


class EditorTimeline(QGraphicsView):
    """Dynamic multi-track timeline for layer-based video editing."""

    seekRequested = Signal(float)
    seekRequestedMs = Signal(int)
    layerSelected = Signal(str)
    layerMoved = Signal(str, float, float)
    playheadMoved = Signal(float)
    segmentSelected = Signal(int)
    segmentTimingChanged = Signal(int, float, float)
    segmentTimingEditStarted = Signal(int, float, float)
    zoomChanged = Signal(int)
    layoutChanged = Signal()
    addLayerRequested = Signal()

    RULER_HEIGHT = 30
    TRACK_HEADER_W = 0
    TRACK_LABEL_H = 24
    TRACK_MIN_H = 40
    TRACK_DEFAULT_H = 80
    CHROME_H = 24
    HANDLE_W = 8
    MIN_DUR = 0.1
    SNAP_THRESHOLD = 0.05
    DEFAULT_PPS = 100
    MIN_PPS = 30
    MAX_PPS = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background-color: #0d1220; border: none;")
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.pixels_per_second = self.DEFAULT_PPS
        self._duration = 10.0
        self._playhead = 0.0
        self._playing = False
        self._timeline: Timeline | None = None
        self._track_heights: dict[str, int] = {}
        self._drag_state = None
        self._hover_layer_id: str = ""
        self._selected_layer_id: str = ""
        self._segment_indices: dict[str, int] = {}
        self._has_add_btn = False

        self._init_default_tracks()

        self.horizontalScrollBar().setStyleSheet(
            "QScrollBar:horizontal{border:none;background:#142030;height:12px;margin:0}"
            "QScrollBar::handle:horizontal{background:#35506f;min-width:30px;border-radius:6px}"
            "QScrollBar::handle:horizontal:hover{background:#416287}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0}"
        )
        self.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical{border:none;background:#142030;width:12px;margin:0}"
            "QScrollBar::handle:vertical{background:#35506f;min-height:30px;border-radius:6px}"
            "QScrollBar::handle:vertical:hover{background:#416287}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0}"
        )

    def _init_default_tracks(self) -> None:
        self._timeline = Timeline(duration=self._duration)
        self._timeline.tracks = [
            Track(name="V1 Original Video", type=LayerType.VIDEO, height=80),
            Track(name="A1 Original Audio", type=LayerType.AUDIO, height=80),
        ]
        for t in self._timeline.tracks:
            self._track_heights[t.id] = t.height
        self._redraw()

    # ---- Legacy API (drop-in replacement for existing TimelineWidget) ----

    def set_segments(self, segments: list) -> None:
        from app.layers.sync_bridge import sync_segments_to_subtitle_layers
        if not self._timeline:
            self._init_default_tracks()

        seg_dicts = []
        for seg in segments:
            d = seg if isinstance(seg, dict) else (seg.to_dict() if hasattr(seg, "to_dict") else {})
            seg_dicts.append(d)

        sync_segments_to_subtitle_layers(self._timeline, seg_dicts)

        # Register any new tracks in _track_heights
        for t in self._timeline.tracks:
            if t.id not in self._track_heights:
                self._track_heights[t.id] = t.height or self.TRACK_DEFAULT_H

        self._segment_indices.clear()
        for t in self._timeline.tracks:
            if t.type == LayerType.SUBTITLE:
                for layer in t.layers:
                    # Prefer the original segment index stored in metadata
                    # (set by sync_segments_to_subtitle_layers). Falls back
                    # to z_index for layers created without metadata.
                    seg_idx = None
                    if isinstance(layer.metadata, dict):
                        raw = layer.metadata.get("_seg_index")
                        if raw is not None:
                            try:
                                seg_idx = int(raw)
                            except (TypeError, ValueError):
                                seg_idx = None
                    if seg_idx is None:
                        seg_idx = int(getattr(layer, "z_index", 0) or 0)
                    self._segment_indices[layer.id] = seg_idx

        end_times = [float(d.get("end", 0)) for d in seg_dicts]
        if end_times:
            self._duration = max(self._duration, max(end_times))

        self._ensure_tracks_populated()
        self._redraw()

    def _ensure_tracks_populated(self):
        if not self._timeline:
            return
        from app.layers.audio import AudioLayer
        from app.layers.video import VideoLayer
        from app.layers.transform import Transform

        v1 = a1 = None
        for t in self._timeline.tracks:
            if t.name == "V1 Original Video":
                v1 = t
            elif t.name == "A1 Original Audio":
                a1 = t

        max_dur = self._duration
        for t in self._timeline.tracks:
            for l in t.layers:
                max_dur = max(max_dur, l.end)
        self._duration = max_dur

        if v1 and not v1.layers:
            v1.layers.append(VideoLayer(
                name="V1 Original Video", source="",
                start=0.0, end=max_dur,
                transform=Transform(x=0, y=0, scale_x=1.0, scale_y=1.0),
            ))
        elif v1 and v1.layers:
            for l in v1.layers:
                if max_dur > l.end:
                    l.end = max_dur

        if a1 and not a1.layers:
            a1.layers.append(AudioLayer(
                name="A1 Original Audio",
                source="",
                start=0.0, end=max_dur,
                volume=1.0,
            ))
        elif a1 and a1.layers:
            for l in a1.layers:
                if max_dur > l.end:
                    l.end = max_dur

    def set_duration_ms(self, ms: int) -> None:
        self._duration = max(0, ms / 1000.0)
        self._redraw()

    set_duration = set_duration_ms

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.viewport().update()

    def set_active_segment_index(self, index: int) -> None:
        if not self._timeline:
            return
        # Do not override a user-selected non-subtitle layer. The auto-select
        # is only meant to highlight the currently playing subtitle. If the
        # user has selected an audio/video/blur layer, leave it alone.
        current_id = str(self._selected_layer_id or "")
        if current_id:
            current_track = None
            for t in self._timeline.tracks:
                for l in t.layers:
                    if l.id == current_id:
                        current_track = t
                        break
                if current_track is not None:
                    break
            # If the previously selected layer no longer exists in the
            # timeline (e.g. a stale BlurLayer from a previous project),
            # clear the selection so the auto-select can proceed and the
            # inspector shows the correct card.
            if current_track is None:
                self._selected_layer_id = ""
            elif current_track.type != LayerType.SUBTITLE:
                return
        for lid, idx in self._segment_indices.items():
            if idx == index:
                self._selected_layer_id = lid
                self.viewport().update()
                return

    def set_waveform_data(self, samples: list, duration_s: float) -> None:
        pass

    def set_video_thumbnails(self, thumbnails: list) -> None:
        pass

    def set_video_source(self, path: str, duration_s: float) -> None:
        from app.layers.sync_bridge import ensure_v1_a1_tracks
        if not self._timeline:
            self._init_default_tracks()
        if duration_s <= 0:
            duration_s = self._probe_video_duration(path)
        if duration_s > 0:
            ensure_v1_a1_tracks(self._timeline, path, duration_s)
            self._duration = max(self._duration, duration_s)
        self._redraw()

    @staticmethod
    def _probe_video_duration(path: str) -> float:
        try:
            import subprocess
            from app.video_processor import _ffprobe_path
            ffprobe = _ffprobe_path()
            if not os.path.exists(ffprobe):
                return 0.0
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return float(result.stdout.strip() or 0)
        except Exception:
            pass
        return 0.0

    @property
    def duration(self) -> int:
        return int(self._duration * 1000)

    def enable_add_layer_button(self) -> None:
        self._has_add_btn = True

    def sync_blur_regions(self, blur_regions: list[dict] | None) -> None:
        from app.layers.sync_bridge import sync_blur_regions_to_layers
        if not self._timeline:
            self._init_default_tracks()
        sync_blur_regions_to_layers(self._timeline, blur_regions)
        self._redraw()

    def sync_tts_track(self, voice_track_path: str, duration: float = 0.0, segments: list | None = None) -> None:
        from app.layers.sync_bridge import sync_tts_to_audio_layers
        if not self._timeline:
            self._init_default_tracks()
        dur = duration if duration > 0 else self._duration
        sync_tts_to_audio_layers(self._timeline, voice_track_path, 0.0, dur, segments=segments)
        # Register track height
        for t in self._timeline.tracks:
            if t.id not in self._track_heights:
                self._track_heights[t.id] = t.height or self.TRACK_DEFAULT_H
        self._redraw()

    # ---- End legacy API ----

    def set_playhead(self, seconds: float) -> None:
        self._playhead = seconds
        viewport = self.viewport()
        if viewport:
            viewport.update()
        self.playheadMoved.emit(seconds)

    def set_position(self, ms: int) -> None:
        self.set_playhead(ms / 1000.0)

    def zoom_in(self) -> None:
        self.pixels_per_second = min(self.MAX_PPS, int(self.pixels_per_second * 1.25))
        self._redraw()

    def zoom_out(self) -> None:
        self.pixels_per_second = max(self.MIN_PPS, int(self.pixels_per_second * 0.8))
        self._redraw()

    def fit_timeline(self) -> None:
        if self._duration > 0:
            w = self.viewport().width() - self.TRACK_HEADER_W - 20 if self.viewport() else 800
            self.pixels_per_second = int(max(self.MIN_PPS, w / self._duration))
        self._redraw()
        self.zoomChanged.emit(int(self.pixels_per_second / self.DEFAULT_PPS * 100))

    def reset_zoom(self) -> None:
        self.pixels_per_second = self.DEFAULT_PPS
        self._redraw()
        self.zoomChanged.emit(100)

    def zoom_percent(self) -> int:
        return int(self.pixels_per_second / self.DEFAULT_PPS * 100)

    def select_layer(self, layer_id: str) -> None:
        self._selected_layer_id = layer_id
        self.viewport().update()

    def _redraw(self) -> None:
        if not self._timeline:
            return
        tl = self._timeline
        tracks = [t for t in tl.tracks if t.visible]
        total_h = self.RULER_HEIGHT + sum(
            self._track_heights.get(t.id, self.TRACK_DEFAULT_H) for t in tracks
        )
        scene_w = self.TRACK_HEADER_W + max(self._duration * self.pixels_per_second + 200, 800)
        self._scene.setSceneRect(0, 0, scene_w, total_h)
        self.layoutChanged.emit()
        self.viewport().update()

    def _compute_duration(self, timeline: Timeline) -> float:
        dur = 0.0
        for track in timeline.tracks:
            for layer in track.layers:
                dur = max(dur, layer.end)
        return max(dur, 10.0)

    def _rebuild_track_heights(self) -> None:
        if not self._timeline:
            return
        for track in self._timeline.tracks:
            if track.id not in self._track_heights:
                self._track_heights[track.id] = track.height or self.TRACK_DEFAULT_H

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._timeline:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)

        tracks = [t for t in self._timeline.tracks if t.visible]
        scroll_x = self.horizontalScrollBar().value()
        view_w = self.viewport().width()

        y = 0

        self._draw_ruler_sticky(painter, scroll_x, view_w)
        y = self.RULER_HEIGHT

        for track in tracks:
            th = self._track_heights.get(track.id, self.TRACK_DEFAULT_H)
            self._draw_track_body(painter, track, scroll_x, y, th)
            self._draw_track_layers(painter, track, scroll_x, y, th)
            y += th

        self._draw_playhead(painter, scroll_x)

        painter.end()

    def _draw_ruler_sticky(self, painter: QPainter, scroll_x: int, view_w: int) -> None:
        painter.fillRect(0, 0, view_w, self.RULER_HEIGHT, QColor("#0a0f1a"))
        painter.setPen(QColor("#35506f"))
        painter.drawLine(0, self.RULER_HEIGHT - 1, view_w, self.RULER_HEIGHT - 1)

        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        major_interval = self._tick_interval()

        t = 0.0
        while t <= self._duration + 5:
            x = int(t * self.pixels_per_second) - scroll_x
            if x > view_w:
                break
            if x > -10:
                if int(t) % int(max(major_interval, 1)) < 0.5:
                    painter.setPen(QColor("#35506f"))
                    painter.drawLine(x, self.RULER_HEIGHT - 10, x, self.RULER_HEIGHT)
                    ts = f"{int(t // 60)}:{int(t % 60):02d}"
                    painter.setPen(QColor("#6b8cb8"))
                    painter.drawText(int(x) + 2, 16, ts)
                else:
                    painter.setPen(QColor("#1e2d42"))
                    painter.drawLine(x, self.RULER_HEIGHT - 5, x, self.RULER_HEIGHT)
            t += 1.0

    def _draw_track_header(self, painter: QPainter, track: Track,
                           y: int, h: int) -> None:
        header_rect = QRectF(0, y, self.TRACK_HEADER_W, h)
        painter.fillRect(header_rect, QColor("#142030"))
        painter.setPen(QColor("#1e2d42"))
        painter.drawRect(header_rect)

        font = QFont("Segoe UI", 9, QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#6b8cb8"))
        icon = {"video": "\u25b6", "audio": "\u266b", "subtitle": "T",
                "text": "Aa", "image": "\u25a3", "sticker": "\u2605",
                "blur": "\u25a3"}
        label = f"  {icon.get(track.type.value, '?')} {track.name or track.type.value.title()}"
        painter.drawText(QRectF(4, y + 4, self.TRACK_HEADER_W - 8, self.TRACK_LABEL_H),
                         Qt.AlignLeft, label)

        if track.locked:
            painter.setPen(QColor("#e04040"))
            painter.drawText(QRectF(self.TRACK_HEADER_W - 24, y + 4, 20, self.TRACK_LABEL_H),
                             Qt.AlignRight, "\U0001f512")

    def _draw_track_body(self, painter: QPainter, track: Track,
                         scroll_x: int, y: int, h: int) -> None:
        view_w = self.viewport().width()
        body_rect = QRectF(0, y, view_w, h)
        painter.fillRect(body_rect, QColor("#0a0f1a"))
        painter.setPen(QColor("#1e2d42"))
        painter.drawRect(body_rect)

        painter.setPen(QColor("#1e2d42"))
        for i in range(1, int(self._duration) + 1):
            x = int(i * self.pixels_per_second) - scroll_x
            if x > view_w:
                break
            if x > 0:
                painter.drawLine(x, y, x, y + h)

    def _tick_interval(self) -> int:
        if self.pixels_per_second < 40:
            return 10
        if self.pixels_per_second < 80:
            return 5
        if self.pixels_per_second < 150:
            return 2
        return 1

    def _draw_track_layers(self, painter: QPainter, track: Track,
                           scroll_x: int, y: int, h: int) -> None:
        margin = 4
        bar_h = h - margin * 2
        view_w = self.viewport().width()

        for layer in track.layers:
            if not layer.visible:
                continue
            x = int(layer.start * self.pixels_per_second) - scroll_x
            w = max(int(layer.duration * self.pixels_per_second), 20)
            bar_y = y + margin

            clip_x = max(x, 0)
            clip_w = min(x + w, view_w) - clip_x
            if clip_w <= 0:
                continue

            is_selected = layer.id == self._selected_layer_id

            if layer.type == LayerType.BLUR:
                self._draw_blur_layer_bar(painter, layer, x, bar_y, w, bar_h, is_selected)
            else:
                self._draw_standard_layer_bar(painter, layer, x, bar_y, w, bar_h, view_w, is_selected)

    def _draw_standard_layer_bar(self, painter, layer, x, y, w, h, view_w, is_selected):
        color = self._layer_color(layer.type)
        if is_selected:
            color = color.lighter(130)

        rect = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.fillPath(path, color)
        painter.setPen(QPen(color.darker(140), 1))
        painter.drawPath(path)

        if w > 40:
            painter.setPen(QColor("#ffffff"))
            font = QFont("Segoe UI", 8)
            painter.setFont(font)
            label = layer.name or layer.type.value.title()
            short_label = os.path.basename(label) if os.path.sep in label else label
            text_rect = QRectF(x + 4, y, min(w - 8, view_w - x - 4), h)
            elided = painter.fontMetrics().elidedText(short_label, Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        if is_selected:
            painter.setPen(QPen(QColor("#4a8cff"), 2))
            painter.drawPath(path)

    def _draw_blur_layer_bar(self, painter, layer, x, y, w, h, is_selected):
        color = QColor("#6b5b7b")
        if is_selected:
            color = color.lighter(130)

        # Stack multiple BlurLayers vertically inside the same track so
        # the user can see every region instead of only the topmost one.
        try:
            z = int(getattr(layer, "z_index", 0) or 0)
        except (TypeError, ValueError):
            z = 0
        row_h = 14
        max_rows = max(1, (h - 4) // row_h)
        row = min(z, max_rows - 1)
        y_offset = 2 + row * row_h
        sub_h = max(8, row_h - 4)
        sub_y = y + y_offset
        rect = QRectF(x, sub_y, w, sub_h)
        painter.fillRect(rect, QColor(color.red(), color.green(), color.blue(), 60))
        pen = QPen(QColor("#9b8bae"), 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        painter.setPen(QColor("#b8a8c8"))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        label = layer.name or "Blur"
        painter.drawText(QRectF(x + 4, sub_y, max(w - 8, 0), sub_h),
                         Qt.AlignVCenter | Qt.AlignLeft, label)

        if is_selected:
            painter.setPen(QPen(QColor("#4a8cff"), 2, Qt.DashLine))
            painter.drawRect(rect)

    @staticmethod
    def _layer_color(layer_type: LayerType) -> QColor:
        colors = {
            LayerType.VIDEO: QColor("#2a6bcf"),
            LayerType.AUDIO: QColor("#2a9d3f"),
            LayerType.SUBTITLE: QColor("#c96b2a"),
            LayerType.TEXT: QColor("#9b4dca"),
            LayerType.IMAGE: QColor("#2a9baa"),
            LayerType.STICKER: QColor("#d4a028"),
            LayerType.BLUR: QColor("#6b5b7b"),
        }
        return colors.get(layer_type, QColor("#4a5568"))

    def _draw_playhead(self, painter: QPainter, scroll_x: int) -> None:
        x = self.TRACK_HEADER_W + int(self._playhead * self.pixels_per_second) - scroll_x
        if x < 0 or x > self.viewport().width():
            return
        painter.setPen(QPen(QColor("#e04040"), 2))
        painter.drawLine(int(x), 0, int(x), int(self._scene.height()))
        painter.setBrush(QColor("#e04040"))
        painter.setPen(Qt.NoPen)
        triangle = [QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 8)]
        painter.drawPolygon(triangle)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            scroll_x = self.horizontalScrollBar().value()
            in_ruler = pos.y() < self.RULER_HEIGHT
            if in_ruler:
                t = self._pos_to_time(pos.x(), scroll_x)
                if t >= 0:
                    self.set_playhead(t)
                    self.seekRequested.emit(t)
                    self.seekRequestedMs.emit(int(t * 1000))

            clicked_layer = self._hit_test_layer(pos, scroll_x)
            if clicked_layer:
                self._selected_layer_id = clicked_layer
                self.layerSelected.emit(clicked_layer)
                idx = self._segment_indices.get(clicked_layer, -1)
                if idx >= 0:
                    self.segmentSelected.emit(idx)
                self.viewport().update()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            pos = event.position()
            # Only scrub the playhead while the user drags inside the
            # ruler. Dragging on a track body should not move the
            # playhead - that is reserved for layer selection/edits.
            if pos.y() < self.RULER_HEIGHT:
                scroll_x = self.horizontalScrollBar().value()
                t = self._pos_to_time(pos.x(), scroll_x)
                if t >= 0:
                    self.set_playhead(t)
                    self.seekRequested.emit(t)
                    self.seekRequestedMs.emit(int(t * 1000))
        super().mouseMoveEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
        else:
            super().wheelEvent(event)

    def _pos_to_time(self, x: float, scroll_x: int) -> float:
        t = (x + scroll_x - self.TRACK_HEADER_W) / self.pixels_per_second
        return max(0.0, min(t, self._duration))

    def _hit_test_layer(self, pos, scroll_x: int) -> str:
        if not self._timeline:
            return ""
        y = self.RULER_HEIGHT
        for track in self._timeline.tracks:
            if not track.visible:
                continue
            th = self._track_heights.get(track.id, self.TRACK_DEFAULT_H)
            if y <= pos.y() <= y + th:
                # Iterate in REVERSE so the topmost stacked layer (highest
                # z_index) is selected first. This matches the visual order
                # used by `_draw_blur_layer_bar`.
                row_h = 14
                max_rows = max(1, (th - 4) // row_h)
                layers = list(track.layers)
                for layer in reversed(layers):
                    if not layer.visible:
                        continue
                    lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                    lw = max(int(layer.duration * self.pixels_per_second), 20)
                    if not (lx - 4 <= pos.x() <= lx + lw + 4):
                        continue
                    # Account for the vertical stacking in the B1 Blur
                    # track so clicks on a specific row select the right
                    # layer.
                    try:
                        z = int(getattr(layer, "z_index", 0) or 0)
                    except (TypeError, ValueError):
                        z = 0
                    row = min(z, max_rows - 1)
                    y_offset = 2 + row * row_h
                    sub_y = y + y_offset
                    sub_h = max(8, row_h - 4)
                    if sub_y <= pos.y() <= sub_y + sub_h:
                        return layer.id
                # Fallback: any layer in the x range
                for layer in layers:
                    if not layer.visible:
                        continue
                    lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                    lw = max(int(layer.duration * self.pixels_per_second), 20)
                    if lx - 4 <= pos.x() <= lx + lw + 4:
                        return layer.id
            y += th
        return ""
