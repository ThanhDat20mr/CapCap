import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _section_title(text):
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _section_card():
    card = QFrame()
    card.setObjectName("statusCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)
    return card, layout


def _build_collapsible_section(title: str, start_expanded: bool = True):
    wrapper = QFrame()
    wrapper.setObjectName("statusCard")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(12, 11, 12, 11)
    wrapper_layout.setSpacing(8)

    toggle_btn = QToolButton()
    toggle_btn.setText(("▼ " if start_expanded else "▶ ") + title)
    toggle_btn.setCheckable(True)
    toggle_btn.setChecked(start_expanded)
    toggle_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
    toggle_btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #8ad7ff; border: none; padding: 0; }")

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(10)
    content.setVisible(start_expanded)

    def _toggle_section(checked: bool):
        toggle_btn.setText(("▼ " if checked else "▶ ") + title)
        content.setVisible(checked)
        content.setMaximumHeight(16777215 if checked else 0)

    toggle_btn.toggled.connect(_toggle_section)
    wrapper_layout.addWidget(toggle_btn)
    wrapper_layout.addWidget(content)
    return wrapper, content_layout


def _build_hidden_status_widgets(gui):
    gui.workflow_hint_label = QLabel()
    gui.workflow_hint_label.setObjectName("helperLabel")
    gui.workflow_hint_label.setWordWrap(True)
    gui.workflow_hint_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    gui.workflow_hint_label.setTextInteractionFlags(Qt.NoTextInteraction)


def _build_style_preset_card(title: str, line_one: str, line_two: str, radio: QRadioButton):
    card = QFrame()
    card.setObjectName("statusCard")
    card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    card.setStyleSheet(
        "QFrame#statusCard { background-color: #132132; border: 1px solid #35506f; border-radius: 14px; }"
        "QFrame#statusCard:hover { border-color: #5aa6d9; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(4)
    layout.addWidget(radio, 0, Qt.AlignTop)

    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    title_label.setAlignment(Qt.AlignCenter)

    style_key = title.strip().lower()
    preview_frame = QFrame()
    preview_frame.setFixedHeight(88)
    preview_frame.setStyleSheet(
        "QFrame {"
        "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1d2940, stop:1 #0d1522);"
        "border:1px solid #2d425d; border-radius: 12px; }"
    )
    preview_layout = QVBoxLayout(preview_frame)
    preview_layout.setContentsMargins(10, 10, 10, 10)
    preview_layout.setSpacing(2)

    preview_top = QLabel(line_one)
    preview_bottom = QLabel(line_two)
    preview_top.setAlignment(Qt.AlignCenter)
    preview_bottom.setAlignment(Qt.AlignCenter)

    if style_key == "tiktok":
        preview_top.setStyleSheet("font-size: 18px; font-weight: 900; color: #ffffff;")
        preview_bottom.setStyleSheet("font-size: 16px; font-weight: 900; color: #ffd400;")
    elif style_key == "youtube":
        preview_top.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #ffffff; "
            "background-color: rgba(0, 0, 0, 255); padding: 4px 8px; border-radius: 7px;"
        )
        preview_bottom.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #ffffff; "
            "background-color: rgba(0, 0, 0, 255); padding: 4px 8px; border-radius: 7px;"
        )
    elif style_key == "short":
        preview_top.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff; letter-spacing: 1px;")
        preview_bottom.setStyleSheet("font-size: 13px; color: #dbe5f3;")
    else:
        preview_top.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff;")
        preview_bottom.setStyleSheet(
            "font-size: 13px; color: #ffffff; background-color: rgba(0, 0, 0, 120); "
            "padding: 3px 8px; border-radius: 7px;"
        )

    preview_layout.addStretch(1)
    preview_layout.addWidget(preview_top)
    preview_layout.addWidget(preview_bottom)
    preview_layout.addStretch(1)

    layout.addWidget(title_label, 0, Qt.AlignCenter)
    layout.addWidget(preview_frame)
    return card


def _build_filter_preset_button(label: str):
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setObjectName("workflowTabBtn")
    btn.setMinimumHeight(32)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return btn


def _build_filter_slider_row(title: str, slider: QSlider, value_label: QLabel):
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)
    title_label = QLabel(title)
    title_label.setObjectName("helperLabel")
    value_label.setObjectName("helperLabel")
    value_label.setMinimumWidth(42)
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    header.addWidget(title_label)
    header.addStretch(1)
    header.addWidget(value_label)
    layout.addLayout(header)
    layout.addWidget(slider)
    return wrapper


