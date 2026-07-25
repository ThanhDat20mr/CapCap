import os
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView


from app.layers.base import BaseLayer, LayerType
from app.layers.timeline import Timeline, Track, Clip
from app.layers.dub_subtitle import DubSubtitleLayer


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
    TRACK_MIN_H = 32
    TRACK_DEFAULT_H = 56
    REGION_TRACK_ROW_H = 60
    CHILD_TRACK_H = 48
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
        # Presentation-only track hiding. Never write this to Track.visible:
        # preview and export must continue using the real project visibility.
        self._timeline_hidden_track_ids: set[str] = set()
        self._segment_indices: dict[str, int] = {}
        self._has_add_btn = False
        self._voice_sync_mode: str = "Smart"

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
            Track(name="V1 Video", type=LayerType.VIDEO, height=80),
            Track(name="A1 Audio", type=LayerType.AUDIO, height=80),
        ]
        for t in self._timeline.tracks:
            self._track_heights[t.id] = t.height
        self._redraw()

    def is_track_shown_on_timeline(self, track) -> bool:
        return bool(getattr(track, "visible", True) and track.id not in self._timeline_hidden_track_ids)

    def set_track_shown_on_timeline(self, track_id: str, shown: bool) -> None:
        track_id = str(track_id or "")
        if not track_id:
            return
        if shown:
            self._timeline_hidden_track_ids.discard(track_id)
        else:
            self._timeline_hidden_track_ids.add(track_id)
            if self._selected_layer_id:
                track, _layer = self._find_layer_by_id(self._selected_layer_id)
                if track is not None and track.id == track_id:
                    self._selected_layer_id = ""
        self._redraw()

    # ---- Legacy API (drop-in replacement for existing TimelineWidget) ----

    def set_segments(self, segments: list) -> None:
        from app.layers.sync_bridge import sync_segments_to_dub_subtitle_layers
        if not self._timeline:
            self._init_default_tracks()

        seg_dicts = []
        for seg in segments:
            d = seg if isinstance(seg, dict) else (seg.to_dict() if hasattr(seg, "to_dict") else {})
            seg_dicts.append(d)

        sync_segments_to_dub_subtitle_layers(self._timeline, seg_dicts)

        # Register any new tracks in _track_heights (height adapts
        # to the number of layers in the track).
        for t in self._timeline.tracks:
            if t.id not in self._track_heights:
                self._track_heights[t.id] = self._compute_track_height(t)

        self._segment_indices.clear()
        for t in self._timeline.tracks:
            if t.type == LayerType.DUB_SUBTITLE:
                for layer in t.layers:
                    # Prefer the original segment index stored in metadata
                    # (set by sync_segments_to_dub_subtitle_layers). Falls
                    # back to z_index for layers created without metadata.
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
            if t.name == "V1 Video":
                v1 = t
            elif t.name == "A1 Audio":
                a1 = t

        max_dur = self._duration
        for t in self._timeline.tracks:
            for l in t.layers:
                max_dur = max(max_dur, l.end)
        self._duration = max_dur

        if v1 and not v1.layers:
            v1.layers.append(VideoLayer(
                name="V1 Video", source="",
                start=0.0, end=max_dur,
                transform=Transform(x=0, y=0, scale_x=1.0, scale_y=1.0),
            ))
        elif v1 and v1.layers:
            for l in v1.layers:
                if max_dur > l.end:
                    l.end = max_dur

        if a1 and not a1.layers:
            a1.layers.append(AudioLayer(
                name="A1 Audio",
                source="",
                start=0.0, end=max_dur,
                volume=1.0,
            ))
        elif a1 and a1.layers:
            for l in a1.layers:
                if max_dur > l.end:
                    l.end = max_dur

    def set_duration_ms(self, ms: int) -> None:
        new_dur = max(0, ms / 1000.0)
        old_dur = self._duration
        self._duration = new_dur
        # The underlying Timeline model's `duration` is read by code that
        # creates full-video-spanning layers (e.g. MaskLayer end fallback).
        # Without this, the Mask track only spans the default 10s and not
        # the actual video length (Bug 1). Also re-span any Mask track
        # layers that were created before the real duration was known
        # (e.g. restored from project state) so they cover the whole video.
        if self._timeline is not None:
            self._timeline.duration = new_dur
            if new_dur > old_dur:
                for t in self._timeline.tracks:
                    if t.type != LayerType.MASK:
                        continue
                    for layer in t.layers:
                        try:
                            prev_end = float(layer.end)
                        except Exception:
                            prev_end = 0.0
                        # Only extend layers that were spanning the full
                        # previous duration (or had no end set yet), so we
                        # don't clobber a user-trimmed mask clip.
                        if prev_end <= 0 or abs(prev_end - old_dur) < 0.05:
                            layer.end = new_dur
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
            elif current_track.type not in (
                LayerType.SUBTITLE,
                LayerType.DUB_SUBTITLE,
            ):
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
            # Keep the Timeline model's duration in sync so layers that
            # span the whole video (Mask track) use the real length.
            self._timeline.duration = self._duration
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
        from app.layers.sync_bridge import sync_tts_to_dub_subtitle_layers
        if not self._timeline:
            self._init_default_tracks()
        sync_tts_to_dub_subtitle_layers(
            self._timeline, voice_track_path, segments=segments
        )
        # Register track height (adapts to the number of layers)
        for t in self._timeline.tracks:
            if t.id not in self._track_heights:
                self._track_heights[t.id] = self._compute_track_height(t)
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

    def set_voice_sync_mode(self, mode: str) -> None:
        """Update the active voice-timing sync mode and re-stack the
        tracks. Timeline Priority disables row stacking because the
        audio is always cut to the segment window.
        """
        mode_key = (mode or "").strip()
        if mode_key == self._voice_sync_mode:
            return
        self._voice_sync_mode = mode_key
        self._redraw()

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
        tracks = [t for t in tl.tracks if self.is_track_shown_on_timeline(t)]
        # Recompute each track's height based on its layer count so
        # tracks with more layers (e.g. multiple blur regions) expand.
        for t in tracks:
            self._track_heights[t.id] = self._compute_track_height(t)
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
            self._track_heights[track.id] = self._compute_track_height(track)

    def _compute_track_height(self, track) -> int:
        """Compute a track's height. Region tracks (Blur, Logo, Mask)
        allocate one full base slot per visible layer. Subtitle and dub tracks (overlap-stacked)
        use the same CHILD_TRACK_H slot for every row — primary and
        overlap-child rows are equally small — so the whole track stays
        compact.
        """
        base = int(getattr(track, "height", None) or self.TRACK_DEFAULT_H)
        if self._uses_layer_rows(track):
            num_layers = max(1, len([l for l in track.layers if l.visible]))
            # B1, L1, and M1 intentionally share the same compact row
            # size. Older B1 projects may carry a 100px track height.
            return self.REGION_TRACK_ROW_H * num_layers
        if self._should_overlap_stack(track):
            visible = [l for l in track.layers if l.visible]
            # Sort by start time for proper overlap detection
            visible_sorted = sorted(visible, key=lambda l: float(getattr(l, "start", 0.0)))
            _, num_rows = self._compute_overlap_rows(visible_sorted)
            return self.CHILD_TRACK_H * max(1, num_rows)
        return base

    @staticmethod
    def _is_blur_track(track) -> bool:
        name = (track.name or "").lower()
        prefix = name.split(" ")[0] if name else ""
        if prefix == "b1":
            return True
        return any(getattr(l, "type", None) == LayerType.BLUR
                   for l in getattr(track, "layers", []))

    @classmethod
    def _uses_layer_rows(cls, track) -> bool:
        """Whether every visible layer receives its own vertical row.

        B1 has always worked this way. L1, M1, and T1 layers commonly span the
        full video too, so without the same layout the last painted clip
        hides every earlier logo/mask layer and they cannot be selected.
        """
        if cls._is_blur_track(track):
            return True
        name = (getattr(track, "name", "") or "").lower()
        prefix = name.split(" ")[0] if name else ""
        if prefix in ("l1", "m1", "t1"):
            return True
        return any(
            getattr(layer, "type", None) in (LayerType.MASK, LayerType.TEXT)
            for layer in getattr(track, "layers", [])
        )

    @staticmethod
    def _is_subtitle_track(track) -> bool:
        track_type = getattr(track, "type", None)
        if track_type in (LayerType.SUBTITLE, LayerType.DUB_SUBTITLE):
            return True
        return any(
            getattr(l, "type", None) in (LayerType.SUBTITLE, LayerType.DUB_SUBTITLE)
            for l in getattr(track, "layers", [])
        )

    @staticmethod
    def _is_dub_track(track) -> bool:
        # Legacy A2 Dub name prefix kept for projects that still have
        # a separate audio track from the old two-track layout.
        name = (track.name or "").lower()
        prefix = name.split(" ")[0] if name else ""
        if prefix == "a2":
            return True
        return False

    def _should_overlap_stack(self, track) -> bool:
        """True for tracks whose overlapping layers should stack vertically
        inside the same track. The new TS1 DubSubtitle layout inherits
        the stacking; legacy A2 Dub still does.

        In Timeline Priority mode the audio is always cut to the
        segment window, so no two layers can overlap in audio time.
        Stacking is disabled and the track collapses to a single row.
        """
        is_subtitle = self._is_subtitle_track(track)
        if is_subtitle:
            sync_mode = (self._voice_sync_mode or "").strip().lower()
            if sync_mode == "timeline priority":
                return False
        return is_subtitle or self._is_dub_track(track)

    @staticmethod
    def _compute_overlap_rows(visible_layers):
        """Greedy overlap-aware row assignment.

        Returns (layer_rows, num_rows) where layer_rows is a list of
        row indices (0-based) in the same order as visible_layers.
        A new row is started only when a layer overlaps with every
        existing row's last segment. Used for subtitle tracks so
        overlapping Sub N layers stack vertically inside the same TS1
        track, mirroring how Blur 1 and Blur 2 stack inside B1.

        Overlap detection uses `_audio_end` from layer metadata when
        present (the actual TTS audio length), so a layer whose
        generated voice bleeds past its segment end still triggers
        row stacking. The bar itself is drawn from layer.start to
        layer.end — only the overlap comparison sees the audio end.
        """
        rows: list[float] = []
        layer_rows: list[int] = []
        for layer in visible_layers:
            try:
                start = float(getattr(layer, "start", 0.0))
                end = float(getattr(layer, "end", 0.0))
            except (TypeError, ValueError):
                start = end = 0.0
            audio_end = end
            meta = getattr(layer, "metadata", None) or {}
            if isinstance(meta, dict):
                raw = meta.get("_audio_end")
                if raw is not None:
                    try:
                        audio_end = max(end, float(raw))
                    except (TypeError, ValueError):
                        audio_end = end
            row_index = 0
            for r_idx, last_end in enumerate(rows):
                if last_end <= start:
                    row_index = r_idx
                    break
            else:
                row_index = len(rows)
                rows.append(audio_end)
            if row_index < len(rows):
                rows[row_index] = max(rows[row_index], audio_end)
            layer_rows.append(row_index)
        return layer_rows, len(rows)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._timeline:
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)

        tracks = [t for t in self._timeline.tracks if self.is_track_shown_on_timeline(t)]
        scroll_x = self.horizontalScrollBar().value()
        # Apply the vertical scroll offset so the tracks scroll within
        # the viewport while the ruler stays sticky at the top.
        scroll_y = self.verticalScrollBar().value()
        view_w = self.viewport().width()

        y = self.RULER_HEIGHT - scroll_y

        for track in tracks:
            th = self._track_heights.get(track.id, self.TRACK_DEFAULT_H)
            self._draw_track_body(painter, track, scroll_x, y, th)
            self._draw_track_layers(painter, track, scroll_x, y, th)
            y += th

        # Playhead spans the full scene height (uses scene coords)
        self._draw_playhead(painter, scroll_x)

        # Draw the sticky ruler LAST so it stays on top of any
        # scrolled tracks that might overlap the ruler area.
        self._draw_ruler_sticky(painter, scroll_x, view_w)

        painter.end()

    def _draw_ruler_sticky(self, painter: QPainter, scroll_x: int, view_w: int, scroll_y: int = 0) -> None:
        # The ruler is sticky at the top of the viewport (scroll_y
        # is accepted for API compatibility but not applied here).
        ruler_y = 0
        painter.fillRect(0, ruler_y, view_w, self.RULER_HEIGHT, QColor("#0a0f1a"))
        painter.setPen(QColor("#35506f"))
        painter.drawLine(0, ruler_y + self.RULER_HEIGHT - 1, view_w, ruler_y + self.RULER_HEIGHT - 1)

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
                    painter.drawLine(x, ruler_y + self.RULER_HEIGHT - 10, x, ruler_y + self.RULER_HEIGHT)
                    ts = f"{int(t // 60)}:{int(t % 60):02d}"
                    painter.setPen(QColor("#6b8cb8"))
                    painter.drawText(int(x) + 2, ruler_y + 16, ts)
                else:
                    painter.setPen(QColor("#1e2d42"))
                    painter.drawLine(x, ruler_y + self.RULER_HEIGHT - 5, x, ruler_y + self.RULER_HEIGHT)
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
        view_w = self.viewport().width()
        uses_layer_rows = self._uses_layer_rows(track)
        overlap_stack = self._should_overlap_stack(track)
        # Force every bar on a subtitle track to share the same orange
        # color, regardless of the layer's runtime class or type. This
        # guarantees the track reads as a single uniform subtitle strip
        # even if a layer was hydrated with the wrong type (e.g. a
        # stale SubtitleLayer rather than a DubSubtitleLayer from an
        # older project file).
        force_subtitle_color = self._is_subtitle_track(track)
        visible_layers = [l for l in track.layers if l.visible]
        if overlap_stack:
            # Sort by start time for proper overlap detection
            visible_layers_sorted = sorted(visible_layers, key=lambda l: float(getattr(l, "start", 0.0)))
            layer_rows, num_rows = self._compute_overlap_rows(visible_layers_sorted)
            num_rows = max(1, num_rows)
            # All rows (primary + overlap-child) share the same small
            # CHILD_TRACK_H height so the whole track stays compact.
            row_slots: list[tuple[int, int]] = []
            cursor = y + margin
            for r in range(num_rows):
                row_slots.append((cursor, self.CHILD_TRACK_H))
                cursor += self.CHILD_TRACK_H
        else:
            num_layers = max(1, len(visible_layers))
            row_h = (h - margin * 2) / num_layers if num_layers > 0 else h
        for row_index, layer in enumerate(track.layers):
            if not layer.visible:
                continue
            x = int(layer.start * self.pixels_per_second) - scroll_x
            w = max(int(layer.duration * self.pixels_per_second), 20)
            if overlap_stack:
                # Look up the row assigned to this layer in the sorted
                # visible list (it was indexed in start-time order by
                # _compute_overlap_rows).
                try:
                    visible_idx = visible_layers_sorted.index(layer)
                    row = layer_rows[visible_idx]
                except ValueError:
                    row = 0
                bar_y, slot_h = row_slots[row]
                bar_h = max(slot_h - margin * 2, 8)
            elif uses_layer_rows:
                visible_count = sum(1 for l in track.layers[:track.layers.index(layer) + 1] if l.visible)
                z = max(0, visible_count - 1)
                z = min(z, num_layers - 1)
                bar_y = y + margin + z * row_h
                bar_h = max(row_h - 2, 8)
            else:
                bar_y = y + margin
                bar_h = h - margin * 2
            clip_x = max(x, 0)
            clip_w = min(x + w, view_w) - clip_x
            if clip_w <= 0:
                continue
            is_selected = layer.id == self._selected_layer_id
            track_name = (getattr(track, "name", "") or "").split(" ")[0]
            is_subtitle_track_name = track_name in ("TS1", "S1")
            if layer.type == LayerType.BLUR:
                self._draw_blur_layer_bar(painter, layer, x, bar_y, w, bar_h, is_selected)
            else:
                self._draw_standard_layer_bar(
                    painter, layer, x, bar_y, w, bar_h, view_w,
                    is_selected, force_subtitle_color=force_subtitle_color,
                    force_subtitle_track=is_subtitle_track_name,
                )

    def _draw_standard_layer_bar(self, painter, layer, x, y, w, h, view_w, is_selected, is_overflow_row: bool = False, force_subtitle_color: bool = False, force_subtitle_track: bool = False):
        # Every subtitle bar (DubSubtitleLayer, SubtitleLayer, or any
        # layer drawn on the TS1 track) uses the exact same fill +
        # border constants so the track reads as one uniform subtitle
        # strip regardless of which row the layer is on or whether
        # it's the currently playing/selected segment. No lighter()
        # or darker() is called on the fill — selection is shown only
        # by an accent border drawn on top.
        # Use type-based check as the primary signal so the fill is
        # uniform even if the layer was hydrated as a plain BaseLayer
        # (whose default type is VIDEO) by an older class map. The
        # isinstance and track-name checks are kept as belt-and-braces
        # for layers that have already been re-instantiated correctly.
        # The dub_text attribute sniff is a final fallback so a
        # pre-existing DubSubtitleLayer whose `type` was clobbered
        # still renders as a subtitle bar.
        layer_type = getattr(layer, "type", None)
        is_subtitle_type = layer_type in (LayerType.SUBTITLE, LayerType.DUB_SUBTITLE)
        has_dub_marker = bool(
            getattr(layer, "dub_text", None) or getattr(layer, "_seg_dict", None)
        )
        if is_subtitle_type or force_subtitle_color or force_subtitle_track or has_dub_marker:
            fill = QColor(201, 107, 42)   # #c96b2a — exact RGB, no derivation
            border = QColor(141, 75, 29)  # #8d4b1d — color.darker(140) baked in
        else:
            fill = self._layer_color(layer.type)
            border = fill.darker(140)

        rect = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.fillPath(path, fill)
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)

        if w > 40:
            painter.setPen(QColor("#ffffff"))
            font = QFont("Segoe UI", 8)
            painter.setFont(font)
            if getattr(layer, "type", None) == LayerType.DUB_SUBTITLE:
                # Default: show dub_text (the voice-spoken text) on the
                # timeline bar so the user sees what the dub voice is
                # actually saying. Fall back to text, then layer name.
                label = (
                    str(getattr(layer, "dub_text", "") or "").strip()
                    or str(getattr(layer, "text", "") or "").strip()
                    or layer.name
                )
            else:
                label = layer.name or layer.type.value.title()
            short_label = os.path.basename(label) if os.path.sep in label else label
            text_rect = QRectF(x + 4, y, min(w - 8, view_w - x - 4), h)
            elided = painter.fontMetrics().elidedText(short_label, Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

            # Audio glyph on DubSubtitleLayer bars that have generated
            # voice audio. Small speaker shape on the right edge of
            # the bar.
            if (
                getattr(layer, "type", None) == LayerType.DUB_SUBTITLE
                and getattr(layer, "audio_path", "")
                and h >= 14
            ):
                # Use a fixed glyph color (no derivation from the bar
                # fill) so the glyph can't make one bar look lighter
                # than another.
                self._draw_audio_glyph(painter, x + w - 14, y + (h - 10) / 2, QColor("#ffffff"))
                # _draw_audio_glyph leaves the brush set to the glyph
                # color (white). Reset it so the next bar's border
                # drawPath doesn't fill that bar white. Without this
                # reset the brush leaks across bars in the same paint
                # event: the first audio-glyph bar turns the next bar
                # white via its border stroke, and the selection
                # drawPath on the clicked bar also fills white over
                # the orange fillPath.
                painter.setBrush(Qt.NoBrush)

        if is_selected:
            painter.setPen(QPen(QColor("#4a8cff"), 2))
            # _draw_audio_glyph above left the brush as glyph_color
            # (white). drawPath() strokes AND fills, so without
            # resetting the brush the selection pass would paint the
            # bar white on top of the orange fillPath from earlier.
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    @staticmethod
    def _draw_audio_glyph(painter, x, y, color):
        """Draw a small speaker glyph at (x, y) to indicate the layer
        has generated voice audio. The colour is lightened to be
        visible on the bar fill.
        """
        from PySide6.QtGui import QColor as _QC
        glyph_color = _QC(
            min(color.red() + 120, 255),
            min(color.green() + 120, 255),
            min(color.blue() + 120, 255),
        )
        painter.setPen(glyph_color)
        painter.setBrush(glyph_color)
        x0 = float(x)
        y0 = float(y)
        h = 10.0
        w_box = 4.0
        # Speaker cone
        speaker = QPainterPath()
        speaker.moveTo(x0, y0 + h * 0.25)
        speaker.lineTo(x0 + w_box, y0 + h * 0.25)
        speaker.lineTo(x0 + w_box + 3, y0)
        speaker.lineTo(x0 + w_box + 3, y0 + h)
        speaker.lineTo(x0 + w_box, y0 + h * 0.75)
        speaker.lineTo(x0, y0 + h * 0.75)
        speaker.closeSubpath()
        painter.drawPath(speaker)
        # Sound waves
        for w_off, w_amp in ((6, 0.35), (8, 0.55), (10, 0.75)):
            wave = QPainterPath()
            wave.moveTo(x0 + w_box + 2 + w_off * 0.3, y0 + h * (0.5 - w_amp * 0.3))
            wave.quadTo(
                x0 + w_box + 2 + w_off,
                y0 + h * 0.5,
                x0 + w_box + 2 + w_off * 0.3,
                y0 + h * (0.5 + w_amp * 0.3),
            )
            painter.drawPath(wave)

    def _draw_blur_layer_bar(self, painter, layer, x, y, w, h, is_selected):
        color = QColor("#6b5b7b")

        # Each child layer fills the full track height (passed as h)
        # so Blur 1 and Blur 2 both span the entire B1 track. The
        # bar is drawn at the given y/h without splitting into rows.
        rect = QRectF(x, y, w, h)
        painter.fillRect(rect, QColor(color.red(), color.green(), color.blue(), 60))
        pen = QPen(QColor("#9b8bae"), 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        painter.setPen(QColor("#b8a8c8"))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        label = layer.name or "Blur"
        painter.drawText(QRectF(x + 4, y, max(w - 8, 0), h),
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
            LayerType.DUB_SUBTITLE: QColor("#c96b2a"),
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

    def _get_effective_layer_end(self, layer) -> float:
        """Get the effective end time for a layer."""
        return float(layer.end)

    def _hit_test_edge(self, pos, scroll_x: int, scroll_y: int = 0):
        """Return ('left'|'right', layer_id) if pos is near a bar edge,
        or ('body', layer_id) if inside the bar, or (None, '')."""
        if not self._timeline:
            return None, ""
        click_y = pos.y() + scroll_y
        y = self.RULER_HEIGHT
        margin = 4
        for track in self._timeline.tracks:
            if not self.is_track_shown_on_timeline(track):
                continue
            th = self._track_heights.get(track.id, self.TRACK_DEFAULT_H)
            if not (y <= click_y <= y + th):
                y += th
                continue
            visible_layers = [l for l in track.layers if l.visible]
            num_layers = max(1, len(visible_layers))
            uses_layer_rows = self._uses_layer_rows(track)
            overlap_stack = self._should_overlap_stack(track)
            layers_in_row = []
            if overlap_stack and num_layers > 1:
                # Sort by start time for proper overlap detection
                visible_layers_sorted = sorted(visible_layers, key=lambda l: float(getattr(l, "start", 0.0)))
                layer_rows, num_rows = self._compute_overlap_rows(visible_layers_sorted)
                row_slots = []
                cursor = y + margin
                for r in range(num_rows):
                    row_slots.append((cursor, self.CHILD_TRACK_H))
                    cursor += self.CHILD_TRACK_H
                row = -1
                for r, (slot_y, slot_h) in enumerate(row_slots):
                    if slot_y <= click_y <= slot_y + slot_h:
                        row = r
                        break
                if row < 0:
                    return None, ""
                for visible_idx, layer in enumerate(visible_layers_sorted):
                    if layer_rows[visible_idx] == row:
                        layers_in_row.append(layer)
            elif uses_layer_rows and num_layers > 1:
                row_h = (th - margin * 2) / num_layers
                rel_y = click_y - y - margin
                row = max(0, min(int(rel_y / row_h), num_layers - 1))
                layers_in_row = [visible_layers[row]]
            else:
                layers_in_row = [layer for layer in track.layers if layer.visible]
            for layer in layers_in_row:
                lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                lw = max(int(layer.duration * self.pixels_per_second), 20)
                if lx - 4 <= pos.x() <= lx + lw + 4:
                    dx = pos.x() - lx
                    if dx <= self.HANDLE_W:
                        return "left", layer.id
                    if lw - dx <= self.HANDLE_W:
                        return "right", layer.id
                    return "body", layer.id
            return None, ""
        return None, ""

    def _find_layer_by_id(self, layer_id: str):
        if not self._timeline:
            return None, None
        for track in self._timeline.tracks:
            for layer in track.layers:
                if layer.id == layer_id:
                    return track, layer
        return None, None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            scroll_x = self.horizontalScrollBar().value()
            scroll_y = self.verticalScrollBar().value()
            in_ruler = pos.y() < self.RULER_HEIGHT
            if in_ruler:
                t = self._pos_to_time(pos.x(), scroll_x)
                if t >= 0:
                    self.set_playhead(t)
                    self.seekRequested.emit(t)
                    self.seekRequestedMs.emit(int(t * 1000))

            edge, lid = self._hit_test_edge(pos, scroll_x, scroll_y)
            if lid and edge in ("left", "right"):
                _, layer = self._find_layer_by_id(lid)
                if layer:
                    effective_end = self._get_effective_layer_end(layer)
                    self._drag_state = {
                        "type": f"resize_{edge}",
                        "layer_id": lid,
                        "start_time": float(layer.start),
                        "end_time": float(effective_end),
                        "layer_start_x": float(self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x),
                    }
                    self._selected_layer_id = lid
                    self.layerSelected.emit(lid)
                    idx = self._segment_indices.get(lid, -1)
                    if idx >= 0:
                        self.segmentTimingEditStarted.emit(idx, float(layer.start), float(effective_end))
                        self.segmentSelected.emit(idx)
                    self.viewport().update()
                    event.accept()
                    return

            elif lid:
                self._selected_layer_id = lid
                self.layerSelected.emit(lid)
                idx = self._segment_indices.get(lid, -1)
                if idx >= 0:
                    self.segmentSelected.emit(idx)
                self.viewport().update()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_state and event.button() == Qt.LeftButton:
            drag = self._drag_state
            self._drag_state = None
            self.setCursor(Qt.ArrowCursor)
            lid = drag["layer_id"]
            _, layer = self._find_layer_by_id(lid)
            if layer:
                start = float(layer.start)
                end = float(self._get_effective_layer_end(layer))
                idx = self._segment_indices.get(lid, -1)
                if idx >= 0:
                    self.segmentTimingChanged.emit(idx, start, end)
            self.viewport().update()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        scroll_x = self.horizontalScrollBar().value()
        scroll_y = self.verticalScrollBar().value()
        if self._drag_state:
            drag = self._drag_state
            t = self._pos_to_time(pos.x(), scroll_x)
            t = max(0.0, min(t, self._duration))
            _, layer = self._find_layer_by_id(drag["layer_id"])
            if layer:
                if drag["type"] == "resize_left":
                    new_start = min(t, drag["end_time"] - self.MIN_DUR)
                    new_start = max(0.0, new_start)
                    layer.start = new_start
                elif drag["type"] == "resize_right":
                    new_end = max(t, drag["start_time"] + self.MIN_DUR)
                    new_end = min(new_end, self._duration)
                    layer.end = new_end
                self.viewport().update()
            event.accept()
            return

        if event.buttons() & Qt.LeftButton:
            in_ruler = pos.y() < self.RULER_HEIGHT
            if in_ruler:
                t = self._pos_to_time(pos.x(), scroll_x)
                if t >= 0:
                    self.set_playhead(t)
                    self.seekRequested.emit(t)
                    self.seekRequestedMs.emit(int(t * 1000))

        edge, lid = self._hit_test_edge(pos, scroll_x, scroll_y)
        if lid and edge in ("left", "right"):
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
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

    def _hit_test_layer(self, pos, scroll_x: int, scroll_y: int = 0) -> str:
        if not self._timeline:
            return ""
        click_y = pos.y() + scroll_y
        y = self.RULER_HEIGHT
        margin = 4
        for track in self._timeline.tracks:
            if not self.is_track_shown_on_timeline(track):
                continue
            th = self._track_heights.get(track.id, self.TRACK_DEFAULT_H)
            if not (y <= click_y <= y + th):
                y += th
                continue
            visible_layers = [l for l in track.layers if l.visible]
            num_layers = max(1, len(visible_layers))
            uses_layer_rows = self._uses_layer_rows(track)
            overlap_stack = self._should_overlap_stack(track)
            if overlap_stack and num_layers > 1:
                # Sort by start time for proper overlap detection
                visible_layers_sorted = sorted(visible_layers, key=lambda l: float(getattr(l, "start", 0.0)))
                layer_rows, num_rows = self._compute_overlap_rows(visible_layers_sorted)
                num_rows = max(1, num_rows)
                # All rows are the same CHILD_TRACK_H tall. Recompute the
                # same Y positions the painter uses.
                row_slots: list[tuple[int, int]] = []
                cursor = y + margin
                for r in range(num_rows):
                    row_slots.append((cursor, self.CHILD_TRACK_H))
                    cursor += self.CHILD_TRACK_H
                row = -1
                for r, (slot_y, slot_h) in enumerate(row_slots):
                    if slot_y <= click_y <= slot_y + slot_h:
                        row = r
                        break
                if row < 0:
                    return ""
                for visible_idx, layer in enumerate(visible_layers_sorted):
                    if layer_rows[visible_idx] != row:
                        continue
                    lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                    lw = max(int(layer.duration * self.pixels_per_second), 20)
                    if lx - 4 <= pos.x() <= lx + lw + 4:
                        return layer.id
                return ""
            if uses_layer_rows and num_layers > 1:
                row_h = (th - margin * 2) / num_layers
                rel_y = click_y - y - margin
                row = max(0, min(int(rel_y / row_h), num_layers - 1))
                # Find the layer in that row
                visible_count = 0
                for layer in track.layers:
                    if not layer.visible:
                        continue
                    if visible_count == row:
                        lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                        lw = max(int(layer.duration * self.pixels_per_second), 20)
                        if lx - 4 <= pos.x() <= lx + lw + 4:
                            return layer.id
                        break
                    visible_count += 1
                return ""
            for layer in track.layers:
                if not layer.visible:
                    continue
                lx = self.TRACK_HEADER_W + int(layer.start * self.pixels_per_second) - scroll_x
                lw = max(int(layer.duration * self.pixels_per_second), 20)
                if lx - 4 <= pos.x() <= lx + lw + 4:
                    return layer.id
            return ""
        return ""
