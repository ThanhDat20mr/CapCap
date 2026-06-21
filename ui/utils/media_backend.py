import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from runtime_paths import bin_path
from video_processor import srt_to_ass


class QtMediaPlayerBackend(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)

    def __init__(self, video_view):
        super().__init__(video_view)
        from widgets import VideoView

        self.backend_name = "qt"
        self.video_view = video_view
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)
        if isinstance(video_view, VideoView):
            self._player.setVideoOutput(video_view.video_item)
        self._player.positionChanged.connect(self.positionChanged.emit)
        self._player.durationChanged.connect(self.durationChanged.emit)
        self._mute_original = False
        self._mute_dubbed = False

    def setSource(self, source):
        self._source_path = source.toLocalFile() if isinstance(source, QUrl) else str(source)
        self._player.setSource(source)

    def play(self):
        self._player.play()

    def pause(self):
        self._player.pause()

    def stop(self):
        self._player.stop()

    def setPosition(self, position):
        self._player.setPosition(position)

    def position(self):
        return self._player.position()

    def duration(self):
        return self._player.duration()

    def playbackState(self):
        return self._player.playbackState()

    def is_playing(self):
        return self.playbackState() == QMediaPlayer.PlayingState

    def set_subtitle_file(self, subtitle_path, subtitle_style=None):
        return None

    def clear_subtitle(self):
        return None

    def set_audio_file(self, audio_path):
        return None

    def clear_audio(self):
        return None

    def set_original_audio_file(self, audio_path):
        return None

    def _clear_original_audio(self):
        return None

    def set_blur_region(self, blur_region=None):
        return None

    def clear_blur_region(self):
        return None

    def set_volume(self, percent):
        value = max(0, min(100, int(percent)))
        self._audio_output.setVolume(value / 100.0)

    def set_original_volume(self, percent):
        value = max(0, min(200, int(percent))) / 100.0
        self._audio_output.setVolume(value)

    def set_dubbed_volume(self, percent):
        value = max(0, min(200, int(percent))) / 100.0
        self._audio_output.setVolume(value)

    def original_volume(self):
        return int(round(self._audio_output.volume() * 100.0))

    def dubbed_volume(self):
        return int(round(self._audio_output.volume() * 100.0))

    def volume(self):
        return int(round(self._audio_output.volume() * 100.0))

    def set_muted(self, muted):
        self._mute_original = bool(muted)
        self._mute_dubbed = bool(muted)
        self._audio_output.setMuted(bool(muted))

    def is_muted(self):
        return bool(self._audio_output.isMuted())

    def set_mute_original(self, muted):
        self._mute_original = bool(muted)
        self._audio_output.setMuted(self._mute_original and self._mute_dubbed)

    def set_mute_dubbed(self, muted):
        self._mute_dubbed = bool(muted)
        self._audio_output.setMuted(self._mute_original and self._mute_dubbed)

    def is_original_muted(self):
        return self._mute_original

    def is_dubbed_muted(self):
        return self._mute_dubbed

    def set_playback_rate(self, rate):
        try:
            self._player.setPlaybackRate(float(rate))
        except Exception:
            pass

    def playback_rate(self):
        try:
            return float(self._player.playbackRate())
        except Exception:
            return 1.0


