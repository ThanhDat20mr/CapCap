import hashlib
import os
import json
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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


def _get_video_duration(video_path: str) -> float:
    try:
        import subprocess
        ffprobe = _ffmpeg_path().replace("ffmpeg.exe", "ffprobe.exe")
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return float(result.stdout.strip() or 0)
    except Exception:
        pass
    return 0.0


MSG_STYLE = """
    QMessageBox { background-color: #0f1724; }
    QLabel { color: #d7e3f4; }
    QPushButton { background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
        border-radius: 8px; padding: 6px 16px; font-weight: 600; }
    QPushButton:hover { background-color: #29405d; }
"""


class ProjectCard(QFrame):
    def __init__(self, video_path: str, thumbnail_cache_dir: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self._orig_pixmap = None
        self.setObjectName("statusCard")
        self.setMinimumSize(180, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("ProjectCard:hover { border: 2px solid #4ecdc4; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumb_label = QLabel()
        self.thumb_label.setMinimumSize(160, 120)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #0d1220; border-radius: 6px;")
        self.thumb_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout.addWidget(self.thumb_label)

        self.name_label = QLabel(os.path.basename(video_path))
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(36)
        self.name_label.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: 600;")
        layout.addWidget(self.name_label)

        self._load_thumb(thumbnail_cache_dir)

    def _load_thumb(self, cache_dir):
        thumb_path = os.path.join(cache_dir, _thumbnail_name(self.video_path))
        if not os.path.exists(thumb_path):
            thumb_path = _extract_thumbnail(self.video_path, thumb_path)
        if os.path.exists(thumb_path):
            self._orig_pixmap = QPixmap(thumb_path)
            self._update_thumb()
        else:
            self.thumb_label.setText("No Preview")

    def _update_thumb(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return
        w = self.thumb_label.width()
        if w > 0:
            self.thumb_label.setPixmap(self._orig_pixmap.scaled(w, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb()

    def mousePressEvent(self, event):
        if not self.isEnabled():
            event.ignore()
            return
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
        self.selected_device = "cuda"
        self._thumbnail_dir = os.path.join(os.path.dirname(__file__), "..", "..", "temp", "launcher_thumbs")

        from runtime_paths import asset_path
        from PySide6.QtGui import QIcon
        logo = asset_path("capcap.png")
        if os.path.exists(logo):
            self.setWindowIcon(QIcon(logo))

        self.setWindowTitle("CapCap - Video Translator")
        self.setMinimumSize(840, 540)
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
        QTimer.singleShot(0, self._load_recent)
        QTimer.singleShot(0, self._validate_resources_for_device)

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

        has_gpu, gpu_name, cuda_ready = self._detect_gpu_with_cuda()
        gpu_usable = has_gpu and cuda_ready
        self.selected_device = "cuda" if gpu_usable else "cpu"
        LauncherWindow._gpu_name = gpu_name if has_gpu else ""

        self._gpu_label = QLabel()
        header_text.addWidget(self._gpu_label)
        self._update_gpu_label(has_gpu, gpu_name, cuda_ready)

        self._missing_label = QLabel("", self)
        self._missing_label.setWordWrap(True)
        self._missing_label.setStyleSheet(
            "font-size: 11px; color: #ff6b6b; padding: 4px 8px;"
            " background-color: #3b1a1a; border: 1px solid #ff6b6b55; border-radius: 6px;"
        )
        self._missing_label.hide()
        header_text.addWidget(self._missing_label)

        device_row = QHBoxLayout()
        device_row.setSpacing(0)
        self.cpu_btn = QPushButton("CPU")
        self.cpu_btn.setCheckable(True)
        self.cpu_btn.setChecked(not gpu_usable)
        self.cpu_btn.setEnabled(True)
        self.gpu_btn = QPushButton("GPU (Recommended)" if gpu_usable else "GPU (N/A)")
        self.gpu_btn.setCheckable(True)
        self.gpu_btn.setChecked(gpu_usable)
        self.gpu_btn.setEnabled(gpu_usable)

        btn_style = """
            QPushButton {
                color: #8ea3bb; border: 1px solid #2f4868; padding: 3px 10px;
                font-size: 11px; font-weight: 600; border-radius: 0;
                background-color: transparent;
            }
            QPushButton:checked {
                background-color: #1a3a5c; color: #8ad7ff; border-color: #4ecdc4;
            }
            QPushButton:disabled {
                color: #445566; border-color: #1e3045;
            }
        """
        self.cpu_btn.setStyleSheet(btn_style + "QPushButton { border-top-left-radius: 6px; border-bottom-left-radius: 6px; }")
        self.gpu_btn.setStyleSheet(btn_style + "QPushButton { border-top-right-radius: 6px; border-bottom-right-radius: 6px; }")

        def _select_cpu(checked):
            if checked:
                self.gpu_btn.setChecked(False)
                self.selected_device = "cpu"
                self._validate_resources_for_device()
            elif not self.gpu_btn.isChecked():
                self.cpu_btn.setChecked(True)

        def _select_gpu(checked):
            if checked:
                self.cpu_btn.setChecked(False)
                self.selected_device = "cuda"
                self._validate_resources_for_device()
            elif not self.cpu_btn.isChecked():
                self.gpu_btn.setChecked(True)

        self.cpu_btn.clicked.connect(_select_cpu)
        self.gpu_btn.clicked.connect(_select_gpu)

        device_row.addWidget(self.cpu_btn)
        device_row.addWidget(self.gpu_btn)
        device_row.addStretch()
        header_text.addLayout(device_row)
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

        self.split_btn = QPushButton("Split Video")
        self.split_btn.setMinimumHeight(44)
        self.split_btn.setMinimumWidth(120)
        self.split_btn.setStyleSheet("""
            QPushButton {
                background-color: #22344d;
                color: #8ad7ff;
                font-weight: 600;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid #34506f;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
        """)
        self.split_btn.clicked.connect(self._on_split_video)
        header.addWidget(self.split_btn)

        self.resource_btn = QPushButton("Manage Resources")
        self.resource_btn.setMinimumHeight(44)
        self.resource_btn.setMinimumWidth(150)
        self.resource_btn.setStyleSheet("""
            QPushButton {
                background-color: #22344d;
                color: #8ad7ff;
                font-weight: 600;
                font-size: 13px;
                border-radius: 8px;
                border: 1px solid #34506f;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
        """)
        self.resource_btn.clicked.connect(self._on_manage_resources)
        header.addWidget(self.resource_btn)
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

        try:
            service = self._resource_service()
            is_ok, missing = service.validate_device(self.selected_device)
            if not is_ok:
                from PySide6.QtWidgets import QMessageBox
                labels = [label for _rid, label in missing]
                if self.selected_device == "cpu":
                    prefix = "CPU mode needs:"
                else:
                    prefix = "GPU mode needs:"
                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Warning)
                mb.setWindowTitle("Missing Resources")
                mb.setText(f"{prefix}\n\n" + "\n".join(f"- {label}" for label in labels))
                mb.setInformativeText("Open Manage Resources to download them.")
                mb.addButton("Manage Resources", QMessageBox.AcceptRole)
                mb.addButton("Close", QMessageBox.RejectRole)
                mb.setStyleSheet(MSG_STYLE)
                mb.exec()
                self._validate_resources_for_device()
                return
        except Exception as exc:
            print(f"[Launcher] Resource validation failed: {exc}")

        duration = _get_video_duration(self.selected_video)
        MAX_DURATION = 7200
        if duration > MAX_DURATION:
            h = int(duration // 3600)
            m = int((duration % 3600) // 60)
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self, "Video Too Long",
                f"This video is {h}h {m}m long.\nCapCap works best with videos under 2 hours.\n\n"
                "Use 'Split Video' to cut it into 2-hour segments first.",
                QMessageBox.Ok,
            )
            reply.setStyleSheet(MSG_STYLE)
            return

        LauncherWindow._selected_device = self.selected_device
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
        self._save_device_env()
        super().accept()

    @staticmethod
    def _save_device_env():
        device = getattr(LauncherWindow, "_selected_device", "cuda")
        gpu_name = getattr(LauncherWindow, "_gpu_name", "")
        print(f"[Launcher] Saving CAPCAP_DEVICE={device}, GPU={gpu_name}")
        os.environ["CAPCAP_DEVICE"] = device
        os.environ["CAPCAP_GPU_NAME"] = gpu_name
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith("CAPCAP_DEVICE="):
                    lines[i] = f"CAPCAP_DEVICE={device}\n"
                    found = True
                    break
            if not found:
                lines.append(f"CAPCAP_DEVICE={device}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            print(f"[Launcher] Failed to write .env: {e}")

    def _resource_service(self):
        from runtime_paths import workspace_root
        from services import ResourceDownloadService
        return ResourceDownloadService(workspace_root())

    def _validate_resources_for_device(self):
        try:
            service = self._resource_service()
        except Exception as exc:
            print(f"[Launcher] Failed to load resource service: {exc}")
            self.new_btn.setEnabled(True)
            return
        device = self.selected_device
        is_ok, missing = service.validate_device(device)
        self.new_btn.setEnabled(is_ok)
        if device == "cuda":
            has_gpu = True
            gpu_name = ""
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    gpu_name = result.stdout.strip().split("\n")[0].strip()
            except Exception:
                pass
            cuda_ready = is_ok
            self._update_gpu_label(has_gpu, gpu_name, cuda_ready)
            if not cuda_ready:
                self.gpu_btn.setEnabled(False)
                self.gpu_btn.setText("GPU (N/A)")
        elif device == "cpu":
            has_gpu, _gpu_name, cuda_ready = self._detect_gpu_with_cuda()
            gpu_usable = has_gpu and cuda_ready
            if gpu_usable:
                self.gpu_btn.setEnabled(True)
                self.gpu_btn.setText("GPU (Recommended)")
                self._update_gpu_label(has_gpu, _gpu_name, cuda_ready)
        if is_ok:
            self._missing_label.hide()
            self._missing_label.setText("")
            if hasattr(self, "new_btn") and self.new_btn.toolTip():
                self.new_btn.setToolTip("")
        else:
            labels = [label for _rid, label in missing]
            if device == "cpu":
                prefix = "CPU mode needs:"
            else:
                prefix = "GPU mode needs:"
            text = f"{prefix} {', '.join(labels)}. Open Manage Resources to set them up."
            self._missing_label.setText(text)
            self._missing_label.show()
            self.new_btn.setToolTip(text)
        try:
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                if isinstance(widget, ProjectCard):
                    widget.setEnabled(is_ok)
        except Exception:
            pass

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

        columns = min(3, max(1, (self.grid_widget.width() - 24) // 242))
        for i, proj in enumerate(existing):
            card = ProjectCard(proj["video_path"], self._thumbnail_dir, self)
            row, col = divmod(i, max(1, columns))
            self.grid.addWidget(card, row, col)
            self.grid.setColumnStretch(col, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._load_recent)

    def _on_new_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm);;All Files (*)"
        )
        if path:
            self.selected_video = path
            self.accept()

    def _on_manage_resources(self):
        from views.resource_manager import open_resource_manager
        open_resource_manager(parent=self)
        self._validate_resources_for_device()

    def _on_split_video(self):
        from PySide6.QtWidgets import QMessageBox, QProgressDialog, QInputDialog
        from PySide6.QtCore import QThread, Signal
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Long Video to Split", "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm);;All Files (*)"
        )
        if not path:
            return

        duration = _get_video_duration(path)
        if duration <= 7200:
            mb = QMessageBox(QMessageBox.Information, "No Split Needed",
                "This video is under 2 hours. You can open it directly with '+ New Project'.",
                QMessageBox.Ok, self)
            mb.setStyleSheet(MSG_STYLE)
            mb.exec()
            return

        h = int(duration // 3600)
        m = int((duration % 3600) // 60)

        seg_minutes, ok = QInputDialog.getInt(
            self, "Segment Duration",
            f"Video is {h}h {m}m.\nSplit into segments of how many minutes?",
            120, 10, 1440, 10,
        )
        if not ok:
            return

        seg_seconds = seg_minutes * 60
        base, ext = os.path.splitext(path)
        out_pattern = f"{base}_part%03d{ext}"

        reply = QMessageBox(QMessageBox.Question, "Confirm Split",
            f"Split into {seg_minutes}-minute segments using stream copy (no re-encode, fast).\n\n"
            f"Output: {out_pattern}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, self)
        reply.setStyleSheet(MSG_STYLE)
        if reply.exec() != QMessageBox.Yes:
            return

        progress = QProgressDialog("Splitting video...", None, 0, 0, self)
        progress.setWindowTitle("Split Video")
        progress.setModal(True)
        progress.setCancelButton(None)
        progress.show()

        import subprocess
        import threading

        def _do_split():
            try:
                subprocess.run(
                    [_ffmpeg_path(), "-y", "-i", path, "-c", "copy",
                     "-f", "segment", "-segment_time", str(seg_seconds),
                     "-reset_timestamps", "1", out_pattern],
                    capture_output=True, timeout=3600,
                )
                progress.accept()
            except Exception as e:
                progress.accept()
                print(f"[Split] Error: {e}")

        threading.Thread(target=_do_split, daemon=True).start()
        progress.exec()

        mb = QMessageBox(QMessageBox.Information, "Done",
            f"Video split into {seg_minutes}-minute segments.\nSaved alongside the original file.",
            QMessageBox.Ok, self)
        mb.setStyleSheet(MSG_STYLE)
        mb.exec()

    def _detect_gpu_with_cuda(self):
        has_gpu = False
        gpu_name = ""
        cuda_ready = False
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_name = result.stdout.strip().split("\n")[0].strip()
                has_gpu = True
        except Exception:
            pass
        if not has_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    name = torch.cuda.get_device_name(0)
                    vram = torch.cuda.get_device_properties(0).total_mem // (1024 ** 3)
                    gpu_name = f"{name} ({vram}GB)"
                    has_gpu = True
            except Exception:
                pass
        if has_gpu:
            try:
                service = self._resource_service()
                cuda_ready = service.is_requirement_met("cuda:whisper")
            except Exception:
                pass
        return has_gpu, gpu_name, cuda_ready

    def _update_gpu_label(self, has_gpu: bool, gpu_name: str, cuda_ready: bool):
        if has_gpu:
            if cuda_ready:
                self._gpu_label.setText(f"GPU: {gpu_name}  \u2713 CUDA ready")
                self._gpu_label.setStyleSheet("font-size: 11px; color: #4ecdc4;")
            else:
                self._gpu_label.setText(f"GPU: {gpu_name}  \u2717 CUDA pack missing")
                self._gpu_label.setStyleSheet("font-size: 11px; color: #ffa500;")
        else:
            self._gpu_label.setText("CPU only")
            self._gpu_label.setStyleSheet("font-size: 11px; color: #5a7a9a;")

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
