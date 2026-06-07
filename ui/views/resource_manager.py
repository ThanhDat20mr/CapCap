import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from runtime_paths import workspace_root as default_workspace_root
from services import ResourceDownloadService
from worker_adapters.processing_workers import ResourceDownloadWorker


def open_resource_manager(workspace_root: str = None, parent=None,
                          on_finished=None):
    if workspace_root is None:
        workspace_root = default_workspace_root()

    service = ResourceDownloadService(workspace_root)
    state = {"resource_id": "", "percent": 0, "message": "", "running": False}
    worker = [None]
    active_resource_id = [""]
    dialog_ref = [None]

    def _refresh(dialog):
        rows = getattr(dialog, "_resource_rows", {})
        if not rows:
            return
        resources = {item["id"]: item for item in service.list_resources()}
        active_rid = active_resource_id[0]
        is_running = state["running"]
        for resource_id, row in rows.items():
            item = resources.get(resource_id, row.get("item", {}))
            row["item"] = item
            status = str(item.get("status", "missing")).strip().lower()
            target_dir = str(item.get("target_dir", "")).strip()
            description = str(item.get("description", "")).strip()
            status_label = row.get("status_label")
            if status_label is not None:
                lines = [status.title()]
                if description:
                    lines.append(description)
                if target_dir:
                    lines.append(target_dir)
                status_label.setText("\n".join(lines))
            button = row.get("button")
            if button is not None:
                if is_running and resource_id == active_rid:
                    button.setText("Downloading...")
                    button.setEnabled(False)
                elif status == "installed":
                    button.setText("Installed")
                    button.setEnabled(False)
                elif resource_id == "voice:pack" and status == "partial":
                    button.setText("Complete Pack")
                    button.setEnabled(not is_running)
                else:
                    button.setText("Download")
                    button.setEnabled(not is_running)

        footer_text = str(state.get("message", "") or "").strip() or "Select a resource to download."
        if hasattr(dialog, "_resource_footer"):
            dialog._resource_footer.setText(footer_text)
        if hasattr(dialog, "_resource_progress_bar"):
            try:
                value = int(state.get("percent", 0))
            except Exception:
                value = 0
            if is_running and value < 0:
                dialog._resource_progress_bar.setRange(0, 0)
            else:
                dialog._resource_progress_bar.setRange(0, 100)
                dialog._resource_progress_bar.setValue(max(0, min(100, value)))

    def _on_progress(percent: int, message: str):
        try:
            value = int(percent)
        except Exception:
            value = -1
        state.update({
            "resource_id": active_resource_id[0],
            "percent": value,
            "message": str(message or "").strip() or "Downloading resource...",
            "running": True,
        })
        dialog = dialog_ref[0]
        if dialog is not None and hasattr(dialog, "_resource_footer"):
            dialog._resource_footer.setText(str(message or "").strip() or "Downloading resource...")
        if dialog is not None and hasattr(dialog, "_resource_progress_bar"):
            if value < 0:
                dialog._resource_progress_bar.setRange(0, 0)
            else:
                if dialog._resource_progress_bar.maximum() == 0:
                    dialog._resource_progress_bar.setRange(0, 100)
                dialog._resource_progress_bar.setValue(max(0, min(100, value)))

    def _on_finished(resource_id: str, error: str):
        worker[0] = None
        active_resource_id[0] = ""
        state.update({
            "resource_id": "",
            "percent": 0 if error else 100,
            "message": "Download failed." if error else "Download completed.",
            "running": False,
        })
        dialog = dialog_ref[0]
        if dialog is not None and hasattr(dialog, "_resource_footer"):
            dialog._resource_footer.setText("Download failed." if error else "Download completed.")
            _refresh(dialog)
        if dialog is not None and hasattr(dialog, "_resource_progress_bar"):
            dialog._resource_progress_bar.setRange(0, 100)
            dialog._resource_progress_bar.setValue(100 if not error else 0)
        if not error:
            if on_finished:
                on_finished()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(dialog_ref[0] or parent, "Download Failed",
                                f"Could not download resource '{resource_id}'.\n\n{error}")

    def _start_download(dialog, resource_id: str):
        w = worker[0]
        if w is not None and w.isRunning():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(dialog, "Download in Progress",
                                    "A resource is already downloading.")
            return
        dialog_ref[0] = dialog
        active_resource_id[0] = str(resource_id or "").strip()
        state.update({
            "resource_id": active_resource_id[0],
            "percent": 0,
            "message": f"Preparing download: {resource_id}",
            "running": True,
        })
        if hasattr(dialog, "_resource_footer"):
            dialog._resource_footer.setText(f"Preparing download: {resource_id}")
        if hasattr(dialog, "_resource_progress_bar"):
            dialog._resource_progress_bar.setRange(0, 100)
            dialog._resource_progress_bar.setValue(0)
        w = ResourceDownloadWorker(workspace_root, resource_id)
        w.progress.connect(_on_progress)
        w.finished.connect(_on_finished)
        worker[0] = w
        _refresh(dialog)
        w.start()

    dialog = QDialog(parent)
    dialog.setWindowTitle("Manage Resources")
    dialog.setModal(True)
    dialog.resize(760, 550)
    dialog.setStyleSheet("""
        QDialog { background-color: #0f1724; }
        QLabel { color: #d7e3f4; background-color: transparent; }
        QLabel#resourceTitle { color: #f8fbff; font-size: 16px; font-weight: 700; }
        QLabel#resourceHint { color: #9fb3ca; font-size: 12px; }
        QWidget#resourceContent { background-color: transparent; }
        QScrollArea { border: none; background-color: #0f1724; }
        QFrame#resourceCard { background-color: #132033; border: 1px solid #2f4868; border-radius: 12px; }
        QPushButton {
            background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
            border-radius: 10px; padding: 8px 16px; font-weight: 600; min-width: 84px;
        }
        QPushButton:hover { background-color: #29405d; }
        QPushButton:disabled { color: #8ea3bb; background-color: #182636; border-color: #29405d; }
    """)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("Download runtime resources from Hugging Face", dialog)
    title.setObjectName("resourceTitle")
    layout.addWidget(title)

    hint = QLabel(
        f"Whisper models use faster-whisper download/cache. Extra runtime files come from: {service.repo_id} @ {service.revision}\n"
        "Use this screen to install Whisper, GPU runtime, and local Piper voices separately.",
        dialog,
    )
    hint.setObjectName("resourceHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    layout.addWidget(scroll, 1)

    content = QWidget(dialog)
    content.setObjectName("resourceContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(10)
    scroll.setWidget(content)

    dialog._resource_rows = {}

    resources = service.list_resources()

    cpu_items = [r for r in resources if r.get("kind") == "sensevoice"]
    gpu_kinds = {"ai", "whisper", "cuda"}
    gpu_items = [r for r in resources if r.get("kind") in gpu_kinds]
    voice_items = [r for r in resources if r.get("kind") == "voice"]

    def _add_card(item, target_layout):
        card = QFrame(dialog)
        card.setObjectName("resourceCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(8)

        text_layout = QVBoxLayout()
        name_label = QLabel(str(item.get("name", item.get("id", "Resource"))), dialog)
        name_label.setStyleSheet("color: #f8fbff; font-weight: 700; background-color: transparent;")
        status_label = QLabel("", dialog)
        status_label.setObjectName("resourceHint")
        status_label.setStyleSheet("color: #9fb3ca; background-color: transparent;")
        status_label.setWordWrap(True)
        text_layout.addWidget(name_label)
        text_layout.addWidget(status_label)
        card_layout.addLayout(text_layout, 1)

        button = QPushButton("Download", dialog)
        button.clicked.connect(lambda _checked=False, rid=item["id"], dlg=dialog: _start_download(dlg, rid))
        card_layout.addWidget(button)
        target_layout.addWidget(card)
        dialog._resource_rows[item["id"]] = {
            "item": item,
            "status_label": status_label,
            "button": button,
        }

    def _make_section(title_text, expanded):
        wrapper = QFrame()
        wrapper.setObjectName("statusCard")
        wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(8, 2, 8, 2)
        wrapper_layout.setSpacing(0)

        btn = QToolButton()
        btn.setText(("▼ " if expanded else "▶ ") + title_text)
        btn.setCheckable(True)
        btn.setChecked(expanded)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #8ad7ff; border: none; padding: 2px 4px; margin: 0; }")

        inner = QWidget()
        inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 4)
        inner_layout.setSpacing(2)
        inner.setVisible(expanded)
        if not expanded:
            inner.setMaximumHeight(0)

        btn.toggled.connect(lambda c: (
            btn.setText(("▼ " if c else "▶ ") + title_text),
            inner.setVisible(c),
            inner.setMaximumHeight(16777215 if c else 0),
        ))
        wrapper_layout.addWidget(btn)
        wrapper_layout.addWidget(inner)
        return wrapper, inner_layout

    if cpu_items:
        cpu_card, cpu_layout = _make_section("CPU Resource", expanded=True)
        for item in cpu_items:
            _add_card(item, cpu_layout)
        content_layout.addWidget(cpu_card)

    if gpu_items:
        cpu_mode = os.getenv("CAPCAP_DEVICE", "cuda").strip().lower() == "cpu"
        if not cpu_mode:
            gpu_card, gpu_layout = _make_section("GPU Resource", expanded=False)
            for item in gpu_items:
                _add_card(item, gpu_layout)
            content_layout.addWidget(gpu_card)

    for item in voice_items:
        _add_card(item, content_layout)

    content_layout.addStretch()

    dialog._resource_footer = QLabel("Select a resource to download.", dialog)
    dialog._resource_footer.setObjectName("resourceHint")
    dialog._resource_footer.setWordWrap(True)
    layout.addWidget(dialog._resource_footer)

    dialog._resource_progress_bar = QProgressBar(dialog)
    dialog._resource_progress_bar.setRange(0, 100)
    dialog._resource_progress_bar.setValue(0)
    dialog._resource_progress_bar.setTextVisible(True)
    layout.addWidget(dialog._resource_progress_bar)

    close_row = QHBoxLayout()
    close_row.addStretch()
    close_btn = QPushButton("Close", dialog)
    close_btn.clicked.connect(dialog.accept)
    close_row.addWidget(close_btn)
    layout.addLayout(close_row)

    def _on_dialog_closed():
        w = worker[0]
        if w is not None and w.isRunning():
            print("[ResourceMgr] Dialog closed, terminating active download...")
            w.quit()
            w.wait(3000)
            if w.isRunning():
                w.terminate()
                w.wait(2000)
            state.update({"running": False, "message": "Download cancelled."})
        worker[0] = None

    dialog.accepted.connect(_on_dialog_closed)
    dialog.rejected.connect(_on_dialog_closed)

    _refresh(dialog)
    dialog.exec()