def build_start_group(gui, left_layout):
    _build_hidden_status_widgets(gui)

    gui.video_path_edit = QLineEdit()
    gui.video_path_edit.setPlaceholderText("Choose one video to process...")
    gui.video_path_edit.hide()

    gui.final_output_folder_edit = QLineEdit(os.path.join(gui.workspace_root, "output"))
    gui.final_output_folder_edit.setPlaceholderText("Folder to save final results...")
    gui.final_output_folder_edit.hide()

    gui.run_all_btn = QPushButton("Generate")
    gui.run_all_btn.setObjectName("mainActionBtn")
    gui.run_all_btn.clicked.connect(gui.smart_generate)

    gui.export_btn = QPushButton("Export")
    gui.export_btn.setObjectName("mainActionBtn")
    gui.export_btn.clicked.connect(gui.export_final_video)

    gui.preview_5s_btn = QPushButton("Open 5-Second Preview")
    gui.preview_5s_btn.clicked.connect(gui.preview_five_seconds)
    gui.preview_frame_btn = QPushButton("Open Large Frame Preview")
    gui.preview_frame_btn.clicked.connect(gui.preview_exact_frame)
    gui.open_output_btn = QPushButton("Open Results Folder")
    gui.open_output_btn.clicked.connect(lambda: gui.open_folder(gui.final_output_folder_edit.text()))

    gui.stabilize_button(gui.run_all_btn, min_width=240)
    gui.stabilize_button(gui.export_btn, min_width=180)

    workflow_shell, workflow_shell_layout = _section_card()
    workflow_shell_layout.setSpacing(12)

    workflow_title = QLabel("Workflow")
    workflow_title.setObjectName("statusHeadline")
    workflow_shell_layout.addWidget(workflow_title)

    tab_bar = QWidget()
    tab_bar_layout = QGridLayout(tab_bar)
    tab_bar_layout.setContentsMargins(0, 0, 0, 0)
    tab_bar_layout.setHorizontalSpacing(8)
    tab_bar_layout.setVerticalSpacing(8)
    tab_bar_layout.setColumnStretch(0, 1)
    tab_bar_layout.setColumnStretch(1, 1)
    tab_group = QButtonGroup(gui)
    tab_group.setExclusive(True)
    gui.left_panel_stack = QStackedWidget()
    gui.left_panel_stack.setObjectName("leftPanelStack")

    gui.workflow_page_containers = {}
    gui.workflow_page_hints = {}
    gui.workflow_tab_buttons = {}

    def _make_page(page_key: str):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        lock_hint = QLabel("")
        lock_hint.setObjectName("helperLabel")
        lock_hint.setWordWrap(True)
        lock_hint.setVisible(False)
        layout.addWidget(lock_hint)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        layout.addWidget(content)

        gui.workflow_page_containers[page_key] = content
        gui.workflow_page_hints[page_key] = lock_hint
        return page, content_layout

    pages = []
    media_page, media_layout = _make_page("media")
    language_page, language_layout = _make_page("language")
    voice_page, voice_layout = _make_page("voice")
    style_page, style_layout = _make_page("style")
    filter_page, filter_layout = _make_page("filter")
    advanced_page, advanced_layout = _make_page("advanced")
    gui.workflow_advanced_layout = advanced_layout
    pages.extend([media_page, language_page, voice_page, style_page, filter_page, advanced_page])

    def _add_tab(label: str, page_index: int, page_key: str, checked: bool = False):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setMinimumHeight(34)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setObjectName("workflowTabBtn")
        tab_group.addButton(btn)
        row = page_index // 2
        col = page_index % 2
        tab_bar_layout.addWidget(btn, row, col)
        btn.toggled.connect(lambda active, idx=page_index: active and gui.left_panel_stack.setCurrentIndex(idx))
        gui.workflow_tab_buttons[page_key] = btn
        return btn

    _add_tab("Media", 0, "media", checked=True)
    _add_tab("Language", 1, "language")
    _add_tab("Voice", 2, "voice")
    _add_tab("Style", 3, "style")
    _add_tab("Filter", 4, "filter")
    _add_tab("Advanced", 5, "advanced")
    gui.show_progress_btn = QPushButton("Show Progress")
    gui.show_progress_btn.clicked.connect(gui.show_active_progress_dialog)
    gui.show_progress_btn.setVisible(False)
    gui.show_progress_btn.setEnabled(False)
    gui.show_progress_btn.setObjectName("workflowTabBtn")
    gui.show_progress_btn.setMinimumHeight(34)
    gui.show_progress_btn.setMinimumWidth(0)
    gui.show_progress_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    tab_bar_layout.addWidget(gui.show_progress_btn, 3, 0, 1, 2)
    workflow_shell_layout.addWidget(tab_bar)

    upload_card, upload_layout = _build_collapsible_section("Video")
    upload_card.hide()

    output_card, output_layout = _build_collapsible_section("Output")
    output_mode_card, output_mode_layout = _section_card()
    output_mode_title = QLabel("Create")
    output_mode_title.setObjectName("sectionTitle")
    output_mode_layout.addWidget(output_mode_title)
    gui.output_mode_combo = QComboBox()
    gui.output_mode_combo.addItems(
        [
            "Vietnamese subtitles only",
            "Vietnamese voice only",
            "Vietnamese subtitles + voice",
        ]
    )
    gui.output_mode_combo.setCurrentText("Vietnamese subtitles + voice")
    gui.output_mode_combo.hide()
    gui.output_subtitle_radio = QRadioButton("Subtitles only")
    gui.output_voice_radio = QRadioButton("Voice only")
    gui.output_both_radio = QRadioButton("Subtitles + voice")
    gui.output_both_radio.setChecked(True)
    gui.output_mode_group = QButtonGroup(gui)
    gui.output_mode_group.addButton(gui.output_subtitle_radio)
    gui.output_mode_group.addButton(gui.output_voice_radio)
    gui.output_mode_group.addButton(gui.output_both_radio)
    gui.output_subtitle_radio.toggled.connect(
        lambda checked: checked and gui.output_mode_combo.setCurrentText("Vietnamese subtitles only")
    )
    gui.output_voice_radio.toggled.connect(
        lambda checked: checked and gui.output_mode_combo.setCurrentText("Vietnamese voice only")
    )
    gui.output_both_radio.toggled.connect(
        lambda checked: checked and gui.output_mode_combo.setCurrentText("Vietnamese subtitles + voice")
    )
    output_mode_layout.addWidget(gui.output_subtitle_radio)
    output_mode_layout.addWidget(gui.output_voice_radio)
    output_mode_layout.addWidget(gui.output_both_radio)
    output_layout.addWidget(output_mode_card)

    output_quality_card, output_quality_layout = _section_card()
    output_quality_title = QLabel("Quality")
    output_quality_title.setObjectName("sectionTitle")
    output_quality_layout.addWidget(output_quality_title)
    gui.output_quality_combo = QComboBox()
    gui.output_quality_combo.addItem("Max (source)", "source")
    gui.output_quality_combo.addItem("720p", "720p")
    gui.output_quality_combo.addItem("1080p (Full HD)", "1080p")
    gui.output_quality_combo.addItem("1440p (2K)", "1440p")
    gui.output_quality_combo.addItem("2160p (4K)", "2160p")
    output_quality_layout.addWidget(gui.output_quality_combo)
    output_fps_row = QVBoxLayout()
    output_fps_row.addWidget(QLabel("Frame rate"))
    gui.output_fps_combo = QComboBox()
    gui.output_fps_combo.addItem("Source (Recommended)", "source")
    gui.output_fps_combo.addItem("24 FPS", "24")
    gui.output_fps_combo.addItem("30 FPS", "30")
    gui.output_fps_combo.addItem("60 FPS", "60")
    output_fps_row.addWidget(gui.output_fps_combo)
    output_quality_layout.addLayout(output_fps_row)
    output_ratio_row = QVBoxLayout()
    output_ratio_row.addWidget(QLabel("Ratio"))
    gui.output_ratio_combo = QComboBox()
    gui.output_ratio_combo.addItem("Source (Recommended)", "source")
    gui.output_ratio_combo.addItem("16:9", "16:9")
    gui.output_ratio_combo.addItem("9:16", "9:16")
    gui.output_ratio_combo.addItem("1:1", "1:1")
    gui.output_ratio_combo.addItem("4:3", "4:3")
    gui.output_ratio_combo.currentIndexChanged.connect(gui.on_output_ratio_changed)
    output_ratio_row.addWidget(gui.output_ratio_combo)
    output_quality_layout.addLayout(output_ratio_row)
    output_scale_row = QVBoxLayout()
    output_scale_row.addWidget(QLabel("Canvas"))
    gui.output_scale_mode_combo = QComboBox()
    gui.output_scale_mode_combo.addItem("Fit", "fit")
    gui.output_scale_mode_combo.addItem("Fill", "fill")
    gui.output_scale_mode_combo.currentIndexChanged.connect(gui.on_output_scale_mode_changed)
    output_scale_row.addWidget(gui.output_scale_mode_combo)
    gui.reset_framing_btn = QPushButton("Reset Framing")
    gui.reset_framing_btn.setToolTip("Reset the fill focus to center")
    gui.reset_framing_btn.hide()
    output_scale_row.addWidget(gui.reset_framing_btn)
    output_quality_layout.addLayout(output_scale_row)
    output_layout.addWidget(output_quality_card)
    media_layout.addWidget(output_card)

    language_card, language_layout = _build_collapsible_section("Language")
    gui.lang_whisper_combo = QComboBox()
    gui.lang_whisper_combo.addItem("Auto Detect", "auto")
    gui.lang_whisper_combo.addItem("Chinese", "zh")
    gui.lang_whisper_combo.addItem("Japanese", "ja")
    gui.lang_whisper_combo.addItem("Korean", "ko")
    gui.lang_whisper_combo.addItem("English", "en")
    gui.lang_target_combo = QComboBox()
    gui.lang_target_combo.addItem("Vietnamese", "vi")
    gui.lang_target_combo.setCurrentIndex(0)
    language_pair_card, language_pair_layout = _section_card()
    language_pair_title = QLabel("Language Pair")
    language_pair_title.setObjectName("sectionTitle")
    language_pair_layout.addWidget(language_pair_title)
    source_row = QVBoxLayout()
    source_row.addWidget(QLabel("Original language"))
    source_row.addWidget(gui.lang_whisper_combo)
    target_row = QVBoxLayout()
    target_row.addWidget(QLabel("Translate to"))
    target_row.addWidget(gui.lang_target_combo)
    language_pair_layout.addLayout(source_row)
    language_pair_layout.addLayout(target_row)

    gui.skip_translation_cb = QCheckBox("Keep original text (skip translation)")
    gui.skip_translation_cb.setChecked(False)
    language_pair_layout.addWidget(gui.skip_translation_cb)
    language_layout.addWidget(language_pair_card)

    def toggle_translation_fields(checked):
        gui.lang_target_combo.setEnabled(not checked)

    gui.skip_translation_cb.toggled.connect(toggle_translation_fields)

    language_page.layout().addWidget(language_card)

    voice_card, voice_layout = _build_collapsible_section("Voice")
    gui.voice_section_card = voice_card
    gui.voice_engine_combo = QComboBox()
    gui.voice_engine_combo.addItem("Fast Voice", "fast")
    gui.free_voice_combo = QComboBox()
    gui.voice_gender_combo = QComboBox()
    gui.voice_gender_combo.addItems(["Any", "Male", "Female"])
    gui.voice_gender_combo.currentTextChanged.connect(gui.on_voice_gender_changed)
    gui.voice_speed_spin = QComboBox()
    gui.voice_speed_spin.setEditable(True)
    gui.voice_speed_spin.addItems(["0.8x", "0.9x", "1.0x", "1.1x", "1.2x", "1.3x", "1.4x", "1.5x", "1.6x", "1.8x", "2.0x"])
    gui.voice_speed_spin.setCurrentText("1.0x")
    gui.voice_timing_sync_combo = QComboBox()
    gui.voice_timing_sync_combo.addItems(["Off", "Smart", "Force"])
    gui.voice_timing_sync_combo.setCurrentText("Smart")
    gui.audio_handling_combo = QComboBox()
    gui.audio_handling_combo.addItem("Fast (recommended)", "fast")
    gui.audio_handling_combo.addItem("Cleaner voice", "clean")
    gui.audio_handling_combo.setCurrentIndex(0)
    gui.audio_handling_hint_label = QLabel("Fast keeps things quick. Cleaner voice removes more background noise before voice generation.", gui)
    gui.audio_handling_hint_label.setObjectName("helperLabel")
    gui.audio_handling_hint_label.setWordWrap(True)
    gui.audio_handling_hint_label.hide()
    gui.free_voice_combo.currentIndexChanged.connect(gui.on_selected_voice_changed)
    gui.voice_engine_combo.currentIndexChanged.connect(gui.on_voice_engine_changed)
    gui.preview_voice_btn = QPushButton("Preview Selected Voice")
    gui.preview_voice_btn.clicked.connect(gui.preview_selected_voice_sample)
    gui.voice_preview_meta_label = QLabel("Listen to a short sample before generating the full voice track.", gui)
    gui.voice_preview_meta_label.setObjectName("helperLabel")
    gui.voice_preview_meta_label.setWordWrap(True)
    gui.voice_preview_meta_label.hide()
    voice_setup_card, voice_setup_layout = _section_card()
    voice_setup_title = QLabel("Voice Setup")
    voice_setup_title.setObjectName("sectionTitle")
    voice_setup_layout.addWidget(voice_setup_title)
    voice_setup_layout.addWidget(QLabel("Voice engine"))
    voice_setup_layout.addWidget(gui.voice_engine_combo)
    gui.fast_voice_panel = QWidget()
    fast_voice_layout = QVBoxLayout(gui.fast_voice_panel)
    fast_voice_layout.setContentsMargins(0, 0, 0, 0)
    fast_voice_layout.setSpacing(8)
    fast_voice_layout.addWidget(QLabel("Fast voice"))
    fast_voice_layout.addWidget(gui.free_voice_combo)
    fast_voice_layout.addWidget(QLabel("Voice type"))
    fast_voice_layout.addWidget(gui.voice_gender_combo)
    voice_setup_layout.addWidget(gui.fast_voice_panel)
    gui.ai_dubbing_rewrite_cb = QCheckBox("Use AI Rewrite Dubbing for voice timing")
    gui.ai_dubbing_rewrite_cb.setChecked(False)
    gui.ai_dubbing_rewrite_hint_label = QLabel(
        "Keeps subtitle text readable, but lets AI create a shorter spoken version for TTS when timing is tight.",
        gui,
    )
    gui.ai_dubbing_rewrite_hint_label.setObjectName("helperLabel")
    gui.ai_dubbing_rewrite_hint_label.setWordWrap(True)
    voice_layout.addWidget(voice_setup_card)

    voice_preview_card, voice_preview_layout = _section_card()
    voice_preview_title = QLabel("Preview")
    voice_preview_title.setObjectName("sectionTitle")
    voice_preview_layout.addWidget(voice_preview_title)
    voice_preview_layout.addWidget(gui.preview_voice_btn)
    voice_layout.addWidget(voice_preview_card)
    voice_page.layout().addWidget(voice_card)

    subtitle_card, subtitle_layout = _build_collapsible_section("Subtitle Style", start_expanded=True)
    base_style_label = QLabel("Presets")
    base_style_label.setObjectName("sectionTitle")
    subtitle_layout.addWidget(base_style_label)
    gui.subtitle_preset_tiktok_radio = QRadioButton("TikTok")
    gui.subtitle_preset_youtube_radio = QRadioButton("YouTube")
    gui.subtitle_preset_minimal_radio = QRadioButton("Short")
    gui.subtitle_preset_custom_radio = QRadioButton("Custom")
    gui.subtitle_preset_tiktok_radio.setChecked(True)
    gui.subtitle_preset_group = QButtonGroup(gui)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_tiktok_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_youtube_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_minimal_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_custom_radio)

    preset_grid = QGridLayout()
    preset_grid.setContentsMargins(0, 0, 0, 0)
    preset_grid.setHorizontalSpacing(8)
    preset_grid.setVerticalSpacing(8)
    preset_grid.setColumnStretch(0, 1)
    preset_grid.setColumnStretch(1, 1)
    preset_grid.addWidget(_build_style_preset_card("TikTok", "TRENDING", "WORDS POP", gui.subtitle_preset_tiktok_radio), 0, 0)
    preset_grid.addWidget(_build_style_preset_card("YouTube", "Clean subtitle", "with solid box", gui.subtitle_preset_youtube_radio), 0, 1)
    preset_grid.addWidget(_build_style_preset_card("Short", "HELLO", "world", gui.subtitle_preset_minimal_radio), 1, 0)
    preset_grid.addWidget(_build_style_preset_card("Custom", "My", "style", gui.subtitle_preset_custom_radio), 1, 1)
    subtitle_layout.addLayout(preset_grid)

    style_library_card, style_library_layout = _section_card()
    style_library_title = QLabel("Saved Styles")
    style_library_title.setObjectName("sectionTitle")
    style_library_layout.addWidget(style_library_title)
    gui.save_subtitle_style_btn = QPushButton("+ Save This Style")
    gui.save_subtitle_style_btn.clicked.connect(gui.save_current_subtitle_style_preset)
    gui.saved_subtitle_style_combo = QComboBox()
    gui.saved_subtitle_style_combo.addItem("My Presets")
    gui.saved_subtitle_style_combo.currentIndexChanged.connect(gui.load_selected_subtitle_style_preset)
    style_library_layout.addWidget(gui.save_subtitle_style_btn)
    style_library_layout.addWidget(gui.saved_subtitle_style_combo)
    subtitle_layout.addWidget(style_library_card)
    gui.style_library_card = style_library_card

    highlight_card, highlight_card_layout = _build_collapsible_section("Keyword Highlight", start_expanded=False)
    gui.subtitle_keyword_highlight_cb = QCheckBox("Highlight key words")
    gui.subtitle_keyword_highlight_cb.setChecked(False)
    gui.subtitle_highlight_color_combo = QComboBox()
    gui.subtitle_highlight_color_combo.addItems(["Yellow", "Cyan", "Green", "Pink"])
    gui.subtitle_highlight_mode_combo = QComboBox()
    gui.subtitle_highlight_mode_combo.addItems(["Auto", "Manual", "Auto + Manual"])
    highlight_card_layout.addWidget(gui.subtitle_keyword_highlight_cb)

    highlight_color_row = QHBoxLayout()
    highlight_color_row.addWidget(QLabel("Color:"))
    highlight_color_row.addWidget(gui.subtitle_highlight_color_combo, 1)
    highlight_card_layout.addLayout(highlight_color_row)

    highlight_mode_row = QHBoxLayout()
    highlight_mode_row.addWidget(QLabel("Source:"))
    highlight_mode_row.addWidget(gui.subtitle_highlight_mode_combo, 1)
    highlight_card_layout.addLayout(highlight_mode_row)
    subtitle_layout.addWidget(highlight_card)
    gui.highlight_card = highlight_card

    position_card, position_layout = _build_collapsible_section("Text Position", start_expanded=False)
    position_wrapper = QFrame()
    position_wrapper.setObjectName("statusCard")
    position_wrapper_layout = QVBoxLayout(position_wrapper)
    position_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    position_wrapper_layout.setSpacing(10)

    position_grid = QGridLayout()
    position_grid.setContentsMargins(0, 0, 0, 0)
    position_grid.setHorizontalSpacing(10)
    position_grid.setVerticalSpacing(8)

    gui.subtitle_position_mode_combo = QComboBox()
    gui.subtitle_position_mode_combo.addItem("Quick placement", "anchor")
    gui.subtitle_position_mode_combo.addItem("Custom X/Y", "custom")
    gui.subtitle_align_label = QLabel("Placement:")
    gui.subtitle_align_combo = QComboBox()
    gui.subtitle_align_combo.addItems(["Bottom", "Bottom Left", "Bottom Right", "Center", "Top"])
    gui.subtitle_align_combo.setCurrentText("Bottom")
    gui.subtitle_custom_x_label = QLabel("Custom X:")
    gui.subtitle_custom_x_spin = QSpinBox()
    gui.subtitle_custom_x_spin.setRange(0, 100)
    gui.subtitle_custom_x_spin.setValue(50)
    gui.subtitle_custom_x_spin.setSuffix(" %")
    gui.subtitle_custom_y_label = QLabel("Custom Y:")
    gui.subtitle_custom_y_spin = QSpinBox()
    gui.subtitle_custom_y_spin.setRange(0, 100)
    gui.subtitle_custom_y_spin.setValue(86)
    gui.subtitle_custom_y_spin.setSuffix(" %")
    gui.subtitle_bottom_offset_label = QLabel("Vertical Offset:")
    gui.subtitle_bottom_offset_spin = QSpinBox()
    gui.subtitle_bottom_offset_spin.setRange(0, 300)
    gui.subtitle_bottom_offset_spin.setValue(30)
    gui.subtitle_bottom_offset_spin.setSuffix(" px")

    position_grid.addWidget(QLabel("Placement mode:"), 0, 0)
    position_grid.addWidget(gui.subtitle_position_mode_combo, 0, 1)
    position_grid.addWidget(gui.subtitle_align_label, 1, 0)
    position_grid.addWidget(gui.subtitle_align_combo, 1, 1)
    position_grid.addWidget(gui.subtitle_custom_x_label, 2, 0)
    position_grid.addWidget(gui.subtitle_custom_x_spin, 2, 1)
    position_grid.addWidget(gui.subtitle_custom_y_label, 3, 0)
    position_grid.addWidget(gui.subtitle_custom_y_spin, 3, 1)
    position_grid.addWidget(gui.subtitle_bottom_offset_label, 4, 0)
    position_grid.addWidget(gui.subtitle_bottom_offset_spin, 4, 1)

    position_wrapper_layout.addLayout(position_grid)
    position_layout.addWidget(position_wrapper)
    subtitle_layout.addWidget(position_card)
    gui.subtitle_position_card = position_card

    timing_card, timing_layout = _build_collapsible_section("Animation & Timing", start_expanded=False)
    timing_wrapper = QFrame()
    timing_wrapper.setObjectName("statusCard")
    timing_wrapper_layout = QVBoxLayout(timing_wrapper)
    timing_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    timing_wrapper_layout.setSpacing(10)

    timing_grid = QGridLayout()
    timing_grid.setContentsMargins(0, 0, 0, 0)
    timing_grid.setHorizontalSpacing(10)
    timing_grid.setVerticalSpacing(8)

    custom_title_card, custom_title_layout = _build_collapsible_section("Text Style", start_expanded=False)
    custom_wrapper = QFrame()
    custom_wrapper.setObjectName("statusCard")
    custom_wrapper_layout = QVBoxLayout(custom_wrapper)
    custom_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    custom_wrapper_layout.setSpacing(10)
    gui.custom_settings_toggle_btn = QToolButton()
    gui.custom_settings_toggle_btn.setText("▼ Style Details")
    gui.custom_settings_toggle_btn.setCheckable(True)
    gui.custom_settings_toggle_btn.setChecked(True)
    gui.custom_settings_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
    gui.custom_settings_toggle_btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #dbe5f3; border: none; padding: 0; }")
    custom_wrapper_layout.addWidget(gui.custom_settings_toggle_btn)

    gui.custom_settings_content = QWidget()
    custom_controls_layout = QGridLayout(gui.custom_settings_content)
    custom_controls_layout.setContentsMargins(0, 0, 0, 0)
    custom_controls_layout.setHorizontalSpacing(10)
    custom_controls_layout.setVerticalSpacing(8)

    gui.subtitle_font_combo = QComboBox()
    gui.subtitle_font_combo.setEditable(True)
    gui.subtitle_font_combo.addItems(["Montserrat", "Roboto", "Inter", "Poppins", "Arial", "Segoe UI", "Tahoma", "Verdana", "Times New Roman"])
    gui.subtitle_font_combo.setCurrentText("Segoe UI")
    gui.subtitle_font_size_spin = QSpinBox()
    gui.subtitle_font_size_spin.setRange(12, 72)
    gui.subtitle_font_size_spin.setValue(60)
    gui.subtitle_color_btn = QPushButton("White")
    gui.subtitle_color_hex = "#FFFFFF"
    gui.subtitle_color_btn.clicked.connect(gui.choose_subtitle_color)
    gui.subtitle_background_color_btn = QPushButton("#000000")
    gui.subtitle_background_color_hex = "#000000"
    gui.subtitle_background_color_btn.clicked.connect(gui.choose_subtitle_background_color)
    gui.subtitle_background_cb = QCheckBox("Background Box")
    gui.subtitle_background_cb.setChecked(False)
    gui.subtitle_outline_cb = QCheckBox("Text Outline")
    gui.subtitle_outline_cb.setChecked(True)
    gui.subtitle_bold_cb = QCheckBox("Bold")
    gui.subtitle_bold_cb.setChecked(True)
    gui.subtitle_single_line_cb = QCheckBox("Single-line subtitle (Netflix)")
    gui.subtitle_single_line_cb.setChecked(False)
    gui.subtitle_animation_combo = QComboBox()
    gui.subtitle_animation_combo.addItems(
        ["Static", "Pop In", "Slide Up", "Fade In", "Fade Out", "Pulse", "Background Appear", "Typewriter", "Word Highlight Karaoke"]
    )
    gui.subtitle_animation_combo.setCurrentText("Pop In")
    gui.subtitle_animation_combo.currentTextChanged.connect(lambda _value: gui.on_subtitle_animation_changed())
    gui.subtitle_animation_time_spin = QDoubleSpinBox()
    gui.subtitle_animation_time_spin.setRange(0.1, 2.5)
    gui.subtitle_animation_time_spin.setSingleStep(0.05)
    gui.subtitle_animation_time_spin.setDecimals(2)
    gui.subtitle_animation_time_spin.setValue(0.22)
    gui.subtitle_animation_time_spin.setSuffix(" s")
    gui.subtitle_animation_time_label = QLabel("Duration")
    gui.subtitle_bg_alpha_spin = QDoubleSpinBox()
    gui.subtitle_bg_alpha_spin.setRange(0.0, 1.0)
    gui.subtitle_bg_alpha_spin.setSingleStep(0.05)
    gui.subtitle_bg_alpha_spin.setDecimals(2)
    gui.subtitle_bg_alpha_spin.setValue(0.6)
    gui.subtitle_bg_alpha_spin.setSuffix(" alpha")
    gui.subtitle_karaoke_timing_label = QLabel("Text Timing")
    gui.subtitle_karaoke_timing_combo = QComboBox()
    gui.subtitle_karaoke_timing_combo.addItem("Vietnamese pacing", "vietnamese")
    gui.subtitle_karaoke_timing_combo.addItem("Source speech timing", "source")
    gui.subtitle_karaoke_timing_combo.setCurrentIndex(0)
    gui.subtitle_karaoke_timing_combo.currentTextChanged.connect(lambda _value: gui.update_subtitle_preview_style())

    custom_controls_layout.addWidget(QLabel("Font:"), 0, 0)
    custom_controls_layout.addWidget(gui.subtitle_font_combo, 0, 1)
    custom_controls_layout.addWidget(QLabel("Size:"), 1, 0)
    custom_controls_layout.addWidget(gui.subtitle_font_size_spin, 1, 1)
    custom_controls_layout.addWidget(QLabel("Text Color:"), 2, 0)
    custom_controls_layout.addWidget(gui.subtitle_color_btn, 2, 1)
    custom_controls_layout.addWidget(QLabel("Background color:"), 3, 0)
    custom_controls_layout.addWidget(gui.subtitle_background_color_btn, 3, 1)
    custom_controls_layout.addWidget(QLabel("Background opacity:"), 4, 0)
    custom_controls_layout.addWidget(gui.subtitle_bg_alpha_spin, 4, 1)
    custom_controls_layout.addWidget(gui.subtitle_background_cb, 5, 0)
    custom_controls_layout.addWidget(gui.subtitle_outline_cb, 5, 1)
    custom_controls_layout.addWidget(gui.subtitle_bold_cb, 6, 0)
    custom_controls_layout.addWidget(gui.subtitle_single_line_cb, 6, 1)
    custom_wrapper_layout.addWidget(gui.custom_settings_content)
    custom_title_layout.addWidget(custom_wrapper)
    subtitle_layout.addWidget(custom_title_card)
    gui.custom_title_card = custom_title_card

    timing_grid.addWidget(QLabel("Animation:"), 0, 0)
    timing_grid.addWidget(gui.subtitle_animation_combo, 0, 1)
    timing_grid.addWidget(gui.subtitle_animation_time_label, 1, 0)
    timing_grid.addWidget(gui.subtitle_animation_time_spin, 1, 1)
    timing_grid.addWidget(gui.subtitle_karaoke_timing_label, 2, 0)
    timing_grid.addWidget(gui.subtitle_karaoke_timing_combo, 2, 1)

    timing_wrapper_layout.addLayout(timing_grid)
    timing_layout.addWidget(timing_wrapper)
    subtitle_layout.addWidget(timing_card)
    gui.subtitle_timing_card = timing_card

    gui.subtitle_preset_summary_label = QLabel()
    gui.subtitle_preset_summary_label.setObjectName("helperLabel")
    gui.subtitle_preset_summary_label.setWordWrap(True)
    gui.subtitle_preset_summary_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    gui.subtitle_preset_summary_label.setTextInteractionFlags(Qt.NoTextInteraction)
    subtitle_layout.addWidget(gui.subtitle_preset_summary_label)

    gui.subtitle_x_offset_spin = QSpinBox()
    gui.subtitle_x_offset_spin.setRange(-400, 400)
    gui.subtitle_x_offset_spin.setValue(0)
    gui.subtitle_x_offset_spin.hide()

    def _toggle_custom_section(checked: bool):
        gui.custom_settings_toggle_btn.setText(("▼ " if checked else "▶ ") + "Style Details")
        gui.custom_settings_content.setVisible(checked)

    gui.custom_settings_toggle_btn.toggled.connect(_toggle_custom_section)
    style_page.layout().addWidget(subtitle_card)

    filter_shell, filter_shell_layout = _build_collapsible_section("Video Filter")
    filter_presets_card, filter_presets_layout = _section_card()
    filter_presets_title = QLabel("Preset")
    filter_presets_title.setObjectName("sectionTitle")
    filter_presets_layout.addWidget(filter_presets_title)
    filter_preset_grid = QGridLayout()
    filter_preset_grid.setContentsMargins(0, 0, 0, 0)
    filter_preset_grid.setHorizontalSpacing(8)
    filter_preset_grid.setVerticalSpacing(8)
    gui.video_filter_preset_group = QButtonGroup(gui)
    gui.video_filter_preset_group.setExclusive(True)
    gui.video_filter_preset_buttons = {}
    for idx, (preset_key, preset_label) in enumerate([
        ("original", "Original"),
        ("bright", "Bright"),
        ("warm", "Warm"),
        ("vivid", "Vivid"),
        ("cool", "Cool"),
        ("soft", "Soft"),
    ]):
        btn = _build_filter_preset_button(preset_label)
        btn.setChecked(preset_key == "original")
        btn.clicked.connect(lambda _checked=False, key=preset_key: gui.on_video_filter_preset_selected(key))
        gui.video_filter_preset_group.addButton(btn)
        gui.video_filter_preset_buttons[preset_key] = btn
        filter_preset_grid.addWidget(btn, idx // 3, idx % 3)
    filter_presets_layout.addLayout(filter_preset_grid)
    filter_shell_layout.addWidget(filter_presets_card)

    intensity_card, intensity_layout = _section_card()
    intensity_title = QLabel("Intensity")
    intensity_title.setObjectName("sectionTitle")
    intensity_layout.addWidget(intensity_title)
    intensity_header = QHBoxLayout()
    intensity_header.setContentsMargins(0, 0, 0, 0)
    intensity_header.setSpacing(8)
    intensity_hint = QLabel("Preset strength")
    intensity_hint.setObjectName("helperLabel")
    gui.video_filter_intensity_value_label = QLabel("75")
    gui.video_filter_intensity_value_label.setObjectName("helperLabel")
    gui.video_filter_intensity_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    intensity_header.addWidget(intensity_hint)
    intensity_header.addStretch(1)
    intensity_header.addWidget(gui.video_filter_intensity_value_label)
    intensity_layout.addLayout(intensity_header)
    gui.video_filter_intensity_slider = QSlider(Qt.Horizontal)
    gui.video_filter_intensity_slider.setRange(0, 100)
    gui.video_filter_intensity_slider.setValue(75)
    gui.video_filter_intensity_slider.valueChanged.connect(gui.on_video_filter_intensity_changed)
    gui.video_filter_intensity_slider.sliderReleased.connect(gui.on_video_filter_slider_released)
    intensity_layout.addWidget(gui.video_filter_intensity_slider)
    filter_shell_layout.addWidget(intensity_card)

    adjust_card, adjust_layout = _section_card()
    adjust_title = QLabel("Adjust")
    adjust_title.setObjectName("sectionTitle")
    adjust_layout.addWidget(adjust_title)
    gui.video_filter_adjust_sliders = {}
    gui.video_filter_adjust_value_labels = {}
    for field_key, field_label in (
        ("brightness", "Brightness"),
        ("contrast", "Contrast"),
        ("saturation", "Saturation"),
        ("temperature", "Temperature"),
        ("highlights", "Highlights"),
        ("shadows", "Shadows"),
    ):
        value_label = QLabel("0")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(-100, 100)
        slider.setValue(0)
        slider.valueChanged.connect(lambda value, key=field_key: gui.on_video_filter_adjust_changed(key, value))
        slider.sliderReleased.connect(gui.on_video_filter_slider_released)
        gui.video_filter_adjust_sliders[field_key] = slider
        gui.video_filter_adjust_value_labels[field_key] = value_label
        adjust_layout.addWidget(_build_filter_slider_row(field_label, slider, value_label))
    gui.video_filter_reset_adjust_btn = QPushButton("Reset Adjust")
    gui.video_filter_reset_adjust_btn.clicked.connect(gui.reset_video_filter_adjustments)
    gui.video_filter_reset_btn = QPushButton("Reset All")
    gui.video_filter_reset_btn.clicked.connect(gui.reset_video_filters)
    filter_action_row = QHBoxLayout()
    filter_action_row.setContentsMargins(0, 0, 0, 0)
    filter_action_row.setSpacing(8)
    filter_action_row.addStretch(1)
    gui.video_filter_apply_btn = QPushButton("Apply Filter")
    gui.video_filter_apply_btn.clicked.connect(gui.apply_current_video_filter)
    filter_action_row.addWidget(gui.video_filter_apply_btn)
    filter_action_row.addWidget(gui.video_filter_reset_adjust_btn)
    filter_action_row.addWidget(gui.video_filter_reset_btn)
    adjust_layout.addLayout(filter_action_row)
    gui.video_filter_render_status_label = QLabel("")
    gui.video_filter_render_status_label.setObjectName("helperLabel")
    gui.video_filter_render_status_label.setWordWrap(True)
    gui.video_filter_render_status_label.hide()
    adjust_layout.addWidget(gui.video_filter_render_status_label)
    gui.video_filter_render_progress = QProgressBar()
    gui.video_filter_render_progress.setRange(0, 0)
    gui.video_filter_render_progress.setTextVisible(False)
    gui.video_filter_render_progress.setFixedHeight(6)
    gui.video_filter_render_progress.hide()
    adjust_layout.addWidget(gui.video_filter_render_progress)
    filter_shell_layout.addWidget(adjust_card)
    filter_page.layout().addWidget(filter_shell)

    for page in pages:
        page.layout().addStretch()
        gui.left_panel_stack.addWidget(page)

    workflow_shell_layout.addWidget(gui.left_panel_stack, 1)
    left_layout.addWidget(workflow_shell)


def build_workflow_group(left_layout):
    return None







