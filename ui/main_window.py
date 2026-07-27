import sys
import os
import re
import json
import copy
import hashlib
import shutil
import threading
from uuid import uuid4
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QToolButton, QLabel, QLineEdit,
                             QFileDialog, QTextEdit, QComboBox,
                             QDoubleSpinBox,
                             QFrame, QProgressBar, QMessageBox,
                             QScrollArea,
                             QColorDialog, QTabWidget, QDialog, QSizePolicy, QInputDialog, QLayout)
from PySide6.QtCore import Qt, QUrl, QTimer, QSettings, QEvent
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QIcon, QKeySequence, QPixmap, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

APP_PATH = os.path.join(os.path.dirname(__file__), '..', 'app')
if APP_PATH not in sys.path:
    sys.path.append(APP_PATH)

from services import GUIProjectBridge, ProjectService, ResourceDownloadService, VoiceCatalogService
from controllers import PipelineController, PreviewController, SubtitleController
from helpers import (
    build_guidance_state,
    build_preview_context_text,
    build_workflow_hint,
    extract_subtitle_text_entries,
    format_segments_to_srt,
    format_timestamp,
    get_export_button_label,
    get_output_mode_key,
    parse_srt_to_segments,
    validate_srt_text,
)
from new_highlight_selector import auto_select_matches
from video_processor import srt_to_ass
from audio_mixer import ffprobe_wav_duration
from utils.display_utils import (
    cleanup_temp_preview_files as cleanup_temp_preview_files_impl,
    clear_log as clear_log_impl,
    log_message as log_message_impl,
    show_error as show_error_impl,
    show_frame_preview_dialog as show_frame_preview_dialog_impl,
    show_processed_files as show_processed_files_impl,
)
from utils.file_dialog_utils import (
    browse_audio_folder as browse_audio_folder_impl,
    browse_audio_source as browse_audio_source_impl,
    browse_background_audio as browse_background_audio_impl,
    browse_existing_mixed_audio as browse_existing_mixed_audio_impl,
    browse_srt_output_folder as browse_srt_output_folder_impl,
    browse_voice_output_folder as browse_voice_output_folder_impl,
    cleanup_file_if_exists as cleanup_file_if_exists_impl,
    open_folder as open_folder_impl,
)
from utils.icon_utils import load_icon
from utils.media_utils import (
    browse_video as browse_video_impl,
    duration_changed as duration_changed_impl,
    position_changed as position_changed_impl,
    refresh_video_dimensions as refresh_video_dimensions_impl,
    set_position as set_position_impl,
    setup_media_player as setup_media_player_impl,
    stop_video as stop_video_impl,
    toggle_play as toggle_play_impl,
    update_duration_label as update_duration_label_impl,
    update_frame_preview_thumbnail as update_frame_preview_thumbnail_impl,
)
from utils.settings_utils import load_user_settings as load_user_settings_impl, save_user_settings as save_user_settings_impl
from views import build_main_window_ui
from widgets.progress_dialog import BackgroundableProgressDialog
from runtime_paths import app_path, asset_path, models_path, workspace_root
from runtime_profile import is_remote_profile
from worker_adapters import (
    ExtractionWorker,
    ResourceDownloadWorker,
    SegmentAudioPreviewWorker,
    VoiceSamplePreviewWorker,
    VocalSeparationWorker,
    VoiceOverWorker,
)

# Import our backend modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))
from video_processor import get_video_dimensions
from workflows.voice_workflow import predict_speed_ratios
from audio_mixer import mix_voice_with_background


def _default_asr_engine() -> str:
    cpu_mode = os.getenv("CAPCAP_DEVICE", "cuda").strip().lower() == "cpu"
    return "sensevoice" if cpu_mode else "whisper"


class _BootstrapMediaBackend:
    backend_name = "bootstrap"
    _source_path = ""

    def setSource(self, source):
        self._source_path = ""

    def play(self):
        return None

    def pause(self):
        return None

    def stop(self):
        return None

    def setPosition(self, position):
        return None

    def position(self):
        return 0

    def duration(self):
        return 0

    def playbackState(self):
        return QMediaPlayer.StoppedState

    def is_playing(self):
        return False

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
        return None

    def volume(self):
        return 100

    def set_muted(self, muted):
        return None

    def is_muted(self):
        return False

    def set_mute_original(self, muted):
        return None

    def set_mute_dubbed(self, muted):
        return None

    def is_original_muted(self):
        return False

    def is_dubbed_muted(self):
        return False

    def set_original_volume(self, percent):
        return None

    def set_dubbed_volume(self, percent):
        return None

    def original_volume(self):
        return 100

    def dubbed_volume(self):
        return 100

    def set_playback_rate(self, rate):
        return None

    def playback_rate(self):
        return 1.0

class VideoTranslatorGUI(QMainWindow):
    VOICE_ENTRY_ID_ROLE = Qt.UserRole + 1

    def __init__(self):
        super().__init__()
        self._current_video_path = ""
        title = "CapCap Video Translator"
        if is_remote_profile():
            title += " (Remote)"
        self.setWindowTitle(title)
        self.settings = QSettings("CapCap", "VideoTranslatorGUI")
        self.setAcceptDrops(True)
        self.logo_path = asset_path("capcap.png")
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))
        self.setWindowFlag(Qt.FramelessWindowHint)
        
        # Maximize and prevent resizing
        self.setWindowState(Qt.WindowMaximized)
        # To strictly prevent resizing after maximizing:
        self.setFixedSize(QApplication.primaryScreen().availableGeometry().size())
        
        # Stylesheet for Premium Dark Mode
        self.setStyleSheet("""
            QMainWindow {
                background-color: #101826;
            }
            QWidget {
                color: #dbe5f3;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            #centralWidget {
                background-color: #101826;
            }
            #leftPanelArea {
                background-color: #121b2b;
                border-right: 1px solid #223248;
            }
            #leftPanelContainer {
                background-color: #121b2b;
            }
            #rightPanel {
                background-color: #101826;
            }
            QGroupBox {
                border: none;
                border-radius: 0px;
                margin-top: 0px;
                font-weight: bold;
                color: #f3f7fb;
                background-color: transparent;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #8ad7ff;
            }
            QFrame#heroCard, QFrame#statusCard, QFrame#sideInfoCard {
                background-color: #0d1624;
                border: 1px solid #24384f;
                border-radius: 14px;
            }
            QFrame#audioSourcePanel {
                background-color: #101d2d;
                border: 1px solid #2a455f;
                border-radius: 10px;
            }
            QLabel#audioSourceTitle {
                color: #edf7ff;
                font-weight: 700;
            }
            QFrame#subtitleInspectorHandle {
                background-color: #0d1624;
                border: 1px solid #24384f;
                border-left: none;
                border-top-right-radius: 14px;
                border-bottom-right-radius: 14px;
            }
            QPushButton#subtitleInspectorHandleBtn {
                background-color: #162638;
                color: #8ad7ff;
                border: 1px solid #31506d;
                border-right: none;
                border-top-left-radius: 999px;
                border-bottom-left-radius: 999px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                font-size: 20px;
                font-weight: 900;
                padding: 0px;
            }
            QPushButton#subtitleInspectorHandleBtn:hover {
                background-color: #1d3047;
                border-color: #4d82b5;
            }
            QLabel#heroTitle {
                font-size: 20px;
                font-weight: 700;
                color: #f8fbff;
            }
            QLabel#heroBody, QLabel#statusBody, QLabel#helperLabel, QLabel#previewContextLabel {
                color: #a9b8cb;
                line-height: 1.35em;
            }
            QLabel#helperLabel[filterModified="true"] {
                color: #8ad7ff;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                font-size: 13px;
                font-weight: 700;
                color: #8ad7ff;
            }
            QLabel#timingChip {
                background-color: #173049;
                color: #9fe5ff;
                border: 1px solid #356081;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#statusHeadline {
                font-size: 16px;
                font-weight: 700;
                color: #f8fbff;
            }
            QLabel#statusPill {
                background-color: #1d3a52;
                color: #9fe5ff;
                border: 1px solid #336180;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#statusChip {
                background-color: #152537;
                color: #dbe5f3;
                border: 1px solid #2e4764;
                border-radius: 999px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QLabel#statusChip[state="ok"] {
                background-color: #153528;
                color: #c8f7df;
                border: 1px solid #2f7a55;
            }
            QLabel#statusChip[state="running"] {
                background-color: #3a2d12;
                color: #ffe29a;
                border: 1px solid #9b7530;
            }
            QLabel#statusChip[state="na"] {
                background-color: #1c2430;
                color: #9fb3ca;
                border: 1px solid #3a4a5f;
            }
            QLabel#statusChip[state="pending"] {
                background-color: #152537;
                color: #dbe5f3;
                border: 1px solid #2e4764;
            }
            QPushButton {
                background-color: #213248;
                color: #ffffff;
                border: 1px solid #304b69;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2d4665;
                border-color: #4575a8;
            }
            QPushButton#mainActionBtn, QToolButton#mainActionBtn {
                background-color: #4ed0b3;
                color: #0b1620;
                border: none;
                border-radius: 10px;
                font-size: 13px;
                font-weight: bold;
                border-bottom: 2px solid #258971;
                padding: 8px 14px;
            }
            QPushButton#mainActionBtn:hover, QToolButton#mainActionBtn:hover {
                background-color: #66ddc2;
            }
            QToolButton#mainActionBtn::menu-indicator {
                image: none;
                width: 0px;
            }
            QPushButton#secondaryActionBtn {
                background-color: #18314a;
                color: #dff4ff;
                border: 1px solid #4f88b4;
                font-size: 13px;
                font-weight: 700;
                padding: 8px 14px;
            }
            QPushButton#secondaryActionBtn:hover {
                background-color: #21405f;
                border-color: #69a9dc;
            }
            QPushButton#secondaryActionBtn::menu-indicator {
                width: 0px;
                image: none;
            }
            QMenu#headerMoreMenu, QMenu#generateMenu, QMenu#generateStepMenu {
                background-color: #0f1724;
                color: #e6eef9;
                border: 1px solid #30425b;
                padding: 6px;
            }
            QMenu#headerMoreMenu::item, QMenu#generateMenu::item, QMenu#generateStepMenu::item {
                background-color: transparent;
                color: #e6eef9;
                padding: 8px 14px;
                border-radius: 8px;
            }
            QMenu#generateStepMenu::item:enabled {
                background-color: #17324a;
                color: #e8f7ff;
                border: 1px solid #39749e;
                font-weight: 700;
            }
            QMenu#generateStepMenu::item:disabled {
                background-color: #111b29;
                color: rgba(151, 169, 190, 110);
                border: 1px solid #1d2a3a;
                font-weight: 400;
            }
            QMenu#headerMoreMenu::item:selected, QMenu#generateMenu::item:selected, QMenu#generateStepMenu::item:selected {
                background-color: #213248;
                color: #ffffff;
            }
            QMenu#generateStepMenu::item:disabled:selected {
                background-color: #111b29;
                color: rgba(151, 169, 190, 110);
            }
            QMenu#headerMoreMenu::separator, QMenu#generateMenu::separator, QMenu#generateStepMenu::separator {
                height: 1px;
                background: #2b425c;
                margin: 6px 8px;
            }
            QPushButton#workflowTabBtn {
                background-color: #162638;
                color: #9fb3ca;
                border: 1px solid #2b425c;
                border-radius: 10px;
                padding: 5px 9px;
                font-size: 10px;
                font-weight: 700;
            }
            QPushButton#workflowTabBtn:hover {
                background-color: #1c3047;
                border-color: #44698f;
            }
            QPushButton#workflowTabBtn:checked {
                background-color: #24425f;
                color: #f8fbff;
                border-color: #5fb9ff;
            }
            QStackedWidget#leftPanelStack {
                background: transparent;
            }
            QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #111927;
                border: 1px solid #31445d;
                border-radius: 10px;
                color: #ffffff;
                padding: 8px;
            }
            QScrollArea#segmentEditorScroll {
                background-color: transparent;
                border: none;
            }
            QWidget#segmentEditorContainer {
                background-color: transparent;
            }
            QFrame#segmentInspectorCard {
                background-color: #0d1624;
                border: 1px solid #24384f;
                border-radius: 0px;
            }
            QTextEdit#segmentInspectorEditor {
                background-color: #111b2b;
                border: 1px solid #35506f;
                border-radius: 10px;
                padding: 10px 12px;
            }
            QTextEdit#segmentInspectorEditor:focus {
                border: 1px solid #5fb9ff;
                background-color: #122033;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #8ad7ff;
            }
            QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
                background-color: #0d1420;
                color: #8b9bb0;
                border: 1px solid #243447;
            }
            QLineEdit::placeholder, QTextEdit {
                selection-background-color: #325173;
            }
            QProgressBar {
                border: 1px solid #2a3a50;
                border-radius: 10px;
                text-align: center;
                background-color: #111927;
                color: white;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5ed5c9, stop:1 #2b9f96);
                border-radius: 10px;
            }
            QLabel {
                background: transparent;
                color: #dbe5f3;
                font-size: 12px;
            }
            QCheckBox {
                background: transparent;
                color: #dbe5f3;
            }
            QRadioButton {
                background: transparent;
                color: #dbe5f3;
            }
            QScrollArea {
                border: none;
                background-color: #121b2b;
            }
            QScrollBar:vertical {
                border: none;
                background: #142030;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #35506f;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #416287;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            /* Fix ComboBox Dropdown colors */
            QComboBox QAbstractItemView {
                background-color: #111927;
                color: #ffffff;
                selection-background-color: #325173;
                border: 1px solid #31445d;
                outline: none;
            }
            QMessageBox {
                background-color: #101826;
            }
            QMessageBox QLabel {
                color: #e6eef9;
                background: transparent;
            }
            QMessageBox QPushButton {
                min-width: 96px;
            }
            QTabWidget::pane {
                border: 1px solid #30425b;
                border-radius: 12px;
                background: #111927;
                top: -1px;
            }
            QTabBar::tab {
                background: #1d2c40;
                color: #a8bad2;
                padding: 9px 14px;
                border: 1px solid #30425b;
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                min-width: 110px;
            }
            QTabBar::tab:selected {
                background: #111927;
                color: #8ad7ff;
            }
        """)

        # -----------------------------
        # State (must exist before setup_ui)
        # -----------------------------
        # Track generated/selected artifacts for quick inspection.
        # Keys are stable IDs, values are absolute file paths.
        self.processed_artifacts = {}
        self.workspace_root = workspace_root()
        self._cleanup_temp_root()
        self.project_service = ProjectService(self.workspace_root)
        self.project_bridge = GUIProjectBridge(self.project_service)
        self.voice_catalog_service = VoiceCatalogService(self.workspace_root)
        self.subtitle_controller = SubtitleController(self)
        self.pipeline_controller = PipelineController(self)
        self.preview_controller = PreviewController(self)
        self.current_project_state = None
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.selected_whisper_model_name = "medium"
        self._last_audio_preview_path = ""
        self._segment_preview_threads = {}
        self._voice_sample_preview_thread = None
        self._voiceover_force_refresh = False
        self.voice_catalog_entries_all = []
        self.voice_catalog_entries = []

        self.voice_catalog_map = {}
        self._voice_signals_bound = False
        self._media_backend_ready = False
        self._blur_region_signal_bound = False
        self._blur_edit_finished_signal_bound = False
        self._preview_audio_signals_bound = False
        self.media_player = _BootstrapMediaBackend()
        self.voice_preview_dialog = None
        self._voice_preview_row_buttons = {}
        self._tracked_progress_dialogs = []
        self._timeline_timing_undo_stack = []
        self._timeline_timing_redo_stack = []
        self._suspend_timeline_undo = False
        self._timeline_waveform_cache_key = None
        self._timeline_waveform_samples = []
        self._timeline_waveform_duration_s = 0.0
        self._timeline_waveform_worker = None
        self._desired_timeline_waveform_request = None
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self._timeline_thumbnail_worker = None
        self._desired_timeline_thumbnail_request = None
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        self._allow_post_pipeline_preview_assets = False
        self._subtitle_custom_style_state = None
        self._subtitle_preset_apply_in_progress = False
        self._video_filter_ui_sync = False
        self._video_filter_preset_key = "original"
        self._video_filter_intensity = 75
        self._video_filter_adjust_overrides = {
            "brightness": 0,
            "contrast": 0,
            "saturation": 0,
            "temperature": 0,
            "highlights": 0,
            "shadows": 0,
        }
        self._video_filter_user_modified = {
            "brightness": False,
            "contrast": False,
            "saturation": False,
            "temperature": False,
            "highlights": False,
            "shadows": False,
        }
        self._pending_video_filter_preview = False
        self._filter_thumbnail_visible = False
        self._filter_preview_blur_was_checked = False
        self._filter_preview_ocr_was_editable = False
        self._suspend_ocr_overlay = False
        self._ocr_overlay_visible = True
        self._play_video_filter_preview_when_ready = False
        self._filter_thumbnail_target_height = 320
        self._video_filter_preview_dirty = False
        self._video_filter_apply_requested = False
        self._blur_edit_finish_syncing = False
        self._blur_region_preview_dirty = False
        # Simple pipeline runner (Run All)
        self._pipeline_active = False
        self._pipeline_step = ""

        # Pre-rendered video state
        self.last_preview_video_path = ""
        self.last_styled_preview_path = ""
        self.last_styled_preview_signature = ""
        self.last_exact_preview_5s_path = ""

        self._deferred_startup_stage1_done = False
        self._deferred_startup_stage2_done = False

        self.setup_ui()
        self._configure_local_voice_mode_ui()
        self._timeline_visual_refresh_timer = QTimer(self)
        self._timeline_visual_refresh_timer.setSingleShot(True)
        self._timeline_visual_refresh_timer.timeout.connect(self._run_pending_timeline_visual_refresh)
        QTimer.singleShot(0, self._run_deferred_startup_stage1)
        QTimer.singleShot(600, self._run_deferred_startup_stage2)

    def get_selected_subtitle_preset(self) -> str:
        if getattr(self, "subtitle_preset_custom_radio", None) and self.subtitle_preset_custom_radio.isChecked():
            return "custom"
        if getattr(self, "subtitle_preset_tiktok_radio", None) and self.subtitle_preset_tiktok_radio.isChecked():
            return "tiktok"
        if getattr(self, "subtitle_preset_youtube_radio", None) and self.subtitle_preset_youtube_radio.isChecked():
            return "youtube"
        if getattr(self, "subtitle_preset_minimal_radio", None) and self.subtitle_preset_minimal_radio.isChecked():
            return "minimal"
        return "youtube"

    def get_subtitle_preset_config(self, preset_key: str | None = None) -> dict:
        preset = (preset_key or self.get_selected_subtitle_preset()).lower()
        presets = {
            "tiktok": {
                "label": "TikTok",
                "font_name": "Montserrat",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFD400",
                "outline_color": "#000000",
                "outline_width": 7,
                "shadow_color": "#000000",
                "shadow_depth": 2,
                "shadow_alpha": 0.7,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.0,
                "animation": "Word Highlight Karaoke",
                "bold": True,
                "auto_keyword_highlight": True,
                "highlight_mode": "Auto + Manual",
                "summary": "Large subtitle with karaoke-style word timing and highlighted keywords for short-form videos.",
            },
            "youtube": {
                "label": "YouTube",
                "font_name": "Roboto",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFFFFF",
                "outline_color": "#000000",
                "outline_width": 3,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.35,
                "background_box": True,
                "background_color": "#000000",
                "background_alpha": 1.0,
                "animation": "Fade In",
                "bold": False,
                "auto_keyword_highlight": False,
                "highlight_mode": "Manual",
                "summary": "Clean subtitle with a solid background box for long-form readability.",
            },
            "minimal": {
                "label": "Short",
                "font_name": "Inter",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFFFFF",
                "outline_color": "#000000",
                "outline_width": 0,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.15,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.0,
                "animation": "Slide Up",
                "bold": False,
                "summary": "Light, modern caption with almost no stroke and a gentle slide/fade entrance.",
            },
            "custom": {
                "label": "Custom",
                "font_name": "Segoe UI",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFD400",
                "outline_color": "#000000",
                "outline_width": 3,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.3,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.6,
                "animation": "Pop In",
                "bold": True,
                "auto_keyword_highlight": False,
                "highlight_mode": "Auto",
                "summary": "Your editable working preset. Manual style changes can switch here automatically.",
            },
        }
        return presets.get(preset, presets["tiktok"]).copy()

    def parse_srt_to_segments(self, srt_text):
        return parse_srt_to_segments(srt_text)

    def validate_srt_text(self, srt_text, expected_len=None):
        return validate_srt_text(srt_text, expected_len=expected_len)

    def extract_subtitle_text_entries(self, srt_text):
        return extract_subtitle_text_entries(srt_text)

    def format_to_srt(self, segments):
        return format_segments_to_srt(segments)

    def format_timestamp(self, seconds):
        return format_timestamp(seconds)

    def setup_ui(self):
        build_main_window_ui(self)

    def _run_deferred_startup_stage1(self):
        if getattr(self, "_deferred_startup_stage1_done", False):
            return
        self._deferred_startup_stage1_done = True
        self.setup_audio_preview_player()
        self.load_user_settings()
        self.refresh_saved_subtitle_style_presets()

    def _run_deferred_startup_stage2(self):
        if getattr(self, "_deferred_startup_stage2_done", False):
            return
        self._deferred_startup_stage2_done = True
        self.load_voice_preview_catalog()
        self.ensure_local_translator_auto_configured()

    def ensure_media_backend_ready(self):
        if getattr(self, "_media_backend_ready", False):
            return
        self.setup_media_player()
        if hasattr(self, "video_view") and hasattr(self.video_view, "blurRegionChanged"):
            if getattr(self, "_blur_region_signal_bound", False):
                try:
                    self.video_view.blurRegionChanged.disconnect(self.on_preview_blur_region_changed)
                except Exception:
                    pass
            self.video_view.blurRegionChanged.connect(self.on_preview_blur_region_changed)
            self._blur_region_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "blurEditFinished"):
            if getattr(self, "_blur_edit_finished_signal_bound", False):
                try:
                    self.video_view.blurEditFinished.disconnect(self.on_blur_edit_finished)
                except Exception:
                    pass
            self.video_view.blurEditFinished.connect(self.on_blur_edit_finished)
            self._blur_edit_finished_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "subtitlePositionChanged"):
            if not getattr(self, "_subtitle_position_drag_signal_bound", False):
                self.video_view.subtitlePositionChanged.connect(self.on_subtitle_position_dragged)
                self._subtitle_position_drag_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "textLayerSelected"):
            if not getattr(self, "_text_layer_signal_bound", False):
                self.video_view.textLayerSelected.connect(self._on_text_layer_selected_from_preview)
                self.video_view.textLayerMoved.connect(self._on_text_layer_moved)
                self._text_layer_signal_bound = True

    def _on_text_layer_selected_from_preview(self, layer_id):
        if hasattr(self, "timeline"):
            self.timeline._selected_layer_id = str(layer_id)
            self.timeline._redraw()
        self.on_timeline_layer_selected(str(layer_id))

    def _on_text_layer_moved(self, layer_id, x, y):
        layer = next((item for item in self._text_layers() if item.id == layer_id), None)
        if layer is None:
            return
        layer.transform.x, layer.transform.y = float(x), float(y)
        self.persist_current_timeline_project_data()

    def _configure_local_voice_mode_ui(self):
        if hasattr(self, "use_free_voice_radio"):
            try:
                self.use_free_voice_radio.setChecked(True)
                self.use_free_voice_radio.setVisible(False)
                self.use_free_voice_radio.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "use_premium_voice_radio"):
            try:
                self.use_premium_voice_radio.setChecked(False)
                self.use_premium_voice_radio.setVisible(False)
                self.use_premium_voice_radio.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "premium_voice_combo"):
            try:
                self.premium_voice_combo.clear()
                self.premium_voice_combo.setVisible(False)
                self.premium_voice_combo.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "preview_voice_btn"):
            try:
                self.preview_voice_btn.setText("Preview voice")
            except Exception:
                pass
        if hasattr(self, "voice_preview_meta_label"):
            try:
                self.voice_preview_meta_label.setText("Generate a short preview audio clip with the selected local voice.")
            except Exception:
                pass

    def setup_audio_preview_player(self):
        if getattr(self, "_preview_audio_signals_bound", False):
            return
        self._preview_audio_signals_bound = True
        self.audio_preview_player = QMediaPlayer(self)
        self.audio_preview_output = QAudioOutput(self)
        self.audio_preview_player.setAudioOutput(self.audio_preview_output)
        self.voice_preview_library_player = QMediaPlayer(self)
        self.voice_preview_library_output = QAudioOutput(self)
        self.voice_preview_library_player.setAudioOutput(self.voice_preview_library_output)
        self.voice_preview_dialog = None
        self._voice_preview_row_buttons = {}

    def _voice_catalog_data_value(self, entry: dict) -> str:
        provider = str(entry.get("provider", "")).strip().lower()
        provider_voice = str(entry.get("provider_voice", "")).strip()
        entry_id = str(entry.get("id", "")).strip()
        if provider == "piper":
            return entry_id
        if provider == "edge":
            return f"edge:{provider_voice or 'vi-VN-HoaiMyNeural'}"
        return ""

    def _voice_provider_label(self, provider: str) -> str:
        provider_key = str(provider or "").strip().lower()
        if provider_key == "piper":
            return "Local"
        if provider_key == "edge":
            return "Edge"
        return str(provider or "Other").strip().title() or "Other"

    def _current_voice_tier(self) -> str:
        return "free"

    def _selected_voice_gender(self) -> str:
        if not hasattr(self, "voice_gender_combo"):
            return "any"
        return str(self.voice_gender_combo.currentText()).strip().lower()

    def _entry_has_preview_media(self, entry: dict | None) -> bool:
        if not entry:
            return False
        return bool(
            entry.get("preview_video_path")
            or entry.get("preview_video_url")
            or entry.get("preview_audio_path")
            or entry.get("preview_audio_url")
        )

    def set_voice_combo_value(self, combo, value):
        target = str(value or "").strip()
        if not combo or not target:
            return
        for index in range(combo.count()):
            item_value = str(combo.itemData(index) or "").strip()
            item_entry_id = str(combo.itemData(index, self.VOICE_ENTRY_ID_ROLE) or "").strip()
            if item_value == target or item_entry_id == target:
                combo.setCurrentIndex(index)
                return

    def _get_previewable_voice_catalog_entry(self):
        return None

    def _update_voice_preview_meta(self):
        if not hasattr(self, "voice_preview_meta_label"):
            return
        total_entries = len(self.voice_catalog_entries or [])
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setVisible(True)
            self.preview_voice_btn.setEnabled(total_entries > 0)
        if total_entries <= 0:
            self.voice_preview_meta_label.setText("No voices are available in the catalog yet.")
            return
        self.voice_preview_meta_label.setText(
            f"Local voices: {total_entries}. Click “Preview voice” to generate a short test clip."
        )

    def _current_voice_engine_key(self) -> str:
        combo = getattr(self, "voice_engine_combo", None)
        if combo is None:
            return "fast"
        return str(combo.currentData() or "fast").strip().lower() or "fast"

    def _resolve_active_voice_name(self, *, persist_new_clone: bool = False) -> str:
        free_value = str(self.free_voice_combo.currentData() or "").strip() if hasattr(self, "free_voice_combo") else ""
        if free_value and free_value.startswith("edge:"):
            return free_value
        if free_value and free_value in getattr(self, "voice_catalog_map", {}):
            return free_value
        target_language = self.get_target_language_code()
        if target_language == "vi" and "ngochuyen" in getattr(self, "voice_catalog_map", {}):
            return "ngochuyen"
        if target_language == "vi" and "vi_VN-vais1000-medium" in getattr(self, "voice_catalog_map", {}):
            return "vi_VN-vais1000-medium"
        if hasattr(self, "free_voice_combo") and self.free_voice_combo.count() > 0:
            fallback_value = str(self.free_voice_combo.itemData(0) or "").strip()
            if fallback_value:
                return fallback_value
            fallback_entry_id = str(self.free_voice_combo.itemData(0, self.VOICE_ENTRY_ID_ROLE) or "").strip()
            if fallback_entry_id:
                return fallback_entry_id
        return ""

    def on_voice_engine_changed(self):
        self._voiceover_force_refresh = True

    def load_voice_preview_catalog(self):
        self._auto_sync_piper_voices_to_catalog()
        self.voice_catalog_entries_all = self.voice_catalog_service.load_catalog()
        self._apply_piper_voice_meta_overrides()
        if self.voice_preview_dialog is not None:
            self.voice_preview_dialog.close()
            self.voice_preview_dialog = None
        self.refresh_voice_catalog_combos()

    def _load_piper_voice_meta(self) -> dict:
        meta_path = models_path("piper", "voices_meta.json")
        if not os.path.exists(meta_path):
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return {}
            voices = payload.get("voices", {})
            return voices if isinstance(voices, dict) else {}
        except Exception:
            return {}

    def _normalize_gender_value(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        if raw in {"m", "male", "nam"}:
            return "male"
        if raw in {"f", "female", "nu", "ná»¯"}:
            return "female"
        if raw in {"any", "unknown", "none"}:
            return ""
        return raw

    def _voice_gender_sort_rank(self, value: str) -> int:
        normalized = self._normalize_gender_value(value)
        if normalized == "female":
            return 0
        if normalized == "male":
            return 1
        return 2

    def _voice_entry_sort_key(self, entry: dict) -> tuple:
        provider = str(entry.get("provider", "")).strip().lower()
        name = str(entry.get("name", entry.get("id", ""))).strip().lower()
        return (
            self._voice_gender_sort_rank(str(entry.get("gender", ""))),
            0 if provider == "edge" else 1,
            name,
        )

    def _apply_piper_voice_meta_overrides(self):
        voices_meta = self._load_piper_voice_meta()
        if not voices_meta:
            return
        for entry in self.voice_catalog_entries_all or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("provider", "")).strip().lower() != "piper":
                continue
            voice_id = str(entry.get("id", "")).strip()
            if not voice_id:
                continue
            meta = voices_meta.get(voice_id, {})
            if not isinstance(meta, dict):
                continue
            if "gender" in meta:
                entry["gender"] = self._normalize_gender_value(meta.get("gender", ""))

    def _auto_sync_piper_voices_to_catalog(self):
        model_directories = (
            (models_path("piper"), "models/piper"),
            (models_path("piper-en"), "models/piper-en"),
        )
        if not any(os.path.isdir(path) for path, _relative_path in model_directories):
            return
        catalog_path = app_path("voice_preview_catalog.json")
        os.makedirs(os.path.dirname(catalog_path), exist_ok=True)

        def titleize(voice_id: str) -> str:
            stem = str(voice_id or "").strip()
            if not stem:
                return "Voice"
            if re.match(r"^[a-z]{2}_[A-Z]{2}-", stem):
                return stem
            text = re.sub(r"[_-]+", " ", stem, flags=re.UNICODE).strip()
            text = re.sub(r"\s+", " ", text, flags=re.UNICODE)
            parts = [p for p in text.split(" ") if p]
            out = []
            for part in parts:
                if any(ch.isdigit() for ch in part):
                    out.append(part)
                else:
                    out.append(part[:1].upper() + part[1:].lower())
            return " ".join(out) if out else stem

        def language_from_piper_config(model_path: str) -> str:
            cfg_path = f"{model_path}.json"
            if not os.path.exists(cfg_path):
                return ""
            try:
                with open(cfg_path, "r", encoding="utf-8", errors="ignore") as handle:
                    head = handle.read(16384)
            except Exception:
                return ""
            match = re.search(
                r"\"espeak\"\\s*:\\s*{[^}]*\"voice\"\\s*:\\s*\"([^\"]+)\"",
                head,
                flags=re.IGNORECASE | re.DOTALL,
            )
            voice = (match.group(1).strip() if match else "").lower()
            if not voice:
                return ""
            return re.split(r"[-_]", voice, 1)[0].strip().lower()

        def provider_voice_for_model(model_path: str, relative_dir: str) -> str:
            return f"{relative_dir}/{os.path.basename(model_path)}"

        try:
            if os.path.exists(catalog_path):
                with open(catalog_path, "r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle) or {}
            else:
                payload = {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", 2)
        payload.setdefault("voices", [])
        voices = list(payload.get("voices", []) or [])

        by_id = {}
        for entry in voices:
            if isinstance(entry, dict) and entry.get("id"):
                by_id[str(entry.get("id")).strip()] = entry

        model_paths = []
        for models_dir, relative_dir in model_directories:
            if not os.path.isdir(models_dir):
                continue
            model_paths.extend(
                (os.path.join(models_dir, name), relative_dir)
                for name in os.listdir(models_dir)
                if name.lower().endswith(".onnx")
            )
        model_paths.sort(key=lambda item: (item[1], os.path.basename(item[0]).lower()))
        changed = False
        model_ids = set()
        if not model_paths:
            # No models => remove all Piper voices from catalog (keep non-piper voices like Edge).
            new_voices = []
            for entry in voices:
                if not isinstance(entry, dict):
                    continue
                provider = str(entry.get("provider", "")).strip().lower()
                if provider == "piper":
                    changed = True
                    continue
                new_voices.append(entry)
            if not changed:
                return
            payload["voices"] = new_voices
            try:
                with open(catalog_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
            except Exception as exc:
                try:
                    self.log(f"[Voice Catalog] Auto-sync Piper failed: {exc}")
                except Exception:
                    pass
            return

        for model_path, relative_dir in model_paths:
            voice_id = os.path.splitext(os.path.basename(model_path))[0]
            model_ids.add(voice_id)
            pv = provider_voice_for_model(model_path, relative_dir)
            lang = language_from_piper_config(model_path) or "vi"

            existing = by_id.get(voice_id)
            if isinstance(existing, dict) and str(existing.get("provider", "")).strip().lower() == "piper":
                if str(existing.get("provider_voice", "")).strip() != pv:
                    existing["provider_voice"] = pv
                    changed = True
                if not str(existing.get("language", "")).strip():
                    existing["language"] = lang
                    changed = True
                for key in ("preview_audio_url", "preview_audio_path", "preview_video_url", "preview_video_path"):
                    if key not in existing:
                        existing[key] = ""
                        changed = True
                if "tier" not in existing:
                    existing["tier"] = "free"
                    changed = True
                if "enabled" not in existing:
                    existing["enabled"] = True
                    changed = True
                if "tags" not in existing:
                    existing["tags"] = ["local", "piper"]
                    changed = True
                continue

            if voice_id == "vi_VN-vais1000-medium":
                name = "Vais1000 Medium (Local)"
            else:
                name = f"{titleize(voice_id)} (Local)"
            voices.append(
                {
                    "id": voice_id,
                    "name": name,
                    "provider": "piper",
                    "provider_voice": pv,
                    "language": lang,
                    "gender": "",
                    "tier": "free",
                    "preview_video_url": "",
                    "preview_video_path": "",
                    "preview_audio_url": "",
                    "preview_audio_path": "",
                    "enabled": True,
                    "tags": ["local", "piper"],
                }
            )
            changed = True

        # Remove Piper entries whose models were deleted.
        new_voices = []
        for entry in voices:
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider == "piper":
                entry_id = str(entry.get("id", "")).strip()
                if not entry_id or entry_id not in model_ids:
                    changed = True
                    continue
            new_voices.append(entry)
        voices = new_voices

        if not changed:
            return

        payload["voices"] = voices
        try:
            with open(catalog_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception as exc:
            try:
                self.log(f"[Voice Catalog] Auto-sync Piper failed: {exc}")
            except Exception:
                pass

    def refresh_voice_catalog_combos(self):
        self.voice_catalog_entries = []
        target_language = self.get_target_language_code()
        for entry in (self.voice_catalog_entries_all or []):
            if not entry or not isinstance(entry, dict):
                continue
            if not entry.get("enabled", True):
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider not in {"piper", "edge"}:
                continue
            entry_language = str(entry.get("language", "")).strip().lower().split("-", 1)[0]
            if entry_language and entry_language != target_language:
                continue
            self.voice_catalog_entries.append(entry)
        self.voice_catalog_entries.sort(key=self._voice_entry_sort_key)
        self.voice_catalog_map = {entry.get("id", ""): entry for entry in self.voice_catalog_entries if entry.get("id")}
        if not hasattr(self, "free_voice_combo"):
            return

        selected_gender = self._selected_voice_gender()
        previous_free = str(self.free_voice_combo.currentData() or "")

        self.free_voice_combo.clear()
        for entry in self.voice_catalog_entries:
            entry_gender = str(entry.get("gender", "")).strip().lower()
            if selected_gender in ("male", "female") and entry_gender not in (selected_gender, "any", ""):
                continue
            self.free_voice_combo.addItem(
                str(entry.get("name", entry.get("id", "Voice"))),
                self._voice_catalog_data_value(entry),
            )
            index = self.free_voice_combo.count() - 1
            self.free_voice_combo.setItemData(index, entry.get("id", ""), self.VOICE_ENTRY_ID_ROLE)

        if self.free_voice_combo.count() > 0:
            self.free_voice_combo.setCurrentIndex(0)
        if previous_free:
            self.set_voice_combo_value(self.free_voice_combo, previous_free)
        elif target_language == "vi" and "ngochuyen" in self.voice_catalog_map:
            self.set_voice_combo_value(self.free_voice_combo, "ngochuyen")
        elif target_language == "vi" and "vi_VN-vais1000-medium" in self.voice_catalog_map:
            self.set_voice_combo_value(self.free_voice_combo, "vi_VN-vais1000-medium")
        if not self._voice_signals_bound:
            self._voice_signals_bound = True
        self.on_voice_tier_changed()
        self._update_voice_preview_meta()

    def on_voice_gender_changed(self):
        self.refresh_voice_catalog_combos()

    def on_target_language_changed(self, _index: int = -1):
        """Show and select only local voices that match the output language."""
        self._voiceover_force_refresh = True
        if getattr(self, "voice_catalog_entries_all", None):
            self.refresh_voice_catalog_combos()

    def on_selected_voice_changed(self):
        self._update_voice_preview_meta()
        self._preload_active_voice_if_needed()

    def _preload_active_voice_if_needed(self):
        voice_name = self.get_active_voice_name()
        if not voice_name:
            return
        if str(voice_name).startswith("f5:"):
            return
        entry_id = str(self.free_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE) or '').strip() if hasattr(self, 'free_voice_combo') else ''
        entry = self.voice_catalog_map.get(entry_id) if hasattr(self, 'voice_catalog_map') else None
        provider = str((entry or {}).get('provider', '')).strip().lower()
        if provider != 'piper':
            return
        current_token = voice_name.strip()
        if getattr(self, '_voice_preload_inflight', '') == current_token or getattr(self, '_voice_preloaded_name', '') == current_token:
            return

        self._voice_preload_inflight = current_token

        def _worker(expected_voice: str):
            try:
                self._preload_tts_voice_impl(expected_voice)
                def _mark_ready():
                    if getattr(self, '_voice_preload_inflight', '') == expected_voice:
                        self._voice_preload_inflight = ''
                        self._voice_preloaded_name = expected_voice
                        self.log(f"[Voice] Piper voice preloaded: {expected_voice}")
                QTimer.singleShot(0, _mark_ready)
            except Exception as exc:
                def _mark_failed():
                    if getattr(self, '_voice_preload_inflight', '') == expected_voice:
                        self._voice_preload_inflight = ''
                        self.log(f"[Voice] Piper preload skipped: {exc}")
                QTimer.singleShot(0, _mark_failed)

        threading.Thread(target=_worker, args=(current_token,), daemon=True).start()

    def get_selected_premium_voice_catalog_entry(self):
        if not hasattr(self, "premium_voice_combo"):
            return None
        if not hasattr(self, "voice_catalog_entries"):
            return None
        entry_id = self.premium_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE)
        if entry_id and entry_id in self.voice_catalog_map:
            return self.voice_catalog_map[entry_id]
        current_value = str(self.premium_voice_combo.currentData() or "")
        for entry in self.voice_catalog_entries:
            if self._voice_catalog_data_value(entry) == current_value:
                return entry
        return None

    def get_active_voice_name(self) -> str:
        return self._resolve_active_voice_name(persist_new_clone=False)

    def on_voice_tier_changed(self):
        mode = self.get_output_mode_key() if hasattr(self, "output_mode_combo") else "both"
        if hasattr(self, "free_voice_combo"):
            self.free_voice_combo.setEnabled(True)
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setVisible(mode in ("voice", "both"))
        self._update_voice_preview_meta()

    def _parse_voice_speed_value(self) -> float:
        raw = str(getattr(self, "voice_speed_spin", None).currentText() if getattr(self, "voice_speed_spin", None) else "1.0x").strip().lower()
        raw = raw.replace("x", "")
        try:
            return float(raw or "1.0")
        except ValueError:
            return 1.0

    def _percent_to_db(self, percent: int) -> float:
        """Convert volume percentage (0-200) to dB gain."""
        if percent <= 0:
            return -60.0
        import math
        return 20.0 * math.log10(percent / 100.0)

    # -----------------------------
    # Logging + error helpers
    # -----------------------------
    def log(self, message: str):
        log_message_impl(self, message)

    def clear_log(self):
        clear_log_impl(self)

    def _register_progress_dialog(self, dialog):
        if dialog is None:
            return
        self._tracked_progress_dialogs = [d for d in self._tracked_progress_dialogs if d is not None]
        if dialog not in self._tracked_progress_dialogs:
            self._tracked_progress_dialogs.append(dialog)
            try:
                dialog.destroyed.connect(lambda *_args, dlg=dialog: self._unregister_progress_dialog(dlg))
            except Exception:
                pass
        self._update_progress_reopen_button()

    def _unregister_progress_dialog(self, dialog):
        self._tracked_progress_dialogs = [d for d in self._tracked_progress_dialogs if d is not dialog]
        self._update_progress_reopen_button()

    def _active_progress_dialogs(self):
        active = []
        for dialog in list(getattr(self, "_tracked_progress_dialogs", []) or []):
            if dialog is None:
                continue
            try:
                if dialog.isVisible():
                    active.append(dialog)
                    continue
                if getattr(dialog, "isHidden", None) and not dialog.isHidden():
                    active.append(dialog)
            except Exception:
                continue
        return active

    def _update_progress_reopen_button(self):
        button = getattr(self, "show_progress_btn", None)
        if button is None:
            return
        tracked = [d for d in getattr(self, "_tracked_progress_dialogs", []) if d is not None]
        button.setVisible(bool(tracked))
        button.setEnabled(bool(tracked))

    def show_active_progress_dialog(self):
        dialogs = [d for d in getattr(self, "_tracked_progress_dialogs", []) if d is not None]
        if not dialogs:
            self._update_progress_reopen_button()
            return
        dialog = dialogs[-1]
        try:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception:
            pass
        self._update_progress_reopen_button()

    def _resource_service(self) -> ResourceDownloadService:
        return ResourceDownloadService(self.workspace_root)

    def _open_vietdict_folder(self, resource_id: str):
        from runtime_paths import models_path
        dir_path = models_path("vietnormalizer")
        os.makedirs(dir_path, exist_ok=True)
        os.startfile(dir_path)

    def _create_vietdict_template(self, resource_id: str):
        import csv
        from runtime_paths import models_path
        dir_path = models_path("vietnormalizer")
        os.makedirs(dir_path, exist_ok=True)

        acronyms_path = os.path.join(dir_path, "acronyms.csv")
        if not os.path.exists(acronyms_path):
            with open(acronyms_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["acronym", "transliteration"])
                w.writerow(["vtv", "vô tuyến truyền hình"])
                w.writerow(["CLB", "câu lạc bộ"])
            print(f"[VietDict] Created template: {acronyms_path}")

        nonvn_path = os.path.join(dir_path, "non-vietnamese-words.csv")
        if not os.path.exists(nonvn_path):
            with open(nonvn_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["original", "transliteration"])
                w.writerow(["iPhone", "ai phôn"])
            print(f"[VietDict] Created template: {nonvn_path}")

        os.startfile(dir_path)

    def _vietdict_add_row(self, table):
        from PySide6.QtWidgets import QTableWidgetItem
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem(""))
        table.setItem(r, 1, QTableWidgetItem(""))
        table.scrollToBottom()

    def _vietdict_remove_row(self, table):
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for r in rows:
            table.removeRow(r)

    def open_normalizer_dict_dialog(self):
        import csv
        from pathlib import Path
        from runtime_paths import models_path
        custom_dir = Path(models_path("vietnormalizer"))
        custom_dir.mkdir(parents=True, exist_ok=True)

        DICT_DEFS = [
            {"label": "Acronyms", "file": "acronyms.csv", "col_a": "acronym", "col_b": "transliteration"},
            {"label": "Non-Vietnamese Words", "file": "non-vietnamese-words.csv", "col_a": "original", "col_b": "transliteration"},
        ]

        dialog = QDialog(self)
        dialog.setWindowTitle("Normalizer Dictionary")
        dialog.setModal(True)
        dialog.resize(700, 520)
        dialog.setStyleSheet("""
            QDialog { background-color: #0f1724; }
            QLabel { color: #d7e3f4; background-color: transparent; }
            QTableWidget { background-color: #132033; color: #d7e3f4; gridline-color: #2f4868;
                border: 1px solid #2f4868; border-radius: 8px; font-size: 13px; }
            QTableWidget::item:selected { background-color: #29405d; color: #f8fbff; }
            QHeaderView::section { background-color: #1a2c44; color: #8ad7ff; border: none;
                padding: 6px 8px; font-weight: 700; font-size: 12px; }
            QPushButton { background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
                border-radius: 8px; padding: 6px 16px; font-weight: 600; }
            QPushButton:hover { background-color: #29405d; }
            QPushButton#dangerBtn { background-color: #5a1a1a; border-color: #8b2a2a; }
            QPushButton#dangerBtn:hover { background-color: #7a2828; }
            QPushButton#primaryBtn { background-color: #1a4a5a; border-color: #2a6a8b; }
            QPushButton#primaryBtn:hover { background-color: #1e5a6e; }
            QTabWidget::pane { border: 1px solid #2f4868; background-color: #0f1724; border-radius: 8px; }
            QTabBar::tab { background-color: #1a2c44; color: #9fb3ca; padding: 8px 20px; border: 1px solid #2f4868;
                border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #132033; color: #8ad7ff; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Manage Normalizer Dictionary", dialog)
        title.setStyleSheet("color: #f8fbff; font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        hint = QLabel(f"Dictionary location: {custom_dir}\nEntries here override built-in normalizer rules.", dialog)
        hint.setStyleSheet("color: #9fb3ca; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        from PySide6.QtWidgets import QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
        tabs = QTabWidget(dialog)
        layout.addWidget(tabs, 1)

        tables = {}

        for defn in DICT_DEFS:
            tab = QWidget(dialog)
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            tab_layout.setSpacing(8)

            table = QTableWidget(0, 2, dialog)
            table.setHorizontalHeaderLabels([defn["col_a"].title(), defn["col_b"].title()])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.verticalHeader().setVisible(False)
            tab_layout.addWidget(table, 1)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            add_btn = QPushButton("+ Add Row", dialog)
            remove_btn = QPushButton("Remove Selected", dialog)
            remove_btn.setObjectName("dangerBtn")
            btn_row.addWidget(add_btn)
            btn_row.addWidget(remove_btn)
            btn_row.addStretch()
            tab_layout.addLayout(btn_row)

            add_btn.clicked.connect(lambda _checked=False, t=table: self._vietdict_add_row(t))
            remove_btn.clicked.connect(lambda _checked=False, t=table: self._vietdict_remove_row(t))

            tables[defn["file"]] = {"table": table, "defn": defn}
            tabs.addTab(tab, defn["label"])

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch()

        save_btn = QPushButton("Save All", dialog)
        save_btn.setObjectName("primaryBtn")
        close_btn = QPushButton("Close", dialog)
        close_btn.clicked.connect(dialog.accept)
        bottom_row.addWidget(save_btn)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

        def _load_all():
            for fname, meta in tables.items():
                file_path = custom_dir / fname
                table = meta["table"]
                table.setRowCount(0)
                if file_path.exists():
                    try:
                        with open(file_path, encoding="utf-8", newline="") as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                a = (row.get(meta["defn"]["col_a"]) or "").strip()
                                b = (row.get(meta["defn"]["col_b"]) or "").strip()
                                if a or b:
                                    r = table.rowCount()
                                    table.insertRow(r)
                                    table.setItem(r, 0, QTableWidgetItem(a))
                                    table.setItem(r, 1, QTableWidgetItem(b))
                    except Exception:
                        pass

        def _save_all():
            for fname, meta in tables.items():
                file_path = custom_dir / fname
                table = meta["table"]
                rows = []
                for r in range(table.rowCount()):
                    a = (table.item(r, 0).text() if table.item(r, 0) else "").strip()
                    b = (table.item(r, 1).text() if table.item(r, 1) else "").strip()
                    if a or b:
                        rows.append({meta["defn"]["col_a"]: a, meta["defn"]["col_b"]: b})
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=[meta["defn"]["col_a"], meta["defn"]["col_b"]])
                    w.writeheader()
                    w.writerows(rows)
            print("[VietDict] Dictionary saved.")

        save_btn.clicked.connect(_save_all)

        _load_all()
        dialog.exec()

    def _missing_resource_entries(self, *, include_whisper: bool = False, include_voice: bool = False) -> list[tuple[str, str]]:
        service = self._resource_service()
        missing: list[tuple[str, str]] = []

        if include_whisper and not is_remote_profile():
            engine = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower()
            if engine == "sensevoice":
                if not service.is_resource_installed("sensevoice:model"):
                    missing.append(("sensevoice:model", "SenseVoice model"))
            else:
                model_name = self.get_whisper_model_name()
                resource_id = f"whisper:{model_name}"
                if not service.is_resource_installed(resource_id):
                    missing.append((resource_id, f"Whisper {model_name.title()} model"))

        if include_voice and not is_remote_profile():
            voice_name = self.get_active_voice_name()
            if voice_name and not str(voice_name).startswith("edge:") and not str(voice_name).startswith("f5:"):
                resource_id = f"voice:{voice_name}"
                if not service.is_resource_installed(resource_id):
                    voice_label = voice_name
                    voice_entry = self.voice_catalog_map.get(voice_name) if hasattr(self, "voice_catalog_map") else None
                    if isinstance(voice_entry, dict):
                        voice_label = str(voice_entry.get("name", voice_name)).strip() or voice_name
                    missing.append((resource_id, f"Local voice: {voice_label}"))

        deduped: list[tuple[str, str]] = []
        seen = set()
        for item in missing:
            if item[0] in seen:
                continue
            seen.add(item[0])
            deduped.append(item)
        return deduped

    def ensure_required_resources(self, action_label: str, *, include_whisper: bool = False, include_voice: bool = False) -> bool:
        missing = self._missing_resource_entries(include_whisper=include_whisper, include_voice=include_voice)
        if not missing:
            return True

        missing_lines = "\n".join(f"- {label}" for _resource_id, label in missing)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Missing Resources")
        box.setText(f"{action_label} cannot start because some required resources are missing.")
        box.setInformativeText(
            "Open Manage Resources for download links and target folders:\n\n"
            f"{missing_lines}"
        )
        open_btn = box.addButton("Manage Resources", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_resource_manager_dialog()
        return False

    def open_resource_manager_dialog(self):
        from views.resource_manager import open_resource_manager
        open_resource_manager(
            self.workspace_root,
            parent=self,
            on_finished=lambda: self._on_resource_download_complete(),
        )

    def _on_resource_download_complete(self):
        try:
            self.load_voice_preview_catalog()
        except Exception:
            pass
        self.refresh_ui_state()

    def show_error(self, title: str, short_msg: str, details: str = ""):
        show_error_impl(self, title, short_msg, details)

    def stabilize_button(self, button: QPushButton, min_width: int = 220, min_height: int = 42):
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(min_height)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def make_helper_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("helperLabel")
        return label

    def using_existing_audio_source(self) -> bool:
        mixed_path = self._normalize_local_file_path(
            self.mixed_audio_edit.text().strip() if hasattr(self, "mixed_audio_edit") else ""
        )
        use_existing = bool(hasattr(self, "use_existing_audio_radio") and self.use_existing_audio_radio.isChecked())
        return bool(use_existing and mixed_path and os.path.exists(mixed_path))

    def _normalize_local_file_path(self, path: str) -> str:
        value = str(path or "").replace("\r", "").replace("\n", "").replace("\t", " ").strip().strip('"').strip("'")
        if not value:
            return ""

        value = os.path.expandvars(os.path.expanduser(value))
        candidates = []
        if os.path.isabs(value):
            candidates.append(value)
        else:
            candidates.append(os.path.join(self.workspace_root, value))
            current_project = getattr(self, "current_project_state", None)
            if current_project and getattr(current_project, "project_root", ""):
                candidates.append(os.path.join(current_project.project_root, value))
            candidates.append(os.path.join(self.workspace_root, value))

        for candidate in candidates:
            normalized = os.path.normpath(os.path.abspath(candidate))
            if os.path.exists(normalized):
                return normalized

        fallback = candidates[0] if candidates else value
        return os.path.normpath(os.path.abspath(fallback))

    def resolve_selected_audio_path(self) -> str:
        if self.using_existing_audio_source():
            return self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
        candidates = [
            self.processed_artifacts.get("mixed_vi"),
            self.last_mixed_vi_path,
            self.last_voice_vi_path,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""

    def _resolve_preview_voice_only_audio_path(self) -> str:
        if self.using_existing_audio_source():
            return ""
        candidates = [
            self.processed_artifacts.get("voice_vi"),
            self.last_voice_vi_path,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""

    def _resolve_preview_background_audio_path(self) -> str:
        audio_mode_key = str(self.get_audio_handling_mode() or "fast").strip().lower()
        if audio_mode_key == "clean":
            candidates = [self.last_music_path]
        else:
            candidates = [
                self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
                self.processed_artifacts.get("audio_extracted"),
                self.last_extracted_audio,
                self.last_music_path,
            ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""

    def _resolve_preview_mixed_audio_path(self) -> str:
        if self.using_existing_audio_source():
            audio_path = self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
            return audio_path if audio_path and os.path.exists(audio_path) else ""
        voice_only = self._resolve_preview_voice_only_audio_path()
        background_audio = self._resolve_preview_background_audio_path()
        if not voice_only or not background_audio:
            return ""

        try:
            voice_stat = os.stat(voice_only)
            background_stat = os.stat(background_audio)
        except OSError:
            return ""

        segments = list(self.get_active_segments() or [])
        audio_mode_key = str(self.get_audio_handling_mode() or "fast").strip().lower()
        original_volume = int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50
        dub_volume = int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100
        signature_payload = {
            "voice": os.path.abspath(voice_only),
            "voice_size": int(voice_stat.st_size),
            "voice_mtime_ns": int(getattr(voice_stat, "st_mtime_ns", int(voice_stat.st_mtime * 1_000_000_000))),
            "background": os.path.abspath(background_audio),
            "background_size": int(background_stat.st_size),
            "background_mtime_ns": int(getattr(background_stat, "st_mtime_ns", int(background_stat.st_mtime * 1_000_000_000))),
            "audio_mode": audio_mode_key,
            "original_volume": original_volume,
            "dub_volume": dub_volume,
            "segments": [
                {
                    "start": round(float(seg.get("start", 0.0)), 3),
                    "end": round(float(seg.get("end", 0.0)), 3),
                }
                for seg in segments
            ],
        }
        mix_hash = hashlib.sha1(json.dumps(signature_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        output_path = os.path.join(self.get_workspace_temp_root(create=True), f"timeline_preview_mix_{mix_hash}.wav")
        if os.path.exists(output_path):
            return output_path

        try:
            from audio_mixer import mix_original_with_dub
            original_gain_db = self._percent_to_db(original_volume)
            dub_gain_db = self._percent_to_db(dub_volume)
            mix_original_with_dub(
                original_wav_path=background_audio,
                dub_wav_path=voice_only,
                output_wav_path=output_path,
                original_gain_db=original_gain_db,
                dub_gain_db=dub_gain_db,
            )
        except Exception as exc:
            self.log(f"[Preview] timeline mix fallback to voice-only: {exc}")
            return ""
        return output_path

    def resolve_timeline_audio_visualization_path(self) -> str:
        preview_mode = str(getattr(self, "_preview_audio_track_mode", "original") or "original").strip().lower()
        if preview_mode == "original":
            candidates = [
                self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
                self.processed_artifacts.get("vocals"),
                self.processed_artifacts.get("audio_extracted"),
                self.last_vocals_path,
                self.last_extracted_audio,
            ]
            for candidate in candidates:
                normalized = self._normalize_local_file_path(candidate)
                if normalized and os.path.exists(normalized):
                    return normalized

        dubbed_audio_kind, dubbed_audio = self._resolve_preview_dubbed_playback_source()
        if dubbed_audio_kind in ("mixed", "voice") and dubbed_audio and os.path.exists(dubbed_audio):
            return dubbed_audio

        candidates = [
            self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
            self.processed_artifacts.get("vocals"),
            self.processed_artifacts.get("audio_extracted"),
            self.last_vocals_path,
            self.last_extracted_audio,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""

    def _resolve_preview_original_video_path(self) -> str:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        normalized = self._normalize_local_file_path(video_path)
        return normalized if normalized and os.path.exists(normalized) else ""

    def _resolve_preview_dubbed_audio_path(self) -> str:
        mixed_audio = self._resolve_preview_mixed_audio_path()
        if mixed_audio:
            return mixed_audio
        return self._resolve_preview_voice_only_audio_path()

    def _has_preview_dubbed_audio_source(self) -> bool:
        if self.using_existing_audio_source():
            audio_path = self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
            return bool(audio_path and os.path.exists(audio_path))
        return bool(self._resolve_preview_voice_only_audio_path())

    def _timeline_audio_track_mutes(self) -> tuple[bool, bool] | None:
        if not hasattr(self, "timeline") or not getattr(self.timeline, "_timeline", None):
            return None
        a1_muted = None
        a2_muted = None
        for track in self.timeline._timeline.tracks:
            if track.name == "A1 Audio":
                a1_muted = bool(track.muted)
            elif track.name in ("A2 Dub", "TS1"):
                a2_muted = bool(track.muted)
        if a1_muted is None and a2_muted is None:
            return None
        return bool(a1_muted), bool(a2_muted)

    def _resolve_preview_dubbed_playback_source(self) -> tuple[str, str]:
        """Resolve which audio file represents the dubbed track in preview.

        For preview we want PURE TTS (voice_vi) so the user hears only
        the new dub voice with natural gaps between segments. The mixed
        (TTS+background) version is only used for final export.

        Returns ("voice", path) | ("mixed", path) | ("original", "").
        """
        track_mutes = self._timeline_audio_track_mutes()
        voice_only = self._resolve_preview_voice_only_audio_path()
        mixed_audio = self._resolve_preview_mixed_audio_path()

        if not track_mutes:
            if voice_only:
                return "voice", voice_only
            if mixed_audio:
                return "mixed", mixed_audio
            return "original", ""

        a1_muted, a2_muted = track_mutes
        if a2_muted:
            return "original", ""
        # Prefer pure TTS for preview in all other cases.
        if voice_only:
            return "voice", voice_only
        if mixed_audio:
            return "mixed", mixed_audio
        return "original", ""

    def _preview_audio_track_choices(self) -> list[tuple[str, str]]:
        choices = [("Original Audio", "original")]
        if self._has_preview_dubbed_audio_source():
            choices.append(("Dub Voice", "dubbed"))
        return choices

    def _preferred_preview_audio_track_mode(self) -> str:
        track_mutes = self._timeline_audio_track_mutes()
        if track_mutes:
            _a1_muted, a2_muted = track_mutes
            if a2_muted:
                return "original"
        mode = str(self.get_output_mode_key() or "subtitle").strip().lower()
        if mode in ("voice", "both"):
            if self._has_preview_dubbed_audio_source():
                return "dubbed"
        return "original"

    def sync_preview_audio_track_to_output(self, *, apply_to_player: bool = True):
        target_mode = self._preferred_preview_audio_track_mode()
        self._preview_audio_track_mode = target_mode

        if not apply_to_player or not getattr(self, "media_player", None):
            return

        source_video = self._resolve_preview_original_video_path()
        current_source = self._normalize_local_file_path(str(getattr(self.media_player, "_source_path", "") or ""))
        should_apply = not current_source
        if source_video and current_source:
            should_apply = os.path.abspath(current_source) == os.path.abspath(source_video)

        if should_apply:
            self._apply_preview_audio_track_selection()
            return

    def _apply_preview_audio_track_selection(self):
        if (
            getattr(self, "_preview_audio_track_switching", False)
            or not hasattr(self, "media_player")
            or not getattr(self, "media_player", None)
        ):
            return
        source_video = self._resolve_preview_original_video_path()
        if not source_video:
            return

        # Always load BOTH the original audio file (extracted audio) and
        # the dubbed audio file as separate sidecar streams. Per-track mute
        # is controlled by the timeline track labels (A1 Original / A2 Dub).
        dubbed_audio_kind, dubbed_audio = self._resolve_preview_dubbed_playback_source()
        if not dubbed_audio or dubbed_audio_kind == "original":
            dubbed_audio = ""
        original_audio = self._resolve_preview_original_audio_path()

        try:
            current_position = int(self.media_player.position())
        except Exception:
            current_position = 0
        try:
            was_playing = bool(self.media_player.is_playing())
        except Exception:
            was_playing = False

        current_source = str(getattr(self.media_player, "_source_path", "") or "")
        should_reset_source = not current_source or os.path.abspath(current_source) != os.path.abspath(source_video)

        self._preview_audio_track_switching = True
        try:
            if should_reset_source:
                try:
                    self.media_player.pause()
                except Exception:
                    pass
                self.media_player.setSource(QUrl.fromLocalFile(source_video))
                self.refresh_video_dimensions(source_video)
                self._preview_video_has_burned_subtitles = False
                self.sync_live_subtitle_preview()
            # Always load the original audio sidecar when available
            if hasattr(self.media_player, "set_original_audio_file"):
                if original_audio:
                    self.media_player.set_original_audio_file(original_audio)
                else:
                    try:
                        self.media_player._clear_original_audio()
                    except Exception:
                        pass
            if dubbed_audio:
                self.media_player.set_audio_file(dubbed_audio)
            else:
                self.media_player.clear_audio()
            if current_position > 0:
                try:
                    self.media_player.setPosition(current_position)
                except Exception:
                    pass
            if was_playing:
                try:
                    self.media_player.play()
                    if hasattr(self, "timeline"):
                        self.timeline.set_playing(True)
                except Exception:
                    pass
            else:
                if hasattr(self, "timeline"):
                    self.timeline.set_playing(False)
            # Only log the preview audio state when at least one audio sidecar
            # was actually applied. Logging "silent" on a freshly opened
            # video (no generate/voice done yet) is misleading noise —
            # Bug 3.
            if original_audio or dubbed_audio:
                active_label = "both" if (original_audio and dubbed_audio) else (
                    "dubbed" if dubbed_audio else "original"
                )
                self.log(f"[Preview] audio: {active_label}")
        finally:
            self._preview_audio_track_switching = False
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)

    def _resolve_preview_original_audio_path(self) -> str:
        """Resolve the original audio file path (separate from source video).

        Fast mode: full extracted audio (vocals + music)
        Clean mode: background stem only (no vocals, to avoid double voices)
        Fallback: extracted_audio artifact
        """
        audio_mode = str(self.get_audio_handling_mode() or "fast").strip().lower()
        candidates: list[str] = []
        if audio_mode == "clean":
            candidates.extend([
                self.last_music_path,
                self.processed_artifacts.get("music"),
            ])
        candidates.extend([
            self.processed_artifacts.get("extracted_audio"),
            self.last_extracted_audio,
            self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
        ])
        for candidate in candidates:
            if not candidate:
                continue
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        # Final fallback: the source video file itself. mpv runs with
        # `ao=null` (video-only) and audio is routed through the A1
        # QMediaPlayer sidecar, so on a freshly opened video (no Generate
        # run yet, no extracted audio artifact) the sidecar would be empty
        # and the user hears nothing. QMediaPlayer decodes the audio
        # track straight out of a video container, so loading the source
        # video into the A1 sidecar restores the original audio. Once the
        # pipeline extracts a dedicated audio file, that takes priority
        # via the candidates above.
        source_video = self._resolve_preview_original_video_path()
        if source_video:
            return source_video
        return ""

    def on_preview_audio_track_changed(self, index: int):
        if getattr(self, "_preview_audio_track_switching", False) or not hasattr(self, "preview_audio_track_combo"):
            return
        mode = str(self.preview_audio_track_combo.itemData(index) or "original").strip().lower()
        self._preview_audio_track_mode = mode if mode in ("original", "dubbed") else "original"
        self._apply_preview_audio_track_selection()

    def _waveform_temp_path(self) -> str:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if not video_path:
            return ""
        video_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:12]
        return os.path.join(self.get_workspace_temp_root(create=True), f"waveform_{video_hash}.wav")

    def _timeline_waveform_request_signature(self):
        audio_path = self.resolve_timeline_audio_visualization_path()
        if audio_path and os.path.exists(audio_path):
            try:
                stat = os.stat(audio_path)
                return (
                    "v2-envelope",
                    "audio",
                    os.path.abspath(audio_path),
                    int(stat.st_size),
                    int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                )
            except Exception:
                return ("v2-envelope", "audio", os.path.abspath(audio_path), 0, 0)

        video_path = self._normalize_local_file_path(self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else "")
        if video_path and os.path.exists(video_path):
            try:
                stat = os.stat(video_path)
                return (
                    "v2-envelope",
                    "video-fallback",
                    os.path.abspath(video_path),
                    int(stat.st_size),
                    int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                    str(getattr(self, "_preview_audio_track_mode", "original") or "original"),
                )
            except Exception:
                return (
                    "v2-envelope",
                    "video-fallback",
                    os.path.abspath(video_path),
                    0,
                    0,
                    str(getattr(self, "_preview_audio_track_mode", "original") or "original"),
                )
        return None

    def _timeline_thumbnail_request_signature(self):
        video_path = self._normalize_local_file_path(self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else "")
        duration_s = max(0.0, float(getattr(self.timeline, "duration", 0) or 0) / 1000.0) if hasattr(self, "timeline") else 0.0
        if not video_path or not os.path.exists(video_path) or duration_s <= 0.0:
            return None
        try:
            stat = os.stat(video_path)
            return (
                os.path.abspath(video_path),
                int(stat.st_size),
                int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                int(round(duration_s)),
            )
        except Exception:
            return (os.path.abspath(video_path), 0, 0, int(round(duration_s)))

    def refresh_timeline_waveform(self):
        if not hasattr(self, "timeline"):
            print("[Timeline] no timeline widget")
            return
        self._desired_timeline_waveform_request = None
        self._timeline_waveform_cache_key = None
        self._timeline_waveform_samples = []
        self._timeline_waveform_duration_s = 0.0
        self.timeline.set_waveform_data([], 0.0)

    def _on_timeline_waveform_ready(self, request_signature, waveform, duration_s, error):
        self._timeline_waveform_worker = None
        if request_signature != self._desired_timeline_waveform_request:
            self.refresh_timeline_waveform()
            return
        if error:
            print(f"[Timeline] waveform generation failed: {error}")
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = []
            self._timeline_waveform_duration_s = 0.0
        else:
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = list(waveform or [])
            self._timeline_waveform_duration_s = max(0.0, float(duration_s or 0.0))
            print(
                f"[Timeline] waveform generated: samples={len(self._timeline_waveform_samples)} "
                f"duration={self._timeline_waveform_duration_s:.1f}s"
            )
        if hasattr(self, "timeline"):
            self.timeline.set_waveform_data(self._timeline_waveform_samples, self._timeline_waveform_duration_s)

    def schedule_timeline_visual_refresh(self, *, waveform: bool = True, thumbnails: bool = True, delay_ms: int = 40):
        if not bool(getattr(self, "_allow_post_pipeline_preview_assets", False)):
            return
        if waveform:
            self._pending_timeline_waveform_refresh = True
        if thumbnails:
            self._pending_timeline_thumbnail_refresh = True
        timer = getattr(self, "_timeline_visual_refresh_timer", None)
        if timer is None:
            self._run_pending_timeline_visual_refresh()
            return
        timer.start(max(0, int(delay_ms)))

    def _run_pending_timeline_visual_refresh(self):
        refresh_waveform = bool(getattr(self, "_pending_timeline_waveform_refresh", False))
        refresh_thumbnails = bool(getattr(self, "_pending_timeline_thumbnail_refresh", False))
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        if refresh_waveform:
            self.refresh_timeline_waveform()
        if refresh_thumbnails:
            self.refresh_timeline_video_thumbnails()

    def refresh_timeline_video_thumbnails(self):
        if not hasattr(self, "timeline"):
            return
        # Timeline thumbnails are disabled to keep long videos lightweight.
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self.timeline.set_video_thumbnails([])
        self._desired_timeline_thumbnail_request = None
        return

    def _on_timeline_video_thumbnails_ready(self, request_signature, thumbnails, error):
        self._timeline_thumbnail_worker = None
        if request_signature != self._desired_timeline_thumbnail_request:
            self.refresh_timeline_video_thumbnails()
            return
        if error:
            print(f"[Timeline] thumbnail generation failed: {error}")
            self._timeline_video_thumb_cache_key = request_signature
            self._timeline_video_thumbnails = []
        else:
            pixmaps = []
            for timestamp_s, output_path in list(thumbnails or []):
                pixmap = QPixmap(str(output_path or ""))
                if not pixmap.isNull():
                    pixmaps.append((float(timestamp_s), pixmap))
            self._timeline_video_thumb_cache_key = request_signature
            self._timeline_video_thumbnails = pixmaps
        if hasattr(self, "timeline"):
            self.timeline.set_video_thumbnails(self._timeline_video_thumbnails)

    def on_audio_source_mode_changed(self):
        if not hasattr(self, "audio_source_hint_label"):
            return
        using_existing = bool(hasattr(self, "use_existing_audio_radio") and self.use_existing_audio_radio.isChecked())
        if using_existing:
            self.audio_source_hint_label.setText(
                "Use a completed audio file for preview and export. TTS and background-audio settings are not used."
            )
        else:
            self.audio_source_hint_label.setText(
                "Create a voice from translated subtitles. You can optionally mix in background audio."
            )
        generated_panel = getattr(self, "generated_audio_source_panel", None)
        if generated_panel:
            generated_panel.setVisible(not using_existing)
        existing_panel = getattr(self, "existing_audio_source_panel", None)
        if existing_panel:
            existing_panel.setVisible(using_existing)
        generated_widgets = [
            "generated_audio_section_label",
            "generated_audio_section_hint",
            "bg_music_label",
            "bg_music_edit",
            "browse_bg_music_btn",
            "voiceover_btn",
        ]
        existing_widgets = [
            "existing_audio_section_label",
            "existing_audio_section_hint",
            "mixed_audio_label",
            "mixed_audio_edit",
            "browse_mixed_audio_btn",
        ]
        for name in generated_widgets:
            widget = getattr(self, name, None)
            if widget:
                widget.setEnabled(not using_existing)
        for name in existing_widgets:
            widget = getattr(self, name, None)
            if widget:
                widget.setEnabled(using_existing)
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.refresh_ui_state()

    def on_advanced_toggled(self, checked: bool):
        if hasattr(self, "tabs"):
            self.tabs.setVisible(True)
        if hasattr(self, "workflow_advanced_layout"):
            checked = True
        if hasattr(self, "toggle_advanced_btn"):
            self.toggle_advanced_btn.setText(("▼ " if checked else "▶ ") + "Advanced Settings")
        if hasattr(self, "advanced_section_content"):
            self.advanced_section_content.setVisible(bool(checked))

    def on_auto_preview_toggled(self, checked: bool):
        if checked:
            self.schedule_auto_frame_preview()
        else:
            self.auto_frame_preview_timer.stop()
            self.seek_frame_preview_timer.stop()

    def schedule_live_subtitle_preview_refresh(self):
        if not hasattr(self, "live_subtitle_preview_timer"):
            return
        self.live_subtitle_preview_timer.start()

    def refresh_live_subtitle_preview(self):
        self.live_preview_segments, self.live_preview_editor_name = self._resolve_live_preview_segments()
        self.sync_live_subtitle_preview()

    def schedule_live_video_filter_preview(self):
        if not hasattr(self, "video_filter_preview_timer"):
            return
        self._pending_video_filter_preview = True
        if getattr(self, "_styled_preview_running", False):
            return
        self.video_filter_preview_timer.start()

    def _is_video_filter_slider_interacting(self):
        sliders = [getattr(self, "video_filter_intensity_slider", None)]
        sliders.extend(list(getattr(self, "video_filter_adjust_sliders", {}).values()))
        for slider in sliders:
            if slider is not None and slider.isSliderDown():
                return True
        return False

    def on_video_filter_slider_released(self):
        self.schedule_live_video_filter_preview()

    def is_filter_workflow_active(self) -> bool:
        stack = getattr(self, "left_panel_stack", None)
        if stack is None:
            return False
        try:
            return int(stack.currentIndex()) == 4
        except Exception:
            return False

    def _mark_video_filter_preview_dirty(self):
        self._video_filter_preview_dirty = self.has_active_video_filters()
        self._video_filter_apply_requested = False
        self.refresh_ui_state()

    def apply_current_video_filter(self):
        self.log(f"[Filter] apply_current_video_filter called, has_active={self.has_active_video_filters()}")
        if not self.has_active_video_filters():
            self.log("[Filter] No active filters, returning early")
            self._video_filter_preview_dirty = False
            self._video_filter_apply_requested = False
            self.hide_filter_thumbnail_preview()
            self.refresh_ui_state()
            return
        self._video_filter_apply_requested = True
        self.refresh_ui_state()
        self.log("[Filter] Calling preview_controller.preview_video()")
        self.preview_controller.preview_video()

    def revert_video_filter_preview_to_source(self):
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if not video_path or not os.path.exists(video_path):
            return
        self._play_video_filter_preview_when_ready = False
        self.hide_filter_thumbnail_preview()
        try:
            current_position = int(self.media_player.position())
        except Exception:
            current_position = 0
        try:
            self.media_player.pause()
        except Exception:
            pass
        try:
            self.media_player.setSource(QUrl.fromLocalFile(video_path))
            if current_position > 0:
                self.media_player.setPosition(current_position)
        except Exception:
            pass
        self.refresh_video_dimensions(video_path)
        self._preview_video_has_burned_subtitles = False
        self.sync_live_subtitle_preview()
        if hasattr(self, "timeline"):
            self.timeline.set_playing(False)
        self.refresh_ui_state()

    def _can_auto_render_filter_preview(self):
        video_path = self.video_path_edit.text().strip()
        if not video_path or not os.path.exists(video_path):
            return False
        if getattr(self, "_styled_preview_running", False) or getattr(self, "_pipeline_active", False):
            return False
        if self.has_active_video_filters():
            return True
        mode = self.get_output_mode_key()
        if mode == "subtitle":
            return bool(self.last_translated_srt_path and os.path.exists(self.last_translated_srt_path))
        if mode == "voice":
            audio_path = self.resolve_selected_audio_path()
            return bool(audio_path and os.path.exists(audio_path))
        if mode == "both":
            audio_path = self.resolve_selected_audio_path()
            return bool(
                audio_path
                and os.path.exists(audio_path)
                and self.last_translated_srt_path
                and os.path.exists(self.last_translated_srt_path)
            )
        return False

    def run_live_video_filter_preview(self):
        if getattr(self, "_styled_preview_running", False) or getattr(self, "_frame_preview_running", False):
            return
        if not getattr(self, "_pending_video_filter_preview", False):
            return
        if not self.has_active_video_filters():
            self._pending_video_filter_preview = False
            self.hide_filter_thumbnail_preview()
            return
        if not self._can_auto_render_filter_preview():
            self._pending_video_filter_preview = False
            return
        self._pending_video_filter_preview = False
        try:
            self.preview_controller.start_exact_frame_preview(show_dialog=False)
        except Exception as exc:
            self.log(f"[Filter Preview] skipped: {exc}")

    def save_user_settings(self):
        save_user_settings_impl(self)
        try:
            self.settings.setValue("premium_voice_name", "")
            self.settings.setValue("premium_voice_value", "")
            self.settings.setValue("voice_tier", "free")
        except Exception:
            pass

    def load_user_settings(self):
        load_user_settings_impl(self)
        if hasattr(self, "use_premium_voice_radio"):
            try:
                self.use_premium_voice_radio.setChecked(False)
            except Exception:
                pass
        if hasattr(self, "use_free_voice_radio"):
            try:
                self.use_free_voice_radio.setChecked(True)
            except Exception:
                pass

    def ensure_local_translator_auto_configured(self):
        provider = str(os.getenv("AI_POLISHER_PROVIDER") or "").strip().lower()
        if provider != "local":
            return

        managed_keys = [
            "LOCAL_TRANSLATOR_N_CTX",
            "LOCAL_TRANSLATOR_N_THREADS",
            "LOCAL_TRANSLATOR_N_THREADS_BATCH",
            "LOCAL_TRANSLATOR_N_BATCH",
            "LOCAL_TRANSLATOR_N_UBATCH",
            "LOCAL_TRANSLATOR_GPU_LAYERS",
            "LOCAL_TRANSLATOR_FLASH_ATTN",
        ]
        if all(str(os.getenv(key) or "").strip() for key in managed_keys):
            return

        LocalPolisherProvider = self._local_polisher_provider_cls()
        hardware_info = LocalPolisherProvider.detect_runtime_capabilities()
        recommended = LocalPolisherProvider.recommended_runtime_config(hardware_info)
        updates = {
            "LOCAL_TRANSLATOR_N_CTX": str(recommended["n_ctx"]),
            "LOCAL_TRANSLATOR_N_THREADS": str(recommended["n_threads"]),
            "LOCAL_TRANSLATOR_N_THREADS_BATCH": str(recommended["n_threads_batch"]),
            "LOCAL_TRANSLATOR_N_BATCH": str(recommended["n_batch"]),
            "LOCAL_TRANSLATOR_N_UBATCH": str(recommended["n_ubatch"]),
            "LOCAL_TRANSLATOR_GPU_LAYERS": str(recommended["gpu_layers"]),
            "LOCAL_TRANSLATOR_FLASH_ATTN": "true" if recommended["flash_attn"] else "false",
        }

        env_lines = []
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as handle:
                env_lines = handle.readlines()

        new_env_lines = []
        handled_keys = set()
        for line in env_lines:
            match = re.match(r"^([^=]+)=.*", line)
            if match:
                key = match.group(1).strip()
                if key in updates:
                    new_env_lines.append(f"{key}={updates[key]}\n")
                    handled_keys.add(key)
                    continue
            new_env_lines.append(line)

        for key, value in updates.items():
            if key not in handled_keys:
                new_env_lines.append(f"{key}={value}\n")

        with open(".env", "w", encoding="utf-8") as handle:
            handle.writelines(new_env_lines)

        for key, value in updates.items():
            os.environ[key] = value

        if hasattr(self, "log"):
            self.log(f"[Local AI] Auto-optimized for this machine: {LocalPolisherProvider.runtime_status_summary(hardware_info)}")

    @staticmethod
    def _local_polisher_provider_cls():
        from translation.providers.local_polisher import LocalPolisherProvider

        return LocalPolisherProvider

    @staticmethod
    def _preload_tts_voice_impl(voice_name: str):
        from tts_processor import preload_tts_voice

        return preload_tts_voice(voice_name)

    @staticmethod
    def _test_remote_api_connection(base_url: str, token: str) -> dict:
        previous_url = os.environ.get("CAPCAP_REMOTE_API_URL", "")
        previous_token = os.environ.get("CAPCAP_REMOTE_API_TOKEN", "")
        try:
            os.environ["CAPCAP_REMOTE_API_URL"] = (base_url or "").strip()
            if token:
                os.environ["CAPCAP_REMOTE_API_TOKEN"] = token.strip()
            else:
                os.environ.pop("CAPCAP_REMOTE_API_TOKEN", None)
            from remote_api import remote_api_get

            return remote_api_get("/health", timeout=10)
        finally:
            if previous_url:
                os.environ["CAPCAP_REMOTE_API_URL"] = previous_url
            else:
                os.environ.pop("CAPCAP_REMOTE_API_URL", None)
            if previous_token:
                os.environ["CAPCAP_REMOTE_API_TOKEN"] = previous_token
            else:
                os.environ.pop("CAPCAP_REMOTE_API_TOKEN", None)

    def _highlight_color_hex(self) -> str:
        mapping = {
            "Yellow": "#FFD400",
            "Cyan": "#00E5FF",
            "Green": "#5CFF95",
            "Pink": "#FF6BD6",
        }
        return mapping.get(self.subtitle_highlight_color_combo.currentText().strip(), "#FFD400")

    def is_custom_subtitle_position_mode(self) -> bool:
        if not hasattr(self, "subtitle_position_mode_combo"):
            return False
        return str(self.subtitle_position_mode_combo.currentData() or "anchor").strip().lower() == "custom"

    def on_subtitle_position_mode_changed(self, *_args):
        is_custom = self.is_custom_subtitle_position_mode()
        if hasattr(self, "subtitle_align_label"):
            self.subtitle_align_label.setVisible(not is_custom)
        if hasattr(self, "subtitle_align_combo"):
            self.subtitle_align_combo.setVisible(not is_custom)
        if hasattr(self, "subtitle_custom_x_label"):
            self.subtitle_custom_x_label.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_x_spin"):
            self.subtitle_custom_x_spin.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_y_label"):
            self.subtitle_custom_y_label.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_y_spin"):
            self.subtitle_custom_y_spin.setVisible(is_custom)
        if hasattr(self, "subtitle_bottom_offset_label"):
            self.subtitle_bottom_offset_label.setVisible(not is_custom)
        if hasattr(self, "subtitle_bottom_offset_spin"):
            self.subtitle_bottom_offset_spin.setVisible(not is_custom)
        self.update_subtitle_preview_style()

    def on_subtitle_drag_started(self):
        """Swap to the Qt layer only while dragging for immediate feedback."""
        if getattr(self, "_preview_video_has_burned_subtitles", False):
            return
        if hasattr(self, "media_player"):
            self.media_player.clear_subtitle()
        if hasattr(self, "video_view"):
            self.video_view.subtitle_item.set_text_rendering(True)

    def on_subtitle_position_dragged(self, x_percent: int, y_percent: int):
        """Commit a drag from the live subtitle overlay to style controls."""
        x_percent = max(0, min(100, int(x_percent)))
        y_percent = max(0, min(100, int(y_percent)))
        if hasattr(self, "subtitle_position_mode_combo"):
            self.subtitle_position_mode_combo.blockSignals(True)
            index = self.subtitle_position_mode_combo.findData("custom")
            if index >= 0:
                self.subtitle_position_mode_combo.setCurrentIndex(index)
            self.subtitle_position_mode_combo.blockSignals(False)
        for widget, value in (
            (getattr(self, "subtitle_custom_x_spin", None), x_percent),
            (getattr(self, "subtitle_custom_y_spin", None), y_percent),
        ):
            if widget is not None:
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.on_subtitle_position_mode_changed()

    def get_subtitle_position_config(self) -> dict:
        alignment_map = {
            "Bottom Left": 1,
            "Bottom Center": 2,
            "Bottom": 2,
            "Bottom Right": 3,
            "Center": 5,
            "Top Center": 8,
            "Top": 8,
        }
        return {
            "position_mode": "custom" if self.is_custom_subtitle_position_mode() else "anchor",
            "alignment_label": self.subtitle_align_combo.currentText().strip(),
            "alignment": alignment_map.get(self.subtitle_align_combo.currentText(), 2),
            "margin_v": int(self.subtitle_bottom_offset_spin.value()),
            "x_offset": int(self.subtitle_x_offset_spin.value()),
            "custom_position_enabled": self.is_custom_subtitle_position_mode(),
            "custom_position_x": int(self.subtitle_custom_x_spin.value()),
            "custom_position_y": int(self.subtitle_custom_y_spin.value()),
        }

    def _saved_subtitle_style_payload(self) -> dict:
        return {
            "preset": self.get_selected_subtitle_preset(),
            "font": self.subtitle_font_combo.currentText().strip(),
            "size": int(self.subtitle_font_size_spin.value()),
            "color": self.subtitle_color_hex,
            "background_color": getattr(self, "subtitle_background_color_hex", "#000000"),
            "animation": self.subtitle_animation_combo.currentText().strip(),
            "animation_time": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "background": bool(self.subtitle_background_cb.isChecked()),
            "outline": bool(getattr(self, "subtitle_outline_cb", None) and self.subtitle_outline_cb.isChecked()),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else 0.6,
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked()),
            "highlight_color": self.subtitle_highlight_color_combo.currentText().strip(),
            "highlight_mode": self.subtitle_highlight_mode_combo.currentText().strip(),
        }

    def _current_subtitle_style_controls_state(self) -> dict:
        return {
            "font": self.subtitle_font_combo.currentText().strip(),
            "size": int(self.subtitle_font_size_spin.value()),
            "color": self.subtitle_color_hex,
            "background_color": getattr(self, "subtitle_background_color_hex", "#000000"),
            "animation": self.subtitle_animation_combo.currentText().strip(),
            "animation_time": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "background": bool(self.subtitle_background_cb.isChecked()),
            "outline": bool(getattr(self, "subtitle_outline_cb", None) and self.subtitle_outline_cb.isChecked()),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else 0.6,
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked()),
            "highlight_color": self.subtitle_highlight_color_combo.currentText().strip(),
            "highlight_mode": self.subtitle_highlight_mode_combo.currentText().strip(),
            "single_line": bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()),
        }

    def _apply_subtitle_style_controls_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        self.subtitle_font_combo.setCurrentText(str(state.get("font", self.subtitle_font_combo.currentText())))
        self.subtitle_font_size_spin.setValue(int(state.get("size", self.subtitle_font_size_spin.value())))
        self.subtitle_color_hex = str(state.get("color", self.subtitle_color_hex)).upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.subtitle_background_color_hex = str(
            state.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))
        ).upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.subtitle_animation_combo.setCurrentText(str(state.get("animation", self.subtitle_animation_combo.currentText())))
        self.subtitle_animation_time_spin.setValue(float(state.get("animation_time", self.subtitle_animation_time_spin.value())))
        karaoke_mode = str(state.get("karaoke_timing_mode", self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"))
        karaoke_index = self.subtitle_karaoke_timing_combo.findData(karaoke_mode)
        if karaoke_index >= 0:
            self.subtitle_karaoke_timing_combo.setCurrentIndex(karaoke_index)
        self.subtitle_background_cb.setChecked(bool(state.get("background", self.subtitle_background_cb.isChecked())))
        if hasattr(self, "subtitle_outline_cb"):
            self.subtitle_outline_cb.setChecked(bool(state.get("outline", self.subtitle_outline_cb.isChecked())))
        if hasattr(self, "subtitle_bg_alpha_spin"):
            self.subtitle_bg_alpha_spin.setValue(float(state.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
        self.subtitle_bold_cb.setChecked(bool(state.get("bold", self.subtitle_bold_cb.isChecked())))
        self.subtitle_keyword_highlight_cb.setChecked(
            bool(state.get("auto_keyword_highlight", self.subtitle_keyword_highlight_cb.isChecked()))
        )
        self.subtitle_highlight_color_combo.setCurrentText(
            str(state.get("highlight_color", self.subtitle_highlight_color_combo.currentText()))
        )
        self.subtitle_highlight_mode_combo.setCurrentText(
            str(state.get("highlight_mode", self.subtitle_highlight_mode_combo.currentText()))
        )
        if hasattr(self, "subtitle_single_line_cb"):
            self.subtitle_single_line_cb.setChecked(bool(state.get("single_line", self.subtitle_single_line_cb.isChecked())))

    def _capture_subtitle_custom_style_state(self) -> None:
        self._subtitle_custom_style_state = self._current_subtitle_style_controls_state()

    def on_subtitle_style_control_edited(self, *_args):
        if getattr(self, "_subtitle_preset_apply_in_progress", False):
            return
        self._capture_subtitle_custom_style_state()
        custom_radio = getattr(self, "subtitle_preset_custom_radio", None)
        if custom_radio is not None and not custom_radio.isChecked():
            custom_radio.blockSignals(True)
            custom_radio.setChecked(True)
            custom_radio.blockSignals(False)
            self.on_subtitle_preset_changed()

    def _read_saved_subtitle_style_presets(self) -> dict:
        raw_value = self.settings.value("saved_subtitle_styles", "{}")
        try:
            parsed = json.loads(raw_value) if isinstance(raw_value, str) else dict(raw_value)
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def refresh_saved_subtitle_style_presets(self):
        if not hasattr(self, "saved_subtitle_style_combo"):
            return
        saved = self._read_saved_subtitle_style_presets()
        self.saved_subtitle_style_combo.blockSignals(True)
        self.saved_subtitle_style_combo.clear()
        self.saved_subtitle_style_combo.addItem("My Presets", "")
        for name in sorted(saved.keys(), key=str.lower):
            self.saved_subtitle_style_combo.addItem(name, name)
        self.saved_subtitle_style_combo.setCurrentIndex(0)
        self.saved_subtitle_style_combo.blockSignals(False)

    def save_current_subtitle_style_preset(self):
        name, ok = QInputDialog.getText(self, "Save Style", "Preset name:")
        if not ok or not (name or "").strip():
            return
        preset_name = name.strip()
        saved = self._read_saved_subtitle_style_presets()
        saved[preset_name] = self._saved_subtitle_style_payload()
        self.settings.setValue("saved_subtitle_styles", json.dumps(saved, ensure_ascii=False))
        self.refresh_saved_subtitle_style_presets()
        idx = self.saved_subtitle_style_combo.findData(preset_name)
        if idx >= 0:
            self.saved_subtitle_style_combo.setCurrentIndex(idx)

    def load_selected_subtitle_style_preset(self, index: int):
        if index <= 0:
            return
        preset_name = self.saved_subtitle_style_combo.itemData(index)
        saved = self._read_saved_subtitle_style_presets()
        preset = saved.get(preset_name or "")
        if not isinstance(preset, dict):
            return

        key = str(preset.get("preset", "tiktok")).lower()
        if key == "youtube":
            self.subtitle_preset_youtube_radio.setChecked(True)
        elif key == "minimal":
            self.subtitle_preset_minimal_radio.setChecked(True)
        elif key == "custom" and getattr(self, "subtitle_preset_custom_radio", None):
            self.subtitle_preset_custom_radio.setChecked(True)
        else:
            self.subtitle_preset_tiktok_radio.setChecked(True)

        self.subtitle_font_combo.setCurrentText(str(preset.get("font", self.subtitle_font_combo.currentText())))
        self.subtitle_font_size_spin.setValue(int(preset.get("size", self.subtitle_font_size_spin.value())))
        self.subtitle_color_hex = str(preset.get("color", self.subtitle_color_hex)).upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.subtitle_background_color_hex = str(preset.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))).upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.subtitle_animation_combo.setCurrentText(str(preset.get("animation", self.subtitle_animation_combo.currentText())))
        self.subtitle_animation_time_spin.setValue(float(preset.get("animation_time", self.subtitle_animation_time_spin.value())))
        karaoke_mode = str(preset.get("karaoke_timing_mode", self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"))
        karaoke_index = self.subtitle_karaoke_timing_combo.findData(karaoke_mode)
        if karaoke_index >= 0:
            self.subtitle_karaoke_timing_combo.setCurrentIndex(karaoke_index)
        self.subtitle_background_cb.setChecked(bool(preset.get("background", self.subtitle_background_cb.isChecked())))
        if hasattr(self, "subtitle_outline_cb"):
            self.subtitle_outline_cb.setChecked(bool(preset.get("outline", self.subtitle_outline_cb.isChecked())))
        if hasattr(self, "subtitle_bg_alpha_spin"):
            self.subtitle_bg_alpha_spin.setValue(float(preset.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
        self.subtitle_bold_cb.setChecked(bool(preset.get("bold", self.subtitle_bold_cb.isChecked())))
        self.subtitle_keyword_highlight_cb.setChecked(bool(preset.get("auto_keyword_highlight", self.subtitle_keyword_highlight_cb.isChecked())))
        self.subtitle_highlight_color_combo.setCurrentText(str(preset.get("highlight_color", self.subtitle_highlight_color_combo.currentText())))
        self.subtitle_highlight_mode_combo.setCurrentText(str(preset.get("highlight_mode", self.subtitle_highlight_mode_combo.currentText())))
        self._capture_subtitle_custom_style_state()
        self.on_subtitle_preset_changed()

    def ensure_current_project(self):
        video_path = self.video_path_edit.text().strip()
        state = self.project_bridge.ensure_project(
            video_path=video_path,
            mode=self.get_output_mode_key(),
            translator_ai=self.is_ai_polish_enabled(),
            input_language=self.get_source_language_code(),
            target_language=self.get_target_language_code(),
        )
        if not state:
            return None
        audio_handling_mode = self.get_audio_handling_mode()
        if str(state.settings.get("audio_handling_mode", "fast")).strip().lower() != audio_handling_mode:
            state.set_setting("audio_handling_mode", audio_handling_mode)
            self.project_service.save_project(state)
        self.current_project_state = state
        self.processed_artifacts.update(state.artifacts)
        return state

    def update_project_step(self, step_name: str, status: str):
        state = self.ensure_current_project()
        if not state:
            return
        self.project_bridge.update_step(state, step_name, status)

    def update_project_artifact(self, artifact_name: str, path: str):
        state = self.ensure_current_project()
        if not state or not path:
            return
        normalized_path = self._normalize_local_file_path(path)
        self.processed_artifacts[artifact_name] = normalized_path
        self.project_bridge.update_artifact(state, artifact_name, normalized_path)

    def _dict_segments_to_models(self, segments, *, translated=False):
        return self.project_bridge.dict_segments_to_models(segments, translated=translated)

    def _sync_segment_models_from_current_segments(self):
        self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
        self.current_translated_segment_models = self._dict_segments_to_models(
            self.current_translated_segments,
            translated=True,
        )

    def persist_transcription_project_data(self, raw_segments, srt_path=""):
        state = self.ensure_current_project()
        if not state:
            return
        self.current_segment_models = self.project_bridge.persist_transcription(state, raw_segments, srt_path)

    def persist_translation_project_data(self, translated_segments, srt_path=""):
        state = self.ensure_current_project()
        if not state:
            return
        self.current_translated_segment_models = self.project_bridge.persist_translation(
            state,
            self.current_segment_models,
            translated_segments,
            srt_path,
        )
        signature = self.build_current_translation_signature()
        if signature:
            state.set_setting("translation_signature", signature)
            self.project_service.save_project(state)

    def build_current_translation_signature(self, source_segments=None):
        base_segments = list(source_segments or self.current_segments or [])
        if not base_segments:
            transcript_text = self.transcript_text.toPlainText().strip() if hasattr(self, "transcript_text") else ""
            if transcript_text:
                base_segments = self.parse_srt_to_segments(transcript_text)
        if not base_segments:
            return ""
        return self.project_service.build_translation_signature(
            base_segments,
            src_lang=self.get_source_language_code(),
            target_lang=self.get_target_language_code(),
            enable_polish=self.is_ai_polish_enabled(),
            optimize_subtitles=False,
            style_instruction=self.get_ai_style_instruction(),
        )

    def build_current_voice_signature(self, segments=None, background_path=""):
        voice_segments = list(segments or [])
        if not voice_segments:
            voice_segments = self._get_voiceover_segments()
        if not voice_segments:
            return ""
        return self.project_service.build_voice_signature(
            voice_segments,
            audio_handling_mode=self.get_audio_handling_mode(),
            voice_name=self.get_active_voice_name(),
            voice_speed=self._parse_voice_speed_value(),
            timing_sync_mode=str(self.voice_timing_sync_combo.currentText()).strip(),
            background_path=background_path,
            original_volume=int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50,
            dub_volume=int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100,
        )

    def persist_current_timeline_project_data(self):
        state = self.ensure_current_project()
        if not state:
            return
        if self.current_segments:
            self.current_segment_models = self.project_bridge.persist_transcription(
                state,
                self.current_segments,
                self.last_original_srt_path,
            )
        if self.current_translated_segments:
            self.current_translated_segment_models = self.project_bridge.persist_translation(
                state,
                self.current_segment_models,
                self.current_translated_segments,
                self.last_translated_srt_path,
            )
            signature = self.build_current_translation_signature()
            if signature:
                state.set_setting("translation_signature", signature)
        if self.current_project_state:
            voice_signature = self.build_current_voice_signature(
                segments=self._get_voiceover_segments(),
                background_path=self.resolve_background_audio_path(),
            )
            if voice_signature:
                state.set_setting("voice_signature", voice_signature)
        
        # Save timeline data (includes mask and logo layers)
        if hasattr(self, "timeline") and self.timeline._timeline:
            import json
            timeline_data = self.timeline._timeline.to_dict()
            # Save timeline to a file in the project directory
            timeline_path = os.path.join(state.project_root, "timeline", "timeline.json")
            os.makedirs(os.path.dirname(timeline_path), exist_ok=True)
            with open(timeline_path, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, ensure_ascii=False, indent=2)
            state.set_artifact("timeline", timeline_path)
        
        self.project_service.save_project(state)

    def _cache_core_timeline_tracks_only(self):
        """Keep only V1, A1, and TS1 when a video session is closed.

        Optional editing tracks remain fully usable (and exportable) during
        the active session. They are deliberately not retained in the
        reopen cache, preventing Blur/Logo/Mask/Text tracks from following
        a video into its next editing session.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        core_track_names = {"V1 Video", "A1 Audio", "TS1"}
        timeline = self.timeline._timeline
        removed = [track for track in timeline.tracks if track.name not in core_track_names]
        if removed:
            timeline.tracks = [track for track in timeline.tracks if track.name in core_track_names]
            for track in removed:
                self.timeline._track_heights.pop(track.id, None)
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            retained_ids = {layer.id for track in timeline.tracks for layer in track.layers}
            if selected_id not in retained_ids:
                self.timeline._selected_layer_id = ""
            self.timeline._redraw()
            self.persist_current_timeline_project_data()
        state = getattr(self, "current_project_state", None)
        if state is not None:
            # Blur and mask also have legacy settings fallbacks. Clear those
            # cache entries so they cannot recreate optional tracks on load.
            state.set_setting("blur_state", {"enabled": False, "regions": []})
            state.set_setting("mask_state", {"enabled": False, "regions": []})
            self.project_service.save_project(state)
        if removed:
            self.log(f"[Timeline Cache] Retained core tracks only; discarded {len(removed)} optional track(s).")

    def load_project_context(self, state):
        if not state:
            return
        self._allow_post_pipeline_preview_assets = False
        audio_handling_mode = str(getattr(state, "settings", {}).get("audio_handling_mode", "") or "").strip().lower()
        if audio_handling_mode and hasattr(self, "audio_handling_combo"):
            combo_index = self.audio_handling_combo.findData(audio_handling_mode)
            if combo_index >= 0:
                self.audio_handling_combo.setCurrentIndex(combo_index)
        context = self.project_bridge.load_context(state)
        self.processed_artifacts = {}
        self.last_original_srt_path = ""
        self.last_translated_srt_path = ""
        self.last_extracted_audio = ""
        self.last_vocals_path = ""
        # Sync timeline track mute -> GUI per-track mute state
        self._sync_timeline_mute_to_gui()
        self.last_music_path = ""
        self.last_voice_vi_path = ""
        self.last_mixed_vi_path = ""
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.current_segments = []
        self.current_translated_segments = []
        if hasattr(self, "audio_source_edit"):
            self.audio_source_edit.clear()
        if hasattr(self, "transcript_text"):
            self.transcript_text.clear()
        if hasattr(self, "translated_text"):
            self.translated_text.clear()
        if hasattr(self, "timeline"):
            self.timeline.set_segments([])
            self.timeline.set_video_thumbnails([])
            self.timeline.set_playing(False)
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self.processed_artifacts.update(context["artifacts"])
        self.last_original_srt_path = self._normalize_local_file_path(context["last_original_srt_path"] or self.last_original_srt_path)
        self.last_translated_srt_path = self._normalize_local_file_path(context["last_translated_srt_path"] or self.last_translated_srt_path)
        self.last_extracted_audio = self._normalize_local_file_path(context["last_extracted_audio"] or self.last_extracted_audio)
        self.last_vocals_path = self._normalize_local_file_path(context["last_vocals_path"] or self.last_vocals_path)
        self.last_music_path = self._normalize_local_file_path(context["last_music_path"] or self.last_music_path)
        self.last_voice_vi_path = self._normalize_local_file_path(context["last_voice_vi_path"] or self.last_voice_vi_path)
        self.last_mixed_vi_path = self._normalize_local_file_path(context["last_mixed_vi_path"] or self.last_mixed_vi_path)
        self.current_segment_models = context["current_segment_models"]
        self.current_translated_segment_models = context["current_translated_segment_models"]
        self.current_segments = context["current_segments"]
        self.current_translated_segments = context["current_translated_segments"]
        if self.current_translated_segments:
            self.refresh_auto_keyword_highlights(force=True)
        if self.get_audio_handling_mode() == "clean" and self.last_vocals_path and os.path.exists(self.last_vocals_path):
            self.audio_source_edit.setText(self.last_vocals_path)
        elif self.last_extracted_audio and os.path.exists(self.last_extracted_audio):
            self.audio_source_edit.setText(self.last_extracted_audio)
        elif self.last_vocals_path and os.path.exists(self.last_vocals_path):
            self.audio_source_edit.setText(self.last_vocals_path)
        if self.current_segments:
            self.transcript_text.setText(self.format_to_srt(self.current_segments))
        if self.current_translated_segments:
            self.translated_text.setText(self.format_to_srt(self.current_translated_segments))
        if self.current_translated_segments or self.current_segments:
            self._enable_post_pipeline_preview_assets(refresh=True)
            self.apply_segments_to_timeline()
            self.set_selected_segment_index(0, sync_ui=True)
        # Restore A2 Dub track if TTS was generated
        voice_path = context.get("artifacts", {}).get("voice_vi", "")
        if voice_path and os.path.exists(voice_path) and hasattr(self, "timeline"):
            self.timeline.sync_tts_track(voice_path, segments=self.current_translated_segments or self.current_segments)
            # Enable Audio tab since voice generation was completed
            if hasattr(self, "audio_tab_btn"):
                self.audio_tab_btn.setEnabled(True)
        self._sync_timeline_mute_to_gui()
        self._update_ocr_overlay()
        # Clear any stale layer selection from the previous project so
        # the inspector does not stay pinned to a track that no longer
        # exists (e.g. a BlurLayer from a previous project that was
        # removed by _restore_project_blur_state).
        if hasattr(self, "timeline"):
            try:
                self.timeline.select_layer("")
            except Exception:
                pass
        self._show_default_inspector()
        self._restore_project_blur_state(state)
        if hasattr(self, "_restore_project_mask_state"):
            try:
                self._restore_project_mask_state(state)
            except Exception:
                pass
        # Force the dual-track sidecar player to re-initialize for this
        # project. Without this, reopening a project would leave the
        # original/dubbed QMediaPlayer sidecars pointing at the previous
        # project's audio files (or empty), so the user hears nothing
        # until they press Generate.
        try:
            if hasattr(self, "sync_preview_audio_track_to_output"):
                self.sync_preview_audio_track_to_output(apply_to_player=True)
        except Exception:
            pass
        # Stop any active playback so the user re-presses Play after
        # reopening. Otherwise mpv / QMediaPlayer may keep playing the
        # previous source.
        try:
            if hasattr(self, "media_player") and self.media_player is not None:
                self.media_player.pause()
        except Exception:
            pass

    def _enable_post_pipeline_preview_assets(self, *, refresh: bool = True):
        self._allow_post_pipeline_preview_assets = True
        if refresh:
            self.refresh_timeline_waveform()
            self.refresh_timeline_video_thumbnails()

    def resolve_background_audio_path(self) -> str:
        manual_candidate = self.bg_music_edit.text().strip() if hasattr(self, "bg_music_edit") else ""
        if manual_candidate:
            normalized = self._normalize_local_file_path(manual_candidate)
            if normalized and os.path.exists(normalized):
                self.last_music_path = normalized
                self.processed_artifacts["music"] = normalized
                return normalized

        audio_mode = self.get_audio_handling_mode()
        state_artifacts = getattr(getattr(self, "current_project_state", None), "artifacts", {}) if getattr(self, "current_project_state", None) else {}
        candidates = []
        if audio_mode == "clean":
            candidates.extend(
                [
                    getattr(self, "last_music_path", ""),
                    state_artifacts.get("music", ""),
                    getattr(self, "last_extracted_audio", ""),
                    state_artifacts.get("extracted_audio", ""),
                ]
            )
        else:
            candidates.extend(
                [
                    getattr(self, "last_extracted_audio", ""),
                    state_artifacts.get("extracted_audio", ""),
                    getattr(self, "last_music_path", ""),
                    state_artifacts.get("music", ""),
                ]
            )
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                if audio_mode == "clean":
                    self.last_music_path = normalized
                    self.processed_artifacts["music"] = normalized
                else:
                    self.processed_artifacts["background_source"] = normalized
                return normalized
        return ""

    def has_reusable_voice_inputs(self) -> bool:
        state = self.ensure_current_project()
        if state and not self.translated_text.toPlainText().strip():
            self.load_project_context(state)
        translated_srt = self.translated_text.toPlainText().strip()
        if not translated_srt:
            return False
        return bool(self.parse_srt_to_segments(translated_srt))

    def schedule_auto_frame_preview(self):
        if not bool(getattr(self, "_allow_post_pipeline_preview_assets", False)):
            return
        if not hasattr(self, "auto_preview_frame_cb") or not self.auto_preview_frame_cb.isChecked():
            return
        if self.auto_preview_frame_cb.isHidden():
            return
        if getattr(self, "_pipeline_active", False):
            return
        if not self.video_path_edit.text().strip() or not self.get_active_segments():
            return
        self.frame_preview_status_label.setText("Refreshing exact frame preview...")
        self.auto_frame_preview_timer.start()

    def trigger_auto_frame_preview(self):
        self.start_exact_frame_preview(show_dialog=False)

    def schedule_seek_frame_preview(self):
        if not bool(getattr(self, "_allow_post_pipeline_preview_assets", False)):
            return
        if not hasattr(self, "auto_preview_frame_cb") or not self.auto_preview_frame_cb.isChecked():
            return
        if self.auto_preview_frame_cb.isHidden():
            return
        if getattr(self, "_pipeline_active", False):
            return
        if self.media_player.is_playing():
            return
        if not self.video_path_edit.text().strip() or not self.get_active_segments():
            return
        self.frame_preview_status_label.setText("Updating exact frame preview for the selected timeline position...")
        self.seek_frame_preview_timer.start()

    def trigger_seek_frame_preview(self):
        if self.media_player.is_playing():
            return
        self.start_exact_frame_preview(show_dialog=False)

    def update_frame_preview_thumbnail(self, image_path: str):
        widget = getattr(self, "frame_preview_image_label", None)
        if widget is not None and hasattr(widget, "set_frame_image"):
            if hasattr(self, "video_view") and self.video_view is not None:
                widget.set_video_dimensions(
                    int(getattr(self.video_view, "video_source_width", 0) or 0),
                    int(getattr(self.video_view, "video_source_height", 0) or 0),
                )
                widget.set_preview_aspect_ratio(getattr(self.video_view, "preview_aspect_key", "source"))
                widget.set_preview_scale_mode(getattr(self.video_view, "preview_scale_mode", "fit"))
                focus_x, focus_y = self.get_output_fill_focus()
                widget.set_preview_fill_focus(focus_x, focus_y)
            widget.set_frame_image(image_path)
            return
        update_frame_preview_thumbnail_impl(self, image_path, QPixmap, Qt)

    def show_filter_thumbnail_preview(self, image_path: str):
        already_visible = bool(getattr(self, "_filter_thumbnail_visible", False))
        self._filter_thumbnail_visible = True
        if already_visible:
            self.update_frame_preview_thumbnail(image_path)
            if hasattr(self, "frame_preview_badge_label"):
                self._position_frame_preview_badge()
                self.frame_preview_badge_label.show()
            return
        self._suspend_preview_region_tools_for_filter()
        if hasattr(self, "preview_context_label"):
            self.preview_context_label.hide()
        if hasattr(self, "frame_preview_status_label"):
            self.frame_preview_status_label.hide()
        if hasattr(self, "frame_preview_image_label"):
            target_height = int(getattr(self, "_filter_thumbnail_target_height", 320) or 320)
            if hasattr(self, "video_view") and self.video_view is not None:
                live_height = int(self.video_view.height() or 0)
                if live_height > 0:
                    target_height = max(320, live_height)
            self._filter_thumbnail_target_height = target_height
            if hasattr(self.frame_preview_image_label, "setMinimumHeight"):
                self.frame_preview_image_label.setMinimumHeight(target_height)
            if hasattr(self.frame_preview_image_label, "setMaximumHeight"):
                self.frame_preview_image_label.setMaximumHeight(target_height)
            self.frame_preview_image_label.show()
        if hasattr(self, "video_view"):
            self.video_view.hide()
        self._force_hide_ocr_overlay_for_filter()
        self.update_frame_preview_thumbnail(image_path)
        if hasattr(self, "frame_preview_badge_label"):
            self._position_frame_preview_badge()
            self.frame_preview_badge_label.show()
        QTimer.singleShot(0, self._force_hide_ocr_overlay_for_filter)

    def hide_filter_thumbnail_preview(self):
        self._filter_thumbnail_visible = False
        if hasattr(self, "frame_preview_badge_label"):
            self.frame_preview_badge_label.hide()
        if hasattr(self, "frame_preview_image_label"):
            if hasattr(self.frame_preview_image_label, "setMinimumHeight"):
                self.frame_preview_image_label.setMinimumHeight(0)
            if hasattr(self.frame_preview_image_label, "setMaximumHeight"):
                self.frame_preview_image_label.setMaximumHeight(16777215)
            if hasattr(self.frame_preview_image_label, "clear_frame_image"):
                self.frame_preview_image_label.clear_frame_image()
            self.frame_preview_image_label.hide()
        if hasattr(self, "frame_preview_status_label"):
            self.frame_preview_status_label.hide()
        if hasattr(self, "preview_context_label"):
            self.preview_context_label.hide()
        if hasattr(self, "video_view"):
            self.video_view.show()
        self._restore_preview_region_tools_after_filter()

    def _suspend_preview_region_tools_for_filter(self):
        self._suspend_ocr_overlay = True
        self._filter_preview_blur_was_checked = bool(
            hasattr(self, "blur_area_btn") and self.blur_area_btn.isChecked()
        )
        overlay = getattr(self, "ocr_region_overlay", None)
        self._filter_preview_ocr_was_editable = bool(getattr(overlay, "_editable", False)) if overlay is not None else False

        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(False)
        if hasattr(self, "video_view"):
            self.video_view.set_blur_edit_enabled(False)
        if overlay is not None:
            overlay.set_editable(False)
            overlay.hide()

    def _force_hide_ocr_overlay_for_filter(self):
        if not bool(getattr(self, "_filter_thumbnail_visible", False)):
            return
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            overlay.set_editable(False)
            overlay.hide()

    def _restore_preview_region_tools_after_filter(self):
        self._suspend_ocr_overlay = False
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(True)
        self._sync_blur_controls()

        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            self._update_ocr_overlay()
            if (
                bool(getattr(self, "_filter_preview_ocr_was_editable", False))
                and os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
            ):
                overlay.set_editable(True)
                overlay.sync_to_view()

    def _position_frame_preview_badge(self):
        badge = getattr(self, "frame_preview_badge_label", None)
        if badge is None:
            return
        host = None
        if getattr(self, "_filter_thumbnail_visible", False):
            host = getattr(self, "frame_preview_image_label", None)
        if host is None or not host.isVisible():
            host = getattr(self, "video_view", None)
        if host is None:
            return
        badge.adjustSize()
        content_rect = None
        if hasattr(host, "get_video_content_rect"):
            try:
                content_rect = host.get_video_content_rect()
            except Exception:
                content_rect = None
        if content_rect is not None and content_rect.width() > 0 and content_rect.height() > 0:
            x = host.x() + content_rect.right() - badge.width() - 14
            y = host.y() + content_rect.top() + 14
        else:
            x = host.x() + max(12, host.width() - badge.width() - 14)
            y = host.y() + 14
        badge.move(int(x), int(y))
        badge.raise_()

    def _update_ocr_overlay(self):
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is None:
            return
        is_ocr = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
        btn = getattr(self, "ocr_region_btn", None)
        if btn:
            btn.setVisible(is_ocr)
            btn.blockSignals(True)
            btn.setChecked(bool(getattr(self, "_ocr_overlay_visible", True)))
            btn.blockSignals(False)
        if not is_ocr:
            overlay._requested_visible = False
            overlay.hide()
            overlay.set_editable(False)
        else:
            overlay._requested_visible = bool(getattr(self, "_ocr_overlay_visible", True))
            if bool(getattr(self, "_ocr_overlay_visible", True)):
                overlay.set_editable(True)
                overlay.sync_to_view()
            else:
                overlay.set_editable(False)
                overlay.hide()

    def toggle_ocr_overlay_visibility(self, checked: bool):
        self._ocr_overlay_visible = bool(checked)
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            overlay._requested_visible = bool(checked)
            overlay.set_editable(bool(checked))
            if checked:
                overlay.sync_to_view()
                overlay.raise_()
                QTimer.singleShot(0, overlay.sync_to_view)
            else:
                overlay.hide()
        self._update_ocr_overlay()

    def cleanup_file_if_exists(self, path: str):
        cleanup_file_if_exists_impl(path)

    def get_workspace_temp_root(self, create: bool = False) -> str:
        root = os.path.normpath(os.path.join(self.workspace_root, "temp"))
        if create:
            os.makedirs(root, exist_ok=True)
        return root

    def _cleanup_temp_root(self) -> None:
        root = self.get_workspace_temp_root()
        if not os.path.isdir(root):
            return
        for entry in os.listdir(root):
            fpath = os.path.join(root, entry)
            if not os.path.isfile(fpath):
                continue
            try:
                os.remove(fpath)
            except OSError:
                pass

    def get_current_project_temp_key(self) -> str:
        state = getattr(self, "current_project_state", None)
        project_id = str(getattr(state, "project_id", "") or "").strip()
        if project_id:
            return project_id
        project_root = str(getattr(state, "project_root", "") or "").strip()
        if project_root:
            return os.path.basename(os.path.normpath(project_root))
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if video_path:
            video_name = os.path.splitext(os.path.basename(video_path))[0] or "project"
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", video_name).strip("_").lower() or "project"
            digest = hashlib.sha1(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
            return f"{slug}_{digest}"
        return "global"

    def get_project_temp_root(self, create: bool = False) -> str:
        root = os.path.normpath(
            os.path.join(
                self.get_workspace_temp_root(create=create),
                "projects",
                self.get_current_project_temp_key(),
            )
        )
        if create:
            os.makedirs(root, exist_ok=True)
        return root

    def get_project_temp_path(self, *parts: str, create_parent: bool = False) -> str:
        path = os.path.normpath(os.path.join(self.get_project_temp_root(create=create_parent), *parts))
        if create_parent:
            parent = os.path.dirname(path) if os.path.splitext(path)[1] else path
            if parent:
                os.makedirs(parent, exist_ok=True)
        return path

    def get_project_temp_dir(self, *parts: str) -> str:
        path = self.get_project_temp_path(*parts, create_parent=True)
        os.makedirs(path, exist_ok=True)
        return path
    def get_output_mode_key(self):
        return "both"

    def get_output_quality_key(self):
        if not hasattr(self, "output_quality_combo"):
            return "source"
        value = self.output_quality_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_quality_combo.currentText() or "source").strip().lower() or "source"

    def get_output_fps_key(self):
        if not hasattr(self, "output_fps_combo"):
            return "source"
        value = self.output_fps_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_fps_combo.currentText() or "source").strip().lower() or "source"

    def get_output_ratio_key(self):
        if not hasattr(self, "output_ratio_combo"):
            return "source"
        value = self.output_ratio_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_ratio_combo.currentText() or "source").strip().lower() or "source"

    def get_output_scale_mode_key(self):
        if not hasattr(self, "output_scale_mode_combo"):
            return "fit"
        value = self.output_scale_mode_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_scale_mode_combo.currentText() or "fit").strip().lower() or "fit"

    def get_output_fill_focus(self):
        if hasattr(self, "video_view") and hasattr(self.video_view, "get_preview_fill_focus"):
            return self.video_view.get_preview_fill_focus()
        return (0.5, 0.5)

    def _video_filter_presets(self):
        return {
            "original": {
                "brightness": 0,
                "contrast": 0,
                "saturation": 0,
                "temperature": 0,
                "highlights": 0,
                "shadows": 0,
            },
            "bright": {
                "brightness": 20,
                "contrast": 5,
                "saturation": 5,
                "temperature": 0,
                "highlights": -10,
                "shadows": 20,
            },
            "warm": {
                "brightness": 10,
                "contrast": 5,
                "saturation": 10,
                "temperature": 25,
                "highlights": -5,
                "shadows": 10,
            },
            "vivid": {
                "brightness": 10,
                "contrast": 20,
                "saturation": 25,
                "temperature": 0,
                "highlights": -5,
                "shadows": 5,
            },
            "cool": {
                "brightness": 0,
                "contrast": 15,
                "saturation": 5,
                "temperature": -20,
                "highlights": -10,
                "shadows": -5,
            },
            "soft": {
                "brightness": 10,
                "contrast": -12,
                "saturation": 5,
                "temperature": 10,
                "highlights": -15,
                "shadows": 15,
            },
        }

    def _video_filter_lut_map(self):
        return {
            "warm": asset_path("luts", "Portrait", "Portrait3.cube"),
            "vivid": asset_path("luts", "Color Boost", "Earth_Tone_Boost.cube"),
            "cool": asset_path("luts", "Cinematic", "Cinematic-2.cube"),
        }

    def _video_filter_fields(self):
        return ("brightness", "contrast", "saturation", "temperature", "highlights", "shadows")

    def _clamp_video_filter_value(self, value):
        try:
            numeric = int(round(float(value)))
        except Exception:
            numeric = 0
        return max(-100, min(100, numeric))

    def _default_video_filter_overrides(self):
        return {field: 0 for field in self._video_filter_fields()}

    def _default_video_filter_modified_flags(self):
        return {field: False for field in self._video_filter_fields()}

    def _normalize_video_filter_preset_key(self, preset_key):
        key = str(preset_key or "original").strip().lower()
        return key if key in self._video_filter_presets() else "original"

    def _get_video_filter_base_values(self, preset_key=None):
        key = self._normalize_video_filter_preset_key(preset_key or self._video_filter_preset_key)
        return dict(self._video_filter_presets().get(key, self._video_filter_presets()["original"]))

    def _get_video_filter_scaled_values(self, preset_key=None, intensity=None):
        base_values = self._get_video_filter_base_values(preset_key)
        scale = max(0.0, min(100.0, float(intensity if intensity is not None else self._video_filter_intensity))) / 100.0
        return {
            field: self._clamp_video_filter_value(base_values.get(field, 0) * scale)
            for field in self._video_filter_fields()
        }

    def _get_video_filter_effective_values(self, preset_key=None, intensity=None, overrides=None, modified_flags=None):
        scaled_values = self._get_video_filter_scaled_values(preset_key, intensity)
        effective = {}
        active_overrides = overrides if overrides is not None else self._video_filter_adjust_overrides
        active_modified = modified_flags if modified_flags is not None else self._video_filter_user_modified
        for field in self._video_filter_fields():
            if active_modified.get(field, False):
                effective[field] = self._clamp_video_filter_value(active_overrides.get(field, 0))
            else:
                effective[field] = self._clamp_video_filter_value(scaled_values.get(field, 0))
        return effective

    def _refresh_video_filter_ui(self):
        if not hasattr(self, "video_filter_intensity_slider"):
            return
        self._video_filter_ui_sync = True
        try:
            for preset_key, button in getattr(self, "video_filter_preset_buttons", {}).items():
                button.setChecked(preset_key == self._normalize_video_filter_preset_key(self._video_filter_preset_key))

            self.video_filter_intensity_slider.setValue(int(self._video_filter_intensity))
            if hasattr(self, "video_filter_intensity_value_label"):
                self.video_filter_intensity_value_label.setText(str(int(self._video_filter_intensity)))

            for field, slider in getattr(self, "video_filter_adjust_sliders", {}).items():
                slider.setValue(int(self._video_filter_adjust_overrides.get(field, 0)))
                self._update_video_filter_slider_visual_state(field, slider)
            for field, label in getattr(self, "video_filter_adjust_value_labels", {}).items():
                label.setText(str(int(self._video_filter_adjust_overrides.get(field, 0))))
                is_modified = bool(self._video_filter_user_modified.get(field, False))
                label.setProperty("filterModified", is_modified)
                label.style().unpolish(label)
                label.style().polish(label)
        finally:
            self._video_filter_ui_sync = False

    def _update_video_filter_slider_visual_state(self, field, slider):
        if not slider:
            return
        is_modified = bool(self._video_filter_user_modified.get(field, False))
        if is_modified:
            slider.setStyleSheet(
                "QSlider::groove:horizontal {"
                "background: #223248; height: 6px; border-radius: 3px; }"
                "QSlider::sub-page:horizontal {"
                "background: #4ea6d8; border-radius: 3px; }"
                "QSlider::handle:horizontal {"
                "background: #8ad7ff; width: 14px; margin: -5px 0; border-radius: 7px; }"
            )
        else:
            slider.setStyleSheet("")

    def set_video_filter_state(self, preset_key="original", intensity=75, overrides=None, modified_flags=None):
        self._video_filter_preset_key = self._normalize_video_filter_preset_key(preset_key)
        self._video_filter_intensity = max(0, min(100, int(round(float(intensity)))))
        base_overrides = self._default_video_filter_overrides()
        base_modified_flags = self._default_video_filter_modified_flags()
        for field in self._video_filter_fields():
            if overrides and field in overrides:
                base_overrides[field] = self._clamp_video_filter_value(overrides[field])
            if modified_flags and field in modified_flags:
                base_modified_flags[field] = bool(modified_flags[field])
        self._video_filter_adjust_overrides = base_overrides
        self._video_filter_user_modified = base_modified_flags
        self._refresh_video_filter_ui()
        self.refresh_ui_state()

    def on_video_filter_preset_selected(self, preset_key):
        if self._video_filter_ui_sync:
            return
        normalized_preset = self._normalize_video_filter_preset_key(preset_key)
        seeded_overrides = self._get_video_filter_scaled_values(normalized_preset, 75)
        self.set_video_filter_state(
            normalized_preset,
            75,
            seeded_overrides,
            self._default_video_filter_modified_flags(),
        )
        self._mark_video_filter_preview_dirty()
        self.schedule_live_video_filter_preview()

    def on_video_filter_intensity_changed(self, value):
        if self._video_filter_ui_sync:
            return
        self._video_filter_intensity = max(0, min(100, int(value)))
        self._refresh_video_filter_ui()
        self.refresh_ui_state()
        self._mark_video_filter_preview_dirty()
        if not self._is_video_filter_slider_interacting():
            self.schedule_live_video_filter_preview()

    def on_video_filter_adjust_changed(self, field_key, value):
        if self._video_filter_ui_sync:
            return
        normalized_field = str(field_key or "").strip().lower()
        if normalized_field not in self._video_filter_fields():
            return
        clamped_value = self._clamp_video_filter_value(value)
        scaled_value = self._get_video_filter_scaled_values().get(normalized_field, 0)
        self._video_filter_adjust_overrides[normalized_field] = clamped_value
        self._video_filter_user_modified[normalized_field] = int(clamped_value) != int(scaled_value)
        self._refresh_video_filter_ui()
        self.refresh_ui_state()
        self._mark_video_filter_preview_dirty()
        if not self._is_video_filter_slider_interacting():
            self.schedule_live_video_filter_preview()

    def reset_video_filters(self):
        self.set_video_filter_state(
            "original",
            75,
            self._default_video_filter_overrides(),
            self._default_video_filter_modified_flags(),
        )
        self._video_filter_preview_dirty = False
        self._video_filter_apply_requested = False
        self.revert_video_filter_preview_to_source()
        self.schedule_live_video_filter_preview()

    def reset_video_filter_adjustments(self):
        seeded_overrides = self._get_video_filter_scaled_values(self._video_filter_preset_key, self._video_filter_intensity)
        self.set_video_filter_state(
            self._video_filter_preset_key,
            self._video_filter_intensity,
            seeded_overrides,
            self._default_video_filter_modified_flags(),
        )
        self._mark_video_filter_preview_dirty()
        self.schedule_live_video_filter_preview()

    def get_video_filter_state(self):
        base_values = self._get_video_filter_base_values()
        scaled_values = self._get_video_filter_scaled_values()
        effective_values = self._get_video_filter_effective_values()
        preset_key = self._normalize_video_filter_preset_key(self._video_filter_preset_key)
        lut_path = str(self._video_filter_lut_map().get(preset_key, "") or "").strip()
        if lut_path and not os.path.exists(lut_path):
            lut_path = ""
        lut_strength = 0.0
        if lut_path:
            lut_strength = max(0.0, min(0.45, (float(self._video_filter_intensity) / 100.0) * 0.45))
        active = any(abs(int(value)) > 0 for value in effective_values.values())
        return {
            "preset": preset_key,
            "intensity": int(self._video_filter_intensity),
            "base": base_values,
            "scaled": scaled_values,
            "overrides": dict(self._video_filter_adjust_overrides),
            "modified": dict(self._video_filter_user_modified),
            "final": effective_values,
            "lut_path": lut_path,
            "lut_strength": lut_strength,
            "active": active,
        }

    def has_active_video_filters(self):
        state = self.get_video_filter_state()
        active = bool(state.get("active"))
        return active

    def on_output_ratio_changed(self, *_args):
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_aspect_ratio"):
            self.video_view.set_preview_aspect_ratio(self.get_output_ratio_key())
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_scale_mode"):
            self.video_view.set_preview_scale_mode(self.get_output_scale_mode_key())
        self.update_subtitle_preview_style()
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def on_output_scale_mode_changed(self, *_args):
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_scale_mode"):
            self.video_view.set_preview_scale_mode(self.get_output_scale_mode_key())
        self.update_subtitle_preview_style()
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def on_preview_framing_changed(self, *_args):
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def reset_preview_framing(self):
        if hasattr(self, "video_view") and hasattr(self.video_view, "reset_preview_fill_focus"):
            self.video_view.reset_preview_fill_focus()
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def get_audio_handling_mode(self):
        if not hasattr(self, "audio_handling_combo"):
            return "fast"
        value = self.audio_handling_combo.currentData()
        if value:
            return str(value).strip().lower()
        return "fast"

    def get_source_language_code(self):
        if not hasattr(self, "lang_whisper_combo"):
            return "auto"
        value = self.lang_whisper_combo.currentData()
        if value:
            return str(value)
        return self.lang_whisper_combo.currentText().strip() or "auto"

    def get_target_language_code(self):
        if not hasattr(self, "lang_target_combo"):
            return "vi"
        value = self.lang_target_combo.currentData()
        if value:
            return str(value)
        label = self.lang_target_combo.currentText().strip().lower()
        if "english" in label:
            return "en"
        return "vi"

    def is_ai_polish_enabled(self):
        provider = (os.getenv("AI_POLISHER_PROVIDER") or "gemini").strip().lower()
        if provider == "local":
            return True
        return getattr(self, "translator_ai_cb", None) and self.translator_ai_cb.isChecked()

    def is_skip_translation(self):
        # Translation is always part of the fixed Subtitle + Voice workflow.
        return False

    def is_ai_dubbing_rewrite_enabled(self):
        return bool(getattr(self, "ai_dubbing_rewrite_cb", None) and self.ai_dubbing_rewrite_cb.isChecked())

    def get_ai_dubbing_style_instruction(self):
        if hasattr(self, "translator_style_edit"):
            return " ".join(self.translator_style_edit.text().split()).strip()
        return ""

    def get_ai_style_instruction(self):
        style_parts = []
        if hasattr(self, "translator_style_edit"):
            custom_style = self.translator_style_edit.text().strip()
            if custom_style:
                style_parts.append(custom_style)
        if hasattr(self, "subtitle_single_line_cb") and self.subtitle_single_line_cb.isChecked():
            style_parts.append("[subtitle_layout=single_line]")
        return " | ".join(part for part in style_parts if part).strip()

    def on_output_mode_changed(self, value: str):
        mode = "both"
        if getattr(self, "_filter_thumbnail_visible", False):
            self.hide_filter_thumbnail_preview()
        self.workflow_hint_label.setText(build_workflow_hint(mode, self.is_ai_polish_enabled()))

        show_voice = mode in ("voice", "both")
        if hasattr(self, "voice_section_card"):
            self.voice_section_card.setVisible(show_voice)
        if hasattr(self, "quick_preview_btn"):
            self.quick_preview_btn.setVisible(show_voice)
        if hasattr(self, "styled_preview_btn"):
            self.styled_preview_btn.setVisible(show_voice)
        self.mixed_audio_edit.setEnabled(show_voice)
        if hasattr(self, "use_generated_audio_radio"):
            self.use_generated_audio_radio.setVisible(show_voice)
        if hasattr(self, "use_existing_audio_radio"):
            self.use_existing_audio_radio.setVisible(show_voice)
        if hasattr(self, "browse_bg_music_btn"):
            self.browse_bg_music_btn.setVisible(show_voice)
        if hasattr(self, "browse_mixed_audio_btn"):
            self.browse_mixed_audio_btn.setVisible(show_voice)
        self.export_btn.setText(get_export_button_label(mode))
        self.refresh_ui_state()

    def on_left_panel_workflow_changed(self, index: int):
        # Filter thumbnail preview should only stay active while the Filter page is open.
        if int(index) != 4 and getattr(self, "_filter_thumbnail_visible", False):
            self.hide_filter_thumbnail_preview()

    def _workflow_dependency_state(self) -> dict:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        has_video = bool(video_path and os.path.exists(video_path))
        return {
            "media": {"enabled": True, "reason": ""},
            "language": {"enabled": has_video, "reason": "Select a video first to transcribe and translate."},
            "voice": {"enabled": has_video, "reason": "Select a video first to configure voice and audio."},
            "style": {"enabled": has_video, "reason": "Select a video first to style subtitle output."},
            "filter": {"enabled": has_video, "reason": "Select a video first to preview and apply filters."},
            "advanced": {"enabled": True, "reason": ""},
        }

    def update_workflow_availability(self):
        states = self._workflow_dependency_state()
        current_index = int(self.left_panel_stack.currentIndex()) if hasattr(self, "left_panel_stack") else 0
        page_order = ["media", "language", "voice", "style", "filter", "advanced"]

        for page_key, state in states.items():
            container = getattr(self, "workflow_page_containers", {}).get(page_key) if hasattr(self, "workflow_page_containers") else None
            hint = getattr(self, "workflow_page_hints", {}).get(page_key) if hasattr(self, "workflow_page_hints") else None
            tab_btn = getattr(self, "workflow_tab_buttons", {}).get(page_key) if hasattr(self, "workflow_tab_buttons") else None
            enabled = bool(state.get("enabled"))
            reason = str(state.get("reason", "") or "").strip()
            if container is not None:
                container.setEnabled(enabled)
            if hint is not None:
                hint.setText("" if enabled else reason)
                hint.setVisible(not enabled and bool(reason))
            if tab_btn is not None:
                tab_btn.setEnabled(enabled)
                tab_btn.style().unpolish(tab_btn)
                tab_btn.style().polish(tab_btn)

        active_key = page_order[current_index] if 0 <= current_index < len(page_order) else "media"
        active_state = states.get(active_key, {"enabled": True})
        if not active_state.get("enabled", True):
            for fallback_key in ("media", "advanced"):
                fallback_index = page_order.index(fallback_key)
                fallback_state = states.get(fallback_key, {"enabled": True})
                if fallback_state.get("enabled", True):
                    btn = getattr(self, "workflow_tab_buttons", {}).get(fallback_key) if hasattr(self, "workflow_tab_buttons") else None
                    if btn is not None:
                        btn.setChecked(True)
                    elif hasattr(self, "left_panel_stack"):
                        self.left_panel_stack.setCurrentIndex(fallback_index)
                    break

    def update_guidance_panel(self):
        guidance = build_guidance_state(
            video_path=self.video_path_edit.text(),
            transcript_text=self.transcript_text.toPlainText(),
            translated_text=self.translated_text.toPlainText(),
            translated_srt_path=self.last_translated_srt_path,
            selected_audio_path=self.resolve_selected_audio_path(),
            mode=self.get_output_mode_key(),
            pipeline_active=getattr(self, "_pipeline_active", False),
            mode_label=self.output_mode_combo.currentText(),
        )
        self.update_preview_context_label(guidance["has_subtitles"], guidance["has_voice_audio"])

    def update_project_header(self):
        video_path = self.video_path_edit.text().strip()
        if video_path:
            video_name = os.path.basename(video_path)
            self.project_title_label.setText(f"Project: {video_name}")
            if hasattr(self, "upload_status_label"):
                self.upload_status_label.setText(f"[OK] {video_name} uploaded")
        else:
            self.project_title_label.setText("Project: No video selected")
            if hasattr(self, "upload_status_label"):
                self.upload_status_label.setText("No video uploaded yet")

    def sync_left_panel_container_width(self):
        scroll_area = getattr(self, "left_panel_scroll_area", None)
        container = getattr(self, "left_panel_container", None)
        if not scroll_area or not container:
            return
        viewport_width = max(0, scroll_area.viewport().width())
        if viewport_width <= 0:
            return
        gutter = 10
        target_width = max(320, viewport_width - gutter)
        container.setMaximumWidth(target_width)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            scroll_area = getattr(self, "left_panel_scroll_area", None)
            if scroll_area and watched in (scroll_area, scroll_area.viewport(), scroll_area.verticalScrollBar()):
                QTimer.singleShot(0, self.sync_left_panel_container_width)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            focused = self.focusWidget()
            if isinstance(focused, (QTextEdit, QLineEdit)):
                super().keyPressEvent(event)
                return
            if self.undo_last_timeline_timing_edit():
                event.accept()
                return
        if event.matches(QKeySequence.Redo):
            focused = self.focusWidget()
            if isinstance(focused, (QTextEdit, QLineEdit)):
                super().keyPressEvent(event)
                return
            if self.redo_last_timeline_timing_edit():
                event.accept()
                return
        super().keyPressEvent(event)

    def toggle_controls_panel(self):
        # Hide-controls is disabled - the workflow panel is always visible.
        self.set_controls_panel_visible(True)

    def set_controls_panel_visible(self, visible: bool):
        # The workflow panel is always visible. Hide-controls is disabled.
        if hasattr(self, "left_panel_scroll_area"):
            self.left_panel_scroll_area.setVisible(True)
        QTimer.singleShot(0, self._resync_preview_region_overlays)

    def _resync_preview_region_overlays(self):
        try:
            self._sync_blur_controls()
        except Exception:
            pass
        try:
            self._update_ocr_overlay()
        except Exception:
            pass

    def update_progress_checklist(self):
        self.update_workflow_stage_badges()

    def update_workflow_stage_badges(self):
        """Reflect persisted workflow artifacts in the left-side milestones."""
        badges = getattr(self, "workflow_stage_badges", {}) or {}
        if not badges:
            return
        video_path = str(self.video_path_edit.text() if hasattr(self, "video_path_edit") else "").strip()
        state = getattr(self, "current_project_state", None)
        artifacts = getattr(state, "artifacts", {}) or {}
        steps = getattr(state, "steps", {}) or {}
        has_video = bool(video_path and os.path.exists(video_path))
        transcript = bool(self.current_segments) or bool(artifacts.get("transcript_segments"))
        # PrepareWorkflow writes a compatibility SRT even when translation is
        # intentionally skipped. Only a completed translation artifact/step
        # unlocks the next Step-by-Step action.
        translated = (
            str(steps.get("translate_raw", "")).lower() == "done"
            or bool(artifacts.get("translation_final"))
        )
        voice = bool(artifacts.get("voice_vi") or artifacts.get("mixed_vi") or self.last_voice_vi_path or self.last_mixed_vi_path)
        exported = bool(artifacts.get("final_video"))
        running = str(getattr(self, "_pipeline_step", "") or "") if getattr(self, "_pipeline_active", False) else ""
        values = {
            "prepare": (has_video, "prepare"),
            "transcript": (transcript, "prepare"),
            "translate": (translated, "translation"),
            "tts": (voice, "voiceover"),
            "export": (exported, "export"),
        }
        for key, (complete, running_step) in values.items():
            badge = badges.get(key)
            if badge is None:
                continue
            is_running = running == running_step or (key == "transcript" and running == "prepare")
            if is_running:
                text, color = "Processing…", "#f6c453"
            elif complete:
                text, color = "✓ Completed", "#6ee7d6"
            else:
                text, color = "Not started", "#8394aa"
            badge.setText(text)
            badge.setStyleSheet(f"color: {color}; font-weight: 700;")

        # Step-by-Step is deliberately linear: users can only launch the
        # next missing stage, while Full Pipeline remains the shortcut that
        # runs all required stages in order.
        if hasattr(self, "_generate_transcript_action"):
            self._generate_transcript_action.setEnabled(has_video and not transcript and not self._pipeline_active)
        if hasattr(self, "_generate_translate_action"):
            self._generate_translate_action.setEnabled(transcript and not translated and not self._pipeline_active)
        if hasattr(self, "_generate_import_translated_srt_action"):
            self._generate_import_translated_srt_action.setEnabled(transcript and not self._pipeline_active)
        if hasattr(self, "_generate_tts_action"):
            self._generate_tts_action.setEnabled(
                # TTS is intentionally repeatable: subtitle/voice edits may
                # require regenerating audio after this stage was completed.
                translated and not self._pipeline_active
                and self.get_output_mode_key() in ("voice", "both")
            )

    def update_preview_context_label(self, has_subtitles: bool, has_voice_audio: bool):
        subtitle_source = "Vietnamese review track" if self.current_translated_segments else ("original subtitle track" if self.current_segments else "no subtitle track yet")
        audio_source = "existing mixed audio" if self.using_existing_audio_source() else "generated Vietnamese voice"
        self.preview_context_label.setText(
            build_preview_context_text(
                video_ready=bool(self.video_path_edit.text().strip()),
                has_subtitles=has_subtitles,
                has_voice_audio=has_voice_audio,
                subtitle_source=subtitle_source,
                audio_source=audio_source,
            )
        )

    def choose_subtitle_color(self):
        color = QColorDialog.getColor(QColor(self.subtitle_color_hex), self, "Choose Subtitle Color")
        if not color.isValid():
            return
        self.subtitle_color_hex = color.name().upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.on_subtitle_style_control_edited()
        self.update_subtitle_preview_style()

    def choose_subtitle_background_color(self):
        current = getattr(self, "subtitle_background_color_hex", "#000000")
        color = QColorDialog.getColor(QColor(current), self, "Choose Subtitle Background Color")
        if not color.isValid():
            return
        self.subtitle_background_color_hex = color.name().upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.on_subtitle_style_control_edited()
        self.update_subtitle_preview_style()

    def on_subtitle_font_scale_changed(self, _index: int = -1):
        """Translate the friendly percentage picker into the stored font size."""
        combo = getattr(self, "subtitle_font_scale_combo", None)
        spin = getattr(self, "subtitle_font_size_spin", None)
        if combo is None or spin is None:
            return
        percent = int(combo.currentData() or 100)
        spin.setValue(max(spin.minimum(), min(spin.maximum(), round(60 * percent / 100.0))))

    def sync_subtitle_font_scale_control(self, size: int | None = None):
        """Keep the visible selector honest when a preset/project sets a size."""
        combo = getattr(self, "subtitle_font_scale_combo", None)
        spin = getattr(self, "subtitle_font_size_spin", None)
        if combo is None or spin is None:
            return
        size = int(spin.value() if size is None else size)
        choices = [int(combo.itemData(index)) for index in range(combo.count())]
        if not choices:
            return
        nearest = min(choices, key=lambda percent: abs((60 * percent / 100.0) - size))
        index = combo.findData(nearest)
        if index >= 0 and index != combo.currentIndex():
            was_blocked = combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(was_blocked)

    def _subtitle_render_dimensions(self) -> tuple[int, int]:
        """Return the canvas dimensions the export ASS file is authored for."""
        source_w = max(1, int(getattr(self.video_view, "video_source_width", 0) or 1920))
        source_h = max(1, int(getattr(self.video_view, "video_source_height", 0) or 1080))
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        controller = getattr(self, "preview_controller", None)
        if controller is not None and video_path:
            try:
                target_w, target_h = controller._resolve_output_canvas_dimensions(video_path)
                if target_w and target_h:
                    return int(target_w), int(target_h)
            except Exception:
                pass
        return source_w, source_h

    def _resolved_subtitle_font_name(self, requested_font: str) -> str:
        """Use Qt's actual font fallback for both preview and ASS export.

        Preset fonts such as Montserrat are not installed on every Windows
        system. Qt and libass otherwise pick different fallbacks, causing
        identical text and widths to wrap on different words.
        """
        requested_font = str(requested_font or "Segoe UI").strip() or "Segoe UI"
        try:
            bundled_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
            if not getattr(self, "_bundled_subtitle_fonts_registered", False) and os.path.isdir(bundled_dir):
                for filename in os.listdir(bundled_dir):
                    if filename.lower().endswith((".ttf", ".otf")):
                        QFontDatabase.addApplicationFont(os.path.join(bundled_dir, filename))
                self._bundled_subtitle_fonts_registered = True
            resolved = QFontInfo(QFont(requested_font)).family().strip()
            return resolved or requested_font
        except Exception:
            return requested_font

    def update_subtitle_preview_style(self):
        if not hasattr(self, "video_view"):
            return
        item = self.video_view.subtitle_item
        has_video = bool(self.video_path_edit.text().strip())
        has_segments = bool(self.get_active_segments())
        if not has_video or not has_segments:
            item.set_text("")
            item.hide()
            self.sync_live_subtitle_preview()
            return
        render_w, render_h = self._subtitle_render_dimensions()
        self.video_view.set_subtitle_render_dimensions(render_w, render_h)
        source_h = max(1, render_h)
        preview_rect = self.video_view.get_preview_canvas_rect() if hasattr(self.video_view, "get_preview_canvas_rect") else self.video_view.get_video_content_rect()
        preview_h = max(1.0, preview_rect.height() or float(self.video_view.height()) or 1.0)
        preset = self.get_subtitle_preset_config()
        export_font_size = int(self.subtitle_font_size_spin.value())
        preview_scale = preview_h / source_h
        preview_text_scale = preview_scale * 0.85
        # The preview is a scaled view of the source video. Do not impose a
        # 10px floor here: it made several user-selected sizes render as the
        # same size and therefore looked as though the control had stopped
        # updating.
        # Qt's QFont and libass use different font metric engines. At the
        # small sizes used by this live preview, QFont advances the bundled
        # Montserrat glyphs about 15% wider than libass, causing earlier line
        # wraps and a visibly larger preview. Calibrate the editable layer to
        # the ASS renderer, while keeping the exported source size unchanged.
        preview_font_size = max(1, int(round(export_font_size * preview_text_scale)))
        font_name = self._resolved_subtitle_font_name(
            self.subtitle_font_combo.currentText().strip() or preset.get("font_name", "Segoe UI")
        )
        bg_alpha = float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else float(preset.get("background_alpha", 0.0))
        bg_color = QColor(getattr(self, "subtitle_background_color_hex", preset.get("background_color", "#000000")))
        bg_color.setAlpha(max(0, min(255, int(round(bg_alpha * 255.0)))))
        item.set_style(
            font_name=font_name or preset.get("font_name", "Segoe UI"),
            font_size=preview_font_size,
            font_color=QColor(self.subtitle_color_hex),
            # Stroke/shadow values are authored for the source video. Scale
            # them for the smaller Qt preview too; otherwise TikTok's 7px
            # export outline overwhelms its preview-sized glyphs.
            outline_width=(
                float(preset.get("outline_width", 2)) * preview_text_scale
                if not hasattr(self, "subtitle_outline_cb") or self.subtitle_outline_cb.isChecked()
                else 0.0
            ),
            outline_color=QColor(preset.get("outline_color", "#000000")),
            background_box=bool(self.subtitle_background_cb.isChecked()),
            background_color=bg_color,
            single_line=bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()),
            bold=bool(self.subtitle_bold_cb.isChecked()),
            shadow_color=QColor(preset.get("shadow_color", "#000000")),
            shadow_depth=float(preset.get("shadow_depth", 0)) * preview_text_scale,
        )
        position = self.get_subtitle_position_config()
        item.set_alignment(position.get("alignment_label", "Bottom"))
        item.set_positioning(
            x_offset=int(position.get("x_offset", 0)),
            bottom_offset=int(position.get("margin_v", 30)),
            custom_position_enabled=bool(position.get("custom_position_enabled", False)),
            custom_x_percent=int(position.get("custom_position_x", 50)),
            custom_y_percent=int(position.get("custom_position_y", 86)),
        )
        segments = self.live_preview_segments or self.get_active_segments()
        selected = int(getattr(self, "_selected_segment_index", -1))
        self._set_live_subtitle_effects(segments[selected] if 0 <= selected < len(segments) else (segments[0] if segments else None))
        self.video_view.reposition_subtitle()
        self.sync_live_subtitle_preview()
        self.schedule_auto_frame_preview()

    def _set_live_subtitle_effects(self, segment: dict | None, position_ms: int = 0):
        """Feed the editable preview layer the same cue effects used at export."""
        if not hasattr(self, "video_view"):
            return
        item = self.video_view.subtitle_item
        segment = segment or {}
        preset = self.get_subtitle_preset_config()
        text = str(segment.get("text", "") or "")
        mode = self.subtitle_highlight_mode_combo.currentText().strip() if hasattr(self, "subtitle_highlight_mode_combo") else "Auto"
        phrases = []
        if mode in ("Auto", "Auto + Manual"):
            phrases.extend(segment.get("auto_highlights", []) or [])
        if mode in ("Manual", "Auto + Manual"):
            phrases.extend(segment.get("manual_highlights", []) or [])
        animation = self.subtitle_animation_combo.currentText().strip().lower() if hasattr(self, "subtitle_animation_combo") else ""
        animation_duration = max(0.01, float(self.subtitle_animation_time_spin.value())) if hasattr(self, "subtitle_animation_time_spin") else 0.22
        start = float(segment.get("start", 0.0) or 0.0)
        end = max(start + 0.01, float(segment.get("end", start + 0.01) or start + 0.01))
        elapsed = max(0.0, float(position_ms) / 1000.0 - start)
        animation_progress = min(1.0, elapsed / animation_duration)
        if animation == "fade out":
            animation_progress = min(1.0, max(0.0, float(position_ms) / 1000.0 - (end - animation_duration)) / animation_duration)
        karaoke_index = -1
        if animation == "word highlight karaoke" and text:
            words = [word for word in text.split() if word]
            progress = max(0.0, min(0.999, (float(position_ms) / 1000.0 - start) / (end - start)))
            karaoke_index = min(len(words) - 1, int(progress * len(words))) if words else -1
        item.set_effects(
            highlight_color=self._highlight_color_hex() or preset.get("highlight_color", "#FFD400"),
            highlight_phrases=phrases,
            karaoke_word_index=karaoke_index,
            auto_keyword_highlight=bool(self.subtitle_keyword_highlight_cb.isChecked()) if hasattr(self, "subtitle_keyword_highlight_cb") else False,
            animation_style=animation,
            animation_progress=animation_progress,
        )

    def on_single_line_toggled(self, checked: bool):
        self.update_subtitle_preview_style()
        if not self.current_translated_segments:
            return
        if checked:
            self._split_segments_for_single_line()
        else:
            self._single_line_split_cache = None
        self.apply_segments_to_timeline()
        self.schedule_live_subtitle_preview_refresh()

    def _split_segments_for_single_line(self):
        from translation import TranslationOrchestrator
        source = list(self.current_translated_segments or [])
        if not source:
            return
        orchestrator = TranslationOrchestrator()
        provider_type, polisher = orchestrator._resolve_ai_provider()
        if not polisher or not polisher.is_configured():
            polisher = None
        split = orchestrator._split_segments_for_single_line(
            source, polisher=polisher, provider_type=provider_type, target_lang=self.get_target_language_code()
        )
        if split and split != source:
            self._single_line_split_cache = split

    def get_subtitle_export_style(self, segments=None):
        preset = self.get_subtitle_preset_config()
        # Export-only glyph calibration. ASS ScaleX/ScaleY enlarges glyphs
        # without changing font-size-derived line spacing or row placement.
        export_font_scale = max(0.1, float(getattr(self, "subtitle_export_font_scale", 1.0)))
        export_font_size = max(1, int(self.subtitle_font_size_spin.value()))
        style_segments = segments if segments is not None else self.get_active_segments()
        position = self.get_subtitle_position_config()
        custom_bottom_y = None
        if position.get("custom_position_enabled") and hasattr(self, "video_view"):
            try:
                item = self.video_view.subtitle_item
                canvas = self.video_view.get_preview_canvas_rect()
                top_left = self.video_view.mapFromGlobal(item.pos()) if item.is_top_level_overlay() else item.pos()
                custom_bottom_y = max(0.0, min(100.0, (top_left.y() + item.height() - canvas.top()) * 100.0 / canvas.height()))
            except Exception:
                custom_bottom_y = None
        return {
            "font_name": self._resolved_subtitle_font_name(
                self.subtitle_font_combo.currentText().strip() or preset.get("font_name", "Arial")
            ),
            "font_size": export_font_size,
            "font_scale": export_font_scale,
            "font_color": self._hex_to_ass_color(self.subtitle_color_hex),
            "highlight_color": self._hex_to_ass_color(self._highlight_color_hex()),
            "outline_color": self._hex_to_ass_color(preset.get("outline_color", "#000000")),
            "outline_width": (
                float(preset.get("outline_width", 2))
                if not hasattr(self, "subtitle_outline_cb") or self.subtitle_outline_cb.isChecked()
                else 0.0
            ),
            "shadow_color": self._hex_to_ass_color(preset.get("shadow_color", "#000000")),
            "shadow_depth": float(preset.get("shadow_depth", 1)),
            "shadow_alpha": float(preset.get("shadow_alpha", 0.0)),
            "background_color": self._hex_to_ass_color(
                getattr(self, "subtitle_background_color_hex", preset.get("background_color", "#000000"))
            ),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else float(preset.get("background_alpha", 0.0)),
            "animation": self.subtitle_animation_combo.currentText().strip() or preset.get("animation", "Static"),
            "animation_duration": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "position_mode": str(position.get("position_mode", "anchor")),
            "alignment": int(position.get("alignment", 2)),
            "margin_v": int(position.get("margin_v", 30)),
            "custom_position_enabled": bool(position.get("custom_position_enabled", False)),
            "custom_position_x": int(position.get("custom_position_x", 50)),
            "custom_position_y": int(position.get("custom_position_y", 86)),
            "custom_position_bottom_y": custom_bottom_y,
            "background_box": bool(self.subtitle_background_cb.isChecked()),
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "preset_key": self.get_selected_subtitle_preset(),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked())
            and self.subtitle_highlight_mode_combo.currentText().strip() in ("Auto", "Auto + Manual")
            and not any(seg.get("auto_highlights") for seg in (style_segments or [])),
            "manual_highlights": self._build_render_highlight_lists(style_segments or []),
            "word_timings": [list(seg.get("words", [])) for seg in (style_segments or [])],
            "blur_region": (
                self.video_view.get_blur_region_normalized()
                if hasattr(self, "video_view") and self._blur_effect_enabled()
                else None
            ),
            "render_subtitles": False,
        }

    def _build_render_highlight_lists(self, style_segments):
        mode = self.subtitle_highlight_mode_combo.currentText().strip() if hasattr(self, "subtitle_highlight_mode_combo") else "Auto"
        include_auto = mode in ("Auto", "Auto + Manual")
        include_manual = mode in ("Manual", "Auto + Manual")
        rows = []
        for seg in style_segments or []:
            merged = []
            seen = set()
            if include_auto:
                for phrase in seg.get("auto_highlights", []) or []:
                    normalized = self._normalize_manual_highlight(phrase)
                    key = normalized.lower()
                    if normalized and key not in seen:
                        seen.add(key)
                        merged.append(normalized)
            if include_manual:
                for phrase in seg.get("manual_highlights", []) or []:
                    normalized = self._normalize_manual_highlight(phrase)
                    key = normalized.lower()
                    if normalized and key not in seen:
                        seen.add(key)
                        merged.append(normalized)
            rows.append(merged)
        return rows

    def on_subtitle_preset_changed(self):
        preset = self.get_subtitle_preset_config()
        selected = self.get_selected_subtitle_preset()
        self._subtitle_preset_apply_in_progress = True
        try:
            if selected == "custom":
                if self._subtitle_custom_style_state:
                    self._apply_subtitle_style_controls_state(self._subtitle_custom_style_state)
            else:
                self.subtitle_font_combo.setCurrentText(preset.get("font_name", "Arial"))
                self.subtitle_font_size_spin.setValue(int(preset.get("font_size", self.subtitle_font_size_spin.value())))
                self.subtitle_animation_combo.setCurrentText(preset.get("animation", "Static"))
                self.subtitle_background_cb.setChecked(bool(preset.get("background_box", False)))
                self.subtitle_background_color_hex = str(
                    preset.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))
                ).upper()
                if hasattr(self, "subtitle_background_color_btn"):
                    self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
                if hasattr(self, "subtitle_outline_cb"):
                    self.subtitle_outline_cb.setChecked(bool(preset.get("outline_width", 0) > 0))
                if hasattr(self, "subtitle_bg_alpha_spin"):
                    self.subtitle_bg_alpha_spin.setValue(float(preset.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
                self.subtitle_bold_cb.setChecked(bool(preset.get("bold", False)))
                if hasattr(self, "subtitle_keyword_highlight_cb"):
                    self.subtitle_keyword_highlight_cb.setChecked(bool(preset.get("auto_keyword_highlight", False)))
                if hasattr(self, "subtitle_highlight_color_combo"):
                    color_name = "Yellow" if preset.get("highlight_color", "").upper() == "#FFD400" else "Cyan"
                    self.subtitle_highlight_color_combo.setCurrentText(color_name)
                if hasattr(self, "subtitle_highlight_mode_combo"):
                    self.subtitle_highlight_mode_combo.setCurrentText(str(preset.get("highlight_mode", "Auto")))
        finally:
            self._subtitle_preset_apply_in_progress = False
        if hasattr(self, "style_library_card"):
            self.style_library_card.setVisible(True)
        if hasattr(self, "highlight_card"):
            self.highlight_card.setVisible(True)
        if hasattr(self, "custom_title_card"):
            self.custom_title_card.setVisible(True)
        if hasattr(self, "subtitle_preset_summary_label"):
            self.subtitle_preset_summary_label.setText(
                f"{preset.get('label', 'Preset')}: {preset.get('summary', '')}"
            )
        self._update_animation_time_visibility()
        if selected == "custom":
            self._capture_subtitle_custom_style_state()
        self.on_subtitle_position_mode_changed()

    def _update_animation_time_visibility(self):
        current_animation = self.subtitle_animation_combo.currentText().strip().lower()
        show_animation_time = current_animation != "static"
        show_karaoke_timing = current_animation in ("word highlight karaoke", "typewriter")
        if hasattr(self, "subtitle_animation_time_label"):
            self.subtitle_animation_time_label.setVisible(show_animation_time)
        if hasattr(self, "subtitle_animation_time_spin"):
            self.subtitle_animation_time_spin.setVisible(show_animation_time)
        if hasattr(self, "subtitle_karaoke_timing_label"):
            self.subtitle_karaoke_timing_label.setVisible(show_karaoke_timing)
        if hasattr(self, "subtitle_karaoke_timing_combo"):
            self.subtitle_karaoke_timing_combo.setVisible(show_karaoke_timing)

    def on_subtitle_animation_changed(self):
        self._update_animation_time_visibility()
        self.update_subtitle_preview_style()

    def refresh_video_dimensions(self, path: str):
        refresh_video_dimensions_impl(self, path, get_video_dimensions)

    def _hex_to_ass_color(self, hex_color: str) -> str:
        color = QColor(hex_color)
        return f"&H00{color.blue():02X}{color.green():02X}{color.red():02X}"

    def export_final_video(self):
        self.preview_controller.export_final_video()

    def preview_five_seconds(self):
        self.preview_controller.preview_five_seconds()

    def preview_exact_frame(self):
        self.preview_controller.start_exact_frame_preview(show_dialog=True)

    def build_subtitle_preview_srt(self, start_seconds: float, duration_seconds: float):
        return self.preview_controller.build_subtitle_preview_srt(start_seconds, duration_seconds)

    def build_full_active_subtitle_srt(self):
        return self.preview_controller.build_full_active_subtitle_srt()

    def _format_compact_editor_timestamp(self, seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        minutes, sec = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _segment_editor_display_rows(self):
        base_segments = self.current_segments or []
        translated_segments = self.current_translated_segments or []
        row_count = max(len(base_segments), len(translated_segments))
        rows = []
        for idx in range(row_count):
            base = base_segments[idx] if idx < len(base_segments) else {}
            translated = translated_segments[idx] if idx < len(translated_segments) else {}
            reference = translated or base
            rows.append(
                {
                    "segment_index": idx,
                    "start": float(reference.get("start", 0.0)),
                    "end": float(reference.get("end", 0.0)),
                    "original": str(base.get("text", "")),
                    "translated": str(translated.get("text", "")),
                    "spoken": str(translated.get("tts_text") or translated.get("dubbing_vi") or translated.get("text", "")),
                    "subtitle_vi": str(translated.get("subtitle_vi") or translated.get("text", "")),
                    "dubbing_vi": str(translated.get("dubbing_vi") or translated.get("tts_text") or translated.get("text", "")),
                    "ratio": float(translated.get("ratio", 0.0) or 0.0),
                    "attempt_count": int(translated.get("attempt_count", 0) or 0),
                    "action_taken": str(translated.get("action_taken", "")),
                    "voice_speed": float(reference.get("voice_speed", 1.0)),
                    "manual_highlights": list(translated.get("manual_highlights", [])),
                }
            )
        return rows

    def _update_segment_spoken_status(self, index: int):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        segment = {}
        if 0 <= index < len(self.current_translated_segments or []):
            segment = self.current_translated_segments[index] or {}
        subtitle_text = " ".join(str(segment.get("text", "") or "").split()).strip()
        spoken_text = " ".join(str(segment.get("tts_text") or segment.get("dubbing_vi") or segment.get("text", "")).split()).strip()
        # The per-segment status label was moved to the A2 Dub
        # Track Inspector. Update it there so the inspector reflects
        # whether the spoken text matches the subtitle.
        status_label = getattr(self, "audio_inspector_spoken_status_label", None)
        if status_label is not None:
            if spoken_text and subtitle_text and spoken_text != subtitle_text:
                status_label.setText("Spoken text differs from subtitle.")
            elif spoken_text:
                status_label.setText("Spoken text matches subtitle.")
            else:
                status_label.setText("")

    def _resolve_segment_voice_text(self, segment: dict) -> str:
        current = dict(segment or {})
        subtitle_text = " ".join(str(current.get("text", "") or "").split()).strip()
        if bool(current.get("voice_edited")):
            edited_text = " ".join(str(current.get("tts_text") or current.get("dubbing_vi") or "").split()).strip()
            if edited_text:
                return edited_text
        return subtitle_text

    def on_segment_spoken_text_edited(self, index: int, editor: QTextEdit):
        if getattr(self, "_syncing_segment_editor", False):
            return
        if not (0 <= index < len(self.current_translated_segments or [])):
            return
        value = " ".join(editor.toPlainText().split()).strip()
        segment = self.current_translated_segments[index]
        segment["tts_text"] = value
        segment["dubbing_vi"] = value
        segment["voice_edited"] = True
        self._voiceover_force_refresh = True
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self.persist_current_timeline_project_data()
        self._update_segment_spoken_status(index)
        self.refresh_ui_state()

    def use_spoken_text_for_subtitle(self, index: int):
        if not (0 <= index < len(self.current_translated_segments or [])):
            return
        segment = self.current_translated_segments[index]
        spoken_text = " ".join(str(segment.get("tts_text") or segment.get("dubbing_vi") or "").split()).strip()
        if not spoken_text:
            QMessageBox.information(self, "Nothing To Match", "This line does not have voice text yet.")
            return
        segment["text"] = spoken_text
        segment["subtitle_vi"] = spoken_text
        segment["voice_edited"] = True
        self._voiceover_force_refresh = True
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_hidden_translated_text_from_segments()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.sync_segment_editor_rows()
        self.refresh_ui_state()

    def _normalize_manual_highlight(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").replace("\u2029", " ").replace("\n", " ")).strip()

    def refresh_auto_keyword_highlights(self, force: bool = False):
        if not getattr(self, "current_translated_segments", None):
            return
        if not getattr(self, "subtitle_keyword_highlight_cb", None) or not self.subtitle_keyword_highlight_cb.isChecked():
            return
        if not hasattr(self, "subtitle_highlight_mode_combo") or self.subtitle_highlight_mode_combo.currentText().strip() not in ("Auto", "Auto + Manual"):
            return

        pending_indexes = []
        pending_texts = []
        for idx, segment in enumerate(self.current_translated_segments or []):
            text = ' '.join(str(segment.get("text") or "").replace("\n", " ").split()).strip()
            if not text:
                segment["auto_highlights"] = []
                continue
            cached_key = segment.get("_auto_highlights_source_text", "")
            if not force and cached_key == text and isinstance(segment.get("auto_highlights"), list):
                continue
            pending_indexes.append(idx)
            pending_texts.append(text)

        if not pending_texts:
            return

        self.log(f"[Auto Highlight] Generating highlight phrases for {len(pending_texts)} subtitle lines...")
        resolved_batches = [
            [candidate.text for candidate in auto_select_matches(text, max_keywords=2)]
            for text in pending_texts
        ]

        for idx, phrases in zip(pending_indexes, resolved_batches):
            segment = self.current_translated_segments[idx]
            text = ' '.join(str(segment.get("text") or "").replace("\n", " ").split()).strip()
            cleaned = []
            seen = set()
            lowered = text.lower()
            for phrase in phrases or []:
                normalized = self._normalize_manual_highlight(phrase)
                key = normalized.lower()
                if not normalized or key in seen or key not in lowered:
                    continue
                seen.add(key)
                cleaned.append(normalized)
            segment["auto_highlights"] = cleaned
            segment["_auto_highlights_source_text"] = text

        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)

    def _reconcile_manual_highlights(self, segment: dict):
        text = str(segment.get("text", ""))
        cleaned = []
        seen = set()
        for phrase in segment.get("manual_highlights", []):
            normalized = self._normalize_manual_highlight(phrase)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen or key not in text.lower():
                continue
            seen.add(key)
            cleaned.append(normalized)
        segment["manual_highlights"] = cleaned

    def _sync_segment_highlight_chip_row(self, index: int):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        chip_layout = row.get("highlight_chip_layout")
        placeholder = row.get("highlight_placeholder")
        if chip_layout is None:
            return

        while chip_layout.count():
            item = chip_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        highlights = []
        if index < len(self.current_translated_segments):
            highlights = list(self.current_translated_segments[index].get("manual_highlights", []))

        if placeholder:
            placeholder.setVisible(not highlights)

        for phrase in highlights:
            chip = QPushButton(f"[ {phrase} ]")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { background-color: #173049; color: #9fe5ff; border: 1px solid #356081; border-radius: 999px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { background-color: #214161; }"
            )
            chip.clicked.connect(lambda _=False, idx=index, value=phrase: self.remove_segment_manual_highlight(idx, value))
            chip_layout.addWidget(chip)
        chip_layout.addStretch()

    def add_segment_manual_highlight(self, index: int, editor: QTextEdit):
        if index < 0 or index >= len(self.current_translated_segments):
            QMessageBox.warning(self, "Highlight", "Please prepare translated subtitles first.")
            return

        selected_text = self._normalize_manual_highlight(editor.textCursor().selectedText())
        if not selected_text:
            QMessageBox.warning(self, "Highlight", "Select the translated text you want to highlight first.")
            return

        segment = self.current_translated_segments[index]
        segment.setdefault("manual_highlights", [])
        existing = {self._normalize_manual_highlight(item).lower() for item in segment.get("manual_highlights", [])}
        if selected_text.lower() not in existing:
            segment["manual_highlights"].append(selected_text)
        self._reconcile_manual_highlights(segment)
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def remove_segment_manual_highlight(self, index: int, phrase: str):
        if index < 0 or index >= len(self.current_translated_segments):
            return
        target = self._normalize_manual_highlight(phrase).lower()
        segment = self.current_translated_segments[index]
        segment["manual_highlights"] = [
            item for item in segment.get("manual_highlights", [])
            if self._normalize_manual_highlight(item).lower() != target
        ]
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def _update_segment_highlight_button_state(self, index: int, editor: QTextEdit):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        button = row.get("highlight_button")
        if button is None:
            return
        has_selection = bool(self._normalize_manual_highlight(editor.textCursor().selectedText()))
        button.setEnabled(has_selection)

    def _clear_segment_editor_rows(self):
        if not hasattr(self, "segment_editor_layout"):
            return
        while self.segment_editor_layout.count():
            item = self.segment_editor_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget:
                        child_widget.hide()
                        child_widget.setParent(None)
                        child_widget.deleteLater()




    def _get_effective_selected_segment_index(self, rows=None) -> int:
        rows = rows if rows is not None else self._segment_editor_display_rows()
        if not rows:
            return -1
        selected = int(getattr(self, "_selected_segment_index", -1))
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if selected in valid_indexes:
            return selected
        active_index = self._find_active_segment_index(self.media_player.position(), self.live_preview_segments or self.get_active_segments())
        if active_index in valid_indexes:
            return active_index
        return valid_indexes[0]

    def set_selected_segment_index(self, index: int, *, sync_ui: bool = True):
        rows = self._segment_editor_display_rows()
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if not valid_indexes:
            self._selected_segment_index = -1
        elif index in valid_indexes:
            self._selected_segment_index = int(index)
        else:
            self._selected_segment_index = valid_indexes[0]
        if sync_ui:
            self.sync_segment_editor_rows()
        if hasattr(self, "_refresh_audio_inspector_dub_voice_buttons"):
            try:
                self._refresh_audio_inspector_dub_voice_buttons()
            except Exception:
                pass

    def on_timeline_segment_timing_edit_started(self, index: int, start: float, end: float):
        if self._suspend_timeline_undo:
            return
        last_entry = self._timeline_timing_undo_stack[-1] if self._timeline_timing_undo_stack else None
        if last_entry and str(last_entry.get("type", "timing")) == "timing" and int(last_entry.get("index", -1)) == int(index):
            if abs(float(last_entry.get("start", 0.0)) - float(start)) < 0.0001 and abs(float(last_entry.get("end", 0.0)) - float(end)) < 0.0001:
                return
        self._timeline_timing_undo_stack.append(
            {
                "type": "timing",
                "index": int(index),
                "start": float(start),
                "end": float(end),
            }
        )
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

    def on_timeline_segment_selected(self, index: int):
        self.set_selected_segment_index(index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)

    def _set_layer_timing_controls(self, prefix: str, layer) -> None:
        """Populate an overlay inspector's Start/End controls without edits."""
        for suffix, value in (("start", float(layer.start)), ("end", float(layer.end))):
            control = getattr(self, f"{prefix}_inspector_{suffix}_spin", None)
            if control is None:
                continue
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

    def _layer_is_active_at_preview_time(self, layer, time_seconds=None) -> bool:
        """Return whether a layer should be visible at the current playhead."""
        if not bool(getattr(layer, "visible", True)):
            return False
        if time_seconds is None:
            try:
                time_seconds = float(self.media_player.position()) / 1000.0
            except Exception:
                time_seconds = 0.0
        start = max(0.0, float(getattr(layer, "start", 0.0) or 0.0))
        end = float(getattr(layer, "end", 0.0) or 0.0)
        # Legacy layers without a valid duration continue to be visible.
        return end <= start or (start <= float(time_seconds) < end)

    def refresh_timed_layer_preview(self, position_ms=None) -> None:
        """Show only overlay layers whose timeline interval contains the playhead."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        time_seconds = float(position_ms if position_ms is not None else self.media_player.position()) / 1000.0
        tracked = []
        for track in self.timeline._timeline.tracks:
            for layer in track.layers:
                layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                is_logo = layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                if layer_type in {"blur", "mask", "text"} or is_logo:
                    tracked.append((layer.id, self._layer_is_active_at_preview_time(layer, time_seconds)))
        signature = tuple(tracked)
        if signature == getattr(self, "_timed_layer_preview_signature", None):
            return
        self._timed_layer_preview_signature = signature
        selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")

        # Text layers are rendered independently, so filtering their payload
        # makes them disappear/reappear without changing their saved state.
        self._refresh_text_layer_preview(selected_id)

        for track in self.timeline._timeline.tracks:
            if str(getattr(track, "name", "")) == "L1 Logo":
                active = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                if active:
                    target = next((l for l in active if l.id == selected_id), active[0])
                    self._show_logo_overlay(track, target)
                elif hasattr(self.video_view, "clear_logo"):
                    self.video_view.clear_logo()
            elif str(getattr(track, "name", "")) == "M1":
                active_layers = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                regions = self._current_mask_regions_payload(time_seconds=time_seconds)
                if hasattr(self.video_view, "set_mask_regions"):
                    active_index = next((i for i, l in enumerate(active_layers) if l.id == selected_id), 0)
                    self.video_view.set_mask_regions(regions, active_index=active_index, editable=bool(active_layers and selected_id in {l.id for l in active_layers}))
            elif str(getattr(track, "name", "")) == "B1":
                regions = []
                active_layers = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                for layer in active_layers:
                    regions.append({
                        "x": float(getattr(layer, "position_x", 0.0)), "y": float(getattr(layer, "position_y", 0.0)),
                        "width": float(getattr(layer, "width", 0.0)), "height": float(getattr(layer, "height", 0.0)),
                        "blur_strength": float(getattr(layer, "blur_strength", 20.0)),
                        "blur_opacity": float(getattr(layer, "blur_opacity", 1.0)),
                        "pixelate": bool(getattr(layer, "pixelate", False)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
                    })
                if hasattr(self.video_view, "set_blur_regions_normalized"):
                    self.video_view.set_blur_regions_normalized(regions)
                # Blur has a separate MPV filter in addition to its editable
                # outline. Update that filter with the same time-filtered
                # regions; otherwise a filter applied at playback start
                # continues blurring after the outline has disappeared.
                self.apply_preview_blur_region(regions=regions)

    def _wire_layer_timing_controls(self, prefix: str) -> None:
        """Wire one inspector's common Start/End controls once."""
        wired_name = f"_{prefix}_layer_timing_wired"
        if getattr(self, wired_name, False):
            return
        setattr(self, wired_name, True)
        start_control = getattr(self, f"{prefix}_inspector_start_spin", None)
        end_control = getattr(self, f"{prefix}_inspector_end_spin", None)
        if start_control is None or end_control is None:
            return

        def _selected_layer():
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            for track in getattr(getattr(self.timeline, "_timeline", None), "tracks", []):
                for layer in track.layers:
                    if layer.id == selected_id:
                        return track, layer
            return None, None

        def _apply_timing(_value=None):
            track, layer = _selected_layer()
            if layer is None:
                return
            start = max(0.0, float(start_control.value()))
            end = max(start + float(getattr(self.timeline, "MIN_DUR", 0.1)), float(end_control.value()))
            duration = float(getattr(self.timeline, "_duration", 0.0) or 0.0)
            if duration > 0:
                start = min(start, max(0.0, duration - float(getattr(self.timeline, "MIN_DUR", 0.1))))
                end = min(end, duration)
                end = max(end, start + float(getattr(self.timeline, "MIN_DUR", 0.1)))
            layer.start, layer.end = start, end
            self._set_layer_timing_controls(prefix, layer)
            self.timeline._redraw()
            self.persist_current_timeline_project_data()
            self._timed_layer_preview_signature = None
            self.refresh_timed_layer_preview()
            if prefix == "mask":
                self._apply_mask_to_preview(
                    regions=self._current_mask_regions_payload(include_inactive=True)
                )

        start_control.valueChanged.connect(_apply_timing)
        end_control.valueChanged.connect(_apply_timing)

    def on_timeline_layer_timing_changed(self, layer_id: str, start: float, end: float):
        """Persist timeline-handle duration edits for all non-subtitle layers."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        for track in self.timeline._timeline.tracks:
            for layer in track.layers:
                if layer.id != layer_id:
                    continue
                layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                is_logo = layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                if layer_type not in {"blur", "mask", "text"} and not is_logo:
                    return
                layer.start = max(0.0, float(start))
                layer.end = max(layer.start + float(getattr(self.timeline, "MIN_DUR", 0.1)), float(end))
                self.persist_current_timeline_project_data()
                self._timed_layer_preview_signature = None
                self.refresh_timed_layer_preview()
                if layer_type == "mask":
                    self._apply_mask_to_preview(
                        regions=self._current_mask_regions_payload(include_inactive=True)
                    )
                # Refresh the visible inspector values while keeping its
                # layer-specific visual controls and preview selection intact.
                self.on_timeline_layer_selected(layer_id)
                return

    def on_timeline_layer_selected(self, layer_id: str):
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        track = None
        layer = None
        for t in self.timeline._timeline.tracks:
            for l in t.layers:
                if l.id == layer_id:
                    layer = l
                    track = t
                    break
            if layer:
                break
        # The subtitle overlay should only capture the mouse when a concrete
        # subtitle segment (TS1/S1) is selected in the timeline.  Otherwise
        # it stays click-through, preventing accidental moves while editing
        # other video layers.
        if hasattr(self, "video_view") and hasattr(self.video_view, "subtitle_item"):
            layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower() if layer else ""
            self.video_view.subtitle_item.set_editable(layer_type in {"subtitle", "dub_subtitle"})
        if not layer:
            self._show_default_inspector()
            if hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
            return
        # A selection must respect timing immediately, including before the
        # next playback positionChanged signal is emitted.
        self._timed_layer_preview_signature = None
        self.refresh_timed_layer_preview()
        layer_type = str(getattr(layer.type, "value", layer.type)).lower()
        if hasattr(self, "timeline_split_btn"):
            self.timeline_split_btn.setEnabled(
                layer_type in {"subtitle", "dub_subtitle", "blur", "mask", "text"}
                or (layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo")
            )
        if layer_type == "subtitle":
            self._show_subtitle_inspector_for_layer(layer_id)
        elif layer_type == "dub_subtitle":
            self._show_dub_subtitle_inspector_for_layer(layer_id, layer)
        elif layer_type == "audio":
            if str(getattr(track, "name", "")) != "A1 Audio":
                self._show_audio_inspector_for_track(track, layer)
        elif layer_type == "blur":
            self._show_blur_inspector_for_track(track, layer)
        elif layer_type == "video":
            self._show_video_inspector_for_track(track, layer)
        elif layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo":
            self._show_logo_overlay(track, layer)
            self._show_logo_inspector_for_track(track, layer)
        elif layer_type == "mask" or str(getattr(track, "name", "")) == "M1":
            self._show_mask_overlay(track, layer)
            self._show_mask_inspector_for_track(track, layer)
        elif layer_type == "text":
            self._show_text_inspector_for_track(track, layer)
            self._refresh_text_layer_preview(layer.id)
        else:
            # Image, sticker: show default with info
            self._show_default_inspector_for_layer(track, layer)
            if hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
            if hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
                self.video_view.clear_mask_region()

    def _show_logo_overlay(self, track, layer):
        """Show the draggable logo overlay for the selected logo layer."""
        if not hasattr(self, "video_view"):
            return
        path = str(getattr(layer, "source", "") or "")
        if not path:
            return
        try:
            from app.layers.transform import Transform
            transform = getattr(layer, "transform", None) or Transform()
        except Exception:
            transform = None
        # Get position/size from the layer (use transform or defaults)
        if transform is not None and hasattr(transform, "x"):
            x = float(getattr(transform, "x", 0.1)) / 100.0
            y = float(getattr(transform, "y", 0.1)) / 100.0
            scale_x = float(getattr(transform, "scale_x", 1.0))
            scale_y = float(getattr(transform, "scale_y", 1.0))
            w = 0.2 * scale_x
            h = 0.2 * scale_y
        else:
            x, y, w, h = 0.1, 0.1, 0.2, 0.2

        # Store the handler lambdas as attributes so we can disconnect
        # them by reference. This avoids the libpyside RuntimeWarning
        # that occurs when calling disconnect() with no args or with
        # a lambda that was never connected.
        prev_moved = getattr(self, "_logo_moved_handler", None)
        if prev_moved is not None:
            try:
                self.video_view.logoMoved.disconnect(prev_moved)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_deleted = getattr(self, "_logo_deleted_handler", None)
        if prev_deleted is not None:
            try:
                self.video_view.logoDeleted.disconnect(prev_deleted)
            except (RuntimeError, TypeError, Exception):
                pass

        self._logo_overlay_layer = layer

        def _moved_handler(nx, ny, nw, nh, l=layer):
            self._on_logo_moved(l, nx, ny, nw, nh)

        def _deleted_handler(l=layer):
            self._delete_logo_layer(l)

        self._logo_moved_handler = _moved_handler
        self._logo_deleted_handler = _deleted_handler

        self.video_view.logoMoved.connect(_moved_handler)
        self.video_view.logoDeleted.connect(_deleted_handler)

        logos = []
        active_index = 0
        for index, candidate in enumerate(track.layers):
            if not self._layer_is_active_at_preview_time(candidate):
                continue
            source = str(getattr(candidate, "source", "") or "")
            candidate_transform = getattr(candidate, "transform", None)
            if candidate_transform is not None and hasattr(candidate_transform, "x"):
                logo_x = float(getattr(candidate_transform, "x", 0.1)) / 100.0
                logo_y = float(getattr(candidate_transform, "y", 0.1)) / 100.0
                logo_w = 0.2 * float(getattr(candidate_transform, "scale_x", 1.0))
                logo_h = 0.2 * float(getattr(candidate_transform, "scale_y", 1.0))
                logo_rotation = float(getattr(candidate_transform, "rotation", 0.0) or 0.0)
            else:
                logo_x, logo_y, logo_w, logo_h, logo_rotation = 0.1, 0.1, 0.2, 0.2, 0.0
            logos.append({
                "source": source, "x": logo_x, "y": logo_y,
                "width": logo_w, "height": logo_h,
                "opacity": float(getattr(candidate, "opacity", 1.0) or 1.0),
                "rotation": logo_rotation,
            })
            if candidate is layer:
                active_index = len(logos) - 1
        if not logos:
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
            return
        self.video_view.set_logos(logos, active_index=active_index)

        # Push opacity + rotation from the layer to the overlay. We
        # default to fully opaque + 0° for a freshly created logo.
        opacity = float(getattr(layer, "opacity", 1.0) or 1.0)
        rotation = 0.0
        if transform is not None and hasattr(transform, "rotation"):
            try:
                rotation = float(getattr(transform, "rotation", 0.0) or 0.0)
            except (TypeError, ValueError):
                rotation = 0.0
        self.video_view.set_logo_opacity(opacity)
        self.video_view.set_logo_rotation(rotation)

    def _delete_logo_layer(self, layer):
        """Remove the logo layer from the L1 track and clean up."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        remaining_track = None
        remaining_layer = None
        for track in self.timeline._timeline.tracks:
            if layer in track.layers:
                track.layers.remove(layer)
                if not track.layers:
                    try:
                        self.timeline._timeline.tracks.remove(track)
                    except ValueError:
                        pass
                    if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                        del self.timeline._track_heights[track.id]
                else:
                    remaining_track = track
                    remaining_layer = track.layers[0]
                break
        try:
            self.timeline._selected_layer_id = remaining_layer.id if remaining_layer else ""
        except Exception:
            pass
        if hasattr(self.timeline, "_redraw"):
            self.timeline._redraw()
        if hasattr(self.timeline, "viewport"):
            self.timeline.viewport().update()
        if remaining_layer is not None:
            self._show_logo_overlay(remaining_track, remaining_layer)
        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
            self.video_view.clear_logo()
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass
        if hasattr(self, "_show_default_inspector"):
            self._show_default_inspector()

    def _on_logo_moved(self, layer, x, y, w, h):
        """Update the ImageLayer's transform from the logo overlay drag."""
        try:
            from app.layers.transform import Transform
            transform = Transform(
                x=float(x) * 100.0,
                y=float(y) * 100.0,
                scale_x=float(w) / 0.2 if 0.2 > 0 else 1.0,
                scale_y=float(h) / 0.2 if 0.2 > 0 else 1.0,
            )
            layer.transform = transform
        except Exception:
            pass
        # Save timeline data (includes logo layer changes)
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass

    def _show_mask_overlay(self, track, layer):
        """Show the draggable mask overlay for the selected mask layer."""
        if not hasattr(self, "video_view"):
            return
        # Disconnect any previous handlers to avoid the libpyside
        # RuntimeWarning that occurs when calling disconnect() with no
        # args or a lambda that was never connected.
        prev_moved = getattr(self, "_mask_moved_handler", None)
        if prev_moved is not None:
            try:
                self.video_view.maskMoved.disconnect(prev_moved)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_changed = getattr(self, "_mask_region_changed_handler", None)
        if prev_changed is not None:
            try:
                self.video_view.maskRegionChanged.disconnect(prev_changed)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_deleted = getattr(self, "_mask_deleted_handler", None)
        if prev_deleted is not None:
            try:
                self.video_view.maskDeleted.disconnect(prev_deleted)
            except (RuntimeError, TypeError, Exception):
                pass

        self._mask_overlay_layer = layer

        def _moved_handler(nx, ny, nw, nh, l=layer):
            self._on_mask_moved(l, nx, ny, nw, nh)

        def _region_changed_handler(t=track, l=layer):
            # Fired continuously while the user drags the overlay. Push
            # the new region back to the layer + mpv filter so the
            # green mask follows the overlay in real time.
            self._on_mask_overlay_changed(t, l)

        def _deleted_handler(l=layer):
            self._delete_mask_layer(l)

        self._mask_moved_handler = _moved_handler
        self._mask_region_changed_handler = _region_changed_handler
        self._mask_deleted_handler = _deleted_handler

        self.video_view.maskMoved.connect(_moved_handler)
        self.video_view.maskRegionChanged.connect(_region_changed_handler)
        self.video_view.maskDeleted.connect(_deleted_handler)

        regions = self._current_mask_regions_payload()
        try:
            active_index = list(track.layers).index(layer)
        except ValueError:
            active_index = 0
        # The overlay is always shown so the user can move / resize
        # the region regardless of the M1 track toggle. The toggle
        # only controls whether the mpv filter is applied (see
        # on_track_mask_toggled). Without this, the overlay would
        # only appear after the user clicked the mask layer track
        # to re-select it, even though the layer already exists.
        is_playing = False
        try:
            is_playing = bool(self.media_player.is_playing())
        except Exception:
            is_playing = False
        self.video_view.set_mask_regions(
            regions, active_index=active_index, editable=not is_playing,
        )

    def _on_mask_moved(self, layer, x, y, w, h):
        """Update the MaskLayer's geometry from the mask overlay drag.

        Then push the change into the mpv filter chain and persist it.
        """
        try:
            layer.position_x = float(x)
            layer.position_y = float(y)
            layer.width = float(w)
            layer.height = float(h)
        except Exception:
            return
        try:
            self._apply_mask_to_preview()
        except Exception:
            pass
        try:
            if hasattr(self, "persist_project_mask_state"):
                self.persist_project_mask_state()
        except Exception:
            pass
        # Save timeline data (includes mask layer changes)
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass
        # Keep the spinboxes in sync so the inspector shows the new
        # values as the user drags the overlay.
        try:
            if (hasattr(self, "mask_inspector_x_spin")
                    and self.timeline._selected_layer_id == layer.id):
                self.mask_inspector_x_spin.blockSignals(True)
                self.mask_inspector_x_spin.setValue(float(x))
                self.mask_inspector_x_spin.blockSignals(False)
                self.mask_inspector_y_spin.blockSignals(True)
                self.mask_inspector_y_spin.setValue(float(y))
                self.mask_inspector_y_spin.blockSignals(False)
                self.mask_inspector_w_spin.blockSignals(True)
                self.mask_inspector_w_spin.setValue(float(w))
                self.mask_inspector_w_spin.blockSignals(False)
                self.mask_inspector_h_spin.blockSignals(True)
                self.mask_inspector_h_spin.setValue(float(h))
                self.mask_inspector_h_spin.blockSignals(False)
        except Exception:
            pass

    def _on_mask_overlay_changed(self, track, layer):
        """Read the current overlay region and update the layer
        position. The mpv filter is NOT re-applied here — it is
        only applied while the video is playing, to avoid lag
        during the drag. When the user presses play, the latest
        layer position is pushed to mpv via `_apply_mask_to_preview`
        (called from `toggle_play` and the stateChanged handler).
        """
        if not hasattr(self, "video_view"):
            return
        overlay = getattr(self.video_view, "mask_overlay", None)
        if overlay is None or not overlay._regions:
            return
        try:
            active_index = int(getattr(overlay, "_active_index", -1))
            rect = overlay._regions[active_index]
            x = float(rect.x())
            y = float(rect.y())
            w = float(rect.width())
            h = float(rect.height())
        except Exception:
            return
        try:
            layer.position_x = x
            layer.position_y = y
            layer.width = w
            layer.height = h
        except Exception:
            return

    def _delete_mask_layer(self, layer):
        """Remove the mask layer from the M1 track and clean up."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        remaining_track = None
        remaining_layer = None
        for track in self.timeline._timeline.tracks:
            if layer in track.layers:
                track.layers.remove(layer)
                if not track.layers:
                    try:
                        self.timeline._timeline.tracks.remove(track)
                    except ValueError:
                        pass
                    if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                        del self.timeline._track_heights[track.id]
                else:
                    remaining_track = track
                    remaining_layer = track.layers[0]
                break
        try:
            self.timeline._selected_layer_id = remaining_layer.id if remaining_layer else ""
        except Exception:
            pass
        if hasattr(self.timeline, "_redraw"):
            self.timeline._redraw()
        if hasattr(self.timeline, "viewport"):
            self.timeline.viewport().update()
        if remaining_layer is not None:
            self._show_mask_overlay(remaining_track, remaining_layer)
        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
            self.video_view.clear_mask_region()
        try:
            if hasattr(self, "_apply_mask_to_preview"):
                self._apply_mask_to_preview()
        except Exception:
            pass
        try:
            if hasattr(self, "persist_project_mask_state"):
                self.persist_project_mask_state()
        except Exception:
            pass
        if hasattr(self, "_show_default_inspector"):
            self._show_default_inspector()

    def _show_subtitle_inspector_for_layer(self, layer_id: str):
        """Show subtitle inspector and select the matching segment."""
        self._switch_inspector("subtitle")
        if hasattr(self, "timeline") and self.timeline:
            idx = self.timeline._segment_indices.get(layer_id, -1)
            if idx >= 0:
                self.set_selected_segment_index(idx, sync_ui=True)

    def _show_dub_subtitle_inspector_for_layer(self, layer_id: str, layer=None):
        """Show the inspector for a dub subtitle layer."""
        self._switch_inspector("subtitle")
        if hasattr(self, "timeline") and self.timeline:
            idx = self.timeline._segment_indices.get(layer_id, -1)
            if idx >= 0:
                self.set_selected_segment_index(idx, sync_ui=True)

    def _show_audio_inspector_for_track(self, track, layer=None):
        """Show audio inspector populated with the selected track's settings."""
        self._switch_inspector("audio")
        # The Dub Voice section is only for A2 Dub/TS1. Hide it for
        # A1 Audio (or any other audio track).
        track_name = str(getattr(track, "name", "") or "")
        dub_section = getattr(self, "audio_inspector_dub_section", None)
        if dub_section is not None:
            dub_section.setVisible(track_name in ("A2 Dub", "TS1"))
        if track is None:
            return
        track_name = str(getattr(track, "name", "Audio"))
        if hasattr(self, "audio_inspector_track_name_label"):
            self.audio_inspector_track_name_label.setText(track_name)
        if hasattr(self, "audio_inspector_layer_count_label"):
            count = len(list(getattr(track, "layers", [])))
            if layer is not None:
                layer_label = f"Selected: {layer.name}"
            else:
                layer_label = "No layer selected"
            self.audio_inspector_layer_count_label.setText(
                f"{layer_label}    •    {count} layer(s) in track"
            )
        if hasattr(self, "audio_inspector_summary_label"):
            self.audio_inspector_summary_label.setText(
                f"Audio settings for {track_name}. Adjust volume, gain, "
                "speed or mute the track for preview."
            )
        # Load current track metadata into the controls
        meta = getattr(track, "metadata", None) or {}
        try:
            volume = float(meta.get("_volume", 100.0))
        except (TypeError, ValueError):
            volume = 100.0
        try:
            gain = float(meta.get("_gain_db", 0.0))
        except (TypeError, ValueError):
            gain = 0.0
        try:
            speed = float(meta.get("_speed", 1.0))
        except (TypeError, ValueError):
            speed = 1.0
        muted = bool(meta.get("_muted", False))
        solo = bool(meta.get("_solo", False))
        try:
            fade_in = float(meta.get("_fade_in", 0.0))
        except (TypeError, ValueError):
            fade_in = 0.0
        try:
            fade_out = float(meta.get("_fade_out", 0.0))
        except (TypeError, ValueError):
            fade_out = 0.0
        if hasattr(self, "audio_inspector_gain_spin"):
            self.audio_inspector_gain_spin.blockSignals(True)
            self.audio_inspector_gain_spin.setValue(gain)
            self.audio_inspector_gain_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_speed_spin"):
            self.audio_inspector_speed_spin.blockSignals(True)
            self.audio_inspector_speed_spin.setValue(speed)
            self.audio_inspector_speed_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_mute_btn"):
            self.audio_inspector_mute_btn.blockSignals(True)
            self.audio_inspector_mute_btn.setChecked(muted)
            self.audio_inspector_mute_btn.setText("Unmute Track" if muted else "Mute Track")
            self.audio_inspector_mute_btn.blockSignals(False)
        if hasattr(self, "audio_inspector_solo_btn"):
            self.audio_inspector_solo_btn.blockSignals(True)
            self.audio_inspector_solo_btn.setChecked(solo)
            self.audio_inspector_solo_btn.blockSignals(False)
        if hasattr(self, "audio_inspector_fade_in_spin"):
            self.audio_inspector_fade_in_spin.blockSignals(True)
            self.audio_inspector_fade_in_spin.setValue(fade_in)
            self.audio_inspector_fade_in_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_fade_out_spin"):
            self.audio_inspector_fade_out_spin.blockSignals(True)
            self.audio_inspector_fade_out_spin.setValue(fade_out)
            self.audio_inspector_fade_out_spin.blockSignals(False)
        if hasattr(self, "_refresh_audio_inspector_dub_voice_buttons"):
            try:
                self._refresh_audio_inspector_dub_voice_buttons()
            except Exception:
                pass

    def _show_default_inspector_for_layer(self, track, layer):
        self._switch_inspector("default")
        if hasattr(self, "default_inspector_summary_label"):
            tname = getattr(track, "name", "Track") if track else "Track"
            lname = getattr(layer, "name", "Layer") if layer else "Layer"
            ltype = str(getattr(layer.type, "value", layer.type)) if layer else "?"
            self.default_inspector_summary_label.setText(
                f"Selected: {tname} → {lname} ({ltype}).\n"
                "No per-layer settings available for this track type yet."
            )

    def _show_blur_inspector_for_track(self, track, layer=None):
        """Show the Blur Track Inspector populated with the selected track."""
        self._switch_inspector("blur")
        self._wire_blur_inspector_controls()
        self._wire_layer_timing_controls("blur")
        if track is None:
            return
        # B1 mirrors M1 interaction: all regions remain visible in the
        # preview, but only the layer selected in the timeline is editable.
        if layer is not None:
            self._set_layer_timing_controls("blur", layer)
            try:
                active_index = list(track.layers).index(layer)
                self.video_view.set_blur_active_index(active_index)
            except (AttributeError, ValueError):
                pass
        track_name = str(getattr(track, "name", "Blur"))
        if hasattr(self, "blur_inspector_track_name_label"):
            self.blur_inspector_track_name_label.setText(track_name)
        if hasattr(self, "blur_inspector_layer_count_label"):
            count = len(list(getattr(track, "layers", [])))
            if layer is not None:
                self.blur_inspector_layer_count_label.setText(
                    f"Selected: {layer.name}    •    {count} blur region(s) in track"
                )
            else:
                self.blur_inspector_layer_count_label.setText(
                    f"{count} blur region(s) in track"
                )
        # Load show-on-preview state from track metadata
        meta = getattr(track, "metadata", None) or {}
        show = bool(meta.get("_show_on_preview", True))
        if hasattr(self, "blur_inspector_show_cb"):
            self.blur_inspector_show_cb.blockSignals(True)
            self.blur_inspector_show_cb.setChecked(show)
            self.blur_inspector_show_cb.blockSignals(False)
        # Load radius / opacity / pixelate from the selected layer
        # (fall back to defaults when no layer is selected).
        if layer is not None:
            try:
                strength = int(round(float(getattr(layer, "blur_strength", 20.0))))
            except (TypeError, ValueError):
                strength = 20
            strength = max(1, min(20, strength))
            try:
                opacity = float(getattr(layer, "blur_opacity", 1.0))
            except (TypeError, ValueError):
                opacity = 1.0
            opacity = max(0.0, min(1.0, opacity))
            pixelate = bool(getattr(layer, "pixelate", False))
            try:
                pixel_size = int(getattr(layer, "pixelate_size", 12))
            except (TypeError, ValueError):
                pixel_size = 12
            pixel_size = max(2, min(60, pixel_size))
        else:
            strength, opacity, pixelate, pixel_size = 20, 1.0, False, 12

        if hasattr(self, "blur_inspector_radius_slider"):
            self.blur_inspector_radius_slider.blockSignals(True)
            self.blur_inspector_radius_slider.setValue(strength)
            self.blur_inspector_radius_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_radius_value_label"):
            self.blur_inspector_radius_value_label.setText(str(strength))
        if hasattr(self, "blur_inspector_opacity_slider"):
            self.blur_inspector_opacity_slider.blockSignals(True)
            self.blur_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.blur_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_opacity_value_label"):
            self.blur_inspector_opacity_value_label.setText(
                f"{int(round(opacity * 100))}%"
            )
        if hasattr(self, "blur_inspector_pixelate_cb"):
            self.blur_inspector_pixelate_cb.blockSignals(True)
            self.blur_inspector_pixelate_cb.setChecked(pixelate)
            self.blur_inspector_pixelate_cb.blockSignals(False)
        if hasattr(self, "blur_inspector_pixel_size_slider"):
            self.blur_inspector_pixel_size_slider.blockSignals(True)
            self.blur_inspector_pixel_size_slider.setValue(pixel_size)
            self.blur_inspector_pixel_size_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_pixel_size_value_label"):
            self.blur_inspector_pixel_size_value_label.setText(str(pixel_size))

        if hasattr(self, "blur_inspector_summary_label"):
            state = "shown" if show else "hidden"
            self.blur_inspector_summary_label.setText(
                f"Blur regions in '{track_name}'. The visual blur is "
                f"currently {state} on the video preview."
            )

    def _wire_blur_inspector_controls(self):
        """One-time wiring of the Blur Inspector's per-region controls."""
        if getattr(self, "_blur_inspector_wired", False):
            return
        self._blur_inspector_wired = True

        def _selected_blur_layer():
            """Return the currently selected BlurLayer (or None)."""
            if not hasattr(self, "timeline") or not self.timeline._timeline:
                return None, None
            sid = getattr(self.timeline, "_selected_layer_id", "") or ""
            for tr in self.timeline._timeline.tracks:
                for l in tr.layers:
                    if l.id == sid:
                        return l, tr
            return None, None

        def _on_radius_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.blur_strength = int(value)
            except Exception:
                return
            if hasattr(self, "blur_inspector_radius_value_label"):
                self.blur_inspector_radius_value_label.setText(str(int(value)))
            self._sync_blur_layer_to_preview(layer)

        def _on_opacity_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            opacity = max(0.0, min(1.0, float(value) / 100.0))
            try:
                layer.blur_opacity = opacity
            except Exception:
                return
            if hasattr(self, "blur_inspector_opacity_value_label"):
                self.blur_inspector_opacity_value_label.setText(f"{int(value)}%")
            self._sync_blur_layer_to_preview(layer)

        def _on_pixelate_toggled(checked):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.pixelate = bool(checked)
            except Exception:
                return
            self._sync_blur_layer_to_preview(layer)

        def _on_pixel_size_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.pixelate_size = int(value)
            except Exception:
                return
            if hasattr(self, "blur_inspector_pixel_size_value_label"):
                self.blur_inspector_pixel_size_value_label.setText(str(int(value)))
            self._sync_blur_layer_to_preview(layer)

        self._blur_radius_handler = _on_radius_changed
        self._blur_opacity_handler = _on_opacity_changed
        self._blur_pixelate_handler = _on_pixelate_toggled
        self._blur_pixel_size_handler = _on_pixel_size_changed

        if hasattr(self, "blur_inspector_radius_slider"):
            self.blur_inspector_radius_slider.valueChanged.connect(_on_radius_changed)
        if hasattr(self, "blur_inspector_opacity_slider"):
            self.blur_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)
        if hasattr(self, "blur_inspector_pixelate_cb"):
            self.blur_inspector_pixelate_cb.toggled.connect(_on_pixelate_toggled)
        if hasattr(self, "blur_inspector_pixel_size_slider"):
            self.blur_inspector_pixel_size_slider.valueChanged.connect(_on_pixel_size_changed)

    def _sync_blur_layer_to_preview(self, layer):
        """Push a BlurLayer's per-region style back to the video preview
        + persisted state + B1 timeline regions (so the export matches).
        """
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "blur_overlay"):
            return
        try:
            from app.layers.blur import BlurLayer
            regions = self.video_view.blur_overlay._regions or []
        except Exception:
            return
        # Find the index of this layer in the B1 track to map it to
        # the corresponding region in the video overlay.
        idx = -1
        if hasattr(self, "timeline") and self.timeline._timeline:
            for tr in self.timeline._timeline.tracks:
                if tr.id == layer.id or layer in tr.layers:
                    try:
                        idx = list(tr.layers).index(layer)
                    except ValueError:
                        idx = -1
                    break
        if idx < 0 or idx >= len(regions):
            return
        rect = regions[idx]
        try:
            x = float(rect.x())
            y = float(rect.y())
            w = float(rect.width())
            h = float(rect.height())
        except Exception:
            return
        # Build a single-region payload using this layer's style and
        # write it through the normal persist + preview path.
        payload = [{
            "x": x, "y": y, "width": w, "height": h,
            "blur_strength": int(getattr(layer, "blur_strength", 20)),
            "blur_opacity": float(getattr(layer, "blur_opacity", 1.0)),
            "pixelate": bool(getattr(layer, "pixelate", False)),
            "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
        }]
        try:
            if hasattr(self.video_view, "set_blur_regions_normalized"):
                self.video_view.set_blur_regions_normalized(payload)
        except Exception:
            pass
        # Persist and re-apply the filter (so the export matches).
        if hasattr(self, "persist_project_blur_state"):
            try:
                self.persist_project_blur_state(regions=payload)
            except Exception:
                pass
        if hasattr(self, "apply_preview_blur_region"):
            try:
                self.apply_preview_blur_region(regions=payload, force=True)
            except Exception:
                pass
        # Push the new style onto the B1 track layers (one payload
        # entry per BlurLayer).
        if hasattr(self, "timeline") and self.timeline._timeline:
            from app.layers.blur import BlurLayer as _BL
            for tr in self.timeline._timeline.tracks:
                if tr.name == "B1":
                    for i, l in enumerate(tr.layers):
                        if i < len(payload):
                            l.blur_strength = int(payload[i].get("blur_strength", 20))
                            l.blur_opacity = float(payload[i].get("blur_opacity", 1.0))
                            l.pixelate = bool(payload[i].get("pixelate", False))
                            l.pixelate_size = int(payload[i].get("pixelate_size", 12))

    def _show_default_inspector(self):
        self._switch_inspector("default")

    def _text_layers(self):
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return []
        return [layer for track in self.timeline._timeline.tracks for layer in track.layers
                if str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower() == "text"]

    def _refresh_text_layer_preview(self, active_id=""):
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "set_text_layers"):
            return
        # Use the same source-to-preview calibration as the editable
        # subtitle overlay. TextLayer.font_size is authored at source-video
        # scale (60 px at 100%), while QFont draws in preview pixels.
        render_h = max(1, int(getattr(self.video_view, "subtitle_render_height", 0) or 0))
        if render_h <= 1:
            _render_w, render_h = self._subtitle_render_dimensions()
        preview_rect = self.video_view.get_preview_canvas_rect()
        preview_scale = max(1.0, float(preview_rect.height() or self.video_view.height() or 1.0)) / max(1, render_h)
        preview_text_scale = preview_scale * 0.85
        items = []
        for layer in self._text_layers():
            if not self._layer_is_active_at_preview_time(layer):
                continue
            transform = getattr(layer, "transform", None)
            items.append({
                "id": layer.id, "text": getattr(layer, "text", ""),
                "font_name": getattr(layer, "font_name", "Arial"),
                "font_size": max(1, int(round(float(getattr(layer, "font_size", 60)) * preview_text_scale))),
                "font_color": getattr(layer, "font_color", "#FFFFFF"),
                "font_bold": getattr(layer, "font_bold", False),
                "x": getattr(transform, "x", .5) if transform else .5,
                "y": getattr(transform, "y", .5) if transform else .5,
            })
        self.video_view.set_text_layers(items, active_id or getattr(self.timeline, "_selected_layer_id", ""))

    def _show_text_inspector_for_track(self, track, layer):
        self._switch_inspector("text")
        self._wire_text_inspector_controls()
        self._wire_layer_timing_controls("text")
        self._set_layer_timing_controls("text", layer)
        self.text_inspector_content.blockSignals(True)
        self.text_inspector_content.setPlainText(str(getattr(layer, "text", "")))
        self.text_inspector_content.blockSignals(False)
        self.text_inspector_font_combo.blockSignals(True)
        font_name = str(getattr(layer, "font_name", "Arial"))
        if self.text_inspector_font_combo.findText(font_name) < 0:
            self.text_inspector_font_combo.addItem(font_name)
        self.text_inspector_font_combo.setCurrentText(font_name)
        self.text_inspector_font_combo.blockSignals(False)
        size = int(getattr(layer, "font_size", 60))
        choices = [int(self.text_inspector_size_combo.itemData(i)) for i in range(self.text_inspector_size_combo.count())]
        nearest = min(choices, key=lambda percent: abs(60 * percent / 100.0 - size))
        self.text_inspector_size_combo.blockSignals(True)
        self.text_inspector_size_combo.setCurrentIndex(self.text_inspector_size_combo.findData(nearest))
        self.text_inspector_size_combo.blockSignals(False)
        color = str(getattr(layer, "font_color", "#FFFFFF"))
        self.text_inspector_color_btn.setText(color)
        self.text_inspector_color_btn.setStyleSheet(f"background-color: {color}; color: #fff;")
        self.text_inspector_summary_label.setText(f"Selected: {getattr(track, 'name', 'T1 Text')} → {getattr(layer, 'name', 'Text')}. Drag it on the preview to move it.")

    def _wire_text_inspector_controls(self):
        if getattr(self, "_text_inspector_wired", False):
            return
        self._text_inspector_wired = True
        def selected():
            sid = getattr(self.timeline, "_selected_layer_id", "")
            return next((layer for layer in self._text_layers() if layer.id == sid), None)
        def changed():
            layer = selected()
            if layer:
                self._refresh_text_layer_preview(layer.id)
                self.persist_current_timeline_project_data()
        def content_changed():
            layer = selected()
            if layer:
                text = self.text_inspector_content.toPlainText()
                if not text.strip():
                    text = "Text"
                    self.text_inspector_content.blockSignals(True)
                    self.text_inspector_content.setPlainText(text)
                    self.text_inspector_content.blockSignals(False)
                layer.text = text
                first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Text")
                layer.name = first_line[:24] or "Text"
                self.timeline._redraw(); changed()
        def size_changed(_index):
            layer = selected()
            if layer:
                percent = int(self.text_inspector_size_combo.currentData() or 100)
                layer.font_size = int(round(60 * percent / 100.0)); changed()
        def font_changed(value):
            layer = selected()
            if layer: layer.font_name = str(value); changed()
        def color_changed():
            from PySide6.QtWidgets import QColorDialog
            from PySide6.QtGui import QColor
            layer = selected()
            chosen = QColorDialog.getColor(QColor(getattr(layer, "font_color", "#FFFFFF")), self, "Pick text color")
            if layer and chosen.isValid():
                layer.font_color = chosen.name(); self.text_inspector_color_btn.setText(layer.font_color)
                self.text_inspector_color_btn.setStyleSheet(f"background-color: {layer.font_color}; color: #fff;"); changed()
        self.text_inspector_content.textChanged.connect(content_changed)
        self.text_inspector_size_combo.currentIndexChanged.connect(size_changed)
        self.text_inspector_font_combo.currentTextChanged.connect(font_changed)
        self.text_inspector_color_btn.clicked.connect(color_changed)

    def _show_logo_inspector_for_track(self, track, layer=None):
        """Show the Logo Track Inspector populated with the selected L1 layer."""
        self._switch_inspector("logo")
        self._wire_logo_inspector_controls()
        self._wire_layer_timing_controls("logo")
        if layer is None:
            return
        self._set_layer_timing_controls("logo", layer)
        # Read current opacity/rotation from the layer and apply to the
        # inspector controls.
        opacity = float(getattr(layer, "opacity", 1.0) or 1.0)
        rotation = 0.0
        try:
            transform = getattr(layer, "transform", None)
            if transform is not None and hasattr(transform, "rotation"):
                rotation = float(getattr(transform, "rotation", 0.0) or 0.0)
        except Exception:
            rotation = 0.0
        if hasattr(self, "logo_inspector_opacity_slider"):
            self.logo_inspector_opacity_slider.blockSignals(True)
            self.logo_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.logo_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "logo_inspector_opacity_value_label"):
            self.logo_inspector_opacity_value_label.setText(f"{int(round(opacity * 100))}%")
        if hasattr(self, "logo_inspector_rotation_slider"):
            self.logo_inspector_rotation_slider.blockSignals(True)
            self.logo_inspector_rotation_slider.setValue(int(round(rotation)))
            self.logo_inspector_rotation_slider.blockSignals(False)
        if hasattr(self, "logo_inspector_rotation_value_label"):
            self.logo_inspector_rotation_value_label.setText(f"{int(round(rotation))}°")
        if hasattr(self, "logo_inspector_summary_label"):
            tname = getattr(track, "name", "L1 Logo")
            lname = getattr(layer, "name", "Logo")
            self.logo_inspector_summary_label.setText(
                f"Selected: {tname} → {lname}. "
                "Adjust opacity and rotation below; drag the logo on the "
                "preview to reposition."
            )

    def _wire_logo_inspector_controls(self):
        """One-time wiring of the Logo Inspector's opacity/rotation controls."""
        if getattr(self, "_logo_inspector_wired", False):
            return
        self._logo_inspector_wired = True

        def _on_opacity_changed(value, l=None):
            if l is None:
                l = getattr(self, "_logo_overlay_layer", None)
            if l is None:
                return
            opacity = max(0.0, min(1.0, float(value) / 100.0))
            try:
                l.opacity = opacity
            except Exception:
                pass
            if hasattr(self, "logo_inspector_opacity_value_label"):
                self.logo_inspector_opacity_value_label.setText(f"{int(value)}%")
            if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_opacity"):
                self.video_view.set_logo_opacity(opacity)

        def _on_rotation_changed(value, l=None):
            if l is None:
                l = getattr(self, "_logo_overlay_layer", None)
            if l is None:
                return
            rotation = float(value)
            try:
                from app.layers.transform import Transform
                transform = getattr(l, "transform", None) or Transform()
                transform.rotation = rotation
                l.transform = transform
            except Exception:
                pass
            if hasattr(self, "logo_inspector_rotation_value_label"):
                self.logo_inspector_rotation_value_label.setText(f"{int(value)}°")
            if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_rotation"):
                self.video_view.set_logo_rotation(rotation)

        # Store handlers so we can disconnect on re-wire.
        self._logo_opacity_handler = _on_opacity_changed
        self._logo_rotation_handler = _on_rotation_changed

        if hasattr(self, "logo_inspector_opacity_slider"):
            self.logo_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)
        if hasattr(self, "logo_inspector_rotation_slider"):
            self.logo_inspector_rotation_slider.valueChanged.connect(_on_rotation_changed)

    def _show_video_inspector_for_track(self, track, layer=None):
        """Show the Video Track Inspector (V1 Video)."""
        self._switch_inspector("video")
        if track is None:
            return
        if hasattr(self, "video_inspector_summary_label"):
            self.video_inspector_summary_label.setText(
                "Adjust the preset, intensity and fine-tune each channel below."
            )
        # Populate the inline filter controls
        self._wire_video_inspector_controls()
        self._refresh_video_inspector_status()

    def _wire_video_inspector_controls(self):
        """One-time wiring of the inline video filter controls."""
        if getattr(self, "_video_inspector_wired", False):
            return
        # Preset combo
        if hasattr(self, "video_inspector_preset_combo"):
            preset_keys = (
                list(self._video_filter_presets().keys())
                if hasattr(self, "_video_filter_presets")
                else ["original", "bright", "warm", "vivid", "cool", "soft"]
            )
            preset_labels = {
                "original": "Original",
                "bright": "Bright",
                "warm": "Warm",
                "vivid": "Vivid",
                "cool": "Cool",
                "soft": "Soft",
            }
            for key in preset_keys:
                label = preset_labels.get(str(key), str(key).title())
                self.video_inspector_preset_combo.addItem(label, str(key))
            self.video_inspector_preset_combo.currentIndexChanged.connect(
                self._on_video_inspector_preset_changed
            )
        # Intensity
        if hasattr(self, "video_inspector_intensity_slider"):
            self.video_inspector_intensity_slider.valueChanged.connect(
                self._on_video_inspector_intensity_changed
            )
            self.video_inspector_intensity_slider.sliderReleased.connect(
                self._on_video_inspector_intensity_released
            )
        # Adjust sliders
        if hasattr(self, "video_inspector_adjust_sliders"):
            for field_key, (slider, value_lbl) in self.video_inspector_adjust_sliders.items():
                slider.valueChanged.connect(
                    lambda v, lbl=value_lbl, fk=field_key: self._on_video_inspector_adjust_changed(fk, v, lbl)
                )
                slider.sliderReleased.connect(
                    lambda fk=field_key: self._on_video_inspector_adjust_released(fk)
                )
        # Apply / Revert
        if hasattr(self, "video_inspector_apply_btn"):
            self.video_inspector_apply_btn.clicked.connect(self._on_video_inspector_apply)
        if hasattr(self, "video_inspector_revert_btn"):
            self.video_inspector_revert_btn.clicked.connect(self._on_video_inspector_revert)
        self._video_inspector_wired = True
        # Initial UI sync
        self._sync_video_inspector_ui()

    def _sync_video_inspector_ui(self):
        if hasattr(self, "video_inspector_preset_combo"):
            try:
                key = self._normalize_video_filter_preset_key(
                    getattr(self, "_video_filter_preset_key", "original")
                )
                for i in range(self.video_inspector_preset_combo.count()):
                    if self.video_inspector_preset_combo.itemData(i) == key:
                        self.video_inspector_preset_combo.blockSignals(True)
                        self.video_inspector_preset_combo.setCurrentIndex(i)
                        self.video_inspector_preset_combo.blockSignals(False)
                        break
            except Exception:
                pass
        if hasattr(self, "video_inspector_intensity_slider"):
            try:
                self.video_inspector_intensity_slider.blockSignals(True)
                self.video_inspector_intensity_slider.setValue(int(self._video_filter_intensity))
                self.video_inspector_intensity_slider.blockSignals(False)
            except Exception:
                pass
        if hasattr(self, "video_inspector_intensity_value_label"):
            try:
                self.video_inspector_intensity_value_label.setText(str(int(self._video_filter_intensity)))
            except Exception:
                pass
        if hasattr(self, "video_inspector_adjust_sliders"):
            overrides = getattr(self, "_video_filter_adjust_overrides", {}) or {}
            for field_key, (slider, value_lbl) in self.video_inspector_adjust_sliders.items():
                try:
                    val = int(overrides.get(field_key, 0))
                except Exception:
                    val = 0
                try:
                    slider.blockSignals(True)
                    slider.setValue(val)
                    slider.blockSignals(False)
                except Exception:
                    pass
                value_lbl.setText(str(val))

    def _refresh_video_inspector_status(self):
        try:
            if not hasattr(self, "video_inspector_status_label"):
                return
            try:
                active = bool(self.has_active_video_filters())
            except Exception:
                active = False
            
            is_applying = getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False)
            
            if is_applying:
                self.video_inspector_status_label.setText("⟳ Applying filter...")
                self.video_inspector_status_label.setStyleSheet("color: #2196F3; font-weight: bold;")
            elif active:
                self.video_inspector_status_label.setText("✓ Filter applied")
                self.video_inspector_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.video_inspector_status_label.setText("No filter applied")
                self.video_inspector_status_label.setStyleSheet("color: #888; font-weight: normal;")
            
            if hasattr(self, "video_inspector_apply_btn"):
                if is_applying:
                    self.video_inspector_apply_btn.setText("Applying...")
                    self.video_inspector_apply_btn.setEnabled(False)
                elif active:
                    # Filter is active - enable button so user can re-apply if needed
                    self.video_inspector_apply_btn.setText("Apply")
                    self.video_inspector_apply_btn.setEnabled(True)
                else:
                    # No filter - enable button so user can apply
                    self.video_inspector_apply_btn.setText("Apply")
                    self.video_inspector_apply_btn.setEnabled(True)
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"[Filter] Status refresh error: {e}")

    def _on_video_inspector_preset_changed(self, index: int):
        if not hasattr(self, "video_inspector_preset_combo"):
            return
        try:
            key = self.video_inspector_preset_combo.itemData(index)
            if not key:
                return
            self.on_video_filter_preset_selected(str(key))
        except Exception:
            pass
        # When the preset changes, the base values for each adjust
        # field change too. Refresh the slider UI so the user can see
        # what the new preset looks like at the current intensity.
        self._sync_video_inspector_ui()
        self._refresh_video_inspector_status()
        if hasattr(self, "refresh_ui_state"):
            self.refresh_ui_state()

    def _on_video_inspector_intensity_changed(self, value: int):
        if hasattr(self, "video_inspector_intensity_value_label"):
            self.video_inspector_intensity_value_label.setText(str(int(value)))
        try:
            self.on_video_filter_intensity_changed(int(value))
        except Exception:
            pass
        self._refresh_video_inspector_status()

    def _on_video_inspector_intensity_released(self):
        if hasattr(self, "on_video_filter_slider_released"):
            try:
                self.on_video_filter_slider_released()
            except Exception:
                pass
        self._refresh_video_inspector_status()

    def _on_video_inspector_adjust_changed(self, field_key: str, value: int, value_lbl):
        value_lbl.setText(str(int(value)))
        if not isinstance(getattr(self, "_video_filter_adjust_overrides", None), dict):
            self._video_filter_adjust_overrides = {}
        self._video_filter_adjust_overrides[field_key] = int(value)
        if not isinstance(getattr(self, "_video_filter_user_modified", None), dict):
            self._video_filter_user_modified = {}
        self._video_filter_user_modified[field_key] = True
        self._refresh_video_inspector_status()

    def _on_video_inspector_adjust_released(self, field_key: str):
        if hasattr(self, "on_video_filter_slider_released"):
            try:
                self.on_video_filter_slider_released()
            except Exception:
                pass
        self._refresh_video_inspector_status()

    def _on_video_inspector_apply(self):
        self.log("[Filter] Apply button clicked")
        
        # Disable button immediately to prevent double-clicks
        if hasattr(self, "video_inspector_apply_btn"):
            self.video_inspector_apply_btn.setEnabled(False)
            self.video_inspector_apply_btn.setText("Applying...")
        
        try:
            self._video_filter_apply_requested = True
            if hasattr(self, "refresh_ui_state"):
                self.refresh_ui_state()
        except Exception as e:
            self.log(f"[Filter] UI update error: {e}")
        
        if hasattr(self, "apply_current_video_filter"):
            try:
                self.log(f"[Filter] Calling apply_current_video_filter, has_active={self.has_active_video_filters()}")
                self.apply_current_video_filter()
            except Exception as e:
                self.log(f"[Filter] Apply error: {e}")
                if hasattr(self, "show_error"):
                    self.show_error("Filter Error", "Failed to apply filter.", str(e))
                # Re-enable button on error
                if hasattr(self, "video_inspector_apply_btn"):
                    self.video_inspector_apply_btn.setEnabled(True)
                    self.video_inspector_apply_btn.setText("Apply")

    def _on_video_inspector_revert(self):
        if hasattr(self, "revert_video_filter_preview_to_source"):
            try:
                self.revert_video_filter_preview_to_source()
            except Exception:
                pass
        self._refresh_video_inspector_status()
        if hasattr(self, "refresh_ui_state"):
            self.refresh_ui_state()

    def _current_blur_track_for_inspector(self):
        """Return the Blur Track currently displayed in the Blur inspector."""
        if not hasattr(self, "blur_inspector_track_name_label"):
            return None, None
        target = self.blur_inspector_track_name_label.text().strip()
        if not target or target == "-":
            return None, None
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return None, None
        for t in self.timeline._timeline.tracks:
            if t.name == target:
                return t, target
        return None, None

    def on_blur_inspector_show_toggled(self, checked: bool):
        """Toggle whether the blur is rendered on the video preview.

        The blur layers remain in the timeline; only the visual mpv vf
        filter is toggled on/off via the media player's blur region.
        """
        track, _track_name = self._current_blur_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_show_on_preview"] = bool(checked)
        if hasattr(self, "media_player") and self.media_player is not None:
            if checked:
                # Re-apply the blur region to the media player.
                if hasattr(self, "apply_preview_blur_region"):
                    try:
                        self.apply_preview_blur_region(force=True)
                    except Exception:
                        pass
            else:
                # Clear the blur vf filter but keep the layer data.
                try:
                    self.media_player.clear_blur_region()
                except Exception:
                    pass
        if hasattr(self, "blur_inspector_summary_label"):
            state = "shown" if checked else "hidden"
            self.blur_inspector_summary_label.setText(
                f"The visual blur is currently {state} on the video preview."
            )

    def _switch_inspector(self, kind: str):
        if not hasattr(self, "inspector_stack"):
            return
        idx_map = {
            "subtitle": 0,
            "audio": 1,
            "blur": 2,
            "video": 3,
            "default": 4,
            "logo": 5,
            "mask": 6,
            "text": 7,
        }
        target = idx_map.get(kind, 4)
        if self.inspector_stack.currentIndex() != target:
            self.inspector_stack.setCurrentIndex(target)
        # The handle/toggle button is always visible so the user can
        # The handle/toggle UI was removed - the track inspector is
        # always expanded. No need to show/hide a handle.
        # Clicking a track layer opens the inspector (auto-expand shell).
        if kind in ("subtitle", "audio", "blur", "video", "logo", "mask", "text"):
            self.set_inspector_collapsed(False)

    def _current_audio_track_for_inspector(self):
        """Return the Track object currently displayed in the audio inspector."""
        if not hasattr(self, "audio_inspector_card") or not hasattr(self, "timeline"):
            return None, None
        if not self.timeline._timeline:
            return None, None
        if not hasattr(self, "audio_inspector_track_name_label"):
            return None, None
        target = self.audio_inspector_track_name_label.text().strip()
        if not target or target == "-":
            return None, None
        for t in self.timeline._timeline.tracks:
            if t.name == target:
                return t, target
        return None, None

    def on_audio_inspector_gain_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_gain_db"] = float(value)
        self._apply_audio_track_settings(track_name)

    def on_audio_inspector_speed_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_speed"] = float(value)
        self._apply_audio_track_settings(track_name)

    def on_audio_inspector_fade_in_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_fade_in"] = float(value)
        self._apply_audio_track_settings(track_name)

    def on_audio_inspector_fade_out_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_fade_out"] = float(value)
        self._apply_audio_track_settings(track_name)

    def on_audio_inspector_mute_toggled(self, checked: bool):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_muted"] = bool(checked)
        if hasattr(self, "audio_inspector_mute_btn"):
            self.audio_inspector_mute_btn.setText(
                "Unmute Track" if checked else "Mute Track"
            )
        self._apply_audio_track_settings(track_name)

    def on_audio_inspector_solo_toggled(self, checked: bool):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_solo"] = bool(checked)
        self._apply_audio_track_settings(track_name)

    def _refresh_audio_inspector_dub_voice_buttons(self):
        """Enable/disable Dub Voice buttons and populate shared/tabs."""
        idx = int(getattr(self, "_selected_segment_index", -1))
        segments = self.get_active_segments() or []
        valid = 0 <= idx < len(segments)
        seg = segments[idx] if valid and isinstance(segments[idx], dict) else {}
        for attr in (
            "audio_inspector_use_voice_btn",
            "audio_inspector_regenerate_voice_btn",
        ):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(valid)
        # Shared section: Original text
        orig_lbl = getattr(self, "inspector_original_text_label", None)
        orig_widget = getattr(self, "inspector_shared_original_label", None)
        if orig_lbl is not None:
            orig_text = str(seg.get("original_text", "") or "") if valid else ""
            orig_lbl.setText(orig_text if orig_text else "")
            if orig_widget is not None:
                orig_widget.setVisible(bool(orig_text))

    def on_audio_inspector_regenerate_voice_clicked(self):
        idx = int(getattr(self, "_selected_segment_index", -1))
        segments = self.get_active_segments() or []
        if not (0 <= idx < len(segments)):
            return
        self.preview_segment_audio(idx)

    AUDIO_MIX_PRESETS = {
        "original_only": (100, 0),
        "prefer_original": (80, 20),
        "balanced": (100, 100),
        "prefer_dub": (20, 80),
        "dub_only": (0, 100),
    }

    def on_audio_mix_preset_changed(self):
        if not hasattr(self, "audio_mix_preset_combo"):
            return
        preset_key = str(self.audio_mix_preset_combo.currentData() or "").strip().lower()
        if preset_key in self.AUDIO_MIX_PRESETS:
            a1_val, a2_val = self.AUDIO_MIX_PRESETS[preset_key]
            if hasattr(self, "audio_a1_volume_slider"):
                self.audio_a1_volume_slider.blockSignals(True)
                self.audio_a1_volume_slider.setValue(a1_val)
                self.audio_a1_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a1_volume_label"):
                self.audio_a1_volume_label.setText(f"{int(a1_val)}%")
            if hasattr(self, "audio_a2_volume_slider"):
                self.audio_a2_volume_slider.blockSignals(True)
                self.audio_a2_volume_slider.setValue(a2_val)
                self.audio_a2_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a2_volume_label"):
                self.audio_a2_volume_label.setText(f"{int(a2_val)}%")
            self._apply_audio_mix_to_tracks(a1_val, a2_val)

    def on_audio_a1_volume_changed(self, value: int):
        if hasattr(self, "audio_a1_volume_label"):
            self.audio_a1_volume_label.setText(f"{int(value)}%")
        self._sync_audio_track_volume("A1 Audio", int(value))
        self._set_audio_mix_preset_custom()

    def on_audio_a2_volume_changed(self, value: int):
        if hasattr(self, "audio_a2_volume_label"):
            self.audio_a2_volume_label.setText(f"{int(value)}%")
        self._sync_audio_track_volume("TS1", int(value))
        self._set_audio_mix_preset_custom()

    def _apply_audio_mix_to_tracks(self, a1_val: int, a2_val: int):
        self._sync_audio_track_volume("A1 Audio", a1_val)
        self._sync_audio_track_volume("TS1", a2_val)

    def _sync_audio_track_volume(self, track_name: str, volume: int):
        if not hasattr(self, "timeline") or self.timeline is None:
            return
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                if not isinstance(t.metadata, dict):
                    t.metadata = {}
                t.metadata["_volume"] = float(volume)
                self._apply_audio_track_settings(track_name)
                break

    def _set_audio_mix_preset_custom(self):
        if not hasattr(self, "audio_mix_preset_combo"):
            return
        idx = self.audio_mix_preset_combo.findData("custom")
        if idx >= 0 and self.audio_mix_preset_combo.currentIndex() != idx:
            self.audio_mix_preset_combo.setCurrentIndex(idx)

    def _apply_audio_track_settings(self, track_name: str):
        """Apply per-track volume/gain/mute to the underlying media player.

        Maps the timeline track name to the media player:
          "A1 Audio" -> QMediaPlayer #1 (original sidecar)
          "A2 Dub" / "TS1" -> QMediaPlayer #2 (dubbed sidecar)
        """
        if not hasattr(self, "media_player") or self.media_player is None:
            return
        try:
            if track_name == "A1 Audio":
                vol = self._compute_audio_track_volume(track_name, base=100.0)
                gain_db = self._get_audio_track_gain_db(track_name)
                effective = vol * (10 ** (gain_db / 20.0))
                effective = max(0.0, min(200.0, effective))
                if hasattr(self.media_player, "set_original_volume"):
                    self.media_player.set_original_volume(effective)
                muted = self._is_audio_track_muted(track_name)
                if hasattr(self.media_player, "set_mute_original"):
                    self.media_player.set_mute_original(muted)
            elif track_name in ("A2 Dub", "TS1"):
                vol = self._compute_audio_track_volume(track_name, base=100.0)
                gain_db = self._get_audio_track_gain_db(track_name)
                effective = vol * (10 ** (gain_db / 20.0))
                effective = max(0.0, min(200.0, effective))
                if hasattr(self.media_player, "set_dubbed_volume"):
                    self.media_player.set_dubbed_volume(effective)
                muted = self._is_audio_track_muted(track_name)
                if hasattr(self.media_player, "set_mute_dubbed"):
                    self.media_player.set_mute_dubbed(muted)
        except Exception:
            pass

    def _get_audio_track_meta(self, track_name: str) -> dict:
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return {}
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                if not isinstance(t.metadata, dict):
                    t.metadata = {}
                return t.metadata
        return {}

    def _get_audio_track_volume(self, track_name: str) -> float:
        meta = self._get_audio_track_meta(track_name)
        default_vol = 50.0 if track_name.startswith("A1") else 100.0
        try:
            return float(meta.get("_volume", default_vol))
        except (TypeError, ValueError):
            return default_vol

    def _get_audio_track_gain_db(self, track_name: str) -> float:
        meta = self._get_audio_track_meta(track_name)
        try:
            return float(meta.get("_gain_db", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _is_audio_track_muted(self, track_name: str) -> bool:
        meta = self._get_audio_track_meta(track_name)
        if bool(meta.get("_muted", False)):
            return True
        # A soloed track is never muted by another track's solo. If
        # multiple tracks are soloed, all of them play; the rest are muted.
        if bool(meta.get("_solo", False)):
            return False
        # If any OTHER audio track is soloed, this one is muted.
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return False
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                continue
            if str(getattr(t, "name", "")).startswith(("A1", "A2")):
                if isinstance(t.metadata, dict) and bool(t.metadata.get("_solo", False)):
                    return True
        return False

    def _compute_audio_track_volume(self, track_name: str, base: float = 100.0) -> float:
        meta = self._get_audio_track_meta(track_name)
        default_base = 50.0 if track_name.startswith("A1") else base
        try:
            v = float(meta.get("_volume", default_base))
        except (TypeError, ValueError):
            v = default_base
        return max(0.0, min(200.0, v))

    def on_track_mute_toggled(self, track_name: str, is_muted: bool):
        """Handle timeline audio track mute toggling.
        Maps timeline mute to per-track mute on the dual-track player.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                t.muted = is_muted

        muted = bool(is_muted)
        if track_name == "A1 Audio":
            self._mute_original = muted
            if hasattr(self, "media_player"):
                try:
                    self.media_player.set_mute_original(muted)
                except Exception:
                    pass
        elif track_name in ("A2 Dub", "TS1"):
            self._mute_dubbed = muted
            if hasattr(self, "media_player"):
                try:
                    self.media_player.set_mute_dubbed(muted)
                except Exception:
                    pass

        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_muted(track_name, muted)

        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)

    def on_track_blur_toggled(self, track_name: str, is_on: bool):
        """Handle B1 track label click - toggle blur effect."""
        if not hasattr(self, "blur_area_btn"):
            return
        self.blur_area_btn.blockSignals(True)
        self.blur_area_btn.setChecked(bool(is_on))
        self.blur_area_btn.blockSignals(False)
        try:
            self.toggle_blur_effect_enabled(bool(is_on))
        except Exception:
            pass

    def on_track_logo_toggled(self, track_name: str, is_shown: bool):
        """Handle L1 track label click - hide or show the logo overlay."""
        if not hasattr(self, "video_view"):
            return
        if is_shown:
            # Re-show the selected L1 layer when possible.  This matters
            # now that L1 can contain more than one independent logo.
            if hasattr(self, "timeline") and self.timeline._timeline:
                selected_id = getattr(self.timeline, "_selected_layer_id", "")
                for track in self.timeline._timeline.tracks:
                    if track.name == "L1 Logo" and track.layers:
                        try:
                            layer = next(
                                (item for item in track.layers
                                 if item.id == selected_id),
                                track.layers[0],
                            )
                            self._show_logo_overlay(track, layer)
                        except Exception:
                            pass
                        return
            # No layer found - nothing to show
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
        else:
            # Hide the logo overlay
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()

    def on_track_mask_toggled(self, track_name: str, is_shown: bool):
        """Handle M1 track label click - show or hide the mask filter."""
        if not hasattr(self, "media_player"):
            return
        if is_shown:
            # Re-apply the M1 mask filter from the timeline.
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            # Re-show the mask overlay. A label click should restore M1 even
            # when another layer is selected (or the selection was cleared).
            try:
                if hasattr(self, "timeline") and self.timeline._timeline:
                    sid = getattr(self.timeline, "_selected_layer_id", "")
                    for tr in self.timeline._timeline.tracks:
                        if tr.name != "M1" or not tr.layers:
                            continue
                        layer = next((item for item in tr.layers if item.id == sid), tr.layers[0])
                        self._show_mask_overlay(tr, layer)
                        return
            except Exception:
                pass
        else:
            try:
                self.media_player.clear_mask_region()
            except Exception:
                pass
            if hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
                try:
                    self.video_view.clear_mask_region()
                except Exception:
                    pass

    def _sync_timeline_mute_to_gui(self):
        """Pull the current timeline track mute state into the GUI and backend."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        a1_muted = False
        a2_muted = False
        for t in self.timeline._timeline.tracks:
            if t.name == "A1 Audio":
                a1_muted = bool(t.muted)
            elif t.name in ("A2 Dub", "TS1"):
                a2_muted = bool(t.muted)
        self._mute_original = a1_muted
        self._mute_dubbed = a2_muted
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_mute_original(a1_muted)
            except Exception:
                pass
            try:
                self.media_player.set_mute_dubbed(a2_muted)
            except Exception:
                pass
        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_muted("A1 Audio", a1_muted)
            self.track_label_bar.set_muted("TS1", a2_muted)

    def _is_active_timeline_audio_track_muted(self) -> bool:
        track_mutes = self._timeline_audio_track_mutes()
        if not track_mutes:
            return False
        a1_muted, a2_muted = track_mutes
        mode = str(getattr(self, "_preview_audio_track_mode", "original") or "original").strip().lower()
        if mode != "dubbed":
            return a1_muted
        dubbed_audio_kind, _dubbed_path = self._resolve_preview_dubbed_playback_source()
        if dubbed_audio_kind == "voice":
            return a2_muted
        if dubbed_audio_kind == "mixed":
            return a1_muted and a2_muted
        return a1_muted

    def on_add_timeline_layer(self, layer_type: str = "subtitle"):
        if not hasattr(self, "timeline"):
            return

        if layer_type in {"blur", "logo", "mask", "text", "image", "sticker"} and not bool(
            getattr(self, "_optional_layer_controls_ready", False)
        ):
            QMessageBox.information(
                self,
                "Generate Video First",
                "Complete video generation before adding Blur, Logo, Mask, Text, or other overlay layers.",
            )
            return

        tl = self.timeline._timeline
        if not tl:
            return

        from app.layers.base import LayerType
        from app.layers.sync_bridge import find_or_create_track

        if layer_type == "subtitle":
            from app.layers.subtitle import SubtitleLayer
            sub_track = None
            for track in tl.tracks:
                if track.type.value == "subtitle":
                    sub_track = track
                    break
            if sub_track is None:
                return
            idx = len(sub_track.layers)
            last_end = max((l.end for l in sub_track.layers), default=0.0)
            layer = SubtitleLayer(
                name=f"New Subtitle {idx + 1}",
                text="New text",
                start=last_end,
                end=last_end + 2.0,
            )
            layer.z_index = idx
            sub_track.layers.append(layer)
            self.timeline._segment_indices[layer.id] = idx
            self.timeline._duration = max(self.timeline._duration, layer.end)
            self.timeline._redraw()
            seg = {"id": idx, "start": layer.start, "end": layer.end, "text": layer.text}
            if not hasattr(self, "current_segments"):
                self.current_segments = []
            self.current_segments.append(seg)
            if not hasattr(self, "current_translated_segment_models"):
                self.current_translated_segment_models = []
            self.current_translated_segment_models.append(seg)

        elif layer_type == "text":
            from app.layers.text import TextLayer
            text_track = find_or_create_track(tl, "T1 Text", LayerType.TEXT, 80)
            idx = len(text_track.layers)
            layer = TextLayer(
                name=f"Text {idx + 1}",
                text="New text layer",
                start=0.0,
                end=tl.duration if tl.duration > 0 else 10.0,
            )
            layer.font_size = 60
            # Match the subtitle defaults so identical Text/Subtitles size
            # values use the same family and weight out of the box.
            layer.font_name = "Segoe UI"
            layer.font_bold = True
            layer.transform.x = 0.5
            layer.transform.y = 0.5
            layer.z_index = idx
            text_track.layers.append(layer)
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[text_track.id] = text_track.height or 80
            self.timeline._redraw()
            self.timeline._selected_layer_id = layer.id
            self._show_text_inspector_for_track(text_track, layer)
            self._refresh_text_layer_preview(layer.id)

        elif layer_type == "image":
            from app.layers.image import ImageLayer
            img_track = find_or_create_track(tl, "I1 Image", LayerType.IMAGE, 80)
            idx = len(img_track.layers)
            layer = ImageLayer(
                name=f"Image {idx + 1}",
                source="",
                start=0.0,
                end=min(tl.duration, 10.0) if tl.duration > 0 else 10.0,
            )
            layer.z_index = idx
            img_track.layers.append(layer)
            self.timeline._redraw()

        elif layer_type == "logo":
            from app.layers.image import ImageLayer
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Logo / Watermark Image", "",
                "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All Files (*)"
            )
            if not path:
                return
            img_track = find_or_create_track(tl, "L1 Logo", LayerType.IMAGE, 80)
            # L1 supports multiple independent logo layers.  Keep existing
            # layers intact; selecting a timeline layer determines which
            # logo is currently editable in the preview overlay.
            idx = len(img_track.layers)
            dur = tl.duration if tl.duration > 0 else 10.0
            layer = ImageLayer(
                name=f"Logo {idx + 1}",
                source=path,
                start=0.0,
                end=dur,
            )
            layer.z_index = idx
            # Mark as watermark so the preview positions it correctly
            layer.metadata["_is_watermark"] = True
            img_track.layers.append(layer)
            # Register the new track's height in the timeline so it gets
            # a real draw slot.
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[img_track.id] = (
                    img_track.height or 80
                )
            self.timeline._redraw()
            # Show the logo overlay immediately (no need to click the
            # layer first) and persist the logo state.
            try:
                self._show_logo_overlay(img_track, layer)
            except Exception:
                pass

        elif layer_type == "blur":
            from app.layers.blur import BlurLayer
            blur_track = find_or_create_track(tl, "B1", LayerType.BLUR, 60)
            # Register the new track's height in the timeline so it gets a
            # real draw slot (otherwise the track silently uses the default
            # height and may not be visible).
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[blur_track.id] = (
                    blur_track.height or 60
                )
            idx = len(blur_track.layers)
            # Stagger each new blur layer slightly so all layers are
            # visible in the timeline (otherwise overlapping layers at
            # the same position hide each other).
            stagger = idx % 4
            base_y = 0.75 - stagger * 0.06
            base_x = 0.30 + (stagger % 2) * 0.08
            layer = BlurLayer(
                name=f"Blur {idx + 1}",
                position_x=float(base_x),
                position_y=float(base_y),
                width=0.4,
                height=0.1,
                blur_strength=20.0,
                start=0.0,
                end=min(tl.duration, 5.0) if tl.duration > 0 else 5.0,
            )
            layer.z_index = idx
            blur_track.layers.append(layer)
            # Force a redraw so the new track + layer are visible.
            self.timeline._redraw()
            # Auto-scroll the timeline vertically so the new B1
            # track is in view (it sits below V1 + A1 by default).
            try:
                if hasattr(self.timeline, "verticalScrollBar"):
                    y_offset = 0
                    if hasattr(self.timeline, "RULER_HEIGHT"):
                        y_offset = int(self.timeline.RULER_HEIGHT)
                    for tr in tl.tracks:
                        if tr.id == blur_track.id:
                            break
                        y_offset += int(
                            self.timeline._track_heights.get(
                                tr.id, self.timeline.TRACK_DEFAULT_H
                            )
                        )
                    bar = self.timeline.verticalScrollBar()
                    # Make sure the scroll bar range reflects the new scene
                    # size (it is normally auto-sized by the QGraphicsView,
                    # but the range can lag on first update).
                    viewport_h = int(self.timeline.viewport().height())
                    scene_h = int(self.timeline._scene.height())
                    bar.setRange(0, max(0, scene_h - viewport_h))
                    # Center the B1 track in the viewport
                    target = max(0, y_offset - max(0, (viewport_h - 80) // 2))
                    bar.setValue(target)
                    # Make sure the new layer is fully visible too.
                    self.timeline.ensureVisible(
                        0,
                        y_offset,
                        1,
                        int(self.timeline._track_heights.get(
                            blur_track.id, 60
                        )),
                    )
            except Exception:
                pass
            # Auto-enable the blur effect so the visual blur shows on the
            # video preview the moment the layer is added.
            if hasattr(self, "blur_area_btn"):
                self.blur_area_btn.blockSignals(True)
                self.blur_area_btn.setChecked(True)
                self.blur_area_btn.blockSignals(False)
            # Push the new region's normalized data into the video view
            # and force the mpv vf filter to be applied immediately.
            try:
                regions = []
                for ll in blur_track.layers:
                    if not getattr(ll, "visible", True):
                        continue
                    regions.append({
                        "x": float(getattr(ll, "position_x", 0.3)),
                        "y": float(getattr(ll, "position_y", 0.8)),
                        "width": float(getattr(ll, "width", 0.4)),
                        "height": float(getattr(ll, "height", 0.1)),
                        "blur_strength": float(getattr(ll, "blur_strength", 20.0)),
                    })
                if hasattr(self.video_view, "set_blur_regions_normalized"):
                    self.video_view.set_blur_regions_normalized(regions)
                if hasattr(self, "apply_preview_blur_region"):
                    self.apply_preview_blur_region(force=True)
            except Exception:
                pass
            # Persist the new region(s) to the project state so they
            # survive a close/reopen. Without this, the blur_state is
            # only saved on the legacy blur add/edit handlers, and a
            # region added via the new "Blur" button would be lost.
            try:
                if hasattr(self, "persist_project_blur_state"):
                    self.persist_project_blur_state()
            except Exception:
                pass

        elif layer_type == "mask":
            from app.layers.mask import MaskLayer
            mask_track = find_or_create_track(tl, "M1", LayerType.MASK, 60)
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[mask_track.id] = (
                    mask_track.height or 60
                )
            idx = len(mask_track.layers)
            # Offset new regions slightly so their draggable overlays do
            # not start perfectly on top of an existing mask.
            stagger = idx % 4
            layer = MaskLayer(
                name=f"Mask {idx + 1}",
                position_x=0.3 + (stagger % 2) * 0.08,
                position_y=0.4 + (stagger // 2) * 0.08,
                width=0.4,
                height=0.2,
                color="#000000",
                mode="solid",
                pixelate_size=12,
                blur_strength=20,
                start=0.0,
                # Span the full timeline so the mask track is visible
                # across the whole video (like the audio track layers),
                # not a short 5-second segment.
                end=tl.duration if tl.duration > 0 else 5.0,
            )
            layer.z_index = idx
            # Visibility is gated by the play state in
            # _apply_mask_to_preview: the mask filter is only pushed
            # to mpv while the video is playing, so a freshly added
            # mask does not draw on the paused preview.
            mask_track.layers.append(layer)
            self.timeline._redraw()
            # Push the new mask into the mpv filter chain and persist
            # it so the export matches the preview.
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            try:
                if hasattr(self, "persist_project_mask_state"):
                    self.persist_project_mask_state()
            except Exception:
                pass
            # Select the new mask layer so the inspector opens with
            # the right settings loaded.
            try:
                self.timeline._selected_layer_id = layer.id
                self.timeline._redraw()
                self._show_mask_inspector_for_track(mask_track, layer)
                # Show the draggable mask overlay (move + resize handles)
                # immediately so the user can position the mask without
                # having to click the timeline first.
                self._show_mask_overlay(mask_track, layer)
            except Exception:
                pass
        
        # Save timeline data (includes mask and logo layers)
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass

    def _sync_hidden_transcript_text_from_segments(self):
        if getattr(self, "_syncing_segment_editor", False):
            return
        self._syncing_hidden_editor_text = True
        try:
            self.transcript_text.setText(self.format_to_srt(self.current_segments))
        finally:
            self._syncing_hidden_editor_text = False

    def _apply_segment_timing(self, segment: dict, start: float, end: float):
        segment["start"] = float(start)
        segment["end"] = float(end)
        if "tts_group_start" in segment or "tts_group_end" in segment:
            segment["tts_group_start"] = float(start)
            segment["tts_group_end"] = float(end)

    def _build_split_segment_pair(self, segment: dict, split_time: float):
        first = dict(segment or {})
        second = dict(segment or {})

        first["start"] = float(segment.get("start", 0.0))
        first["end"] = float(split_time)
        second["start"] = float(split_time)
        second["end"] = float(segment.get("end", split_time))

        # Keep clip content unchanged on split; only timing is divided.
        first["text"] = str(segment.get("text", "") or "")
        second["text"] = str(segment.get("text", "") or "")
        first["tts_text"] = str(segment.get("tts_text", segment.get("text", "")) or "")
        second["tts_text"] = str(segment.get("tts_text", segment.get("text", "")) or "")
        first["words"] = []
        second["words"] = []
        first["manual_highlights"] = list(segment.get("manual_highlights", []))
        second["manual_highlights"] = list(segment.get("manual_highlights", []))
        if "tts_group_start" in first or "tts_group_end" in first:
            first["tts_group_start"] = float(first["start"])
            first["tts_group_end"] = float(first["end"])
            second["tts_group_start"] = float(second["start"])
            second["tts_group_end"] = float(second["end"])
        return first, second

    def _timeline_neighbor_bounds(self, index: int):
        active_segments = list(self.get_active_segments() or [])
        prev_end = 0.0
        next_start = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        if index > 0 and index - 1 < len(active_segments):
            prev_end = float(active_segments[index - 1].get("end", 0.0))
        if index + 1 < len(active_segments):
            next_start = float(active_segments[index + 1].get("start", next_start))
        return prev_end, next_start

    def nudge_selected_timeline_segment(self, delta_seconds: float):
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            return

        target = segments[index]
        start = float(target.get("start", 0.0))
        end = float(target.get("end", 0.0))
        duration = max(0.0, end - start)
        gap = float(getattr(self.timeline, "SEGMENT_GAP", 0.03))
        prev_end, next_start = self._timeline_neighbor_bounds(index)
        max_timeline = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        min_start = max(0.0, prev_end + gap)
        if index + 1 < len(segments):
            max_start = max(min_start, next_start - gap - duration)
        else:
            max_start = max(0.0, max_timeline - duration)
        new_start = min(max(start + float(delta_seconds), min_start), max_start)
        if abs(new_start - start) < 0.0001:
            return
        new_end = new_start + duration
        self.on_timeline_segment_timing_edit_started(index, start, end)
        self.on_timeline_segment_timing_changed(index, new_start, new_end)

    def ripple_nudge_selected_timeline_segment(self, delta_seconds: float):
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            return

        gap = float(getattr(self.timeline, "SEGMENT_GAP", 0.0))
        max_timeline = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        prev_end, _next_start = self._timeline_neighbor_bounds(index)
        first_start = float(segments[index].get("start", 0.0))
        last_end = float(segments[-1].get("end", 0.0))
        min_delta = max(0.0, prev_end + gap) - first_start
        max_delta = max_timeline - last_end
        actual_delta = min(max(float(delta_seconds), min_delta), max_delta)
        if abs(actual_delta) < 0.0001:
            return

        history_entry = {
            "type": "batch_timing",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(index),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        if 0 <= index < len(self.current_segments or []):
            history_entry["current_before"] = [copy.deepcopy(seg) for seg in self.current_segments[index:]]
            for seg in self.current_segments[index:]:
                self._apply_segment_timing(
                    seg,
                    float(seg.get("start", 0.0)) + actual_delta,
                    float(seg.get("end", 0.0)) + actual_delta,
                )
            history_entry["current_after"] = [copy.deepcopy(seg) for seg in self.current_segments[index:]]
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        if 0 <= index < len(self.current_translated_segments or []):
            history_entry["translated_before"] = [copy.deepcopy(seg) for seg in self.current_translated_segments[index:]]
            for seg in self.current_translated_segments[index:]:
                self._apply_segment_timing(
                    seg,
                    float(seg.get("start", 0.0)) + actual_delta,
                    float(seg.get("end", 0.0)) + actual_delta,
                )
            history_entry["translated_after"] = [copy.deepcopy(seg) for seg in self.current_translated_segments[index:]]
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        self._timeline_timing_undo_stack.append(history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def _apply_timeline_structure_history_entry(self, entry: dict, *, use_after: bool):
        index = int(entry.get("index", -1))
        current_before = [copy.deepcopy(seg) for seg in list(entry.get("current_before", []) or [])]
        current_after = [copy.deepcopy(seg) for seg in list(entry.get("current_after", []) or [])]
        translated_before = [copy.deepcopy(seg) for seg in list(entry.get("translated_before", []) or [])]
        translated_after = [copy.deepcopy(seg) for seg in list(entry.get("translated_after", []) or [])]

        if self.current_segments is not None:
            replace_with = current_after if use_after else current_before
            replace_count = len(current_before if use_after else current_after)
            if current_before or current_after:
                self.current_segments[index:index + replace_count] = replace_with
                self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
                self._sync_hidden_transcript_text_from_segments()

        if self.current_translated_segments is not None:
            replace_with = translated_after if use_after else translated_before
            replace_count = len(translated_before if use_after else translated_after)
            if translated_before or translated_after:
                self.current_translated_segments[index:index + replace_count] = replace_with
                self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
                self._sync_hidden_translated_text_from_segments()

        target_index = int(entry.get("selected_after" if use_after else "selected_before", index))
        self.set_selected_segment_index(target_index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(target_index)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def split_selected_timeline_segment(self):
        # Overlay layers use the same Split action as subtitle/audio blocks.
        # Copying the layer preserves its style, transform and visibility;
        # only its identity and timing are changed.
        if self._split_selected_overlay_layer():
            return
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            QMessageBox.information(self, "Split Segment", "Please select an audio/subtitle block first.")
            return

        target = segments[index]
        split_time = float(self.media_player.position()) / 1000.0
        start = float(target.get("start", 0.0))
        end = float(target.get("end", 0.0))
        min_gap = max(0.12, getattr(self.timeline, "MIN_SEGMENT_DURATION", 0.1))
        if not (start + min_gap < split_time < end - min_gap):
            QMessageBox.information(
                self,
                "Split Segment",
                "Move the playhead inside the selected block before splitting.",
            )
            return

        split_history_entry = {
            "type": "split",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(index + 1),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        if 0 <= index < len(self.current_segments or []):
            split_history_entry["current_before"] = [copy.deepcopy(self.current_segments[index])]
            first, second = self._build_split_segment_pair(self.current_segments[index], split_time)
            self.current_segments[index:index + 1] = [first, second]
            split_history_entry["current_after"] = [copy.deepcopy(first), copy.deepcopy(second)]
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        if 0 <= index < len(self.current_translated_segments or []):
            split_history_entry["translated_before"] = [copy.deepcopy(self.current_translated_segments[index])]
            first, second = self._build_split_segment_pair(self.current_translated_segments[index], split_time)
            self.current_translated_segments[index:index + 1] = [first, second]
            split_history_entry["translated_after"] = [copy.deepcopy(first), copy.deepcopy(second)]
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        self._timeline_timing_undo_stack.append(split_history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(index + 1, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index + 1)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def _split_selected_overlay_layer(self) -> bool:
        """Split a selected Blur, Logo, Mask, or Text layer at the playhead."""
        timeline = getattr(self, "timeline", None)
        if timeline is None or not getattr(timeline, "_timeline", None):
            return False
        selected_id = str(getattr(timeline, "_selected_layer_id", "") or "")
        if not selected_id:
            return False
        selected_track = selected_layer = None
        for track in timeline._timeline.tracks:
            for layer in track.layers:
                if layer.id == selected_id:
                    selected_track, selected_layer = track, layer
                    break
            if selected_layer is not None:
                break
        if selected_layer is None:
            return False
        layer_type = str(getattr(getattr(selected_layer, "type", ""), "value", getattr(selected_layer, "type", ""))).lower()
        is_logo = layer_type == "image" and str(getattr(selected_track, "name", "")) == "L1 Logo"
        if layer_type not in {"blur", "mask", "text"} and not is_logo:
            return False
        split_time = float(self.media_player.position()) / 1000.0
        start, end = float(selected_layer.start), float(selected_layer.end)
        min_duration = max(0.1, float(getattr(timeline, "MIN_DUR", 0.1)))
        if not (start + min_duration < split_time < end - min_duration):
            QMessageBox.information(
                self,
                "Split Layer",
                "Move the playhead inside the selected layer before splitting.",
            )
            return True
        new_layer = copy.deepcopy(selected_layer)
        new_layer.id = uuid4().hex[:12]
        new_layer.name = f"{str(getattr(selected_layer, 'name', 'Layer')).strip() or 'Layer'} 2"
        new_layer.start = split_time
        new_layer.end = end
        new_layer.z_index = int(getattr(selected_layer, "z_index", 0)) + 1
        selected_layer.end = split_time
        index = selected_track.layers.index(selected_layer)
        selected_track.layers.insert(index + 1, new_layer)
        timeline._selected_layer_id = new_layer.id
        timeline._redraw()
        self.persist_current_timeline_project_data()
        self.on_timeline_layer_selected(new_layer.id)
        self.refresh_ui_state()
        return True

    def populate_timeline_layers_menu(self):
        """Build the Layers menu without touching project/preview visibility."""
        menu = getattr(self, "timeline_layers_menu", None)
        timeline = getattr(self, "timeline", None)
        if menu is None:
            return
        menu.clear()
        if timeline is None or not timeline._timeline:
            empty = menu.addAction("No layers")
            empty.setEnabled(False)
            return
        has_tracks = False
        for track in timeline._timeline.tracks:
            # Do not show empty/default tracks. The menu reflects only
            # tracks that currently contain project layers.
            if not track.layers:
                continue
            has_tracks = True
            action = menu.addAction(str(track.name or "Layer Track"))
            action.setCheckable(True)
            action.setChecked(timeline.is_track_shown_on_timeline(track))
            action.setToolTip("Only changes whether this entire track is displayed on the timeline.")
            action.toggled.connect(
                lambda shown, track_id=track.id: timeline.set_track_shown_on_timeline(track_id, shown)
            )
        if not has_tracks:
            empty = menu.addAction("No layer tracks")
            empty.setEnabled(False)

    def delete_selected_timeline_segment(self):
        # If a layer is currently selected in the timeline, remove it
        # from its track. Handles blur (with overlay sync), image/logo,
        # text, and any other layer type.
        if hasattr(self, "timeline") and self.timeline._timeline:
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            if selected_id:
                for track in self.timeline._timeline.tracks:
                    layer = None
                    layer_idx = -1
                    for li, l in enumerate(track.layers):
                        if l.id == selected_id:
                            layer = l
                            layer_idx = li
                            break
                    if layer is None:
                        continue
                    layer_type = str(
                        getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))
                    ).lower()
                    # Use the layer-specific removal paths where they own
                    # preview state.  The Delete timeline button therefore
                    # removes the selected layer rather than merely deleting
                    # a timeline bar and leaving a stale overlay behind.
                    if layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo":
                        self._delete_logo_layer(layer)
                        return
                    if layer_type == "mask" or str(getattr(track, "name", "")) == "M1":
                        self._delete_mask_layer(layer)
                        return
                    # Blur: pop the corresponding overlay region first
                    if layer_type == "blur":
                        try:
                            overlay = getattr(self.video_view, "blur_overlay", None)
                            if overlay is not None and 0 <= layer_idx < len(overlay._regions):
                                overlay._regions.pop(layer_idx)
                                overlay._active_index = min(
                                    layer_idx, len(overlay._regions) - 1
                                )
                                overlay.update()
                                if hasattr(overlay, "sync_to_view"):
                                    overlay.sync_to_view()
                        except Exception:
                            pass
                    # Remove the layer from the track
                    try:
                        if layer in track.layers:
                            track.layers.remove(layer)
                    except ValueError:
                        pass
                    # If the track is now empty, remove it (B1, L1, etc.)
                    if not track.layers:
                        try:
                            self.timeline._timeline.tracks.remove(track)
                        except ValueError:
                            pass
                        if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                            del self.timeline._track_heights[track.id]
                    # Sync blur overlay if needed
                    if layer_type == "blur":
                        try:
                            regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
                            if hasattr(self.timeline, "sync_blur_regions"):
                                self.timeline.sync_blur_regions(regions)
                            if hasattr(self, "apply_preview_blur_region"):
                                self.apply_preview_blur_region(force=True)
                            if hasattr(self, "persist_project_blur_state"):
                                self.persist_project_blur_state()
                        except Exception:
                            pass
                    # Clear selection and redraw
                    try:
                        self.timeline._selected_layer_id = ""
                    except Exception:
                        pass
                    if hasattr(self.timeline, "_redraw"):
                        self.timeline._redraw()
                    if hasattr(self.timeline, "viewport"):
                        self.timeline.viewport().update()
                    # Show default inspector
                    if hasattr(self, "_show_default_inspector"):
                        self._show_default_inspector()
                    # Keep remaining Logo / Mask layers visible. Clearing
                    # the whole overlay here used to hide every surviving
                    # layer until the user clicked one in the timeline.
                    if str(getattr(track, "name", "")) == "L1 Logo":
                        if track.layers:
                            next_layer = track.layers[min(layer_idx, len(track.layers) - 1)]
                            self.timeline._selected_layer_id = next_layer.id
                            self._show_logo_overlay(track, next_layer)
                        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
                            self.video_view.clear_logo()
                    if str(getattr(track, "name", "")) == "M1":
                        if track.layers:
                            next_layer = track.layers[min(layer_idx, len(track.layers) - 1)]
                            self.timeline._selected_layer_id = next_layer.id
                            self._show_mask_overlay(track, next_layer)
                        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
                            self.video_view.clear_mask_region()
                        try:
                            if hasattr(self, "_apply_mask_to_preview"):
                                self._apply_mask_to_preview()
                        except Exception:
                            pass
                        try:
                            if hasattr(self, "persist_project_mask_state"):
                                self.persist_project_mask_state()
                        except Exception:
                            pass
                    if layer_type == "text":
                        # The preview overlay owns a list of all text layers;
                        # refresh it after deletion so only the selected
                        # layer is removed and surviving text stays visible.
                        self._refresh_text_layer_preview("")
                    try:
                        self.persist_current_timeline_project_data()
                    except Exception:
                        pass
                    return
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            QMessageBox.information(self, "Delete Segment", "Please select an audio/subtitle block first.")
            return

        remaining_count = max(0, len(segments) - 1)
        target_selection = min(index, max(0, remaining_count - 1)) if remaining_count else -1
        delete_history_entry = {
            "type": "delete",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(target_selection),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        if 0 <= index < len(self.current_segments or []):
            delete_history_entry["current_before"] = [copy.deepcopy(self.current_segments[index])]
            self.current_segments[index:index + 1] = []
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        if 0 <= index < len(self.current_translated_segments or []):
            delete_history_entry["translated_before"] = [copy.deepcopy(self.current_translated_segments[index])]
            self.current_translated_segments[index:index + 1] = []
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        self._timeline_timing_undo_stack.append(delete_history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(target_selection, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(target_selection)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def on_timeline_segment_timing_changed(self, index: int, start: float, end: float):
        updated = False
        if 0 <= index < len(self.current_segments or []):
            self._apply_segment_timing(self.current_segments[index], start, end)
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()
            updated = True
        if 0 <= index < len(self.current_translated_segments or []):
            self._apply_segment_timing(self.current_translated_segments[index], start, end)
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()
            updated = True
        if not updated:
            return
        self.set_selected_segment_index(index, sync_ui=True)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def _refresh_timeline_history_buttons(self):
        if hasattr(self, "timeline_undo_btn"):
            self.timeline_undo_btn.setEnabled(bool(self._timeline_timing_undo_stack))
        if hasattr(self, "timeline_redo_btn"):
            self.timeline_redo_btn.setEnabled(bool(self._timeline_timing_redo_stack))

    def undo_last_timeline_timing_edit(self):
        if not self._timeline_timing_undo_stack:
            return False
        entry = self._timeline_timing_undo_stack.pop()
        if str(entry.get("type", "timing")) in {"split", "delete", "batch_timing"}:
            self._apply_timeline_structure_history_entry(entry, use_after=False)
            self._timeline_timing_redo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        current_entry = None
        active_segments = self.get_active_segments()
        index = int(entry.get("index", -1))
        if 0 <= index < len(active_segments):
            current_entry = {
                "index": index,
                "start": float(active_segments[index].get("start", 0.0)),
                "end": float(active_segments[index].get("end", 0.0)),
            }
        self._suspend_timeline_undo = True
        try:
            self.on_timeline_segment_timing_changed(
                index,
                float(entry.get("start", 0.0)),
                float(entry.get("end", 0.0)),
            )
        finally:
            self._suspend_timeline_undo = False
        if current_entry:
            self._timeline_timing_redo_stack.append(current_entry)
        self._refresh_timeline_history_buttons()
        return True

    def redo_last_timeline_timing_edit(self):
        if not self._timeline_timing_redo_stack:
            return False
        entry = self._timeline_timing_redo_stack.pop()
        if str(entry.get("type", "timing")) in {"split", "delete", "batch_timing"}:
            self._apply_timeline_structure_history_entry(entry, use_after=True)
            self._timeline_timing_undo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        current_entry = None
        active_segments = self.get_active_segments()
        index = int(entry.get("index", -1))
        if 0 <= index < len(active_segments):
            current_entry = {
                "index": index,
                "start": float(active_segments[index].get("start", 0.0)),
                "end": float(active_segments[index].get("end", 0.0)),
            }
        self._suspend_timeline_undo = True
        try:
            self.on_timeline_segment_timing_changed(
                index,
                float(entry.get("start", 0.0)),
                float(entry.get("end", 0.0)),
            )
        finally:
            self._suspend_timeline_undo = False
        if current_entry:
            self._timeline_timing_undo_stack.append(current_entry)
        self._refresh_timeline_history_buttons()
        return True

    def step_selected_segment(self, direction: int):
        rows = self._segment_editor_display_rows()
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if not valid_indexes:
            self.set_selected_segment_index(-1)
            return
        current = self._get_effective_selected_segment_index(rows)
        try:
            current_pos = valid_indexes.index(current)
        except ValueError:
            current_pos = 0
        target_pos = max(0, min(len(valid_indexes) - 1, current_pos + int(direction)))
        self.set_selected_segment_index(valid_indexes[target_pos], sync_ui=True)

    def _find_segment_editor_row(self, segment_index: int):
        for row in getattr(self, "_segment_editor_rows", []):
            if int(row.get("segment_index", -1)) == int(segment_index):
                return row
        return None

    def _is_subtitle_inspector_details_visible(self) -> bool:
        stack = getattr(self, "inspector_stack", None)
        if not stack or stack.currentIndex() != 0:
            return False
        card = getattr(self, "subtitle_inspector_card", None)
        return bool(card and card.isVisible())

    def is_subtitle_inspector_anchored(self) -> bool:
        # Backwards-compatible alias - the anchor now applies to the
        # entire track inspector (subtitle, audio, blur, default).
        return self.is_inspector_anchored()

    def is_inspector_anchored(self) -> bool:
        checkbox = getattr(self, "anchor_inspector_cb", None)
        return bool(checkbox and checkbox.isChecked())

    def _sync_subtitle_inspector_shell_width(self, visible: bool = None):
        """Width of the inspector shell.

        The shell hosts a QStackedWidget that can show a subtitle, audio or
        default card. Width is driven by the `_inspector_collapsed` state:
        - collapsed=True  -> handle only
        - collapsed=False -> wide enough for the widest card

        The `visible` parameter is ignored (kept for API compatibility).
        """
        shell = getattr(self, "subtitle_inspector_shell", None)
        if shell is None:
            return
        # The handle was removed - no extra handle width to add.
        handle_width = 0

        if bool(getattr(self, "_inspector_collapsed", False)):
            target_width = handle_width
        else:
            widest = 400
            for attr in ("subtitle_inspector_card", "audio_inspector_card", "default_inspector_card"):
                card = getattr(self, attr, None)
                if card is None:
                    continue
                try:
                    raw_max = int(card.maximumWidth() or 0)
                    if raw_max > 5000 or raw_max <= 0:
                        raw_max = 0
                    raw_min = int(card.minimumWidth() or 0)
                    if raw_min > 5000 or raw_min < 0:
                        raw_min = 0
                    raw_hint = int(card.sizeHint().width() or 0)
                    candidate = raw_max or raw_hint or raw_min or 400
                    widest = max(widest, candidate)
                except Exception:
                    pass
            widest = max(400, min(widest, 560))
            target_width = handle_width + widest
        shell.setMinimumWidth(target_width)
        shell.setMaximumWidth(target_width)
        shell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _update_subtitle_inspector_summary(self, rows=None):
        rows = rows if rows is not None else self._segment_editor_display_rows()
        count = len(rows or [])
        if not count:
            self._selected_segment_index = -1
            if hasattr(self, "subtitle_inspector_summary_label"):
                self.subtitle_inspector_summary_label.setText("Selected subtitle: none")
            if hasattr(self, "rewrite_selected_segment_btn"):
                self.rewrite_selected_segment_btn.setEnabled(False)
            return

        selected_index = self._get_effective_selected_segment_index(rows)
        if selected_index < 0 or selected_index >= count:
            selected_index = int(rows[0].get("segment_index", 0))
        self._selected_segment_index = selected_index
        if hasattr(self, "subtitle_inspector_summary_label"):
            self.subtitle_inspector_summary_label.setText(f"Selected subtitle: Block {selected_index + 1} / {count}")
        if hasattr(self, "rewrite_selected_segment_btn"):
            self.rewrite_selected_segment_btn.setEnabled(True)

    def set_subtitle_inspector_details_visible(self, visible: bool, *, sync: bool = True):
        if not visible and self.is_inspector_anchored():
            visible = True
        # The subtitle details widget (segment editor) visibility is
        # independent from the audio/default cards. The shell collapse
        # state is managed via `set_inspector_collapsed` (called from the
        # toggle button handler), not by this function.
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(bool(visible))
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.blockSignals(True)
            toggle_btn.setChecked(bool(visible))
            if str(toggle_btn.objectName() or "") == "subtitleInspectorHandleBtn":
                toggle_btn.setText("▶" if visible else "◀")
                toggle_btn.setToolTip("Hide subtitle editor" if visible else "Show subtitle editor")
            else:
                toggle_btn.setText("Hide details" if visible else "Show details")
            toggle_btn.blockSignals(False)
        anchor_cb = getattr(self, "anchor_inspector_cb", None)
        if anchor_cb is not None:
            toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
            if toggle_btn is not None:
                toggle_btn.setEnabled(not self.is_inspector_anchored())
        if not visible:
            self._clear_segment_editor_rows()
            self._segment_editor_rows = []
            self._update_subtitle_inspector_summary()
        else:
            self._sync_selected_segment_to_playback_position()
            if sync:
                self.sync_segment_editor_rows()
        # Do NOT change the inspector collapsed state from here; the
        # toggle button drives the collapse. Other callers (e.g. media_utils
        # on Play) just hide the details without collapsing the shell.

    def set_inspector_collapsed(self, collapsed: bool):
        """Collapse or expand the inspector shell. The track layer
        inspector is always expanded - collapse is disabled.
        """
        collapsed = False
        self._inspector_collapsed = False
        # Sync shell width
        try:
            self._sync_subtitle_inspector_shell_width(visible=not bool(collapsed))
        except Exception:
            pass
        # Hide the entire stack so no card content is visible when collapsed
        stack = getattr(self, "inspector_stack", None)
        if stack is not None:
            stack.setVisible(not bool(collapsed))
        # Sync subtitle details widget visibility to match
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(not bool(collapsed))
        # Sync toggle button
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.blockSignals(True)
            toggle_btn.setChecked(not bool(collapsed))
            toggle_btn.setText("▶" if collapsed else "◀")
            toggle_btn.setToolTip(
                "Show track inspector" if collapsed else "Hide track inspector"
            )
            toggle_btn.blockSignals(False)

    def show_subtitle_inspector_details(self):
        self.set_subtitle_inspector_details_visible(True, sync=True)

    def toggle_subtitle_inspector_details(self, checked: bool):
        # checked=True means "show details" (expand the inspector shell).
        # checked=False means "hide details" (collapse to handle only).
        self.set_inspector_collapsed(not bool(checked))
        # Also update the subtitle details widget visibility (so the
        # segment editor appears/disappears).
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(bool(checked))

    def on_anchor_inspector_toggled(self, checked: bool):
        if checked:
            # Anchor means: keep the track inspector shell expanded
            # (whichever card is currently shown: subtitle, audio, blur
            # or default).
            self.set_inspector_collapsed(False)
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.setEnabled(not checked)
        self.save_user_settings()

    def _sync_selected_segment_to_playback_position(self):
        if not hasattr(self, "media_player"):
            return
        segments = self.live_preview_segments or self.get_active_segments()
        if not segments:
            return
        try:
            position_ms = int(self.media_player.position())
        except Exception:
            return
        active_index = self._find_active_segment_index(position_ms, segments)
        if active_index >= 0:
            self.set_selected_segment_index(active_index, sync_ui=False)

    def sync_segment_editor_rows(self):
        if not hasattr(self, "segment_editor_layout") or getattr(self, "_syncing_segment_editor", False):
            return
        if not self._is_subtitle_inspector_details_visible():
            self._update_subtitle_inspector_summary()
            return

        self._syncing_segment_editor = True
        try:
            self._clear_segment_editor_rows()
            self._segment_editor_rows = []
            rows = self._segment_editor_display_rows()
            self._update_subtitle_inspector_summary(rows)
            if not rows:
                empty_state = QFrame(self.segment_editor_container if hasattr(self, "segment_editor_container") else None)
                empty_state.setObjectName("statusCard")
                empty_state.setMinimumHeight(180)
                empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                empty_state.setStyleSheet(
                    "QFrame#statusCard { background-color: #132132; border: 1px dashed #35506f; border-radius: 16px; }"
                )
                empty_layout = QVBoxLayout(empty_state)
                empty_layout.setContentsMargins(18, 18, 18, 18)
                empty_layout.setSpacing(8)
                empty_layout.addStretch()
                empty_title = QLabel("Subtitle editor is waiting for content")
                empty_title.setObjectName("statusHeadline")
                empty_title.setAlignment(Qt.AlignCenter)
                empty_body = QLabel("Subtitle editor will appear here once transcript or translation is ready.")
                empty_body.setObjectName("helperLabel")
                empty_body.setWordWrap(True)
                empty_body.setAlignment(Qt.AlignCenter)
                empty_layout.addWidget(empty_title)
                empty_layout.addWidget(empty_body)
                empty_layout.addStretch()
                self.segment_editor_layout.addWidget(empty_state, 1)
                return

            selected_index = self._get_effective_selected_segment_index(rows)
            visible_rows = [row for row in rows if int(row.get("segment_index", -1)) == selected_index]
            if not visible_rows:
                visible_rows = [rows[0]]
                selected_index = int(visible_rows[0].get("segment_index", 0))
            self._update_subtitle_inspector_summary(rows)

            show_original = True
            for row in visible_rows:
                idx = int(row.get("segment_index", 0))
                card = QFrame(self.segment_editor_container if hasattr(self, "segment_editor_container") else None)
                # No border on the subtitle display frame - blends into
                # the inspector shell.
                card.setFrameShape(QFrame.NoFrame)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(4, 4, 4, 4)
                card_layout.setSpacing(6)

                # Start/End timing chips
                timing_meta_layout = QHBoxLayout()
                timing_meta_layout.setContentsMargins(0, 0, 0, 0)
                timing_meta_layout.setSpacing(12)
                start_label = QLabel(f"Start  {self.format_timestamp(row['start'])}")
                start_label.setObjectName("timingChip")
                end_label = QLabel(f"End  {self.format_timestamp(row['end'])}")
                end_label.setObjectName("timingChip")
                timing_meta_layout.addWidget(start_label)
                timing_meta_layout.addWidget(end_label)
                timing_meta_layout.addStretch()

                original_label = QLabel(row["original"] or "", card)
                original_label.setWordWrap(True)
                original_label.setObjectName("helperLabel")
                original_label.setVisible(show_original and bool(row["original"].strip()))

                card_layout.addLayout(timing_meta_layout)

                speed_row = QHBoxLayout()
                speed_row.setContentsMargins(0, 0, 0, 0)
                speed_row.setSpacing(8)
                speed_label = QLabel("Voice Speed:")
                speed_label.setObjectName("helperLabel")
                speed_spin = QDoubleSpinBox()
                speed_spin.setRange(0.5, 3.0)
                speed_spin.setSingleStep(0.1)
                speed_spin.setDecimals(1)
                speed_spin.setValue(float(row.get("voice_speed", 1.0)))
                speed_spin.setSuffix("x")
                speed_spin.setFixedWidth(90)
                speed_spin.valueChanged.connect(
                    lambda val, idx=idx: self.on_segment_voice_speed_changed(idx, val)
                )
                speed_row.addWidget(speed_label)
                speed_row.addWidget(speed_spin)
                speed_row.addStretch()

                card_layout.addLayout(speed_row)
                card_layout.addWidget(original_label)

                # The QTabWidget wrapper (with the "Subtitle" tab label
                # and the horizontal tab bar / "hr" beneath it) has been
                # removed. The translated editor + highlight actions are
                # placed directly in the card layout.
                translated_editor = QTextEdit()
                translated_editor.setObjectName("segmentInspectorEditor")
                translated_editor.setAcceptRichText(False)
                translated_editor.setPlainText(row["translated"])
                translated_editor.setMinimumHeight(96)
                translated_editor.setMaximumHeight(96)
                translated_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                translated_editor.setPlaceholderText("Text shown on screen.")
                translated_editor.textChanged.connect(
                    lambda idx=idx, editor=translated_editor: self.on_segment_translation_edited(idx, editor)
                )
                translated_editor.selectionChanged.connect(
                    lambda idx=idx, editor=translated_editor: self._update_segment_highlight_button_state(idx, editor)
                )
                highlight_btn = QPushButton("Add highlight from selection")
                highlight_btn.setEnabled(False)
                highlight_btn.clicked.connect(
                    lambda _=False, idx=idx, editor=translated_editor: self.add_segment_manual_highlight(idx, editor)
                )

                highlight_action_layout = QHBoxLayout()
                highlight_action_layout.setContentsMargins(0, 0, 0, 0)
                highlight_action_layout.setSpacing(8)
                highlight_action_layout.addWidget(highlight_btn)
                highlight_action_layout.addStretch()

                highlight_meta_layout = QHBoxLayout()
                highlight_meta_layout.setContentsMargins(0, 0, 0, 0)
                highlight_meta_layout.setSpacing(6)
                highlight_placeholder = QLabel("")
                highlight_placeholder.setObjectName("helperLabel")
                highlight_chip_container = QWidget()
                highlight_chip_layout = QHBoxLayout(highlight_chip_container)
                highlight_chip_layout.setContentsMargins(0, 0, 0, 0)
                highlight_chip_layout.setSpacing(6)
                highlight_meta_layout.addWidget(highlight_placeholder)
                highlight_meta_layout.addWidget(highlight_chip_container, 1)

                card_layout.addWidget(translated_editor, 0)
                card_layout.addLayout(highlight_action_layout)
                card_layout.addLayout(highlight_meta_layout)

                for label in card.findChildren(QLabel):
                    label_text = label.text().strip()
                    if len(label_text) <= 2 and not label_text.isascii():
                        label.hide()
                self.segment_editor_layout.addWidget(card, 0)
                self._segment_editor_rows.append(
                    {
                        "segment_index": idx,
                        "frame": card,
                        "original_label": original_label,
                        "translated_editor": translated_editor,
                        "highlight_button": highlight_btn,
                        "highlight_placeholder": highlight_placeholder,
                        "highlight_chip_layout": highlight_chip_layout,
                    }
                )
                self._update_segment_highlight_button_state(idx, translated_editor)
                self._sync_segment_highlight_chip_row(idx)
                self._update_segment_spoken_status(idx)

            self._set_segment_editor_highlight(selected_index)
        finally:
            self._syncing_segment_editor = False

    def sync_segment_editor_from_hidden_text(self):
        if getattr(self, "_syncing_hidden_editor_text", False):
            return

        transcript_text = self.transcript_text.toPlainText().strip()
        if transcript_text and not transcript_text.lower().startswith("transcribing..."):
            parsed_transcript = self.parse_srt_to_segments(transcript_text)
            if parsed_transcript:
                self.current_segments = parsed_transcript

        translated_text = self.translated_text.toPlainText().strip()
        if translated_text and not translated_text.lower().startswith("translating with "):
            base_segments = self.current_translated_segments or self.current_segments
            parsed_translated = self._segments_from_editor_text(translated_text, base_segments)
            if parsed_translated:
                self.current_translated_segments = parsed_translated

        self.sync_segment_editor_rows()

    def _sync_hidden_translated_text_from_segments(self):
        if getattr(self, "_syncing_segment_editor", False):
            return
        self._syncing_hidden_editor_text = True
        try:
            self.translated_text.setText(self.format_to_srt(self.current_translated_segments))
        finally:
            self._syncing_hidden_editor_text = False

    def on_segment_translation_edited(self, index: int, editor: QTextEdit):
        if getattr(self, "_syncing_segment_editor", False):
            return

        base_segments = self.current_segments or self.current_translated_segments
        if not base_segments or index >= len(base_segments):
            return

        if len(self.current_translated_segments) != len(base_segments):
            self.current_translated_segments = [
                {
                    "start": float(base.get("start", 0.0)),
                    "end": float(base.get("end", 0.0)),
                    "text": str(self.current_translated_segments[idx].get("text", "")) if idx < len(self.current_translated_segments) else "",
                    "tts_text": str(self.current_translated_segments[idx].get("tts_text", base.get("tts_text", "")) or "") if idx < len(self.current_translated_segments) else str(base.get("tts_text", "") or ""),
                    "tts_group_id": self.current_translated_segments[idx].get("tts_group_id", base.get("tts_group_id", "")) if idx < len(self.current_translated_segments) else base.get("tts_group_id", ""),
                    "tts_group_start": float(self.current_translated_segments[idx].get("tts_group_start", base.get("tts_group_start", base.get("start", 0.0))) or base.get("start", 0.0)) if idx < len(self.current_translated_segments) else float(base.get("tts_group_start", base.get("start", 0.0)) or base.get("start", 0.0)),
                    "tts_group_end": float(self.current_translated_segments[idx].get("tts_group_end", base.get("tts_group_end", base.get("end", 0.0))) or base.get("end", 0.0)) if idx < len(self.current_translated_segments) else float(base.get("tts_group_end", base.get("end", 0.0)) or base.get("end", 0.0)),
                    "words": list(base.get("words", [])),
                    "manual_highlights": list(base.get("manual_highlights", [])),
                }
                for idx, base in enumerate(base_segments)
            ]

        self.current_translated_segments[index]["text"] = editor.toPlainText().strip()
        self.current_translated_segments[index].setdefault("manual_highlights", [])
        self._reconcile_manual_highlights(self.current_translated_segments[index])
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def on_segment_voice_speed_changed(self, index: int, value: float):
        if getattr(self, "_syncing_segment_editor", False):
            return
        for segments_list in (self.current_translated_segments, self.current_segments):
            if segments_list and 0 <= index < len(segments_list):
                segments_list[index]["voice_speed"] = round(float(value), 1)
                self._voiceover_force_refresh = True
        self.persist_current_timeline_project_data()

    def _set_segment_editor_highlight(self, active_index: int):
        rows = getattr(self, "_segment_editor_rows", [])
        target_frame = None
        for row in rows:
            row_index = int(row.get("segment_index", -1))
            if row_index == active_index:
                row["frame"].setStyleSheet("QFrame#statusCard { background-color: #153149; border: 1px solid #5fb9ff; border-radius: 14px; }")
                target_frame = row["frame"]
            else:
                row["frame"].setStyleSheet("")
        # Scroll the outer inspector card so the highlighted segment
        # is visible. The inner segment_editor_scroll was flattened;
        # the QScrollArea wrapping the subtitle card is at stack index 0.
        if target_frame is not None and hasattr(self, "inspector_stack"):
            try:
                scroll = self.inspector_stack.widget(0)
                if scroll is not None and hasattr(scroll, "ensureWidgetVisible"):
                    scroll.ensureWidgetVisible(target_frame, 0, 36)
            except Exception:
                pass

    def play_audio_preview_file(self, audio_path: str):
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError("Audio preview file was not found.")
        if os.path.getsize(audio_path) <= 44:
            raise RuntimeError("Audio preview file is empty or invalid.")
        if hasattr(self, "media_player") and self.media_player.is_playing():
            self.media_player.pause()
            if hasattr(self, "timeline"):
                self.timeline.set_playing(False)
        self.audio_preview_player.stop()
        self.audio_preview_player.setSource(QUrl.fromLocalFile(audio_path))
        self.audio_preview_player.play()
        self._last_audio_preview_path = audio_path

    def preview_current_audio_track(self):
        audio_path = self.resolve_selected_audio_path()
        if not audio_path or not os.path.exists(audio_path):
            QMessageBox.warning(self, "Missing Voice", "Please generate voice first before using Preview audio.")
            return
        try:
            self.play_audio_preview_file(audio_path)
            self.log(f"[Audio Preview] playing {audio_path}")
        except Exception as exc:
            self.show_error("Audio Preview Failed", "Could not preview the current audio track.", str(exc))

    def _blur_effect_enabled(self) -> bool:
        return bool(hasattr(self, "blur_area_btn") and self.blur_area_btn.isChecked())

    def _sync_blur_controls(self):
        video_view = getattr(self, "video_view", None)
        blur_btn = getattr(self, "blur_area_btn", None)
        blur_add_btn = getattr(self, "blur_add_btn", None)
        if video_view is None or blur_btn is None:
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        blur_enabled = self._blur_effect_enabled()
        is_playing = False
        media_player = getattr(self, "media_player", None)
        if media_player is not None:
            try:
                is_playing = bool(media_player.is_playing())
            except Exception:
                is_playing = False
        # The blur overlay (the draggable rectangle) is only shown
        # when the blur effect is ON. Turning the effect OFF hides
        # the rectangle; turning it ON shows it again for drag.
        has_regions = bool(self._current_blur_regions_payload())
        editing_allowed = (
            blur_enabled
            and has_video
            and has_regions
            and not is_playing
            and not bool(getattr(self, "_filter_thumbnail_visible", False))
        )
        video_view.set_blur_edit_enabled(editing_allowed)
        if blur_add_btn is not None:
            # The "+" button must be clickable even when the blur effect
            # toggle is OFF: pressing it should both enable the effect
            # AND add a region. Requiring the user to toggle first is
            # unnecessary friction.
            blur_add_btn.setEnabled(
                bool(getattr(self, "_optional_layer_controls_ready", False))
                and has_video
                and not is_playing
                and not bool(getattr(self, "_filter_thumbnail_visible", False))
            )

    def toggle_blur_effect_enabled(self, checked: bool):
        if not hasattr(self, "video_view") or not hasattr(self, "blur_area_btn"):
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        if checked and not has_video:
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(False)
            self.blur_area_btn.blockSignals(False)
            QMessageBox.warning(self, "Blur Area", "Please load a video before adding a blur area.")
            return
        # Only show/hide the blur area (overlay rectangle). The actual
        # mpv blur effect is NOT applied on toggle - it is only applied
        # when the video plays, to keep toggling fast and avoid
        # rendering artifacts at the toggle position.
        self._sync_blur_controls()
        self.persist_project_blur_state()
        # Sync the B1 track label so the ON/OFF indicator matches
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_blur_on("B1", bool(checked))
            except Exception:
                pass
        if checked:
            self.log("[Blur Area] blur effect enabled.")

    def add_blur_region(self):
        if not hasattr(self, "video_view"):
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        if not has_video:
            QMessageBox.warning(self, "Blur Area", "Please load a video before adding a blur area.")
            return
        if hasattr(self, "blur_area_btn") and not self.blur_area_btn.isChecked():
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(True)
            self.blur_area_btn.blockSignals(False)
        if hasattr(self.video_view, "add_blur_region"):
            self.video_view.add_blur_region()
        # Do NOT call on_add_timeline_layer("blur") here. The
        # blurRegionChanged signal emitted by add_blur_region() will
        # trigger on_preview_blur_region_changed() which (with the
        # recent fix) syncs the B1 track from the overlay regions
        # even when the blur effect is on. Adding a BlurLayer here too
        # would create a duplicate.
        self._sync_blur_controls()
        self._blur_region_preview_dirty = True
        if hasattr(self, "media_player"):
            self.media_player.clear_blur_region()
        self.persist_project_blur_state()

    def on_blur_edit_finished(self):
        if getattr(self, "_blur_edit_finish_syncing", False):
            return
        if not self._blur_effect_enabled():
            return
        self._blur_region_preview_dirty = True
        self.persist_project_blur_state()

    def toggle_ocr_region_editing(self, checked: bool):
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is None:
            return
        engine = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine())
        if not checked or engine != "ocr":
            overlay.hide()
            overlay.set_editable(False)
            self.ocr_region_btn.setStyleSheet("QPushButton { color: #6ee7d6; font-weight: bold; font-size: 10px; padding: 0; }")
            self._sync_blur_controls()
            return
        if self._blur_effect_enabled():
            self.video_view.set_blur_edit_enabled(False)
        overlay.set_editable(True)
        overlay.sync_to_view()
        self.apply_preview_blur_region()
        self.log("[OCR Region] drag inside the video preview to move or resize the OCR crop.")

    def on_preview_blur_region_changed(self):
        if self._blur_effect_enabled():
            self._blur_region_preview_dirty = True
            # Even when the blur effect is on, the B1 track in the
            # timeline must stay in sync with the overlay regions. Without
            # this, deleting a region from the overlay leaves a stale
            # BlurLayer behind in the timeline. The actual mpv blur
            # effect is only updated when the video plays, to keep
            # editing fast.
            if hasattr(self, "timeline"):
                try:
                    regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
                    self.timeline.sync_blur_regions(regions)
                    if hasattr(self, "persist_project_blur_state"):
                        self.persist_project_blur_state()
                except Exception:
                    pass
            return
        self.apply_preview_blur_region()
        self.persist_project_blur_state()
        if hasattr(self, "timeline"):
            regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
            self.timeline.sync_blur_regions(regions)

    def apply_preview_blur_region(self, *, regions=None, force: bool = False):
        if not hasattr(self, "media_player") or not hasattr(self, "video_view"):
            return
        self._blur_region_preview_dirty = False
        blur_enabled = self._blur_effect_enabled()
        blur_region = regions if regions is not None else (
            self.video_view.get_blur_region_normalized() if hasattr(self.video_view, "get_blur_region_normalized") else None
        )
        # Always apply the blur when enabled and regions exist, even
        # when the video is paused, so the user can see the cached
        # blur effect on the video preview.
        if blur_enabled and blur_region:
            self.media_player.set_blur_region(blur_region)
        else:
            self.media_player.clear_blur_region()

    def _current_blur_regions_payload(self):
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "get_blur_region_normalized"):
            return []
        raw_regions = self.video_view.get_blur_region_normalized()
        if isinstance(raw_regions, dict):
            raw_regions = [raw_regions]
        if not isinstance(raw_regions, list):
            return []
        regions = []
        for region in raw_regions:
            if not isinstance(region, dict):
                continue
            try:
                x = max(0.0, min(1.0, float(region.get("x", 0.0))))
                y = max(0.0, min(1.0, float(region.get("y", 0.0))))
                width = max(0.0, min(1.0 - x, float(region.get("width", 0.0))))
                height = max(0.0, min(1.0 - y, float(region.get("height", 0.0))))
            except (TypeError, ValueError):
                continue
            if width <= 0.0 or height <= 0.0:
                continue
            entry = {
                "x": round(x, 6),
                "y": round(y, 6),
                "width": round(width, 6),
                "height": round(height, 6),
            }
            # Per-region style (radius, opacity, pixelate). Defaults
            # are chosen so an existing region without these keys
            # behaves the same as before the inspector was added.
            try:
                strength = region.get("blur_strength", region.get("strength"))
                if strength is not None:
                    entry["blur_strength"] = int(round(float(strength)))
            except (TypeError, ValueError):
                pass
            try:
                opacity = region.get("blur_opacity", region.get("opacity"))
                if opacity is not None:
                    entry["blur_opacity"] = round(float(opacity), 4)
            except (TypeError, ValueError):
                pass
            if bool(region.get("pixelate", False)):
                entry["pixelate"] = True
                try:
                    entry["pixelate_size"] = int(region.get("pixelate_size", 12))
                except (TypeError, ValueError):
                    entry["pixelate_size"] = 12
            regions.append(entry)
        return regions

    def persist_project_blur_state(self, *, regions=None, enabled=None):
        state = getattr(self, "current_project_state", None)
        if not state:
            return
        if regions is None:
            regions = self._current_blur_regions_payload()
        if enabled is None:
            enabled = self._blur_effect_enabled()
        blur_state = {
            "enabled": bool(enabled),
            "regions": list(regions or []),
        }
        if state.settings.get("blur_state") == blur_state:
            return
        state.set_setting("blur_state", blur_state)
        self.project_service.save_project(state)



    def _restore_project_blur_state(self, state):
        blur_state = dict(getattr(state, "settings", {}).get("blur_state") or {})
        regions = blur_state.get("regions", [])
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_blur_regions_normalized"):
            self.video_view.set_blur_regions_normalized(regions)
        # Always default the blur toggle to ON on project reopen so the
        # blur area is displayed by default. The mpv blur effect is
        # NOT auto-applied on reopen - it is only applied when the
        # video plays.
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(True)
            self.blur_area_btn.blockSignals(False)
        self._sync_blur_controls()
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_blur_on("B1", True)
            except Exception:
                pass
        if hasattr(self, "timeline"):
            self.timeline.sync_blur_regions(regions)
        if hasattr(self, "media_player"):
            self.media_player.clear_blur_region()

    # ---- Mask layer (M1) ----
    def _current_mask_regions_payload(self, *, time_seconds=None, include_inactive=False):
        """Build the mask payload from the M1 track's MaskLayers.

        Visibility is NOT checked here — the play-state gate in
        _apply_mask_to_preview is the single source of truth for
        whether the mask is shown on the video. The payload always
        includes every M1 layer so the mask is ready the moment the
        user presses play.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return []
        items: list[dict] = []
        for tr in self.timeline._timeline.tracks:
            if tr.name != "M1":
                continue
            for layer in tr.layers:
                if not include_inactive and not self._layer_is_active_at_preview_time(layer, time_seconds):
                    continue
                try:
                    items.append({
                        "x": float(getattr(layer, "position_x", 0.3)),
                        "y": float(getattr(layer, "position_y", 0.4)),
                        "width": float(getattr(layer, "width", 0.4)),
                        "height": float(getattr(layer, "height", 0.2)),
                        "color": str(getattr(layer, "color", "#000000")),
                        "mode": str(getattr(layer, "mode", "solid")),
                        "opacity": float(getattr(layer, "opacity", 1.0)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
                        "blur_strength": int(getattr(layer, "blur_strength", 20)),
                        "start": float(getattr(layer, "start", 0.0) or 0.0),
                        "end": float(getattr(layer, "end", 0.0) or 0.0),
                    })
                except (TypeError, ValueError):
                    continue
        return items

    def _apply_mask_to_preview(self, *, regions=None, force: bool = False):
        """Push the M1 mask track into the mpv filter chain.

        The mask is only applied to the video while the player is
        playing. When the video is paused / stopped, the mask is
        cleared from the mpv filter chain so the original frame shows
        through. The draggable overlay remains visible either way so
        the user can position / resize the region while paused.

        `force=True` bypasses the play-state gate (used by direct
        calls from `toggle_play` so the mask is applied/cleared in
        the same code path as the play/pause).
        """
        if not hasattr(self, "media_player"):
            return
        if regions is None:
            regions = self._current_mask_regions_payload(include_inactive=True)
        if force:
            if regions:
                self.media_player.set_mask_region(regions)
            else:
                self.media_player.clear_mask_region()
            return
        is_playing = False
        try:
            is_playing = bool(self.media_player.is_playing())
        except Exception:
            is_playing = False
        if regions and is_playing:
            self.media_player.set_mask_region(regions)
        else:
            self.media_player.clear_mask_region()

    def _on_preview_state_changed(self, _state: int):
        """Re-apply the M1 mask filter when the player state changes.

        The mask is only applied to the video while the player is
        playing. Hooked from `media_player.stateChanged` in
        `setup_media_player` so the mpv filter chain is updated on
        play / pause / stop. The mask overlay is also locked
        (`set_editable(False)`) while the video is playing so the
        user cannot accidentally drag or resize the region during
        playback. Also sync the timeline play state so the timeline
        stops running when the video ends (Bug 2).
        """
        try:
            is_playing = bool(self.media_player.is_playing())
        except Exception:
            is_playing = False
        # Sync the timeline's "playing" flag to the real player state.
        # Without this the timeline keeps animating past the end of the
        # video because the player auto-pauses (keep_open="always") but
        # nothing tells the timeline to stop.
        try:
            if hasattr(self, "timeline") and self.timeline is not None:
                self.timeline.set_playing(is_playing)
        except Exception:
            pass
        # Lock / unlock the mask overlay based on play state.
        try:
            overlay = getattr(self.video_view, "mask_overlay", None)
            if overlay is not None and overlay._regions:
                overlay.set_editable(not is_playing)
        except Exception:
            pass
        # When playback just ended, pause both audio sidecars so they
        # don't drift ahead of the held last frame.
        if not is_playing and hasattr(self, "media_player"):
            try:
                if hasattr(self.media_player, "_original_loaded_path") and getattr(self.media_player, "_original_loaded_path", ""):
                    self.media_player._original_player.pause()
            except Exception:
                pass
            try:
                if hasattr(self.media_player, "_dubbed_loaded_path") and getattr(self.media_player, "_dubbed_loaded_path", ""):
                    self.media_player._dubbed_player.pause()
            except Exception:
                pass
        try:
            self._apply_mask_to_preview()
        except Exception:
            pass

    def persist_project_mask_state(self, *, regions=None):
        state = getattr(self, "current_project_state", None)
        if not state:
            return
        if regions is None:
            regions = self._current_mask_regions_payload()
        mask_state = {"enabled": True, "regions": list(regions or [])}
        if state.settings.get("mask_state") == mask_state:
            return
        state.set_setting("mask_state", mask_state)
        self.project_service.save_project(state)

    def _restore_project_mask_state(self, state):
        mask_state = dict(getattr(state, "settings", {}).get("mask_state") or {})
        regions = mask_state.get("regions", [])
        if hasattr(self, "media_player") and hasattr(self.media_player, "set_mask_region"):
            if regions:
                self.media_player.set_mask_region(regions)
            else:
                self.media_player.clear_mask_region()
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_mask_shown("M1", True)
            except Exception:
                pass
        # Sync the M1 track from the persisted regions.
        if hasattr(self, "timeline") and regions:
            try:
                from app.layers.mask import MaskLayer
                from app.layers.sync_bridge import find_or_create_track
                from app.layers.base import LayerType
                tl = self.timeline._timeline
                track = find_or_create_track(tl, "M1", LayerType.MASK, 60)
                track.layers.clear()
                # Mask layers span the full video duration (like the
                # audio track) so the M1 row matches the video length
                # rather than collapsing to a zero-width clip (Bug 1).
                mask_end = tl.duration if tl.duration > 0 else (
                    self.timeline._duration if hasattr(self.timeline, "_duration") else 0.0
                )
                if mask_end <= 0:
                    mask_end = 5.0
                for i, r in enumerate(regions):
                    layer = MaskLayer(
                        name=f"Mask {i + 1}",
                        position_x=float(r.get("x", 0.3)),
                        position_y=float(r.get("y", 0.4)),
                        width=float(r.get("width", 0.4)),
                        height=float(r.get("height", 0.2)),
                        color=str(r.get("color", "#000000")),
                        mode=str(r.get("mode", "solid")),
                        pixelate_size=int(r.get("pixelate_size", 12)),
                        blur_strength=int(r.get("blur_strength", 20)),
                        start=0.0,
                        end=float(mask_end),
                    )
                    layer.z_index = i
                    track.layers.append(layer)
                if hasattr(self.timeline, "_track_heights"):
                    self.timeline._track_heights[track.id] = 60
                self.timeline._redraw()
                # Show the draggable overlay for the first restored
                # mask so the user can immediately move / resize it
                # after reopening the project (like the blur overlay).
                if track.layers:
                    try:
                        first_layer = track.layers[0]
                        self.timeline._selected_layer_id = first_layer.id
                        self._show_mask_overlay(track, first_layer)
                    except Exception:
                        pass
            except Exception:
                pass

    def _show_mask_inspector_for_track(self, track, layer=None):
        """Show the Mask Track Inspector populated with the selected M1 layer.

        The inspector only exposes the mask's colour + opacity. Position,
        size and mode are not configurable here — the user positions /
        resizes the region via the draggable overlay on the video. The
        mask is only applied to the video while the player is playing.
        """
        self._switch_inspector("mask")
        self._wire_mask_inspector_controls()
        self._wire_layer_timing_controls("mask")
        if layer is None:
            return
        self._set_layer_timing_controls("mask", layer)
        color = str(getattr(layer, "color", "#000000"))
        if hasattr(self, "mask_inspector_color_btn"):
            self.mask_inspector_color_btn.blockSignals(True)
            self.mask_inspector_color_btn.setText(color)
            self.mask_inspector_color_btn.setStyleSheet(
                f"background-color: {color}; color: #fff;"
            )
            self.mask_inspector_color_btn.blockSignals(False)
        try:
            opacity = float(getattr(layer, "opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        opacity = max(0.0, min(1.0, opacity))
        if hasattr(self, "mask_inspector_opacity_slider"):
            self.mask_inspector_opacity_slider.blockSignals(True)
            self.mask_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.mask_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "mask_inspector_opacity_value_label"):
            self.mask_inspector_opacity_value_label.setText(f"{int(round(opacity * 100))}%")
        if hasattr(self, "mask_inspector_summary_label"):
            tname = getattr(track, "name", "M1")
            lname = getattr(layer, "name", "Mask")
            self.mask_inspector_summary_label.setText(
                f"Selected: {tname} → {lname}. Drag the mask on the video "
                "to move it. Drag a corner to resize. The X button deletes "
                "the mask. The mask is applied while the video is playing."
            )

    def _wire_mask_inspector_controls(self):
        """One-time wiring of the Mask Inspector controls.

        Only colour + opacity are wired here. Position / size / mode
        are not configurable in the inspector; the user positions and
        resizes the mask via the draggable overlay on the video.
        """
        if getattr(self, "_mask_inspector_wired", False):
            return
        self._mask_inspector_wired = True

        def _selected_mask_layer():
            if not hasattr(self, "timeline") or not self.timeline._timeline:
                return None, None
            sid = getattr(self.timeline, "_selected_layer_id", "") or ""
            for tr in self.timeline._timeline.tracks:
                for l in tr.layers:
                    if l.id == sid:
                        return l, tr
            return None, None

        def _sync_preview(l):
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            try:
                if hasattr(self, "persist_project_mask_state"):
                    self.persist_project_mask_state()
            except Exception:
                pass

        def _on_opacity_changed(v):
            layer, _ = _selected_mask_layer()
            if layer is None:
                return
            opacity = max(0.0, min(1.0, float(v) / 100.0))
            try:
                layer.opacity = opacity
            except Exception:
                pass
            if hasattr(self, "mask_inspector_opacity_value_label"):
                self.mask_inspector_opacity_value_label.setText(f"{int(v)}%")
            _sync_preview(layer)

        self._mask_opacity_handler = _on_opacity_changed
        if hasattr(self, "mask_inspector_opacity_slider"):
            self.mask_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)

        # Color picker
        from PySide6.QtWidgets import QColorDialog
        def _on_color_clicked():
            from PySide6.QtGui import QColor
            layer, _ = _selected_mask_layer()
            current = QColor(str(getattr(layer, "color", "#000000")))
            chosen = QColorDialog.getColor(current, self, "Pick mask colour")
            if not chosen.isValid():
                return
            hex_str = chosen.name()
            if hasattr(self, "mask_inspector_color_btn"):
                self.mask_inspector_color_btn.setText(hex_str)
                self.mask_inspector_color_btn.setStyleSheet(
                    f"background-color: {hex_str}; color: #fff;"
                )
            if layer is not None:
                try:
                    layer.color = hex_str
                except Exception:
                    pass
                _sync_preview(layer)

        self._mask_color_handler = _on_color_clicked
        if hasattr(self, "mask_inspector_color_btn"):
            self.mask_inspector_color_btn.clicked.connect(_on_color_clicked)

    def _resolve_voice_preview_source(self, entry: dict) -> QUrl:
        preview_path = str(entry.get("preview_video_path", "")).strip()
        preview_url = str(entry.get("preview_video_url", "")).strip()
        preview_audio_path = str(entry.get("preview_audio_path", "")).strip()
        preview_audio_url = str(entry.get("preview_audio_url", "")).strip()

        if preview_path:
            if not os.path.isabs(preview_path):
                preview_path = os.path.join(self.workspace_root, preview_path)
            if not os.path.exists(preview_path):
                raise FileNotFoundError("The configured preview video file was not found.")
            return QUrl.fromLocalFile(preview_path)
        if preview_url:
            return QUrl(preview_url)
        if preview_audio_path:
            if not os.path.isabs(preview_audio_path):
                preview_audio_path = os.path.join(self.workspace_root, preview_audio_path)
            if not os.path.exists(preview_audio_path):
                raise FileNotFoundError("The configured preview audio file was not found.")
            return QUrl.fromLocalFile(preview_audio_path)
        if preview_audio_url:
            return QUrl(preview_audio_url)
        raise RuntimeError("This voice does not have preview media configured yet.")

    def _stop_voice_library_preview(self):
        try:
            self.voice_preview_library_player.stop()
            self.voice_preview_library_player.setSource(QUrl())
        except Exception:
            pass
        for button in self._voice_preview_row_buttons.values():
            button.setText("Preview")

    def _play_voice_preview_entry(self, entry: dict, button: QPushButton | None = None):
        try:
            source = self._resolve_voice_preview_source(entry)
            self._stop_voice_library_preview()
            self.voice_preview_library_player.setSource(source)
            self.voice_preview_library_player.play()
            if button is not None:
                button.setText("Playing...")
            self.log(f"[Voice Preview] playing clip for {entry.get('name', 'voice')}")
        except Exception as exc:
            self.show_error("Voice Preview Failed", "Could not play the selected voice preview clip.", str(exc))

    def _build_voice_preview_popup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Voice Preview Library")
        dialog.setModal(False)
        dialog.resize(720, 560)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #0f1724;
            }
            QWidget {
                background-color: #0f1724;
                color: #dbe5f3;
            }
            QScrollArea {
                border: none;
                background-color: #0f1724;
            }
            QLabel#statusHeadline {
                color: #f8fbff;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                color: #8ad7ff;
                font-weight: 700;
            }
            QLabel#helperLabel {
                color: #9fb3ca;
            }
            QFrame#statusCard {
                background-color: #132033;
                border: 1px solid #2f4868;
                border-radius: 12px;
            }
            QPushButton {
                background-color: #22344d;
                color: #f8fbff;
                border: 1px solid #34506f;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
            QPushButton:disabled {
                background-color: #172435;
                color: #7f92a9;
                border-color: #24384f;
            }
            """
        )

        root_layout = QVBoxLayout(dialog)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        title = QLabel("Voice Preview Library", dialog)
        title.setObjectName("statusHeadline")
        root_layout.addWidget(title)

        hint = QLabel(
            "Preview each configured voice sample here. This popup uses a separate player and does not affect the main video timeline.",
            dialog,
        )
        hint.setObjectName("helperLabel")
        hint.setWordWrap(True)
        root_layout.addWidget(hint)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget(scroll)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        current_provider = None
        self._voice_preview_row_buttons = {}
        entries = sorted(
            list(self.voice_catalog_entries_all or []),
            key=lambda item: (
                str(item.get("tier", "")),
                self._voice_provider_label(str(item.get("provider", ""))),
                str(item.get("name", "")),
            ),
        )
        for entry in entries:
            provider = self._voice_provider_label(str(entry.get("provider", "")).strip())
            if provider != current_provider:
                current_provider = provider
                header = QLabel(provider, container)
                header.setObjectName("sectionTitle")
                layout.addWidget(header)

            row = QFrame(container)
            row.setObjectName("statusCard")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)

            label = QLabel(str(entry.get("name", entry.get("id", "Voice"))), row)
            label.setWordWrap(True)
            meta = QLabel(str(entry.get("tier", "voice")).strip().title(), row)
            meta.setObjectName("helperLabel")
            preview_btn = QPushButton("Preview", row)
            preview_btn.setEnabled(self._entry_has_preview_media(entry))
            preview_btn.clicked.connect(lambda _checked=False, item=entry, btn=preview_btn: self._play_voice_preview_entry(item, btn))

            row_layout.addWidget(label, 1)
            row_layout.addWidget(meta)
            row_layout.addWidget(preview_btn)
            layout.addWidget(row)
            self._voice_preview_row_buttons[str(entry.get("id", ""))] = preview_btn

        layout.addStretch()
        scroll.setWidget(container)
        root_layout.addWidget(scroll, 1)

        close_btn = QPushButton("Close", dialog)
        close_btn.clicked.connect(dialog.close)
        root_layout.addWidget(close_btn, 0, Qt.AlignRight)

        dialog.finished.connect(lambda _result: self._stop_voice_library_preview())
        self.voice_preview_dialog = dialog
        return dialog

    def preview_selected_voice_sample(self):
        if not (self.voice_catalog_entries or []):
            QMessageBox.information(self, "Preview voice", "No local voices are available yet. Please add Piper models to models/piper first.")
            return

        if not self.ensure_required_resources("Voice preview", include_voice=True):
            return

        if self._voice_sample_preview_thread is not None:
            QMessageBox.information(self, "Preview voice", "A preview is already being generated. Please wait a moment.")
            return

        voice_name = self.get_active_voice_name()
        if not voice_name:
            QMessageBox.warning(self, "Preview voice", "Choose a voice first.")
            return
        voice_speed = self._parse_voice_speed_value()
        text = "Chào bạn, đây là bản xem trước giọng nói của mẫu được chọn."  # "Hello, this is a preview of the selected voice sample." in Vietnamese

        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setEnabled(False)
            self.preview_voice_btn.setText("...")

        worker = VoiceSamplePreviewWorker(
            self.workspace_root,
            text,
            voice_name,
            voice_speed,
            temp_dir=self.get_project_temp_dir("voice_sample_preview"),
        )
        worker.progress.connect(self.log)
        worker.finished.connect(self.on_voice_sample_preview_ready)
        self._voice_sample_preview_thread = worker
        worker.start()

    def on_voice_sample_preview_ready(self, audio_path: str, error: str):
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setEnabled(True)
            self.preview_voice_btn.setText("Preview voice")
        self._voice_sample_preview_thread = None

        if error:
            self.show_error("Voice Preview Failed", "Could not generate the preview audio.", error)
            return
        if not audio_path:
            self.show_error("Voice Preview Failed", "Preview audio path is missing.", "")
            return

        try:
            self.play_audio_preview_file(audio_path)
            self.log(f"[Voice Preview] playing generated sample: {audio_path}")
        except Exception as exc:
            self.show_error("Voice Preview Failed", "Could not play the generated preview audio.", str(exc))

    def preview_segment_audio(self, index: int):
        if index < 0 or index >= len(self.current_translated_segments or self.current_segments):
            QMessageBox.warning(self, "Missing Subtitle", "This subtitle line is not ready yet.")
            return

        if not self.ensure_required_resources("Subtitle audio preview", include_voice=True):
            return

        source_segments = self.current_translated_segments or self.current_segments
        text = str(source_segments[index].get("tts_text") or source_segments[index].get("text", "")).strip()
        if not text:
            QMessageBox.warning(self, "Missing Subtitle", "This subtitle line is empty.")
            return

        voice_name = self.get_active_voice_name()
        if not voice_name:
            QMessageBox.warning(self, "Missing Voice", "Choose a voice first before generating subtitle audio preview.")
            return
        voice_speed = self._parse_voice_speed_value()
        row = self._find_segment_editor_row(index)
        # The per-segment "Regenerate voice" button was moved to the
        # A2 Dub Track Inspector. Disable that one instead.
        if getattr(self, "audio_inspector_regenerate_voice_btn", None) is not None:
            self.audio_inspector_regenerate_voice_btn.setEnabled(False)
            self.audio_inspector_regenerate_voice_btn.setText("...")

        existing = self._segment_preview_threads.get(index)
        if existing and existing.isRunning():
            existing.quit()
            existing.wait(2000)
        worker = SegmentAudioPreviewWorker(
            self.workspace_root,
            index,
            text,
            voice_name,
            voice_speed,
            temp_dir=self.get_project_temp_dir("segment_audio_preview"),
            cache_temp_dir=self.get_project_temp_dir("tts"),
        )
        worker.finished.connect(self.on_segment_audio_preview_ready)
        self._segment_preview_threads[index] = worker
        worker.start()

    def on_segment_audio_preview_ready(self, index: int, audio_path: str, error: str):
        btn = getattr(self, "audio_inspector_regenerate_voice_btn", None)

        self._segment_preview_threads.pop(index, None)

        if error:
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("Regenerate voice")
            self.show_error("Audio Preview Failed", "Could not generate preview audio for this subtitle.", error)
            return

        self._voiceover_force_refresh = True
        if btn is not None:
            btn.setEnabled(True)
            btn.setText("Regenerate voice")

        if getattr(self, "last_voice_vi_path", "") and os.path.exists(self.last_voice_vi_path):
            self.run_voiceover()
        else:
            self._apply_segment_audio_end_to_timeline(index=index, audio_path=audio_path)
            try:
                self.play_audio_preview_file(audio_path)
            except Exception as exc:
                self.show_error("Audio Preview Failed", "Could not play the generated preview audio.", str(exc))

    def _apply_segment_audio_end_to_timeline(self, *, index: int, audio_path: str) -> None:
        if not audio_path or not os.path.exists(audio_path):
            return
        actual_d = ffprobe_wav_duration(audio_path)
        if actual_d <= 0.0:
            return
        segs = self.current_translated_segments or self.current_segments
        if not segs or index < 0 or index >= len(segs):
            return
        seg = segs[index]
        try:
            start_s = float(seg.get("start", 0.0))
        except (TypeError, ValueError):
            return
        audio_end = start_s + actual_d
        try:
            cur_end = float(seg.get("end", audio_end))
        except (TypeError, ValueError):
            cur_end = audio_end
        if audio_end > cur_end + 0.01:
            seg["_audio_end"] = audio_end
        else:
            seg.pop("_audio_end", None)
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return
        timeline_model = getattr(timeline, "_timeline", None)
        if timeline_model is None:
            return
        from app.layers.sync_bridge import DUB_SUBTITLE_TRACK_NAME
        target_track = None
        for t in timeline_model.tracks:
            if t.name == DUB_SUBTITLE_TRACK_NAME:
                target_track = t
                break
        if target_track is None:
            return
        for layer in target_track.layers:
            meta = getattr(layer, "metadata", None) or {}
            if not isinstance(meta, dict):
                continue
            try:
                if int(meta.get("_seg_index", -1)) == index:
                    if audio_end > cur_end + 0.01:
                        meta["_audio_end"] = audio_end
                    else:
                        meta.pop("_audio_end", None)
            except (TypeError, ValueError):
                continue
        timeline._redraw()

    def download_subtitle(self):
        srt_text = self.translated_text.toPlainText().strip()
        if not srt_text:
            QMessageBox.warning(self, "Missing Subtitle", "No translated subtitle is ready yet.")
            return
        target_lang = str(self.get_target_language_code() or "translated").lower()
        suggested_name = os.path.splitext(os.path.basename(self.video_path_edit.text().strip() or "subtitle"))[0] + f"_{target_lang}.srt"
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Translated Subtitle", suggested_name, "Subtitle Files (*.srt)")
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(srt_text)
        QMessageBox.information(self, "Saved", f"Translated subtitle exported to:\n\n{file_path}")

    def import_original_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Original Subtitle",
            self.srt_output_folder_edit.text().strip() or self.workspace_root,
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                srt_text = handle.read().strip()
        except Exception as exc:
            self.show_error("Import Failed", "Could not read the selected subtitle file.", str(exc))
            return

        if not srt_text:
            QMessageBox.warning(self, "Import Failed", "The selected subtitle file is empty.")
            return

        imported_segments = self.parse_srt_to_segments(srt_text)
        if not imported_segments:
            QMessageBox.warning(self, "Import Failed", "The selected file could not be parsed as a valid SRT subtitle.")
            return

        self.current_segments = imported_segments
        self.transcript_text.setText(srt_text)
        self.last_original_srt_path = file_path
        self.persist_transcription_project_data(imported_segments, srt_path=file_path)
        state = self.ensure_current_project()
        if state:
            state.set_setting("transcription_signature", "")
            self.project_service.save_project(state)
        self._sync_segment_models_from_current_segments()
        if hasattr(self, "timeline"):
            self.timeline.set_segments(self.current_segments)
            self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
        self.log(f"[Import] Original subtitle loaded: {file_path} ({len(imported_segments)} segments)")
        QMessageBox.information(self, "Import Success", f"Loaded {len(imported_segments)} segments from original subtitle.")
        self.refresh_ui_state()

    def import_translated_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Translated Subtitle",
            self.srt_output_folder_edit.text().strip() or self.workspace_root,
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                srt_text = handle.read().strip()
        except Exception as exc:
            self.show_error("Import Failed", "Could not read the selected subtitle file.", str(exc))
            return

        if not srt_text:
            QMessageBox.warning(self, "Import Failed", "The selected subtitle file is empty.")
            return

        imported_segments = self.parse_srt_to_segments(srt_text)
        if not imported_segments:
            QMessageBox.warning(self, "Import Failed", "The selected file could not be parsed as a valid SRT subtitle.")
            return

        base_segments = self.current_segments or self.current_translated_segments
        if self.keep_timeline_cb.isChecked() and base_segments and len(base_segments) == len(imported_segments):
            merged_segments = []
            for idx, base in enumerate(base_segments):
                merged = dict(imported_segments[idx])
                merged["start"] = float(base.get("start", 0.0))
                merged["end"] = float(base.get("end", 0.0))
                merged["words"] = list(base.get("words", []))
                if "manual_highlights" in imported_segments[idx]:
                    merged["manual_highlights"] = imported_segments[idx]["manual_highlights"]
                elif base.get("manual_highlights"):
                    merged["manual_highlights"] = list(base.get("manual_highlights", []))
                merged_segments.append(merged)
            imported_segments = merged_segments
            srt_text = self.format_to_srt(imported_segments)

        self.translated_text.setText(srt_text)
        self.apply_edited_translation(show_message=False, force_apply=True)
        self.last_translated_srt_path = file_path
        self.processed_artifacts["srt_translated"] = file_path
        self.persist_translation_project_data(self.current_translated_segments, file_path)
        self.refresh_ui_state()
        QMessageBox.information(
            self,
            "Imported",
            "Translated subtitle loaded. You can now run Generate Voice / TTS.\n\n" + file_path,
        )

    def download_original_script(self):
        script_text = self.transcript_text.toPlainText().strip()
        if not script_text:
            QMessageBox.warning(self, "Missing Script", "No original script is ready yet.")
            return
        base_name = os.path.splitext(os.path.basename(self.video_path_edit.text().strip() or "original"))[0] + "_original"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Source Subtitle",
            base_name + ".srt",
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(script_text)
        QMessageBox.information(self, "Saved", f"Source subtitle exported to:\n\n{file_path}")

    def on_export_finished(self, output_path, error):
        self.preview_controller.on_export_finished(output_path, error)

    def on_quick_preview_ready(self, output_path, error):
        self.preview_controller.on_quick_preview_ready(output_path, error)

    def on_exact_frame_ready(self, output_path, error):
        self.preview_controller.on_exact_frame_ready(output_path, error)

    def show_frame_preview_dialog(self, image_path: str):
        show_frame_preview_dialog_impl(self, image_path, QPixmap, Qt)

    # -----------------------------
    # Subtitle source handling
    # -----------------------------
    def get_active_segments(self):
        base = self.current_translated_segments or self.current_segments or []
        if base and bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()):
            split = getattr(self, "_single_line_split_cache", None)
            if split is not None:
                return split
        return base

    def apply_segments_to_timeline(self):
        segs = self.get_active_segments()
        if segs:
            predict_speed_ratios(segs)
        self.timeline.set_segments(segs if segs else [])
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
        # Configure the Qt subtitle overlay before showing its drag target.
        # Otherwise it can briefly use the default size until the first drag.
        self.update_subtitle_preview_style()
        self._show_subtitle_drag_layer()
        self.sync_live_subtitle_preview()

    def _segments_from_editor_text(self, srt_text: str, base_segments):
        srt_text = (srt_text or "").strip()
        if not srt_text:
            return []

        if self.keep_timeline_cb.isChecked() and base_segments:
            edited_texts = self.extract_subtitle_text_entries(srt_text)
            if edited_texts and len(edited_texts) == len(base_segments):
                out = []
                for idx, base in enumerate(base_segments):
                    d = {
                        "start": float(base["start"]),
                        "end": float(base["end"]),
                        "text": edited_texts[idx],
                        "tts_text": str(base.get("tts_text", "") or ""),
                        "tts_group_id": base.get("tts_group_id", ""),
                        "tts_group_start": float(base.get("tts_group_start", base.get("start", 0.0)) or 0.0),
                        "tts_group_end": float(base.get("tts_group_end", base.get("end", 0.0)) or 0.0),
                        "words": list(base.get("words", [])),
                        "manual_highlights": list(base.get("manual_highlights", [])),
                    }
                    raw = base.get("_audio_end")
                    if raw is not None:
                        try:
                            d["_audio_end"] = float(raw)
                        except (TypeError, ValueError):
                            pass
                    out.append(d)
                return out

        parsed_segments = self.parse_srt_to_segments(srt_text)
        if base_segments and len(parsed_segments) == len(base_segments):
            for idx, segment in enumerate(parsed_segments):
                base = base_segments[idx]
                segment["words"] = list(base.get("words", []))
                segment["manual_highlights"] = list(base.get("manual_highlights", []))
                if base.get("tts_text"):
                    segment["tts_text"] = str(base.get("tts_text", "") or "")
                    segment["tts_group_id"] = base.get("tts_group_id", "")
                    segment["tts_group_start"] = float(base.get("tts_group_start", base.get("start", 0.0)) or 0.0)
                    segment["tts_group_end"] = float(base.get("tts_group_end", base.get("end", 0.0)) or 0.0)
        return parsed_segments

    def _write_live_preview_assets(self, segments):
        if not segments:
            self.live_preview_subtitle_path = ""
            self.live_preview_ass_path = ""
            self._live_preview_signature = None
            return "", ""

        preview_dir = self.get_project_temp_dir("preview")
        preview_srt_path = os.path.join(preview_dir, "live_preview_subtitle.srt")

        from subtitle_builder import generate_srt

        video_path = self.video_path_edit.text().strip()
        if (
            video_path
            and os.path.exists(video_path)
            and (
                not getattr(self.video_view, "video_source_width", 0)
                or not getattr(self.video_view, "video_source_height", 0)
            )
        ):
            self.refresh_video_dimensions(video_path)
        video_width, video_height = self._subtitle_render_dimensions()
        subtitle_style = self.get_subtitle_export_style(segments=segments)
        preview_signature = (
            video_path,
            video_width,
            video_height,
            repr(segments),
            repr(subtitle_style),
        )
        if (
            preview_signature == getattr(self, "_live_preview_signature", None)
            and self.live_preview_subtitle_path
            and os.path.exists(self.live_preview_subtitle_path)
            and self.live_preview_ass_path
            and os.path.exists(self.live_preview_ass_path)
        ):
            return self.live_preview_subtitle_path, self.live_preview_ass_path

        # Subtitle or content changed. We no longer revert the media source!
        # Because we'll disable burned-in subs in muxed previews, the rendered
        # background is already blank-subbed and can host our live overlay/mpv track comfortably.
        # This solves the user's complaint that 'it reverts to original'.

        generate_srt(segments, preview_srt_path)
        self.live_preview_subtitle_path = preview_srt_path
        self.live_preview_ass_path = srt_to_ass(
            preview_srt_path,
            video_width=video_width,
            video_height=video_height,
            alignment=subtitle_style.get("alignment", 2),
            margin_v=subtitle_style.get("margin_v", 30),
            font_name=subtitle_style.get("font_name", "Arial"),
            font_size=subtitle_style.get("font_size", 18),
            font_color=subtitle_style.get("font_color", "&H00FFFFFF"),
            background_box=subtitle_style.get("background_box", False),
            animation_style=subtitle_style.get("animation", "Static"),
            highlight_color=subtitle_style.get("highlight_color", "&H00FFFFFF"),
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
            word_timings=subtitle_style.get("word_timings", []),
            custom_position_enabled=subtitle_style.get("custom_position_enabled", False),
            custom_position_x=subtitle_style.get("custom_position_x", 50),
            custom_position_y=subtitle_style.get("custom_position_y", 86),
            single_line=subtitle_style.get("single_line", False),
            log_generation=False,
        )
        self._live_preview_signature = preview_signature
        self.processed_artifacts["subtitle_preview_srt"] = self.live_preview_subtitle_path
        self.processed_artifacts["subtitle_preview_ass"] = self.live_preview_ass_path
        return self.live_preview_subtitle_path, self.live_preview_ass_path

    def _resolve_live_preview_segments(self):
        single_line = bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked())
        if single_line and self.current_translated_segments:
            return self.get_active_segments(), "translated"

        translated_text = self.translated_text.toPlainText().strip()
        if translated_text and not translated_text.lower().startswith("translating with "):
            base_segments = self.current_translated_segments or self.current_segments
            translated_segments = self._segments_from_editor_text(translated_text, base_segments)
            if translated_segments:
                return translated_segments, "translated"

        transcript_text = self.transcript_text.toPlainText().strip()
        if transcript_text and not transcript_text.lower().startswith("transcribing..."):
            transcript_segments = self._segments_from_editor_text(transcript_text, self.current_segments)
            if transcript_segments:
                return transcript_segments, "transcript"

        return [], ""

    def _resolve_live_preview_subtitle_path(self):
        segments, editor_name = self._resolve_live_preview_segments()
        self.live_preview_segments = segments
        self.live_preview_editor_name = editor_name
        return self._write_live_preview_assets(segments)

    def _find_active_segment_index(self, position_ms: int, segments):
        position_seconds = max(0.0, float(position_ms) / 1000.0)
        for idx, seg in enumerate(segments or []):
            if not isinstance(seg, dict):
                continue
            try:
                start_s = float(seg.get("start", 0.0))
                end_s = float(seg.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if start_s <= position_seconds <= end_s:
                return idx
        return -1

    def _find_active_segment_indices(self, position_ms: int, segments) -> list[int]:
        """Return the indices of every segment whose [start, end] contains
        position_ms. Multiple entries are returned when segments overlap in
        time, so the live overlay can stack them on separate lines.
        """
        position_seconds = max(0.0, float(position_ms) / 1000.0)
        result: list[int] = []
        for idx, seg in enumerate(segments or []):
            if not isinstance(seg, dict):
                continue
            try:
                start_s = float(seg.get("start", 0.0))
                end_s = float(seg.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if start_s <= position_seconds <= end_s:
                result.append(idx)
        return result

    def _set_editor_highlight(self, editor, active_index: int):
        if not editor:
            return

        selections = []
        text = editor.toPlainText()
        block_pattern = re.compile(
            r"(^|\n\n)(\d+\n\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}\n.*?)(?=\n\n\d+\n|\Z)",
            re.DOTALL,
        )
        chunks = [(match.start(2), match.end(2)) for match in block_pattern.finditer(text)]

        if 0 <= active_index < len(chunks):
            start, end = chunks[active_index]
            selection = QTextEdit.ExtraSelection()
            selection.cursor = editor.textCursor()
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.format.setBackground(QColor("#183248"))
            selection.format.setForeground(QColor("#EAF6FF"))
            selections.append(selection)
            temp_cursor = editor.textCursor()
            temp_cursor.setPosition(start)
            editor.setTextCursor(temp_cursor)
            editor.ensureCursorVisible()

        editor.setExtraSelections(selections)

    def update_playback_subtitle_highlight(self, position_ms: int):
        try:
            segments = self.live_preview_segments or self.get_active_segments()
            active_index = self._find_active_segment_index(position_ms, segments)
            self.timeline.set_active_segment_index(active_index)
            inspector_visible = self._is_subtitle_inspector_details_visible()
            if inspector_visible and active_index >= 0 and active_index != getattr(self, "_selected_segment_index", -1):
                self.set_selected_segment_index(active_index, sync_ui=True)

            if inspector_visible:
                target_editor = None
                if self.live_preview_editor_name == "translated":
                    target_editor = self.translated_text
                elif self.live_preview_editor_name == "transcript":
                    target_editor = self.transcript_text
                elif self.current_translated_segments:
                    target_editor = self.translated_text
                elif self.current_segments:
                    target_editor = self.transcript_text

                self._set_segment_editor_highlight(active_index)
                self._set_editor_highlight(self.translated_text, active_index if target_editor is self.translated_text else -1)
                self._set_editor_highlight(self.transcript_text, active_index if target_editor is self.transcript_text else -1)

            # Update live overlay text for faster feedback
            if hasattr(self, "video_view"):
                if getattr(self, "_preview_video_has_burned_subtitles", False):
                    self.video_view.subtitle_item.set_text("")
                    self.video_view.subtitle_item.hide()
                else:
                    active_indices = self._find_active_segment_indices(position_ms, segments)
                    if active_indices:
                        active_lines = [segments[i].get("text", "") for i in active_indices]
                        if len(active_lines) == 1:
                            self.video_view.subtitle_item.set_text(active_lines[0])
                        else:
                            self.video_view.subtitle_item.set_lines(active_lines)
                        self._set_live_subtitle_effects(segments[active_indices[0]], position_ms)
                        self.video_view.subtitle_item.show()
                    else:
                        # Keep a real subtitle visible while paused so it
                        # remains a draggable editing layer after subtitle
                        # generation, even if the playhead is between cues.
                        if not self.media_player.is_playing():
                            self._show_subtitle_drag_layer(segments)
                        else:
                             self.video_view.subtitle_item.set_text("")
                             self.video_view.subtitle_item.hide()
                self.video_view.reposition_subtitle()
        except Exception as exc:
            self.log(f"[Preview] subtitle highlight skipped: {exc}")

    def _show_subtitle_drag_layer(self, segments=None):
        """Show a representative live subtitle as the paused drag target."""
        if not hasattr(self, "video_view") or getattr(self, "_preview_video_has_burned_subtitles", False):
            return
        items = list(segments or self.live_preview_segments or self.get_active_segments() or [])
        if not items:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(items)):
            index = 0
        text = str(items[index].get("text", "") or "").strip()
        if not text:
            return
        self.video_view.subtitle_item.set_text(text)
        self._set_live_subtitle_effects(items[index])
        self.video_view.subtitle_item.show()
        self.video_view.reposition_subtitle()

    def sync_live_subtitle_preview(self):
        """Use the fast editable Qt subtitle layer for live preview."""
        if not hasattr(self, "media_player"):
            return
        self.media_player.clear_subtitle()
        if hasattr(self, "video_view"):
            self.video_view.subtitle_item.set_text_rendering(True)
        if getattr(self, "_preview_video_has_burned_subtitles", False):
            if hasattr(self, "video_view"):
                self.video_view.subtitle_item.set_text("")
                self.video_view.subtitle_item.hide()
            return
        position = 0
        try:
            position = int(self.media_player.position())
        except Exception:
            pass
        self.update_playback_subtitle_highlight(position)

    def refresh_ui_state(self):
        """Basic enable/disable rules to guide user flow."""
        v_ok = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        a_ok = bool(self.audio_source_edit.text().strip()) and os.path.exists(self.audio_source_edit.text().strip())
        has_translated_text = bool(self.translated_text.toPlainText().strip())
        selected_audio_path = self.resolve_selected_audio_path()
        has_voice_audio = bool(selected_audio_path and os.path.exists(selected_audio_path))
        has_subtitle_track = bool(self.last_translated_srt_path and os.path.exists(self.last_translated_srt_path))
        mode = self.get_output_mode_key()
        steps = getattr(getattr(self, "current_project_state", None), "steps", {}) or {}
        voice_running = steps.get("generate_tts") == "running" or steps.get("mix_audio") == "running"
        can_export = False
        if mode == "subtitle":
            can_export = v_ok and has_subtitle_track
        elif mode == "voice":
            can_export = v_ok and has_voice_audio
        else:
            can_export = (
                v_ok
                and has_voice_audio
                and has_subtitle_track
            )

        self.extract_btn.setEnabled(v_ok)
        self.vocal_sep_btn.setEnabled(a_ok)
        if hasattr(self, "voice_timing_sync_combo") and hasattr(self, "voice_speed_spin"):
            mode = self.voice_timing_sync_combo.currentText().strip().lower()
            self.voice_speed_spin.setEnabled(mode != "off")
        self.transcribe_btn.setEnabled(a_ok)
        self.translate_btn.setEnabled(bool(self.transcript_text.toPlainText().strip()))
        self.apply_translated_btn.setEnabled(has_translated_text)
        if hasattr(self, "rewrite_translation_btn"):
            self.rewrite_translation_btn.setEnabled(bool(self.transcript_text.toPlainText().strip()) and has_translated_text)
        if hasattr(self, "rewrite_selected_segment_btn"):
            has_selected_segment = 0 <= int(getattr(self, "_selected_segment_index", -1)) < len(self.current_translated_segments or [])
            self.rewrite_selected_segment_btn.setEnabled(
                bool(self.transcript_text.toPlainText().strip()) and has_translated_text and has_selected_segment
            )
        generated_mode = not self.using_existing_audio_source()
        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(has_translated_text and generated_mode and mode in ("voice", "both"))
        preview_enabled = v_ok and not voice_running
        if hasattr(self, "quick_preview_btn"):
            self.quick_preview_btn.setEnabled(preview_enabled)
        if hasattr(self, "styled_preview_btn"):
            self.styled_preview_btn.setEnabled(preview_enabled)
        if hasattr(self, "preview_btn"):
            self.preview_btn.setVisible(True)
            self.preview_btn.setEnabled(preview_enabled and not getattr(self, "_styled_preview_running", False))
        if hasattr(self, "video_filter_apply_btn"):
            has_active_filters = self.has_active_video_filters() if hasattr(self, "has_active_video_filters") else False
            self.video_filter_apply_btn.setVisible(True)
            self.video_filter_apply_btn.setEnabled(
                self.is_filter_workflow_active()
                and v_ok
                and has_active_filters
                and not getattr(self, "_styled_preview_running", False)
            )
            self.video_filter_apply_btn.setText("Applying..." if getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False) else "Apply Filter")
        is_rendering_filter_preview = bool(getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False))
        if hasattr(self, "video_filter_render_status_label"):
            status_text = ""
            if not self.is_filter_workflow_active():
                status_text = ""
            elif getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False):
                status_text = "Rendering filtered preview video..."
            elif getattr(self, "_video_filter_preview_dirty", False):
                status_text = "Filter changes pending. Click Apply Filter to render motion preview."
            elif self.has_active_video_filters() if hasattr(self, "has_active_video_filters") else False:
                status_text = "Filtered preview video is ready."
            self.video_filter_render_status_label.setText(status_text)
            self.video_filter_render_status_label.setVisible(bool(status_text))
        if hasattr(self, "video_filter_render_progress"):
            self.video_filter_render_progress.setVisible(self.is_filter_workflow_active() and is_rendering_filter_preview)
        if hasattr(self, "reset_framing_btn"):
            scale_mode = self.get_output_scale_mode_key() if hasattr(self, "get_output_scale_mode_key") else "fit"
            focus_x, focus_y = self.get_output_fill_focus() if hasattr(self, "get_output_fill_focus") else (0.5, 0.5)
            framing_dirty = abs(float(focus_x) - 0.5) > 0.001 or abs(float(focus_y) - 0.5) > 0.001
            self.reset_framing_btn.setVisible(True)
            self.reset_framing_btn.setEnabled(v_ok and scale_mode == "fill" and framing_dirty)
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(v_ok and not voice_running and not getattr(self, "_styled_preview_running", False))
        if hasattr(self, "stop_btn"):
            self.stop_btn.setEnabled(v_ok and not voice_running)
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(can_export)
        # Overlay tracks are only meaningful once the generated output is
        # ready. Keep their controls disabled before that point so users
        # cannot create layers against an incomplete video workflow.
        self._optional_layer_controls_ready = bool(can_export and not voice_running)
        for button_name in ("blur_add_btn", "add_logo_btn", "add_mask_btn", "add_text_btn", "add_layer_btn"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(self._optional_layer_controls_ready)
        if hasattr(self, "blur_add_btn"):
            self.blur_add_btn.setEnabled(
                self._optional_layer_controls_ready
                and not bool(getattr(self, "_filter_thumbnail_visible", False))
            )
        if hasattr(self, "ocr_region_btn"):
            self.ocr_region_btn.setEnabled(v_ok)
        self._sync_blur_controls()
        if hasattr(self, "free_voice_combo"):
            self.free_voice_combo.setEnabled(
                generated_mode
                and mode in ("voice", "both")
            )
        if hasattr(self, "voice_engine_combo"):
            self.voice_engine_combo.setEnabled(generated_mode and mode in ("voice", "both"))
        if hasattr(self, "premium_voice_combo"):
            self.premium_voice_combo.setEnabled(False)
        if hasattr(self, "bg_music_edit"):
            self.bg_music_edit.setEnabled(generated_mode and mode in ("voice", "both"))
        if hasattr(self, "mixed_audio_edit"):
            self.mixed_audio_edit.setEnabled(mode in ("voice", "both") and bool(hasattr(self, "use_existing_audio_radio") and self.use_existing_audio_radio.isChecked()))
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setVisible(mode in ("voice", "both"))
            self.preview_voice_btn.setEnabled(bool(self.voice_catalog_entries_all))
        has_timeline_segments = bool(self.get_active_segments())
        selected_overlay_is_splittable = False
        selected_layer_id = str(getattr(getattr(self, "timeline", None), "_selected_layer_id", "") or "")
        if selected_layer_id and getattr(getattr(self, "timeline", None), "_timeline", None):
            for track in self.timeline._timeline.tracks:
                for layer in track.layers:
                    if layer.id != selected_layer_id:
                        continue
                    layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                    selected_overlay_is_splittable = layer_type in {"blur", "mask", "text"} or (
                        layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                    )
                    break
                if selected_overlay_is_splittable:
                    break
        if hasattr(self, "timeline_split_btn"):
            self.timeline_split_btn.setEnabled(has_timeline_segments or selected_overlay_is_splittable)
        if hasattr(self, "timeline_delete_btn"):
            self.timeline_delete_btn.setEnabled(has_timeline_segments)

        self._update_generate_button_menu(has_data=has_translated_text or has_timeline_segments)
        self.update_workflow_stage_badges()

        if hasattr(self, "clean_project_action"):
            self.clean_project_action.setEnabled(self._has_cleanable_project_data())
        self.run_all_btn.setEnabled(v_ok and not self._pipeline_active)
        self.preview_frame_btn.setEnabled(v_ok and bool(self.get_active_segments()))
        self.preview_5s_btn.setEnabled(v_ok)
        if hasattr(self, "preview_5s_action"):
            self.preview_5s_action.setEnabled(v_ok)
        self.export_btn.setEnabled(can_export)
        if hasattr(self, "download_subtitle_action"):
            self.download_subtitle_action.setEnabled(bool(self.translated_text.toPlainText().strip()))
        if hasattr(self, "download_original_action"):
            self.download_original_action.setEnabled(bool(self.transcript_text.toPlainText().strip()))
        if hasattr(self, "tabs"):
            self.tabs.setTabEnabled(1, v_ok)
            self.tabs.setTabEnabled(2, v_ok and mode in ("voice", "both"))
        self.update_workflow_availability()
        self.update_guidance_panel()
        self._update_ocr_overlay()

    def _update_generate_button_menu(self, has_data: bool):
        if not hasattr(self, "run_all_btn"):
            return
        btn = self.run_all_btn
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        if btn.menu() is None:
            menu = QMenu(btn)
            menu.setObjectName("generateMenu")
            # The parent menu renders the Step-by-Step / Full Pipeline
            # submenu titles, so it needs its own width—not just the child
            # popup menus.
            menu.setMinimumWidth(220)
            step_menu = menu.addMenu("Step-by-Step")
            step_menu.setObjectName("generateStepMenu")
            step_menu.setMinimumWidth(220)
            transcript_action = QAction("Run to Transcript", step_menu)
            transcript_action.triggered.connect(lambda: self.run_pipeline_to_stage("transcript"))
            translate_menu = step_menu.addMenu("Run to Translate")
            translate_menu.setObjectName("generateStepMenu")
            translate_menu.setMinimumWidth(220)
            translate_action = QAction("Auto Translate", translate_menu)
            translate_action.triggered.connect(lambda: self.run_pipeline_to_stage("translate"))
            import_translation_action = QAction("Import Translated File…", translate_menu)
            import_translation_action.triggered.connect(self.import_translated_srt)
            translate_menu.addActions([translate_action, import_translation_action])
            tts_action = QAction("Run to Generate Voice / TTS", step_menu)
            tts_action.triggered.connect(lambda: self.run_pipeline_to_stage("tts"))
            step_menu.insertAction(translate_menu.menuAction(), transcript_action)
            step_menu.addAction(tts_action)
            full_menu = menu.addMenu("Full Pipeline")
            full_menu.setObjectName("generateStepMenu")
            full_menu.setMinimumWidth(220)
            full_action = QAction("Run full pipeline", full_menu)
            full_action.triggered.connect(self.run_all_pipeline)
            full_menu.addAction(full_action)
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.InstantPopup)
            btn.setText("Generate")
            self._generate_transcript_action = transcript_action
            self._generate_translate_action = translate_action
            self._generate_import_translated_srt_action = import_translation_action
            self._generate_tts_action = tts_action
        self.update_workflow_stage_badges()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                local_path = url.toLocalFile()
                if local_path and os.path.splitext(local_path)[1].lower() in {".mp4", ".mkv", ".avi", ".mov"}:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            event.ignore()
            return
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if local_path and os.path.splitext(local_path)[1].lower() in {".mp4", ".mkv", ".avi", ".mov"}:
                self.ensure_media_backend_ready()
                self.video_path_edit.setText(local_path)
                self.media_player.setSource(QUrl.fromLocalFile(local_path))
                self.refresh_video_dimensions(local_path)
                self.play_btn.setText("Play")
                self.timeline.set_segments([])
                self.timeline.set_playing(False)
                self.current_segments = []
                self.current_translated_segments = []
                self.current_segment_models = []
                self.current_translated_segment_models = []
                self.current_project_state = self.ensure_current_project()
                self._allow_post_pipeline_preview_assets = False
                self.load_project_context(self.current_project_state)
                self.media_player.pause()
                self.media_player.setPosition(0)
                self.refresh_ui_state()
                self.sync_live_subtitle_preview()
                event.acceptProposedAction()
                return
        event.ignore()

    def run_extraction(self):
        v_path = self.video_path_edit.text()
        if not v_path: return
        
        target_dir = self.audio_folder_edit.text()
        file_basename = os.path.splitext(os.path.basename(v_path))[0]
        a_path = os.path.join(target_dir, file_basename + ".wav")
        
        print(f"[Extraction] start: video={v_path} audio={a_path}")
        self.progress_bar.setValue(10)
        self.update_project_step("extract_audio", "running")
        self.extraction_thread = ExtractionWorker(v_path, a_path)
        self.extraction_thread.finished.connect(self.on_extraction_finished)
        self.extraction_thread.start()

    def on_extraction_finished(self, success, path):
        print(f"[Extraction] finished: success={success} path={path}")
        self.progress_bar.setValue(30)
        self.extract_btn.setEnabled(True)
        if success:
            self.last_extracted_audio = path
            self.audio_source_edit.setText(path)
            self.processed_artifacts["audio_extracted"] = path
            self.update_project_artifact("extracted_audio", path)
            self.update_project_step("extract_audio", "done")
            self.log(f"[Audio] Original audio extracted: {path}")
            self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        else:
            self.update_project_step("extract_audio", "failed")
            self.show_error("Error", "Extraction failed.", str(path))
            self._pipeline_fail("Extraction failed.")
            return

        self.refresh_ui_state()
        self._pipeline_advance("extraction")

    def run_vocal_separation(self):
        audio_src = self.audio_source_edit.text()
        if not audio_src or not os.path.exists(audio_src):
            QMessageBox.warning(self, "Error", "Please extract audio or select a source first!")
            return
        
        target_dir = self.audio_folder_edit.text()
        self.progress_bar.setValue(35)
        self.vocal_sep_btn.setEnabled(False)
        self.vocal_sep_btn.setText("Separating... (AI Processing)")
        self.update_project_step("separate_audio", "running")
        
        self.vocal_thread = VocalSeparationWorker(audio_src, target_dir)
        self.vocal_thread.finished.connect(self.on_vocal_separation_finished)
        self.vocal_thread.start()

    def on_vocal_separation_finished(self, vocal, music, error):
        self.vocal_sep_btn.setEnabled(True)
        self.vocal_sep_btn.setText("Separate Voice and Background")
        self.progress_bar.setValue(50)
        
        if error:
            self.update_project_step("separate_audio", "failed")
            err_lower = error.lower()
            missing_demucs = (
                "no module named" in err_lower and "demucs" in err_lower
            ) or (
                "demucs is not installed" in err_lower
            ) or (
                "requires the 'demucs' library" in err_lower
            )
            if missing_demucs:
                QMessageBox.warning(
                    self,
                    "Dependency Missing",
                    "Vocal Separation requires the 'demucs' library.\n\n"
                    "Please run (using the same Python you run this app with):\n"
                    "python -m pip install demucs\n\n"
                    f"Details:\n{error}",
                )
            else:
                QMessageBox.critical(self, "Error", f"Separation failed:\n\n{error}")
            self.log(error)
            self.refresh_ui_state()
            return
        
        if vocal and os.path.exists(vocal):
            self.audio_source_edit.setText(vocal)
            self.last_extracted_audio = vocal
            self.last_vocals_path = vocal
            self.last_music_path = music
            self.processed_artifacts["vocals"] = vocal
            self.update_project_artifact("vocals", vocal)
            if music:
                self.processed_artifacts["music"] = music
                self.update_project_artifact("music", music)
            self.update_project_step("separate_audio", "done")
            QMessageBox.information(self, "Success", 
                f"Audio stems separated!\n\nVocals: {os.path.basename(vocal)}\nBackground: {os.path.basename(music)}\n\nVocals are now selected for transcription.")
            self._pipeline_advance("separation")
        else:
            self.update_project_step("separate_audio", "failed")
            self._pipeline_fail("Separation did not produce output.")
        self.refresh_ui_state()

    def run_transcription(self):
        is_ocr = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
        if not is_ocr and not self.ensure_required_resources("Transcription", include_whisper=True):
            return
        self.subtitle_controller.run_transcription()

    def on_transcription_finished(self, segments, error=""):
        self.subtitle_controller.on_transcription_finished(segments, error)

    def run_translation(self):
        self.subtitle_controller.run_translation()

    def on_translation_finished(self, translated_srt, error):
        self.subtitle_controller.on_translation_finished(translated_srt, error)

    def run_rewrite_translation(self):
        self.subtitle_controller.run_rewrite_translation()

    def run_rewrite_selected_segment(self):
        self.subtitle_controller.run_rewrite_selected_segment()

    def on_rewrite_translation_finished(self, translated_srt, error):
        self.subtitle_controller.on_rewrite_translation_finished(translated_srt, error)

    def on_rewrite_selected_segment_finished(self, translated_srt, error):
        self.subtitle_controller.on_rewrite_selected_segment_finished(translated_srt, error)

    def _close_export_progress_dialog(self):
        try:
            dlg = getattr(self, "export_progress_dialog", None)
            if dlg is not None:
                self._unregister_progress_dialog(dlg)
                dlg.hide()
                dlg.deleteLater()
        finally:
            self.export_progress_dialog = None

    def _ensure_export_progress_dialog(self):
        dlg = getattr(self, "export_progress_dialog", None)
        if dlg is not None:
            return dlg
        dlg = BackgroundableProgressDialog("Preparing final export...", "Hide", 0, 100, self)
        dlg.setWindowTitle("Exporting Video")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoReset(False)
        dlg.setAutoClose(False)
        dlg.setMinimumWidth(520)
        dlg.setValue(0)
        dlg.setLabelText("Exporting final video...\n\nWaiting to start...")
        dlg.setStyleSheet(
            "QProgressDialog { background-color: #101826; color: #e6eef9; }"
            "QLabel { color: #e6eef9; background: transparent; }"
            "QPushButton { background-color: #24364f; color: #ffffff; border: 1px solid #335171; border-radius: 10px; padding: 8px 14px; font-weight: 700; }"
            "QPushButton:hover { background-color: #2d4665; border-color: #4575a8; }"
            "QProgressBar { border: 1px solid #2a3a50; border-radius: 10px; text-align: center; background-color: #111927; color: white; min-height: 16px; }"
            "QProgressBar::chunk { background-color: #4ed0b3; border-radius: 10px; }"
        )
        try:
            dlg.setCancelButtonText("Run in background")
            dlg.canceled.connect(dlg.hide)
        except Exception:
            pass
        self.export_progress_dialog = dlg
        self._register_progress_dialog(dlg)
        dlg.show()
        return dlg

    def on_export_progress(self, percent: int, message: str):
        dlg = self._ensure_export_progress_dialog()
        if dlg is None:
            return
        message_text = str(message or "Exporting final video...").strip() or "Exporting final video..."
        history = list(getattr(self, "_export_progress_messages", []) or [])
        if not history or history[-1] != message_text:
            history.append(message_text)
        self._export_progress_messages = history[-4:]
        dlg.setLabelText("Exporting final video...\n\n" + "\n".join(self._export_progress_messages))
        if percent is None or int(percent) < 0:
            dlg.setRange(0, 0)
        else:
            if dlg.maximum() == 0:
                dlg.setRange(0, 100)
            value = max(0, min(100, int(percent)))
            dlg.setValue(value)
            try:
                self.progress_bar.setValue(value)
            except Exception:
                pass
        dlg.show()

    def get_whisper_model_name(self) -> str:
        return "medium"

    def get_whisper_model_path(self) -> str:
        return os.path.join(self.workspace_root, "models", "ggml-medium.bin")

    def open_model_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.setModal(True)
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #0f1724;
            }
            QLabel {
                color: #d7e3f4;
                background: transparent;
            }
            QLabel#statusHeadline {
                color: #f8fbff;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#helperLabel {
                color: #9fb3ca;
                font-size: 12px;
            }
            QComboBox, QLineEdit {
                background-color: #132033;
                color: #f8fbff;
                border: 1px solid #2f4868;
                border-radius: 10px;
                padding: 8px 10px;
                min-height: 18px;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                background-color: #132033;
                color: #f8fbff;
                border: 1px solid #2f4868;
                selection-background-color: #24486c;
                selection-color: #ffffff;
            }
            QPushButton {
                background-color: #22344d;
                color: #f8fbff;
                border: 1px solid #34506f;
                border-radius: 10px;
                padding: 8px 16px;
                font-weight: 600;
                min-width: 84px;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
            QPushButton:pressed {
                background-color: #1d2d42;
            }
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setSizeConstraint(QLayout.SetFixedSize)

        remote_mode = is_remote_profile()
        cpu_mode = os.getenv("CAPCAP_DEVICE", "cuda").strip().lower() == "cpu"
        LocalPolisherProvider = self._local_polisher_provider_cls() if not remote_mode else None
        # Transcription Engine Section
        engine_title = QLabel("Subtitle source")
        engine_title.setObjectName("statusHeadline")
        layout.addWidget(engine_title)

        engine_combo = QComboBox(dialog)
        if not cpu_mode:
            engine_combo.addItem("Audio (Whisper) - Quality", "whisper")
        engine_combo.addItem("Audio (SenseVoice) - Speed", "sensevoice")
        engine_combo.addItem("Video (OCR)", "ocr")
        current_engine = (os.getenv("TRANSCRIPTION_ENGINE") or _default_asr_engine()).strip().lower()
        idx = engine_combo.findData(current_engine)
        if idx >= 0:
            engine_combo.setCurrentIndex(idx)
        layout.addWidget(engine_combo)

        # OCR Region combo (only visible when OCR selected)
        region_label = QLabel("Subtitle position:")
        region_label.setVisible(current_engine == "ocr")
        region_combo = QComboBox(dialog)
        region_combo.addItem("Bottom (default)", "bottom")
        region_combo.addItem("Top", "top")
        region_combo.addItem("Full frame", "full")
        current_region = (os.getenv("OCR_SUBTITLE_REGION") or "bottom").strip().lower()
        idx = region_combo.findData(current_region)
        if idx >= 0:
            region_combo.setCurrentIndex(idx)
        region_combo.setVisible(current_engine == "ocr")
        layout.addWidget(region_label)
        layout.addWidget(region_combo)

        # Whisper Section
        is_whisper = current_engine == "whisper"
        whisper_title = QLabel("Whisper model")
        whisper_title.setObjectName("statusHeadline")
        whisper_title.setVisible(is_whisper)
        layout.addWidget(whisper_title)
        
        whisper_combo = QComboBox(dialog)
        whisper_combo.addItem("Medium (Accurate)", "medium")
        whisper_combo.setCurrentIndex(0)
        whisper_combo.setVisible(is_whisper)
        layout.addWidget(whisper_combo)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #2f4868;")
        layout.addWidget(divider)

        remote_title = QLabel("Remote API")
        remote_title.setObjectName("statusHeadline")
        remote_title.setVisible(remote_mode)
        layout.addWidget(remote_title)

        remote_url_layout = QVBoxLayout()
        remote_url_label = QLabel("PC API URL:")
        remote_url_edit = QLineEdit(dialog)
        remote_url_edit.setText(os.getenv("CAPCAP_REMOTE_API_URL", "http://127.0.0.1:8765"))
        remote_url_layout.addWidget(remote_url_label)
        remote_url_layout.addWidget(remote_url_edit)
        remote_url_label.setVisible(remote_mode)
        remote_url_edit.setVisible(remote_mode)
        layout.addLayout(remote_url_layout)

        remote_token_layout = QVBoxLayout()
        remote_token_label = QLabel("API Token (optional):")
        remote_token_edit = QLineEdit(dialog)
        remote_token_edit.setEchoMode(QLineEdit.Password)
        remote_token_edit.setText(os.getenv("CAPCAP_REMOTE_API_TOKEN", ""))
        remote_token_layout.addWidget(remote_token_label)
        remote_token_layout.addWidget(remote_token_edit)
        remote_token_label.setVisible(remote_mode)
        remote_token_edit.setVisible(remote_mode)
        layout.addLayout(remote_token_layout)

        remote_actions_layout = QHBoxLayout()
        test_remote_btn = QPushButton("Test Connection", dialog)
        test_remote_btn.setVisible(remote_mode)
        remote_actions_layout.addWidget(test_remote_btn)
        remote_actions_layout.addStretch()
        layout.addLayout(remote_actions_layout)

        remote_hint_label = QLabel(
            "Remote mode keeps Whisper and AI translation on your PC server. "
            "This laptop build only sends extracted audio and subtitle segments over HTTP."
        )
        remote_hint_label.setObjectName("helperLabel")
        remote_hint_label.setWordWrap(True)
        remote_hint_label.setVisible(remote_mode)
        layout.addWidget(remote_hint_label)

        remote_divider = QFrame()
        remote_divider.setFrameShape(QFrame.HLine)
        remote_divider.setStyleSheet("color: #2f4868;")
        remote_divider.setVisible(remote_mode)
        layout.addWidget(remote_divider)

        # AI Translation Section
        ai_title = QLabel("AI Translation")
        ai_title.setObjectName("statusHeadline")
        ai_title.setVisible(not remote_mode)
        layout.addWidget(ai_title)

        provider_layout = QHBoxLayout()
        provider_label = QLabel("Translator Provider:")
        provider_label.setVisible(not remote_mode)
        provider_layout.addWidget(provider_label)
        provider_combo = QComboBox(dialog)
        provider_combo.addItem("Google Translate (free, no key)", "google")
        provider_combo.addItem("Gemini (Google AI Studio)", "gemini")
        provider_combo.addItem("OpenAI", "openai")
        provider_combo.addItem("Ollama (Local)", "ollama")
        if not cpu_mode:
            provider_combo.addItem("Local (GGUF)", "local")
        current_provider = (os.getenv("OPENAI_PROVIDER") or "google").strip().lower()
        if current_provider not in {"google", "gemini", "openai", "ollama", "local"}:
            current_provider = "local"
        if cpu_mode and current_provider == "local":
            current_provider = "google"
        idx = provider_combo.findData(current_provider)
        if idx >= 0:
            provider_combo.setCurrentIndex(idx)
        provider_combo.setVisible(not remote_mode)
        provider_layout.addWidget(provider_combo, 1)
        layout.addLayout(provider_layout)

        local_model_layout = QVBoxLayout()
        local_model_label = QLabel("Local AI Model:")
        local_model_combo = QComboBox(dialog)
        local_model_combo.addItem("Normal Quality AI Model (Hy-MT2)", "normal")
        local_model_combo.addItem("High Quality AI Model (Gemma 4)", "high")
        current_local_model_tier = (os.getenv("LOCAL_TRANSLATOR_MODEL_TIER") or "").strip().lower()
        current_local_model_path = (os.getenv("LOCAL_TRANSLATOR_MODEL_PATH") or "").strip().lower()
        if current_local_model_tier not in {"normal", "high"}:
            if current_local_model_path.endswith("gemma-4-e4b-it-q4_k_m.gguf"):
                current_local_model_tier = "high"
            else:
                current_local_model_tier = "normal"
        idx = local_model_combo.findData(current_local_model_tier)
        if idx >= 0:
            local_model_combo.setCurrentIndex(idx)
        local_model_layout.addWidget(local_model_label)
        local_model_layout.addWidget(local_model_combo)
        local_model_label.setVisible(not remote_mode and not cpu_mode)
        local_model_combo.setVisible(not remote_mode and not cpu_mode)
        layout.addLayout(local_model_layout)

        key_section_widget = QWidget(dialog)
        key_layout = QVBoxLayout(key_section_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_label = QLabel("API Key:")
        key_edit = QLineEdit(dialog)
        key_edit.setEchoMode(QLineEdit.Password)
        key_edit.setText(os.getenv("OPENAI_API_KEY", ""))
        key_layout.addWidget(key_label)
        key_layout.addWidget(key_edit)
        key_section_widget.setVisible(not remote_mode)
        layout.addWidget(key_section_widget)

        model_layout = QVBoxLayout()
        model_label = QLabel("AI Model:")
        model_edit = QLineEdit(dialog)
        model_edit.setText(os.getenv("OPENAI_MODEL", os.getenv("LOCAL_TRANSLATOR_MODEL_PATH", "models/ai/Hy-MT2-1.8B-Q4_K_M.gguf")))
        model_layout.addWidget(model_label)
        model_layout.addWidget(model_edit)
        model_label.setVisible(not remote_mode)
        model_edit.setVisible(not remote_mode)
        layout.addLayout(model_layout)

        base_url_layout = QVBoxLayout()
        base_url_label = QLabel("API URL:")
        base_url_edit = QLineEdit(dialog)
        base_url_edit.setText(os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"))
        base_url_layout.addWidget(base_url_label)
        base_url_layout.addWidget(base_url_edit)
        base_url_label.setVisible(not remote_mode)
        base_url_edit.setVisible(not remote_mode)
        layout.addLayout(base_url_layout)

        provider_hint = QLabel("Get an API key at https://aistudio.google.com/apikey")
        provider_hint.setObjectName("helperLabel")
        provider_hint.setWordWrap(True)
        provider_hint.setVisible(not remote_mode)
        layout.addWidget(provider_hint)

        style_label = QLabel("Translation style (optional):")
        style_label.setObjectName("helperLabel")
        style_edit = QLineEdit(dialog)
        style_edit.setPlaceholderText("e.g. natural, funny, more formal")
        style_edit.setText(os.getenv("TRANSLATOR_STYLE", ""))
        style_label.setVisible(not remote_mode)
        style_edit.setVisible(not remote_mode)
        layout.addWidget(style_label)
        layout.addWidget(style_edit)

        local_model_note = QLabel(
            "Normal Quality uses Hy-MT2 and the current lightweight prompt. "
            "High Quality uses Gemma 4 and the older richer prompt. "
            "High Quality needs a better GPU or it will run slower on CPU."
        )
        local_model_note.setObjectName("helperLabel")
        local_model_note.setWordWrap(True)
        local_model_note.setVisible(not remote_mode and not cpu_mode)
        layout.addWidget(local_model_note)

        def _toggle_visible(widget, visible):
            widget.setVisible(visible)

        def update_provider_fields():
            p = provider_combo.currentData()
            is_ai = p != "google"
            is_gemini = p == "gemini"
            is_openai = p == "openai"
            is_local = p == "local"
            is_google = p == "google"
            _toggle_visible(style_label, not remote_mode and is_ai)
            _toggle_visible(style_edit, not remote_mode and is_ai)
            _toggle_visible(key_section_widget, is_gemini or is_openai)
            _toggle_visible(local_model_label, not remote_mode and is_local and not cpu_mode)
            _toggle_visible(local_model_combo, not remote_mode and is_local and not cpu_mode)
            _toggle_visible(local_model_note, not remote_mode and is_local and not cpu_mode)
            _toggle_visible(base_url_label, not remote_mode and not is_local and is_ai)
            _toggle_visible(base_url_edit, not remote_mode and not is_local and is_ai)
            _toggle_visible(test_btn, not remote_mode and not is_local and is_ai)
            _toggle_visible(test_status, not remote_mode and not is_local and is_ai)
            _toggle_visible(model_label, not remote_mode and is_ai)
            _toggle_visible(model_edit, not remote_mode and is_ai)
            if is_google:
                provider_hint.setText("Free Google web translate, no API key needed. Lower quality than AI translation.")
                key_edit.clear()
                model_edit.clear()
                base_url_edit.clear()
            elif is_gemini:
                model_label.setText("AI Model:")
                if not base_url_edit.text().strip() or base_url_edit.text().strip() == "https://api.openai.com/v1/":
                    base_url_edit.setText("https://generativelanguage.googleapis.com/v1beta/openai/")
                if not model_edit.text().strip():
                    model_edit.setText("gemma-4-31b-it")
                provider_hint.setText("Get an API key at https://aistudio.google.com/apikey")
            elif is_openai:
                model_label.setText("AI Model:")
                if not base_url_edit.text().strip() or base_url_edit.text().strip() == "https://generativelanguage.googleapis.com/v1beta/openai/":
                    base_url_edit.setText("https://api.openai.com/v1/")
                if not model_edit.text().strip():
                    model_edit.setText("gpt-4o-mini")
                provider_hint.setText("Get an API key at https://platform.openai.com/api-keys")
            elif p == "ollama":
                model_label.setText("AI Model:")
                base_url_edit.setText("http://localhost:11434/v1")
                key_edit.clear()
                model_edit.setText("qwen2.5:7b")
                provider_hint.setText("Requires Ollama installed. Run: ollama pull qwen2.5:7b")
            else:
                model_label.setText("Model Path:")
                base_url_edit.setText("")
                base_url_edit.setVisible(False)
                base_url_label.setVisible(False)
                key_section_widget.setVisible(False)
                selected_tier = str(local_model_combo.currentData() or "normal").strip().lower()
                if selected_tier == "high":
                    model_edit.setText("models/ai/gemma-4-E4B-it-Q4_K_M.gguf")
                    provider_hint.setText("Place Gemma 4 GGUF into models/ai/. See Manage Resources for the download link. High Quality needs a better GPU.")
                else:
                    model_edit.setText("models/ai/Hy-MT2-1.8B-Q4_K_M.gguf")
                    provider_hint.setText("Place Hy-MT2 GGUF into models/ai/. See Manage Resources for the download link. Normal Quality is the default lighter model.")
            model_edit.setReadOnly(is_local)
            dialog.layout().invalidate()
            dialog.adjustSize()

        local_model_combo.currentIndexChanged.connect(update_provider_fields)

        test_btn = QPushButton("Test Connection", dialog)
        test_btn.setVisible(not remote_mode)
        test_status = QLabel("")
        test_status.setObjectName("helperLabel")
        test_status.setVisible(not remote_mode)
        test_row = QHBoxLayout()
        test_row.addWidget(test_btn)
        test_row.addWidget(test_status, 1)
        layout.addLayout(test_row)

        def test_ai_connection():
            url = base_url_edit.text().strip()
            key = key_edit.text().strip() or "ollama"
            model = model_edit.text().strip()
            test_status.setText("Testing...")
            test_status.repaint()
            try:
                from openai import OpenAI
                client = OpenAI(api_key=key, base_url=url)
                client.models.list()
                test_status.setText(f"Connected. Model: {model}")
            except Exception as e:
                test_status.setText(f"Failed: {e}")

        test_btn.clicked.connect(test_ai_connection)

        provider_combo.currentIndexChanged.connect(update_provider_fields)
        update_provider_fields()

        def update_engine_fields():
            engine_val = engine_combo.currentData()
            is_ocr = engine_val == "ocr"
            is_whisper = engine_val == "whisper"
            _toggle_visible(whisper_title, is_whisper)
            _toggle_visible(whisper_combo, is_whisper)
            _toggle_visible(region_label, is_ocr)
            _toggle_visible(region_combo, is_ocr)
            dialog.layout().invalidate()
            dialog.adjustSize()

        engine_combo.currentIndexChanged.connect(update_engine_fields)

        local_download_layout = QHBoxLayout()
        manage_resources_btn = QPushButton("Manage Resources", dialog)
        open_voices_folder_btn = QPushButton("Open Voices Folder", dialog)
        local_download_layout.addWidget(manage_resources_btn)
        local_download_layout.addWidget(open_voices_folder_btn)
        manage_resources_btn.setVisible(not remote_mode)
        open_voices_folder_btn.setVisible(not remote_mode)
        layout.addLayout(local_download_layout)

        def _piper_models_dir() -> str:
            return models_path("piper")

        def open_voices_folder():
            voices_dir = _piper_models_dir()
            os.makedirs(voices_dir, exist_ok=True)
            open_folder_impl(self, voices_dir)

        open_voices_folder_btn.clicked.connect(open_voices_folder)
        manage_resources_btn.clicked.connect(self.open_resource_manager_dialog)
        def _test_remote_connection():
            try:
                payload = self._test_remote_api_connection(
                    remote_url_edit.text().strip(),
                    remote_token_edit.text().strip(),
                )
                service_name = str(payload.get("service", "capcap-remote-api") or "capcap-remote-api")
                profile_name = str(payload.get("profile", "local") or "local")
                QMessageBox.information(
                    dialog,
                    "Remote API",
                    f"Connected successfully.\n\nService: {service_name}\nProfile: {profile_name}",
                )
            except Exception as exc:
                QMessageBox.warning(
                    dialog,
                    "Remote API",
                    f"Could not connect to the PC server.\n\n{exc}",
                )

        test_remote_btn.clicked.connect(_test_remote_connection)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton("Cancel", dialog)
        save_btn = QPushButton("Save", dialog)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

        cancel_btn.clicked.connect(dialog.reject)
        save_btn.clicked.connect(dialog.accept)

        # The subtitle is a top-level overlay above MPV's native surface.
        # Hide it for this modal dialog so it cannot paint over Settings.
        subtitle_item = getattr(getattr(self, "video_view", None), "subtitle_item", None)
        text_overlay = getattr(getattr(self, "video_view", None), "text_overlay", None)
        subtitle_was_visible = bool(subtitle_item is not None and subtitle_item.isVisible())
        if subtitle_item is not None:
            subtitle_item.set_suppressed(True)
        if text_overlay is not None:
            text_overlay.set_suppressed(True)
        dialog_result = dialog.exec()
        if dialog_result != QDialog.Accepted:
            if subtitle_item is not None:
                subtitle_item.set_suppressed(False)
            if text_overlay is not None:
                text_overlay.set_suppressed(False)
            if subtitle_was_visible and not getattr(self, "_preview_video_has_burned_subtitles", False):
                QTimer.singleShot(0, self.sync_live_subtitle_preview)
            return

        # Save Logic
        new_whisper = str(whisper_combo.currentData() or "medium").strip().lower()
        new_engine = str(engine_combo.currentData() or "whisper").strip().lower()
        new_ocr_region = str(region_combo.currentData() or "bottom").strip().lower()
        new_key = key_edit.text().strip()
        new_model = model_edit.text().strip()
        new_local_model_tier = str(local_model_combo.currentData() or "normal").strip().lower()
        new_provider = str(provider_combo.currentData()).strip()
        new_base_url = base_url_edit.text().strip()

        self.selected_whisper_model_name = new_whisper
        
        # Transcription engine settings (apply to all modes)
        _engine_updates = {
            "TRANSCRIPTION_ENGINE": new_engine,
            "OCR_SUBTITLE_REGION": new_ocr_region,
        }
        
        # Write back to .env
        env_lines = []
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        
        if remote_mode:
            updates = {
                "CAPCAP_REMOTE_API_URL": remote_url_edit.text().strip() or "http://127.0.0.1:8765",
                "CAPCAP_REMOTE_API_TOKEN": remote_token_edit.text().strip(),
            }
        else:
            if new_provider == "google":
                updates = {
                    "AI_POLISHER_PROVIDER": "google",
                    "OPENAI_PROVIDER": "google",
                    "OPENAI_API_KEY": "",
                    "OPENAI_MODEL": "",
                    "OPENAI_BASE_URL": "",
                }
            elif new_provider == "gemini":
                updates = {
                    "AI_POLISHER_PROVIDER": "gemini",
                    "OPENAI_PROVIDER": "gemini",
                    "OPENAI_API_KEY": new_key,
                    "OPENAI_MODEL": new_model or "gemma-4-31b-it",
                    "OPENAI_BASE_URL": new_base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
                }
            elif new_provider == "ollama":
                updates = {
                    "AI_POLISHER_PROVIDER": "gemini",
                    "OPENAI_PROVIDER": "ollama",
                    "OPENAI_API_KEY": "ollama",
                    "OPENAI_MODEL": new_model,
                    "OPENAI_BASE_URL": new_base_url or "http://localhost:11434/v1",
                }
            elif new_provider == "local":
                if new_local_model_tier == "high":
                    new_model = models_path("ai", "gemma-4-E4B-it-Q4_K_M.gguf")
                else:
                    new_model = models_path("ai", "Hy-MT2-1.8B-Q4_K_M.gguf")
                custom_model = model_edit.text().strip()
                if custom_model and models_path("ai") not in custom_model:
                    custom_model = models_path("ai", os.path.basename(custom_model))
                updates = {
                    "AI_POLISHER_PROVIDER": "local",
                    "OPENAI_PROVIDER": "local",
                    "LOCAL_TRANSLATOR_MODEL_TIER": new_local_model_tier,
                    "LOCAL_TRANSLATOR_MODEL_PATH": custom_model or new_model,
                }
            else:
                updates = {
                    "AI_POLISHER_PROVIDER": "gemini",
                    "OPENAI_PROVIDER": "openai",
                    "OPENAI_API_KEY": new_key,
                    "OPENAI_MODEL": new_model or "gpt-4o-mini",
                    "OPENAI_BASE_URL": new_base_url or "https://api.openai.com/v1/",
                }
        
        updates.update(_engine_updates)

        new_env_lines = []
        handled_keys = set()
        for line in env_lines:
            match = re.match(r"^([^=]+)=.*", line)
            if match:
                k = match.group(1).strip()
                if k in updates:
                    new_env_lines.append(f"{k}={updates[k]}\n")
                    handled_keys.add(k)
                    continue
            new_env_lines.append(line)
        
        for k, v in updates.items():
            if k not in handled_keys:
                new_env_lines.append(f"{k}={v}\n")
        
        with open(".env", "w", encoding="utf-8") as f:
            f.writelines(new_env_lines)
            
        # Update os.environ so it takes effect immediately in this session
        for k, v in updates.items():
            os.environ[k] = v

        self.save_user_settings()
        self._update_ocr_overlay()
        QMessageBox.information(self, "Success", "Settings saved and updated!")
        if subtitle_item is not None:
            subtitle_item.set_suppressed(False)
        if text_overlay is not None:
            text_overlay.set_suppressed(False)
        if subtitle_was_visible and not getattr(self, "_preview_video_has_burned_subtitles", False):
            QTimer.singleShot(0, self.sync_live_subtitle_preview)

    def apply_edited_translation(self, show_message=True, force_apply=True):
        result = self.subtitle_controller.apply_edited_translation(show_message=show_message, force_apply=force_apply)
        if result:
            self.refresh_auto_keyword_highlights()
            self.sync_segment_editor_rows()
            return result



    def setup_media_player(self):
        if getattr(self, "_media_backend_ready", False):
            return
        previous_speed = getattr(self, "_preview_speed", 1.0)
        setup_media_player_impl(self)
        self._preview_speed = previous_speed
        self._media_backend_ready = True
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_playback_rate(previous_speed)
            except Exception:
                pass

    def browse_video(self):
        browse_video_impl(self)

    def browse_audio_folder(self):
        browse_audio_folder_impl(self)

    def browse_srt_output_folder(self):
        browse_srt_output_folder_impl(self)

    def browse_audio_source(self):
        browse_audio_source_impl(self)

    def browse_background_audio(self):
        browse_background_audio_impl(self)

    def browse_existing_mixed_audio(self):
        browse_existing_mixed_audio_impl(self)

    def browse_voice_output_folder(self):
        browse_voice_output_folder_impl(self)

    def _get_voiceover_segments(self):
        source_segments = list(self.current_translated_segments or [])
        if not source_segments:
            translated_srt = self.translated_text.toPlainText().strip()
            return self.parse_srt_to_segments(translated_srt) if translated_srt else []

        grouped_segments = []
        idx = 0
        while idx < len(source_segments):
            segment = dict(source_segments[idx])
            group_id = str(segment.get('tts_group_id', '') or '').strip()
            tts_text = self._resolve_segment_voice_text(segment)
            if not group_id:
                segment['text'] = tts_text
                segment['tts_text'] = str(segment.get('tts_text') or '').strip() if bool(segment.get('voice_edited')) else ''
                grouped_segments.append(segment)
                idx += 1
                continue

            group_items = [segment]
            cursor = idx + 1
            while cursor < len(source_segments):
                candidate = source_segments[cursor]
                if str(candidate.get('tts_group_id', '') or '').strip() != group_id:
                    break
                group_items.append(dict(candidate))
                cursor += 1

            voice_text = ""
            voice_edited = False
            for item in group_items:
                if bool(item.get('voice_edited')):
                    candidate_text = " ".join(str(item.get('tts_text') or item.get('dubbing_vi') or '').split()).strip()
                    if candidate_text:
                        voice_text = candidate_text
                        voice_edited = True
                        break
            if not voice_text:
                voice_text = ' '.join(
                    ' '.join(str(item.get('text') or '').split()).strip()
                    for item in group_items
                ).strip()

            grouped_segments.append({
                'start': float(group_items[0].get('tts_group_start', group_items[0].get('start', 0.0)) or group_items[0].get('start', 0.0)),
                'end': float(group_items[-1].get('tts_group_end', group_items[-1].get('end', 0.0)) or group_items[-1].get('end', 0.0)),
                'text': voice_text,
                'tts_text': voice_text if voice_edited else '',
                'tts_group_id': group_id,
                'voice_edited': voice_edited,
                'source_text': ' '.join(
                    ' '.join(str(item.get('source_text') or item.get('text') or '').split()).strip()
                    for item in group_items
                ).strip(),
            })
            idx = cursor
        return grouped_segments

    def run_voiceover(self):
        if not self.ensure_required_resources("Voice generation", include_voice=True):
            return
        state = self.ensure_current_project()
        if state and not self.translated_text.toPlainText().strip():
            self.load_project_context(state)

        translated_srt = self.translated_text.toPlainText().strip()
        if not translated_srt:
            QMessageBox.warning(self, "Error", "No translated SRT available. Please run translation first (STEP 3).")
            return

        segments = self._get_voiceover_segments()
        if not segments:
            QMessageBox.warning(self, "Error", "Translated SRT could not be parsed to segments.")
            return

        out_dir = self.voice_output_folder_edit.text().strip() or os.path.join(self.workspace_root, "output")
        bg_path = self.resolve_background_audio_path()
        audio_handling_mode = self.get_audio_handling_mode()
        voice_name = self._resolve_active_voice_name(persist_new_clone=True)
        if not voice_name:
            QMessageBox.warning(self, "Missing Voice", "Choose a voice first.")
            return
        voice_speed = self._parse_voice_speed_value()
        timing_sync_mode = str(self.voice_timing_sync_combo.currentText()).strip()
        original_volume = int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50
        dub_volume = int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100
        voice_signature = self.build_current_voice_signature(segments=segments, background_path=bg_path)
        if state and voice_signature:
            force_refresh = bool(getattr(self, "_voiceover_force_refresh", False))
            cached_voice_signature = str(state.settings.get("voice_signature", "") or "").strip()
            cached_voice_track = self._normalize_local_file_path(state.artifacts.get("voice_vi", "") or self.last_voice_vi_path)
            cached_mixed_track = self._normalize_local_file_path(state.artifacts.get("mixed_vi", "") or self.last_mixed_vi_path)
            required_output = cached_mixed_track if bg_path else cached_voice_track
            self.log(
                f"[Voiceover] Cache check: force={force_refresh}, "
                f"cached_sig={'<empty>' if not cached_voice_signature else cached_voice_signature[:16]+'...'}, "
                f"new_sig={'<empty>' if not voice_signature else voice_signature[:16]+'...'}, "
                f"match={cached_voice_signature == voice_signature}, "
                f"required_output={required_output}, exists={os.path.exists(required_output) if required_output else False}"
            )
            if not force_refresh and cached_voice_signature == voice_signature and required_output and os.path.exists(required_output):
                self.last_voice_vi_path = cached_voice_track if cached_voice_track and os.path.exists(cached_voice_track) else self.last_voice_vi_path
                self.last_mixed_vi_path = cached_mixed_track if cached_mixed_track and os.path.exists(cached_mixed_track) else ""
                if self.last_voice_vi_path:
                    self.processed_artifacts["voice_vi"] = self.last_voice_vi_path
                    self.update_project_artifact("voice_vi", self.last_voice_vi_path)
                    self.update_project_step("generate_tts", "done")
                if bg_path:
                    if self.last_mixed_vi_path:
                        self.processed_artifacts["mixed_vi"] = self.last_mixed_vi_path
                        self.update_project_artifact("mixed_vi", self.last_mixed_vi_path)
                        self.update_project_step("mix_audio", "done")
                    else:
                        self.update_project_step("mix_audio", "skipped")
                self.log("[Voiceover] Reusing existing generated audio. Generate did not call TTS again.")
                self.progress_bar.setValue(100)
                self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
                self.refresh_ui_state()
                self._pipeline_advance("voiceover")
                return
        
        combo_text = self.free_voice_combo.currentText() if hasattr(self, "free_voice_combo") else ""
        combo_data = self.free_voice_combo.currentData() if hasattr(self, "free_voice_combo") else ""
        combo_id = self.free_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE) if hasattr(self, "free_voice_combo") else ""
        self.log(f"[Voiceover] Selected voice: text='{combo_text}', data='{combo_data}', id='{combo_id}'")
        
        self.log(
            "[Voiceover] Starting with "
            f"audio_mode={audio_handling_mode}, "
            f"voice={voice_name}, "
            f"speed={voice_speed:.2f}, "
            f"segments={len(segments)}, "
            f"translated_chars={len(translated_srt)}, "
            f"background={bg_path or '<none>'}"
        )
        if state:
            self.log(
                "[Voiceover] State snapshot: "
                f"project={state.project_root}, "
                f"steps={dict(state.steps)}, "
                f"artifacts={dict(state.artifacts)}"
            )

        try:
            self.media_player.pause()
            self.timeline.set_playing(False)
        except Exception:
            pass

        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(False)
            self.voiceover_btn.setText("Generating... (TTS)")
        self.progress_bar.setValue(85)
        self.update_project_step("generate_tts", "running")
        if bg_path:
            self.update_project_step("mix_audio", "running")
        self.refresh_ui_state()
        try:
            QApplication.processEvents()
        except Exception:
            pass
        self._pending_voice_signature = voice_signature

        project_state_path = self.project_service.project_file(self.current_project_state.project_root) if self.current_project_state else ""
        self.voice_thread = VoiceOverWorker(
            self.workspace_root,
            segments,
            out_dir,
            bg_path,
            audio_handling_mode,
            voice_name,
            voice_speed,
            timing_sync_mode,
            original_volume,
            dub_volume,
            project_state_path,
            self.get_project_temp_dir("tts"),
            self.is_ai_dubbing_rewrite_enabled() and self.get_output_mode_key() in ("voice", "both"),
            self.get_ai_dubbing_style_instruction(),
            self.get_source_language_code(),
        )
        self.voice_thread.progress.connect(self.log)
        self.voice_thread.finished.connect(self.on_voiceover_finished)
        self.voice_thread.start()

    def _apply_generated_tts_texts(self, voice_segments):
        source_segments = self.current_translated_segments
        if not source_segments or not voice_segments:
            return False

        updated = False
        grouped_updates = {}
        positional_updates = []
        for seg in list(voice_segments or []):
            tts_text = ' '.join(str((seg or {}).get("tts_text") or (seg or {}).get("text") or "").split()).strip()
            if not tts_text:
                continue
            subtitle_vi = ' '.join(str((seg or {}).get("subtitle_vi") or (seg or {}).get("text") or "").split()).strip()
            dubbing_vi = ' '.join(str((seg or {}).get("dubbing_vi") or tts_text).split()).strip()
            action_taken = str((seg or {}).get("action_taken") or "").strip().lower()
            ratio = float((seg or {}).get("ratio") or 0.0)
            group_id = str((seg or {}).get("tts_group_id") or "").strip()
            try:
                new_start = float((seg or {}).get("start", 0.0))
                new_end = float((seg or {}).get("end", 0.0))
            except (TypeError, ValueError):
                new_start = new_end = None
            try:
                new_original_end = float((seg or {}).get("_original_end")) if (seg or {}).get("_original_end") is not None else None
            except (TypeError, ValueError):
                new_original_end = None
            try:
                new_audio_end = float((seg or {}).get("_audio_end")) if (seg or {}).get("_audio_end") is not None else None
            except (TypeError, ValueError):
                new_audio_end = None
            payload = {
                "tts_text": tts_text,
                "subtitle_vi": subtitle_vi,
                "dubbing_vi": dubbing_vi,
                "action_taken": action_taken,
                "ratio": ratio,
                "attempt_count": int((seg or {}).get("attempt_count") or 1),
                "start": new_start,
                "end": new_end,
                "_original_end": new_original_end,
                "_audio_end": new_audio_end,
            }
            if group_id:
                grouped_updates[group_id] = payload
            else:
                positional_updates.append(payload)

        positional_index = 0
        for seg in source_segments:
            group_id = str((seg or {}).get("tts_group_id") or "").strip()
            if group_id and group_id in grouped_updates:
                next_payload = grouped_updates[group_id]
            elif positional_index < len(positional_updates):
                next_payload = positional_updates[positional_index]
                positional_index += 1
            else:
                continue

            next_tts_text = next_payload["tts_text"]
            current_tts_text = ' '.join(str(seg.get("tts_text") or "").split()).strip()
            if current_tts_text != next_tts_text:
                seg["tts_text"] = next_tts_text
                updated = True
            seg["subtitle_vi"] = next_payload["subtitle_vi"]
            seg["dubbing_vi"] = next_payload["dubbing_vi"]
            seg["action_taken"] = next_payload["action_taken"]
            seg["ratio"] = next_payload["ratio"]
            seg["attempt_count"] = next_payload["attempt_count"]
            # Sync start/end from the voice workflow so the SRT reflects the
            # actual TTS audio duration (see _extend_segment_ends_to_audio).
            new_start = next_payload.get("start")
            new_end = next_payload.get("end")
            if new_start is not None and new_end is not None and new_end > new_start:
                try:
                    old_start = float(seg.get("start", 0.0))
                    old_end = float(seg.get("end", 0.0))
                except (TypeError, ValueError):
                    old_start = old_end = None
                if old_start is not None and old_end is not None:
                    if abs(new_start - old_start) > 0.01 or abs(new_end - old_end) > 0.01:
                        seg["start"] = new_start
                        seg["end"] = new_end
                        updated = True
            new_original_end = next_payload.get("_original_end")
            if new_original_end is not None:
                seg["_original_end"] = new_original_end
            new_audio_end = next_payload.get("_audio_end")
            if new_audio_end is not None:
                seg["_audio_end"] = new_audio_end
            else:
                seg.pop("_audio_end", None)
        return updated

    def _regenerate_translated_srt_from_segments(self):
        """Regenerate the project SRT from current_translated_segments.
        Called after the voice workflow extends a segment's end time to
        match the actual TTS audio duration, so the burned-in subtitle and
        the rendered audio stay in sync.
        """
        out_path = str(getattr(self, "last_translated_srt_path", "") or "").strip()
        if not out_path:
            return
        try:
            from subtitle_builder import generate_srt
            generate_srt(self.current_translated_segments, out_path)
        except Exception as exc:
            print(f"[Voice] SRT regen failed: {exc}")
            return
        self.processed_artifacts["srt_translated"] = out_path
        self.persist_translation_project_data(self.current_translated_segments, out_path)

    def on_voiceover_finished(self, voice_track, mixed, voice_segments, error):
        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(True)
            self.voiceover_btn.setText("Generate Voice / Mix")
        self.progress_bar.setValue(100)

        if error:
            self._voiceover_force_refresh = False
            self._pending_voice_signature = ""
            self.update_project_step("generate_tts", "failed")
            if self.bg_music_edit.text().strip():
                self.update_project_step("mix_audio", "failed")
            QMessageBox.critical(self, "Error", f"Voiceover failed:\n\n{error}")
            self._pipeline_fail("Voiceover failed.")
            self.refresh_ui_state()
            return

        if hasattr(self, "audio_tab_btn"):
            self.audio_tab_btn.setEnabled(True)

        if voice_track and os.path.exists(voice_track):
            self.last_voice_vi_path = voice_track
            self.processed_artifacts["voice_vi"] = voice_track
            self.update_project_artifact("voice_vi", voice_track)
            self.update_project_step("generate_tts", "done")
        if mixed and os.path.exists(mixed):
            self.last_mixed_vi_path = mixed
            self.processed_artifacts["mixed_vi"] = mixed
            self.update_project_artifact("mixed_vi", mixed)
            self.update_project_step("mix_audio", "done")
        elif self.bg_music_edit.text().strip():
            self.update_project_step("mix_audio", "skipped")
        if self._apply_generated_tts_texts(voice_segments):
            self._single_line_split_cache = None
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()
            self.apply_segments_to_timeline()
            if hasattr(self, "timeline") and voice_track:
                self.timeline.sync_tts_track(
                    voice_track,
                    segments=self.current_translated_segments or self.current_segments,
                )
                if hasattr(self, "voice_timing_sync_combo"):
                    self.timeline.set_voice_sync_mode(self.voice_timing_sync_combo.currentText())
            self._sync_timeline_mute_to_gui()
            self.persist_current_timeline_project_data()
            # Regenerate the project SRT from the updated segments so it
            # reflects the actual TTS audio duration (e.g. when a segment
            # was extended in voice_workflow._extend_segment_ends_to_audio).
            self._regenerate_translated_srt_from_segments()
            self.schedule_live_subtitle_preview_refresh()
            self.sync_segment_editor_rows()
        if self.current_project_state:
            voice_signature = self.build_current_voice_signature(
                segments=self._get_voiceover_segments(),
                background_path=self.resolve_background_audio_path(),
            )
            if voice_signature:
                self.current_project_state.set_setting("voice_signature", voice_signature)
                self.project_service.save_project(self.current_project_state)
        self._voiceover_force_refresh = False
        self._pending_voice_signature = ""

        try:
            self._pipeline_advance("voiceover")
        except Exception as exc:
            self.log(f"[Voiceover] pipeline_advance failed: {exc}")
            self.refresh_ui_state()

        if mixed:
            self.log(f"[Voiceover] Generated Vietnamese voice and mixed audio: Voice={voice_track}, Mixed={mixed}")
        else:
            self.log(f"[Voiceover] Generated Vietnamese voice track: {voice_track} (No background mix created.)")

        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.refresh_ui_state()
        self.sync_preview_audio_track_to_output()

    def preview_video(self):
        self.preview_controller.preview_video()

    def on_preview_ready(self, preview_path, error, styled_signature=""):
        self.preview_controller.on_preview_ready(preview_path, error, styled_signature)

    def smart_generate(self):
        if getattr(self, "_pipeline_active", False):
            return
        has_subtitles = bool(self.current_segments)
        has_translated = bool(self.current_translated_segments and self.translated_text.toPlainText().strip())
        mode = self.get_output_mode_key()
        need_voice = mode in ("voice", "both")

        if not has_subtitles or (not has_translated and mode != "voice"):
            self.run_all_pipeline()
        elif need_voice:
            self.run_voiceover_with_progress()
        else:
            self.preview_video()

    def run_voiceover_with_progress(self, target_stage="full"):
        existing = getattr(self, "voice_thread", None)
        if existing and existing.isRunning():
            return
        self._pipeline_active = True
        self._pipeline_step = "voiceover"
        self.pipeline_controller.target_stage = str(target_stage or "full")
        if hasattr(self, "run_all_btn"):
            self.run_all_btn.setEnabled(False)
            self.run_all_btn.setText("Processing...")
        self.pipeline_controller._setup_progress_dialog(includes_separation=False)
        self.pipeline_controller.progress_dialog.skip_step("ai_process")
        self.pipeline_controller.progress_dialog.start_step("voiceover")
        self._voiceover_force_refresh = True
        self.run_voiceover()

    def run_pipeline_to_stage(self, target_stage: str):
        target_stage = str(target_stage or "full").strip().lower()
        if target_stage not in {"transcript", "translate", "tts"}:
            self.run_all_pipeline()
            return
        has_transcript = bool(self.current_segments or self.transcript_text.toPlainText().strip())
        has_translation = bool(self.current_translated_segments or self.translated_text.toPlainText().strip())
        if target_stage == "translate" and not has_transcript:
            QMessageBox.information(self, "Step-by-Step", "Complete Transcript before running Translate.")
            return
        if target_stage == "tts" and not has_translation:
            QMessageBox.information(self, "Step-by-Step", "Complete Translate before running Generate Voice / TTS.")
            return
        if target_stage == "tts" and has_translation:
            self.run_voiceover_with_progress(target_stage="tts")
            return
        mode = self.get_output_mode_key()
        include_voice = target_stage == "tts" and mode in ("voice", "both")
        is_ocr = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
        if not self.ensure_required_resources("Generate", include_whisper=not is_ocr, include_voice=include_voice):
            return
        self.pipeline_controller.run_all_pipeline(target_stage=target_stage)

    def run_all_pipeline(self):
        mode = self.get_output_mode_key()
        include_voice = mode in ("voice", "both")
        is_ocr = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
        if not self.ensure_required_resources("Generate", include_whisper=not is_ocr, include_voice=include_voice):
            return
        self.pipeline_controller.run_all_pipeline(target_stage="full")

    def on_prepare_workflow_finished(self, project_state_path, error):
        self.pipeline_controller.on_prepare_workflow_finished(project_state_path, error)

    def _pipeline_advance(self, completed_step: str):
        self.pipeline_controller.pipeline_advance(completed_step)

    def _pipeline_fail(self, reason: str):
        self.pipeline_controller.pipeline_fail(reason)

    def _pipeline_done(self):
        self.pipeline_controller.pipeline_done()

    def open_folder(self, path):
        open_folder_impl(self, path)

    def show_processed_files(self):
        show_processed_files_impl(self)

    def cleanup_temp_preview_files(self):
        cleanup_temp_preview_files_impl(self)

    def _path_within_root(self, path: str, root: str) -> bool:
        try:
            normalized_path = os.path.normcase(os.path.abspath(path))
            normalized_root = os.path.normcase(os.path.abspath(root))
            return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
        except Exception:
            return False

    def _remove_path_if_safe(self, path: str, *, allowed_roots: list[str], removed: list[str]) -> None:
        normalized = self._normalize_local_file_path(path)
        if not normalized or not os.path.exists(normalized):
            return
        if not any(self._path_within_root(normalized, root) for root in allowed_roots if root):
            return

        def _on_remove_error(func, target, exc_info):
            try:
                os.chmod(target, 0o777)
                func(target)
            except OSError:
                return

        try:
            if os.path.isdir(normalized):
                shutil.rmtree(normalized, onerror=_on_remove_error)
            else:
                os.remove(normalized)
        except OSError:
            return
        if not os.path.exists(normalized):
            removed.append(normalized)

    def _reset_project_runtime_state(self) -> None:
        self.current_project_state = None
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.current_segments = []
        self.current_translated_segments = []
        self.processed_artifacts = {}
        self.last_extracted_audio = ""
        self.last_vocals_path = ""
        self.last_music_path = ""
        self.last_original_srt_path = ""
        self.last_translated_srt_path = ""
        self.last_voice_vi_path = ""
        self.last_mixed_vi_path = ""
        self.last_preview_video_path = ""
        self.last_styled_preview_path = ""
        self.last_styled_preview_signature = ""
        self.last_exported_video_path = ""
        self.last_exact_preview_5s_path = ""
        self.last_exact_preview_frame_path = ""
        self.live_preview_subtitle_path = ""
        self.live_preview_ass_path = ""
        self.live_preview_segments = []
        self.live_preview_editor_name = ""
        self._live_preview_signature = None
        self._timeline_waveform_cache_key = None
        self._timeline_waveform_samples = []
        self._timeline_waveform_duration_s = 0.0
        self._desired_timeline_waveform_request = None
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self._desired_timeline_thumbnail_request = None
        self._allow_post_pipeline_preview_assets = False
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        if hasattr(self, "transcript_text"):
            self.transcript_text.clear()
        if hasattr(self, "translated_text"):
            self.translated_text.clear()
        if hasattr(self, "audio_source_edit"):
            self.audio_source_edit.clear()
        if hasattr(self, "bg_music_edit"):
            self.bg_music_edit.clear()
        if hasattr(self, "mixed_audio_edit"):
            self.mixed_audio_edit.clear()
        if hasattr(self, "video_path_edit"):
            self.video_path_edit.clear()
        if hasattr(self, "timeline"):
            self.timeline.set_segments([])
            self.timeline.set_duration(0)
            self.timeline.set_waveform_data([], 0.0)
            self.timeline.set_video_thumbnails([])
            self.timeline.set_playing(False)
        if hasattr(self, "media_player"):
            try:
                self.media_player.clear_subtitle()
                self.media_player.stop()
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl())
            except Exception:
                pass
        if hasattr(self, "video_view"):
            try:
                self.video_view.clear_blur_region()
            except Exception:
                pass
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0)
        # Force-clear segment editor directly
        self._clear_segment_editor_rows()
        self._segment_editor_rows = []
        self._selected_segment_index = -1
        self.sync_segment_editor_rows()
        self.update_progress_checklist()
        self.refresh_ui_state()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def _has_cleanable_project_data(self) -> bool:
        project_root = str(getattr(getattr(self, "current_project_state", None), "project_root", "") or "").strip()
        candidates = [
            self.last_extracted_audio,
            self.last_vocals_path,
            self.last_music_path,
            self.last_voice_vi_path,
            self.last_mixed_vi_path,
            self.live_preview_subtitle_path,
            self.live_preview_ass_path,
            self.last_preview_video_path,
            self.last_styled_preview_path,
            self.last_exact_preview_5s_path,
            self.last_exact_preview_frame_path,
            self.get_project_temp_path("tts"),
            self.get_project_temp_path("segment_audio_preview"),
            self.get_project_temp_path("voice_sample_preview"),
            self.get_project_temp_path("htdemucs"),
            self.get_project_temp_path("timeline_video_thumbs"),
            self.get_project_temp_root(),
            project_root,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return True
        return False

    def exit_to_launcher(self):
        self._return_to_launcher(project_removed_from_recent=False)

    def clean_current_project(self):
        project_state = getattr(self, "current_project_state", None)
        if not self._has_cleanable_project_data():
            QMessageBox.information(self, "Clean Project", "There is no generated project data to clean right now.")
            return

        confirmation = QMessageBox.question(
            self,
            "Clean Project",
            "This will remove intermediate project files, temp previews, separated audio, and cached TTS files for the current project.\n\n"
            "It will keep your source video, imported assets, and final exported video.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        removed_paths = []
        removed_groups = {
            "Project folder": [],
            "Generated voice files": [],
            "Separated audio": [],
            "Preview temp files": [],
            "TTS cache": [],
            "Temp folders": [],
        }
        project_temp_root = self.get_project_temp_root()
        output_root = os.path.join(self.workspace_root, "output")
        project_root = str(getattr(project_state, "project_root", "") or "").strip()
        project_state_path = self.project_service.project_file(project_root) if project_root else ""
        allowed_roots = [root for root in [project_temp_root, output_root, project_root] if root]

        self.cleanup_temp_preview_files()

        file_candidates = [
            ("Separated audio", self.last_extracted_audio),
            ("Separated audio", self.last_vocals_path),
            ("Separated audio", self.last_music_path),
            ("Generated voice files", self.last_voice_vi_path),
            ("Generated voice files", self.last_mixed_vi_path),
            ("Preview temp files", self.live_preview_subtitle_path),
            ("Preview temp files", self.live_preview_ass_path),
            ("Preview temp files", self.last_styled_preview_path),
            ("Project folder", project_state_path),
        ]
        for group_name, candidate in file_candidates:
            before_count = len(removed_paths)
            self._remove_path_if_safe(candidate, allowed_roots=allowed_roots, removed=removed_paths)
            if len(removed_paths) > before_count:
                removed_groups[group_name].append(removed_paths[-1])

        dir_candidates = [
            ("Project folder", project_root),
            ("TTS cache", self.get_project_temp_path("tts")),
            ("Temp folders", self.get_project_temp_path("segment_audio_preview")),
            ("Temp folders", self.get_project_temp_path("voice_sample_preview")),
            ("Temp folders", self.get_project_temp_path("htdemucs")),
            ("Temp folders", self.get_project_temp_path("timeline_video_thumbs")),
            ("Temp folders", project_temp_root),
        ]
        for group_name, candidate in dir_candidates:
            before_count = len(removed_paths)
            self._remove_path_if_safe(candidate, allowed_roots=allowed_roots, removed=removed_paths)
            if len(removed_paths) > before_count:
                removed_groups[group_name].append(removed_paths[-1])

        self._reset_project_runtime_state()

        if removed_paths:
            self.log(f"[Clean Project] Removed {len(removed_paths)} intermediate paths.")
            detail_lines = ["Cleaned these groups:"]
            for group_name, paths in removed_groups.items():
                if paths:
                    detail_lines.append(f"- {group_name}: {len(paths)} item(s)")
            QMessageBox.information(
                self,
                "Clean Project",
                f"Removed {len(removed_paths)} intermediate paths for the current project.\n\n" + "\n".join(detail_lines),
            )
        else:
            QMessageBox.information(
                self,
                "Clean Project",
                "No removable intermediate files were found for the current project.",
            )
        self._return_to_launcher(project_removed_from_recent=True)

    def _return_to_launcher(self, project_removed_from_recent=True):
        self._cache_core_timeline_tracks_only()
        video_path = getattr(self, "_current_video_path", "")
        if not video_path:
            video_path = os.path.normpath(self.video_path_edit.text().strip())
        self.log(f"[Clean] _return_to_launcher: video_path={video_path}")
        if video_path and project_removed_from_recent:
            try:
                from views.launcher import _load_recent_projects, _save_recent_projects
                projects = _load_recent_projects()
                projects = [p for p in projects if os.path.normpath(p.get("video_path", "")) != os.path.normpath(video_path)]
                _save_recent_projects(None, projects)
                self.log(f"[Clean] Removed from recent: {video_path} -> {len(projects)} remaining")
            except Exception as e:
                self.log(f"[Clean] Failed: {e}")
        self._current_video_path = ""
        self._terminate_workers()
        self.hide()
        QApplication.setQuitOnLastWindowClosed(False)
        QTimer.singleShot(100, _relaunch_launcher)

    def _terminate_workers(self):
        attrs = [
            "extraction_thread",
            "vocal_thread",
            "voice_thread",
            "_voice_sample_preview_thread",
            "transcription_thread",
            "translation_thread",
            "rewrite_translation_thread",
            "prepare_workflow_thread",
            "export_thread",
            "quick_preview_thread",
            "frame_preview_thread",
            "preview_thread",
        ]
        for name in attrs:
            worker = getattr(self, name, None)
            if worker is not None and getattr(worker, "isRunning", lambda: False)():
                print(f"[Cleanup] Terminating worker: {name}")
                try:
                    worker.quit()
                    worker.wait(3000)
                    if worker.isRunning():
                        worker.terminate()
                        worker.wait(2000)
                        print(f"[Cleanup] Force-terminated {name}")
                    else:
                        print(f"[Cleanup] Graceful quit {name}")
                except Exception as e:
                    print(f"[Cleanup] Failed to terminate {name}: {e}")
        threads_dict = getattr(self, "_segment_preview_threads", None)
        if threads_dict:
            for idx, worker in list(threads_dict.items()):
                try:
                    if getattr(worker, "isRunning", lambda: False)():
                        print(f"[Cleanup] Terminating segment preview thread idx={idx}")
                        worker.quit()
                        worker.wait(3000)
                        if worker.isRunning():
                            worker.terminate()
                            worker.wait(2000)
                except Exception as e:
                    print(f"[Cleanup] Failed to terminate segment thread {idx}: {e}")
            threads_dict.clear()
        print("[Cleanup] Worker termination complete.")

    def closeEvent(self, event):
        try:
            # Persist the current blur state BEFORE clearing the overlay.
            # Block the blurRegionChanged signal during the clear so the
            # signal handler does not overwrite the saved state with an
            # empty regions list.
            if hasattr(self, "video_view"):
                try:
                    self.video_view.blurRegionChanged.disconnect(self.on_preview_blur_region_changed)
                except Exception:
                    pass
            if hasattr(self, "persist_project_blur_state"):
                try:
                    self.persist_project_blur_state()
                except Exception:
                    pass
            if hasattr(self, "persist_project_mask_state"):
                try:
                    self.persist_project_mask_state()
                except Exception:
                    pass
            self._cache_core_timeline_tracks_only()
            if hasattr(self, "video_view"):
                self.video_view.clear_blur_region()
            if hasattr(self, "media_player") and hasattr(self.media_player, "clear_mask_region"):
                try:
                    self.media_player.clear_mask_region()
                except Exception:
                    pass
            self.save_user_settings()
            self.cleanup_temp_preview_files()
            self._terminate_workers()
        finally:
            super().closeEvent(event)

    def toggle_play(self):
        toggle_play_impl(self)

    def stop_video(self):
        stop_video_impl(self)

    def position_changed(self, position):
        position_changed_impl(self, position)

    def duration_changed(self, duration):
        duration_changed_impl(self, duration)
        self.schedule_timeline_visual_refresh(waveform=False, thumbnails=True)

    def set_position(self, position):
        set_position_impl(self, position)

    def update_duration_label(self, current, total):
        update_duration_label_impl(self, current, total)

    def refresh_play_button_icon(self):
        """Update the play button icon + tooltip to reflect the current
        media player state (playing vs paused). Called from
        position_changed when playback ends naturally so the button
        switches from the pause icon back to the play icon."""
        if not hasattr(self, "play_btn"):
            return
        playing = False
        try:
            playing = bool(self.media_player.is_playing())
        except Exception:
            playing = False
        play_icon = "pause.svg" if playing else "play.svg"
        play_tip = "Pause preview" if playing else "Play preview"
        try:
            self.play_btn.setIcon(load_icon(asset_path("icons", play_icon), 18))
            self.play_btn.setToolTip(play_tip)
        except Exception:
            pass
        if hasattr(self, "blur_area_btn"):
            blur_active = bool(self.blur_area_btn.isChecked())
            self.blur_area_btn.setToolTip("Blur effect on" if blur_active else "Turn blur effect on or off")
        if hasattr(self, "preview_speed_combo"):
            target = float(getattr(self, "_preview_speed", 1.0))
            index = self.preview_speed_combo.findData(target)
            if index >= 0 and self.preview_speed_combo.currentIndex() != index:
                self.preview_speed_combo.blockSignals(True)
                self.preview_speed_combo.setCurrentIndex(index)
                self.preview_speed_combo.blockSignals(False)
        if hasattr(self, "preview_audio_track_combo"):
            combo = self.preview_audio_track_combo
            entries = self._preview_audio_track_choices()
            current_mode = str(getattr(self, "_preview_audio_track_mode", "both") or "both").strip().lower()
            if current_mode == "dubbed" and not any(value == "dubbed" for _label, value in entries):
                current_mode = "both"
                self._preview_audio_track_mode = "both"
            existing = [(combo.itemText(i), str(combo.itemData(i) or "")) for i in range(combo.count())]
            if existing != entries:
                combo.blockSignals(True)
                combo.clear()
                for label, value in entries:
                    combo.addItem(label, value)
                combo.blockSignals(False)
            target_index = combo.findData(current_mode)
            if target_index < 0:
                target_index = 0
            if combo.currentIndex() != target_index:
                combo.blockSignals(True)
                combo.setCurrentIndex(target_index)
                combo.blockSignals(False)
            combo.setEnabled(combo.count() > 1 and getattr(self, "media_player", None) is not None and getattr(self.media_player, "backend_name", "") == "libmpv")

    def on_preview_speed_changed(self, index: int):
        if not hasattr(self, "preview_speed_combo"):
            return
        rate = self.preview_speed_combo.itemData(index)
        try:
            new_rate = float(rate or 1.0)
        except Exception:
            new_rate = 1.0
        self._preview_speed = new_rate
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_playback_rate(new_rate)
            except Exception:
                pass


def _relaunch_launcher():
    from views.launcher import show_launcher, LauncherWindow
    video_path = show_launcher(None)
    QApplication.setQuitOnLastWindowClosed(True)
    if not video_path:
        QApplication.quit()
        return
    LauncherWindow.add_recent(None, video_path)
    new_window = VideoTranslatorGUI()
    new_window.show()
    def _init():
        new_window._current_video_path = os.path.abspath(video_path)
        new_window.ensure_media_backend_ready()
        new_window.video_path_edit.setText(video_path)
        new_window.media_player.setSource(QUrl.fromLocalFile(video_path))
        if hasattr(new_window, "refresh_video_dimensions"):
            new_window.refresh_video_dimensions(video_path)
        new_window.current_project_state = new_window.ensure_current_project()
        new_window.load_project_context(new_window.current_project_state)
        new_window.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
    QTimer.singleShot(100, _init)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTranslatorGUI()
    window.show()
    sys.exit(app.exec())






