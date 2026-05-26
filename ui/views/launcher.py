import hashlib
import os
import json
import time

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _recent_projects_path():
    return os.path.join(os.path.dirname(__file__), "..", "..", "recent_projects.json")


def _load_recent_projects(settings=None):
    path = _recent_projects_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_recent_projects(settings, projects):
    path = _recent_projects_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)


def _extract_thumbnail(video_path: str, output_path: str) -> str:
    if not os.path.exists(video_path):
        return ""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    import subprocess
    try:
        subprocess.run(
            [_ffmpeg_path(), "-y", "-i", video_path, "-vframes", "1", "-q:v", "3",
             "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
             output_path],
            capture_output=True, timeout=30,
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception:
        pass
    return ""


def _ffmpeg_path():
    from runtime_paths import bin_path
    return os.path.join(bin_path(), "ffmpeg", "ffmpeg.exe")


class ProjectCard(QFrame):
    def __init__(self, video_path: str, thumbnail_cache_dir: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.setObjectName("statusCard")
        self.setFixedSize(220, 180)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("ProjectCard:hover { border: 2px solid #4ecdc4; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(204, 115)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #0d1220; border-radius: 6px;")

        thumb_path = os.path.join(thumbnail_cache_dir, _thumbnail_name(video_path))
        if not os.path.exists(thumb_path):
            thumb_path = _extract_thumbnail(video_path, thumb_path)
        if os.path.exists(thumb_path):
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                self.thumb_label.setPixmap(pixmap.scaled(204, 115, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb_label.setText("No Preview")

        layout.addWidget(self.thumb_label)

        self.name_label = QLabel(os.path.basename(video_path))
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(36)
        self.name_label.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.name_label)

    def mousePressEvent(self, event):
        self.window().selected_video = self.video_path
        self.window().accept()


def _extract_waveform_audio(video_path: str, temp_root: str) -> str:
    video_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:12]
    audio_path = os.path.join(temp_root, f"waveform_{video_hash}.wav")
    if os.path.exists(audio_path):
        return audio_path
    if not os.path.exists(video_path):
        return ""
    os.makedirs(os.path.dirname(audio_path) or ".", exist_ok=True)
    import subprocess
    try:
        subprocess.run(
            [_ffmpeg_path(), "-y", "-loglevel", "error", "-i", video_path,
             "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
            check=True, timeout=60,
        )
        print(f"[Launcher] Waveform audio extracted: {audio_path}")
    except Exception as exc:
        print(f"[Launcher] Waveform extract failed: {exc}")
        return ""
    return audio_path if os.path.exists(audio_path) else ""


class LauncherWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.selected_video = ""
        self._thumbnail_dir = os.path.join(os.path.dirname(__file__), "..", "..", "temp", "launcher_thumbs")

        self.setWindowTitle("CapCap - Video Translator")
        self.setMinimumSize(720, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #0a101e;
                color: #cfe6ff;
            }
            #statusCard {
                background-color: #0f1928;
                border: 1px solid #1e3045;
                border-radius: 8px;
            }
        """)

        self._build_ui()
        self._load_recent()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("CapCap")
        title.setStyleSheet("font-size: 26px; font-weight: 800; color: #ffffff;")
        subtitle = QLabel("Video Translation & Voiceover Studio")
        subtitle.setStyleSheet("font-size: 12px; color: #6ee7d6;")

        header_text = QVBoxLayout()
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text, 1)

        self.new_btn = QPushButton("+ New Project")
        self.new_btn.setMinimumHeight(44)
        self.new_btn.setMinimumWidth(150)
        self.new_btn.setStyleSheet("""
            QPushButton {
                background-color: #4ecdc4;
                color: #0a101e;
                font-weight: 700;
                font-size: 14px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background-color: #6ee7d6;
            }
        """)
        self.new_btn.clicked.connect(self._on_new_project)
        header.addWidget(self.new_btn)
        root.addLayout(header)

        self.section_label = QLabel("Recent Projects")
        self.section_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #8ad7ff;")
        root.addWidget(self.section_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        scroll.setWidget(self.grid_widget)
        root.addWidget(scroll, 1)

        self.empty_label = QLabel("No recent projects. Click \"+ New Project\" to start.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #556677; font-size: 13px;")
        self.empty_label.hide()
        root.addWidget(self.empty_label)

        self.loading_label = QLabel("Preparing video...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color: #4ecdc4; font-size: 16px; font-weight: 700; padding: 20px;")
        self.loading_label.hide()
        root.addWidget(self.loading_label)

    def accept(self):
        if not self.selected_video or not os.path.exists(self.selected_video):
            super().accept()
            return
        self.loading_label.show()
        self.new_btn.setEnabled(False)
        self._extraction_done = False
        import threading
        def _preprocess():
            from runtime_paths import workspace_root
            temp_root = os.path.join(workspace_root(), "temp")
            _extract_waveform_audio(self.selected_video, temp_root)
            self._extraction_done = True
        threading.Thread(target=_preprocess, daemon=True).start()
        self._loader_timer = QTimer()
        self._loader_timer.timeout.connect(self._on_loader_tick)
        self._loader_timer.start(200)

    def _on_loader_tick(self):
        if not getattr(self, "_extraction_done", False):
            return
        self._loader_timer.stop()
        self._finish_accept()

    def _finish_accept(self):
        self.loading_label.hide()
        self.new_btn.setEnabled(True)
        super().accept()

    def _load_recent(self):
        projects = _load_recent_projects()
        os.makedirs(self._thumbnail_dir, exist_ok=True)

        for i in reversed(range(self.grid.count())):
            widget = self.grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        existing = [p for p in projects if os.path.exists(p.get("video_path", ""))]
        if existing != projects:
            _save_recent_projects(None, existing)

        if not existing:
            self.empty_label.show()
            return
        self.empty_label.hide()

        columns = max(1, (self.grid_widget.width() - 24) // 232)
        for i, proj in enumerate(existing):
            card = ProjectCard(proj["video_path"], self._thumbnail_dir, self)
            row, col = divmod(i, max(1, columns))
            self.grid.addWidget(card, row, col)

    def _on_new_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm);;All Files (*)"
        )
        if path:
            self.selected_video = path
            self.accept()

    @staticmethod
    def add_recent(settings_or_none, video_path: str):
        video_path = os.path.normpath(video_path)
        projects = _load_recent_projects()
        projects = [p for p in projects if os.path.exists(p.get("video_path", ""))]
        existing = [p for p in projects if os.path.normpath(p.get("video_path", "")) == video_path]
        if existing:
            projects.remove(existing[0])
        projects.insert(0, {
            "video_path": video_path,
            "opened_at": int(time.time()),
        })
        projects = projects[:12]
        _save_recent_projects(None, projects)


def _thumbnail_name(video_path: str) -> str:
    import hashlib
    h = hashlib.md5(video_path.encode()).hexdigest()
    return f"{h}.jpg"


def show_launcher(settings_or_none) -> str:
    """Show launcher, return selected video path or empty string."""
    w = LauncherWindow()
    if w.exec() == QDialog.Accepted:
        return w.selected_video
    return ""