class MpvMediaPlayerBackend(QObject):
    """Three-track design with truly independent mute:

    - mpv plays the source video with NO audio (`ao=null`) — video only
    - QMediaPlayer sidecar #1 plays the original audio file (extracted_audio)
    - QMediaPlayer sidecar #2 plays the dubbed audio file (mixed_vi)

    Each audio has its own QAudioOutput with its own mute. A sync timer
    keeps all three playheads aligned.

    The mpv Python bindings in this build reject `audio-add`, `lavfi=*`
    af chains, and multi-value `aid`, so we cannot mix both tracks inside
    one mpv. Using two QMediaPlayer sidecars avoids the audio-device
    conflict of two-mpv design and works with the bundled libmpv.
    """

    positionChanged = Signal(int)
    durationChanged = Signal(int)

    def __init__(self, video_view):
        super().__init__(video_view)
        self.backend_name = "libmpv"
        self.video_view = video_view
        self._position_ms = 0
        self._duration_ms = 0
        self._state = QMediaPlayer.StoppedState
        self._source_path = ""
        self._audio_path = ""        # dubbed audio
        self._original_audio_path = ""  # original audio (extracted)
        self._subtitle_ass_path = ""
        self._applied_subtitle_path = ""
        self._sub_track_id = -1
        self._blur_region = None
        self._mute_original = False
        self._mute_dubbed = False

        prepare_mpv_bundle()
        import mpv

        target_wid = video_view.get_mpv_target_winid() if hasattr(video_view, "get_mpv_target_winid") else video_view.winId()
        try:
            target_wid = int(target_wid)
        except Exception:
            target_wid = 0
        if sys.platform.startswith("win"):
            target_wid &= 0xFFFFFFFF

        self._player = mpv.MPV(
            wid=str(target_wid),
            ao="null",  # No audio output from mpv — we use QMediaPlayer sidecars
            input_default_bindings=False,
            input_vo_keyboard=False,
            force_window="no",
            osc=False,
            pause=True,
            keep_open="always",
            sub_auto="no",
            sub_ass_override="no",
        )

        @self._player.event_callback("file-loaded")
        def _on_file_loaded(event):
            self._apply_current_subtitle()
            self._apply_blur_filter()

        # --- Original audio sidecar ---
        self._original_output = QAudioOutput()
        self._original_output.setVolume(1.0)
        self._original_player = QMediaPlayer()
        self._original_player.setAudioOutput(self._original_output)
        self._original_loaded_path = ""
        self._original_position_ms = 0
        self._original_player.positionChanged.connect(self._on_original_position_changed)

        # --- Dubbed audio sidecar ---
        self._dubbed_output = QAudioOutput()
        self._dubbed_output.setVolume(1.0)
        self._dubbed_player = QMediaPlayer()
        self._dubbed_player.setAudioOutput(self._dubbed_output)
        self._dubbed_loaded_path = ""
        self._dubbed_position_ms = 0
        self._dubbed_player.positionChanged.connect(self._on_dubbed_position_changed)
        self._dubbed_player.mediaStatusChanged.connect(self._on_dubbed_status_changed)

        # --- Timers ---
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._poll_state)
        self._poll_timer.start()

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(500)
        self._sync_timer.timeout.connect(self._sync_audio_to_video)
        self._sync_timer.start()

    def _read_property(self, primary_name, fallback_name=None, default=None):
        names = [primary_name]
        if fallback_name:
            names.append(fallback_name)
        for name in names:
            try:
                value = self._player.property(name)
                if value is not None:
                    return value
            except Exception:
                pass
            attr_name = name.replace("-", "_")
            try:
                value = getattr(self._player, attr_name)
                if value is not None:
                    return value
            except Exception:
                pass
        return default

    def _normalize_source(self, source):
        if isinstance(source, QUrl):
            return source.toLocalFile() or source.toString()
        if isinstance(source, str):
            return source
        return ""

    def _poll_state(self):
        try:
            time_pos = self._read_property("time-pos", "time_pos", 0.0)
            duration = self._read_property("duration", default=0.0)
            pause = bool(self._read_property("pause", default=True))
        except Exception:
            return

        next_position = int(float(time_pos or 0.0) * 1000)
        next_duration = int(float(duration or 0.0) * 1000)
        next_state = QMediaPlayer.PausedState if pause else QMediaPlayer.PlayingState
        if not self._source_path:
            next_state = QMediaPlayer.StoppedState

        if next_position != self._position_ms:
            self._position_ms = next_position
            self.positionChanged.emit(next_position)
        if next_duration != self._duration_ms:
            self._duration_ms = next_duration
            self.durationChanged.emit(next_duration)
        self._state = next_state

    def setSource(self, source):
        source_path = self._normalize_source(source)
        if not source_path:
            self.stop()
            self.clear_subtitle()
            try:
                self._player.command("stop")
            except Exception:
                pass
            try:
                self._original_player.stop()
                self._dubbed_player.stop()
            except Exception:
                pass
            self._source_path = ""
            return

        self._source_path = source_path
        self._position_ms = 0
        self._duration_ms = 0
        self._state = QMediaPlayer.PausedState
        self._player.pause = True
        self._player.command("loadfile", source_path, "replace")
        # Reset applied tracking on source change
        self._applied_subtitle_path = ""
        # Pause both audio sidecars at 0 until user plays.
        if self._original_loaded_path:
            try:
                self._original_player.pause()
                self._original_player.setPosition(0)
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.pause()
                self._dubbed_player.setPosition(0)
            except Exception:
                pass
        self._apply_blur_filter()
        self._apply_current_subtitle()

    def play(self):
        if not self._source_path:
            return
        self._player.pause = False
        if self._original_loaded_path:
            try:
                self._original_player.play()
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.play()
            except Exception:
                pass
        self._state = QMediaPlayer.PlayingState

    def pause(self):
        self._player.pause = True
        if self._original_loaded_path:
            try:
                self._original_player.pause()
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.pause()
            except Exception:
                pass
        self._state = QMediaPlayer.PausedState

    def stop(self):
        self._player.pause = True
        if self._original_loaded_path:
            try:
                self._original_player.pause()
                self._original_player.setPosition(0)
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.pause()
                self._dubbed_player.setPosition(0)
            except Exception:
                pass
        try:
            self._player.command("seek", 0, "absolute")
        except Exception:
            pass
        self._position_ms = 0
        self._state = QMediaPlayer.StoppedState
        self.positionChanged.emit(0)

    def setPosition(self, position):
        self._position_ms = int(position)
        if not self._source_path:
            self.positionChanged.emit(self._position_ms)
            return
        seconds = max(0.0, position / 1000.0)
        try:
            self._player.command("seek", seconds, "absolute")
        except Exception:
            pass
        if self._original_loaded_path:
            try:
                self._original_player.setPosition(int(position))
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.setPosition(int(position))
            except Exception:
                pass
        self.positionChanged.emit(self._position_ms)

    def position(self):
        return self._position_ms

    def duration(self):
        return self._duration_ms

    def playbackState(self):
        return self._state

    def is_playing(self):
        return self._state == QMediaPlayer.PlayingState

    def clear_subtitle(self):
        if self._subtitle_ass_path and os.path.exists(self._subtitle_ass_path):
            try:
                os.remove(self._subtitle_ass_path)
            except OSError:
                pass
        self._subtitle_ass_path = ""
        self._applied_subtitle_path = ""
        try:
            self._player.sub_visibility = False
        except Exception:
            pass

    def _build_blur_filter(self):
        raw_regions = self._blur_region or []
        if isinstance(raw_regions, dict):
            raw_regions = [raw_regions]
        if not isinstance(raw_regions, list) or not raw_regions:
            return ""
        video_width = int(self.video_view.video_source_width or 0)
        video_height = int(self.video_view.video_source_height or 0)
        if video_width <= 0 or video_height <= 0:
            return ""
        regions = []
        for blur in raw_regions:
            if not isinstance(blur, dict):
                continue
            try:
                x = max(0, min(video_width - 2, int(round(float(blur.get("x", 0.0)) * video_width))))
                y = max(0, min(video_height - 2, int(round(float(blur.get("y", 0.0)) * video_height))))
                w = max(2, min(video_width - x, int(round(float(blur.get("width", 0.0)) * video_width))))
                h = max(2, min(video_height - y, int(round(float(blur.get("height", 0.0)) * video_height))))
            except (TypeError, ValueError):
                continue
            min_dimension = min(w, h)
            luma_radius = max(1, min(20, int(min_dimension // 2)))
            chroma_radius = max(0, min(20, int(min_dimension // 4)))
            regions.append((x, y, w, h, luma_radius, chroma_radius))
        if not regions:
            return ""

        crop_parts = []
        overlay_parts = []
        for index, (x, y, w, h, luma_radius, chroma_radius) in enumerate(regions):
            crop_parts.append(
                f"[tmp{index}]crop=w={w}:h={h}:x={x}:y={y},boxblur={luma_radius}:3:{chroma_radius}:3[blur{index}]"
            )
            base_label = "main" if index == 0 else f"b{index - 1}"
            output_label = "" if index == len(regions) - 1 else f"[b{index}]"
            overlay_parts.append(f"[{base_label}][blur{index}]overlay={x}:{y}{output_label}")
        split_outputs = "[main]" + "".join(f"[tmp{i}]" for i in range(len(regions)))
        return "lavfi=[" + f"split={len(regions) + 1}{split_outputs};" + ";".join(crop_parts + overlay_parts) + "]"

    def _apply_blur_filter(self):
        try:
            self._player.command("vf", "clr", "")
        except Exception:
            pass
        filter_spec = self._build_blur_filter()
        if not filter_spec:
            return
        try:
            self._player.command("vf", "add", f"@capcap-blur:{filter_spec}")
        except Exception:
            try:
                self._player.vf = filter_spec
            except Exception:
                pass

    def set_blur_region(self, blur_region=None):
        if isinstance(blur_region, list):
            self._blur_region = [dict(region) for region in blur_region if isinstance(region, dict)]
        else:
            self._blur_region = dict(blur_region or {}) if blur_region else None
        self._apply_blur_filter()

    def clear_blur_region(self):
        self._blur_region = None
        self._apply_blur_filter()

    def set_audio_file(self, audio_path):
        """Load the dubbed audio file into the QMediaPlayer sidecar."""
        if not audio_path or not os.path.exists(audio_path):
            self.clear_audio()
            return
        self._audio_path = audio_path
        self._apply_current_dubbed()

    def set_original_audio_file(self, audio_path):
        """Load the original audio file into the QMediaPlayer sidecar."""
        if not audio_path or not os.path.exists(audio_path):
            self._clear_original_audio()
            return
        self._original_audio_path = audio_path
        self._apply_current_original()

    def _clear_original_audio(self):
        self._original_audio_path = ""
        self._original_loaded_path = ""
        try:
            self._original_player.stop()
        except Exception:
            pass
        self._apply_original_mute()

    def clear_audio(self):
        """Unload the dubbed audio sidecar."""
        self._audio_path = ""
        self._dubbed_loaded_path = ""
        try:
            self._dubbed_player.stop()
        except Exception:
            pass
        self._apply_dubbed_mute()

    def _apply_current_dubbed(self):
        if not self._audio_path or not os.path.exists(self._audio_path):
            return
        if self._dubbed_loaded_path == self._audio_path:
            self._apply_dubbed_mute()
            return
        try:
            self._dubbed_player.setSource(QUrl.fromLocalFile(self._audio_path))
            self._dubbed_loaded_path = self._audio_path
        except Exception as exc:
            self.log(f"[Backend] Dubbed audio load failed: {exc}")
            return
        self._apply_dubbed_mute()

    def _apply_current_original(self):
        if not self._original_audio_path or not os.path.exists(self._original_audio_path):
            return
        if self._original_loaded_path == self._original_audio_path:
            self._apply_original_mute()
            return
        try:
            self._original_player.setSource(QUrl.fromLocalFile(self._original_audio_path))
            self._original_loaded_path = self._original_audio_path
        except Exception as exc:
            self.log(f"[Backend] Original audio load failed: {exc}")
            return
        self._apply_original_mute()

    def _on_original_position_changed(self, position):
        self._original_position_ms = int(position or 0)

    def _on_dubbed_position_changed(self, position):
        self._dubbed_position_ms = int(position or 0)

    def _on_dubbed_status_changed(self, status):
        try:
            from PySide6.QtMultimedia import QMediaPlayer as _QMP
            if status == _QMP.EndOfMedia:
                if not self._player.pause and self._state == QMediaPlayer.PlayingState:
                    self._player.pause = True
        except Exception:
            pass

    def _apply_dubbed_mute(self):
        """Mute the dubbed audio QMediaPlayer sidecar."""
        try:
            self._dubbed_output.setMuted(bool(self._mute_dubbed))
        except Exception as exc:
            self.log(f"[Backend] Dubbed mute failed: {exc}")

    def _apply_original_mute(self):
        """Mute the original audio QMediaPlayer sidecar."""
        try:
            self._original_output.setMuted(bool(self._mute_original))
        except Exception as exc:
            self.log(f"[Backend] Original mute failed: {exc}")

    def _apply_video_mute(self):
        # mpv uses ao=null so this is a no-op. Kept for API compatibility.
        pass

    def _resync_audio_position(self):
        try:
            v_pos_ms = int(float(self._player.time_pos or 0) * 1000)
        except Exception:
            v_pos_ms = 0
        if v_pos_ms < 0:
            v_pos_ms = 0
        if self._original_loaded_path:
            try:
                self._original_player.setPosition(int(v_pos_ms))
            except Exception:
                pass
        if self._dubbed_loaded_path:
            try:
                self._dubbed_player.setPosition(int(v_pos_ms))
            except Exception:
                pass

    def _sync_audio_to_video(self):
        if not self._source_path:
            return
        try:
            v_pos_ms = int(float(self._player.time_pos or 0) * 1000)
        except Exception:
            return
        try:
            v_paused = bool(self._player.pause)
        except Exception:
            return
        if self._original_loaded_path:
            try:
                a_state = self._original_player.playbackState()
                a_paused = a_state == QMediaPlayer.PausedState or a_state == QMediaPlayer.StoppedState
            except Exception:
                a_paused = True
            if v_paused != a_paused:
                try:
                    if v_paused:
                        self._original_player.pause()
                    else:
                        self._original_player.play()
                except Exception:
                    pass
            try:
                a_pos_ms = int(self._original_player.position() or 0)
            except Exception:
                a_pos_ms = 0
            if abs(v_pos_ms - a_pos_ms) > 300:
                try:
                    self._original_player.setPosition(int(v_pos_ms))
                except Exception:
                    pass
        if self._dubbed_loaded_path:
            try:
                a_state = self._dubbed_player.playbackState()
                a_paused = a_state == QMediaPlayer.PausedState or a_state == QMediaPlayer.StoppedState
            except Exception:
                a_paused = True
            if v_paused != a_paused:
                try:
                    if v_paused:
                        self._dubbed_player.pause()
                    else:
                        self._dubbed_player.play()
                except Exception:
                    pass
            try:
                a_pos_ms = int(self._dubbed_player.position() or 0)
            except Exception:
                a_pos_ms = 0
            if abs(v_pos_ms - a_pos_ms) > 300:
                try:
                    self._dubbed_player.setPosition(int(v_pos_ms))
                except Exception:
                    pass

    def log(self, text):
        # We can reach out to the gui if needed
        if hasattr(self.video_view, "parent") and hasattr(self.video_view.parent(), "log"):
             self.video_view.parent().log(text)
        elif hasattr(self, "gui") and hasattr(self.gui, "log"):
             self.gui.log(text)

    def set_subtitle_file(self, subtitle_path, subtitle_style=None):
        if not subtitle_path or not os.path.exists(subtitle_path):
            self.clear_subtitle()
            return

        if subtitle_path.lower().endswith(".ass"):
            ass_path = subtitle_path
        else:
            subtitle_style = subtitle_style or {}
            video_width = self.video_view.video_source_width or 1920
            video_height = self.video_view.video_source_height or 1080
            ass_path = srt_to_ass(
                subtitle_path,
                video_width=video_width,
                video_height=video_height,
                alignment=subtitle_style.get("alignment", 2),
                margin_v=subtitle_style.get("margin_v", 30),
                font_name=subtitle_style.get("font_name", "Arial"),
                font_size=subtitle_style.get("font_size", 18),
                font_color=subtitle_style.get("font_color", "&H00FFFFFF"),
                background_box=subtitle_style.get("background_box", False),
                animation_style=subtitle_style.get("animation", "Static"),
                highlight_color=subtitle_style.get("highlight_color", subtitle_style.get("font_color", "&H00FFFFFF")),
                outline_color=subtitle_style.get("outline_color", "&H00000000"),
                outline_width=subtitle_style.get("outline_width", 2.0),
                shadow_color=subtitle_style.get("shadow_color", "&H80000000"),
                shadow_depth=subtitle_style.get("shadow_depth", 1.0),
                background_color=subtitle_style.get("background_color", "&H80000000"),
                background_alpha=subtitle_style.get("background_alpha", 0.5),
                bold=subtitle_style.get("bold", False),
                preset_key=subtitle_style.get("preset_key", ""),
                auto_keyword_highlight=subtitle_style.get("auto_keyword_highlight", False),
                animation_duration=subtitle_style.get("animation_duration", 0.22),
                manual_highlights=subtitle_style.get("manual_highlights", []),
                custom_position_enabled=subtitle_style.get("custom_position_enabled", False),
                custom_position_x=subtitle_style.get("custom_position_x", 50),
                custom_position_y=subtitle_style.get("custom_position_y", 86),
                single_line=subtitle_style.get("single_line", False),
            )
        self._subtitle_ass_path = ass_path
        self._apply_current_subtitle()

    def _apply_current_subtitle(self):
        if not self._source_path:
            return
        if not self._subtitle_ass_path or not os.path.exists(self._subtitle_ass_path):
            try:
                self._player.sub_visibility = False
            except Exception:
                pass
            self._applied_subtitle_path = ""
            return
        try:
            # Remove old subtitle track first to avoid accumulation
            if self._applied_subtitle_path and self._applied_subtitle_path != self._subtitle_ass_path:
                try:
                    self._player.command("sub-remove", self._sub_track_id)
                except Exception:
                    pass
            if self._applied_subtitle_path == self._subtitle_ass_path:
                self._player.command("sub-reload")
            else:
                track_id = self._player.command("sub-add", self._subtitle_ass_path, "select")
                self._sub_track_id = track_id
            self._player.sub_visibility = True
            self._applied_subtitle_path = self._subtitle_ass_path
        except Exception:
            pass

    def set_volume(self, percent):
        try:
            v = max(0, min(100, int(percent)))
            # Legacy global volume: apply to both sidecars.
            try:
                self._original_output.setVolume(v / 100.0)
            except Exception:
                pass
            try:
                self._dubbed_output.setVolume(v / 100.0)
            except Exception:
                pass
        except Exception:
            pass

    def set_original_volume(self, percent):
        try:
            v = max(0.0, min(200.0, float(percent))) / 100.0
            self._original_output.setVolume(v)
        except Exception:
            pass

    def set_dubbed_volume(self, percent):
        try:
            v = max(0.0, min(200.0, float(percent))) / 100.0
            self._dubbed_output.setVolume(v)
        except Exception:
            pass

    def original_volume(self):
        try:
            return int(round(self._original_output.volume() * 100.0))
        except Exception:
            return 100

    def dubbed_volume(self):
        try:
            return int(round(self._dubbed_output.volume() * 100.0))
        except Exception:
            return 100

    def volume(self):
        try:
            return int(round(self._original_output.volume() * 100.0))
        except Exception:
            return 100

    def set_muted(self, muted):
        # Legacy: apply to BOTH tracks so existing callers keep working.
        self.set_mute_original(bool(muted))
        self.set_mute_dubbed(bool(muted))

    def is_muted(self):
        return self._mute_original and self._mute_dubbed

    def set_mute_original(self, muted):
        self._mute_original = bool(muted)
        self._apply_original_mute()

    def set_mute_dubbed(self, muted):
        self._mute_dubbed = bool(muted)
        self._apply_dubbed_mute()

    def is_original_muted(self):
        return self._mute_original

    def is_dubbed_muted(self):
        return self._mute_dubbed

    def set_playback_rate(self, rate):
        try:
            self._player.speed = float(rate)
        except Exception:
            pass

    def playback_rate(self):
        try:
            return float(self._read_property("speed", default=1.0) or 1.0)
        except Exception:
            return 1.0


def create_media_backend(video_view):
    try:
        return MpvMediaPlayerBackend(video_view)
    except Exception:
        return QtMediaPlayerBackend(video_view)


def get_mpv_bundle_dir():
    return Path(bin_path("mpv"))


def is_mpv_backend_available():
    try:
        prepare_mpv_bundle()
        import mpv  # noqa: F401
        return True
    except Exception:
        return False


def prepare_mpv_bundle():
    mpv_dir = get_mpv_bundle_dir()
    if not mpv_dir.exists():
        raise FileNotFoundError(f"Bundled mpv directory not found: {mpv_dir}")

    mpv_dll = mpv_dir / "libmpv-2.dll"
    if not mpv_dll.exists():
        alt_dll = mpv_dir / "mpv-2.dll"
        if alt_dll.exists():
            mpv_dll = alt_dll
        else:
            raise FileNotFoundError(f"Bundled libmpv DLL not found in {mpv_dir}")

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(mpv_dir))

    os.environ["PATH"] = str(mpv_dir) + os.pathsep + os.environ.get("PATH", "")

    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.WinDLL(str(mpv_dll))
        except OSError as exc:
            raise RuntimeError(
                f"Could not load bundled libmpv from {mpv_dll}. "
                "The bundle may be missing dependent runtime DLLs."
            ) from exc
