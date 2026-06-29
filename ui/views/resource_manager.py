import os
import traceback

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
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


_STATUS_STYLES = {
    "installed": ("Ready", "#3ddc97", "#1b3b2c"),
    "partial":   ("Partial", "#f0b347", "#3b2f12"),
    "missing":   ("Missing", "#ff6b6b", "#3b1a1a"),
}


def _status_pill_widget(status_key: str, parent: QWidget) -> QLabel:
    status = str(status_key or "").strip().lower()
    label, fg, bg = _STATUS_STYLES.get(status, _STATUS_STYLES["missing"])
    pill = QLabel(label, parent)
    pill.setAlignment(Qt.AlignCenter)
    pill.setStyleSheet(
        f"color: {fg}; background-color: {bg}; border: 1px solid {fg}55;"
        f" border-radius: 10px; padding: 3px 12px; font-weight: 700; font-size: 12px;"
    )
    pill.setFixedHeight(24)
    return pill


def _make_progress_widget(parent: QWidget) -> QProgressBar:
    bar = QProgressBar(parent)
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(True)
    bar.setFormat("%p%")
    bar.setFixedHeight(20)
    bar.setStyleSheet(
        "QProgressBar { background-color: #1b3b2c; color: #3ddc97; border: 1px solid #2f4868;"
        " border-radius: 8px; text-align: center; font-size: 11px; font-weight: 600; }"
        " QProgressBar::chunk { background-color: #3ddc97; border-radius: 6px; }"
    )
    return bar


def _open_url(url: str) -> bool:
    target = str(url or "").strip()
    if not target:
        return False
    return QDesktopServices.openUrl(QUrl(target))


def _open_folder_dialog(gui_parent, path: str) -> None:
    target = str(path or "").strip()
    if not target:
        return
    from PySide6.QtWidgets import QMessageBox
    try:
        os.makedirs(target, exist_ok=True)
        os.startfile(os.path.abspath(target))
    except Exception as exc:
        QMessageBox.critical(gui_parent, "Error", f"Could not open folder:\n{exc}")


def open_resource_manager(workspace_root: str = None, parent=None,
                          on_finished=None):
    if workspace_root is None:
        workspace_root = default_workspace_root()

    service = ResourceDownloadService(workspace_root)
    state = {"resource_id": "", "running": False}
    worker = [None]
    active_resource_id = [""]
    dialog_ref = [None]
    progress_widgets: dict[str, tuple[QWidget, QWidget]] = {}

    dialog = QDialog(parent)
    dialog.setWindowTitle("Manage Resources")
    dialog.setModal(True)
    dialog.resize(820, 580)
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
            border-radius: 8px; padding: 6px 14px; font-weight: 600; min-width: 90px;
        }
        QPushButton:hover { background-color: #29405d; }
        QPushButton:disabled { color: #8ea3bb; background-color: #182636; border-color: #29405d; }
        QPushButton#primaryBtn {
            background-color: #2563eb; border-color: #3b82f6;
        }
        QPushButton#primaryBtn:hover { background-color: #1d4ed8; }
        QPushButton#autoBtn {
            background-color: #1e6b3e; border-color: #2d9c5c;
        }
        QPushButton#autoBtn:hover { background-color: #247a48; }
        QPushButton#autoBtn:disabled { color: #8ea3bb; background-color: #182636; border-color: #29405d; }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("Manage Resources", dialog)
    title.setObjectName("resourceTitle")
    layout.addWidget(title)

    hint = QLabel(
        "Each resource shows its target folder and download link. "
        "Download the file yourself and drop it into the target folder, "
        "or click 'Auto Download' to fetch it directly from Hugging Face. "
        "Use 'Refresh' to re-check status.",
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

    def _show_status_pill(row, status_key: str):
        new_pill = _status_pill_widget(status_key, dialog)
        row["header_row"].replaceWidget(row["status_pill"], new_pill)
        row["status_pill"].deleteLater()
        row["status_pill"] = new_pill
        row["status_pill"].show()
        if row.get("progress_wrap") is not None:
            row["progress_wrap"].hide()

    def _show_progress(row, indeterminate: bool = False):
        if row.get("progress_bar") is None:
            return
        bar = row["progress_bar"]
        wrap = row["progress_wrap"]
        row["status_pill"].hide()
        if indeterminate:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
        wrap.show()

    def _set_progress_value(row, percent: int, message: str = ""):
        if row.get("progress_bar") is None:
            return
        bar = row["progress_bar"]
        if bar.maximum() == 0:
            bar.setRange(0, 100)
        bar.setValue(max(0, min(100, percent)))
        if message:
            bar.setFormat(f"{percent}%  {message[:40]}")
        else:
            bar.setFormat(f"{percent}%")

    def _update_buttons_state():
        for resource_id, row in dialog._resource_rows.items():
            is_active = state["running"] and resource_id == active_resource_id[0]
            auto_btn = row.get("auto_btn")
            if auto_btn is not None:
                if is_active:
                    auto_btn.setText("Downloading...")
                    auto_btn.setEnabled(False)
                elif row.get("auto_download_supported", False):
                    auto_btn.setText("Auto Download")
                    auto_btn.setEnabled(True)
                else:
                    auto_btn.setText("Manual only")
                    auto_btn.setEnabled(False)

    def _add_card(item, target_layout):
        card = QFrame(dialog)
        card.setObjectName("resourceCard")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        name_label = QLabel(str(item.get("name", item.get("id", "Resource"))), dialog)
        name_label.setStyleSheet("color: #f8fbff; font-weight: 700; font-size: 14px; background-color: transparent;")
        header_row.addWidget(name_label, 1)

        status_pill = _status_pill_widget(item.get("status", "missing"), dialog)
        header_row.addWidget(status_pill, 0, Qt.AlignVCenter | Qt.AlignRight)

        progress_bar = _make_progress_widget(dialog)
        progress_bar.setFixedWidth(180)
        progress_wrap = QWidget(dialog)
        progress_wrap.setFixedWidth(180)
        pw_layout = QHBoxLayout(progress_wrap)
        pw_layout.setContentsMargins(0, 2, 0, 0)
        pw_layout.setSpacing(0)
        pw_layout.addWidget(progress_bar)
        progress_wrap.hide()
        header_row.addWidget(progress_wrap, 0, Qt.AlignVCenter | Qt.AlignRight)

        outer.addLayout(header_row)

        description = str(item.get("description", "")).strip()
        if description:
            desc_label = QLabel(description, dialog)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #c0d0e3; font-size: 12px; background-color: transparent;")
            outer.addWidget(desc_label)

        target_dir = str(item.get("target_dir", "")).strip()
        if target_dir:
            path_row = QHBoxLayout()
            path_row.setSpacing(6)
            path_label = QLabel("Target folder:", dialog)
            path_label.setStyleSheet("color: #8ea3bb; font-size: 11px; background-color: transparent;")
            path_value = QLabel(target_dir, dialog)
            path_value.setStyleSheet("color: #d7e3f4; font-size: 11px; font-family: monospace; background-color: transparent;")
            path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_value.setWordWrap(True)
            path_row.addWidget(path_label, 0)
            path_row.addWidget(path_value, 1)
            outer.addLayout(path_row)

        expected = str(item.get("expected_filename", "")).strip()
        if expected:
            file_row = QHBoxLayout()
            file_row.setSpacing(6)
            file_caption = QLabel("Expected file:", dialog)
            file_caption.setStyleSheet("color: #8ea3bb; font-size: 11px; background-color: transparent;")
            file_value = QLabel(expected, dialog)
            file_value.setStyleSheet("color: #d7e3f4; font-size: 11px; font-family: monospace; background-color: transparent;")
            file_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            file_value.setWordWrap(True)
            file_row.addWidget(file_caption, 0)
            file_row.addWidget(file_value, 1)
            outer.addLayout(file_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)

        download_url = str(item.get("download_url", "")).strip()
        download_btn = QPushButton("Open Download Page", dialog)
        download_btn.setObjectName("primaryBtn")
        download_btn.setEnabled(bool(download_url))
        if download_url:
            download_btn.setToolTip(download_url)
        download_btn.clicked.connect(
            lambda _checked=False, url=download_url: _open_url(url)
        )
        button_row.addWidget(download_btn)

        auto_download_supported = bool(item.get("auto_download_supported", False))
        auto_btn = QPushButton("Auto Download", dialog)
        auto_btn.setObjectName("autoBtn")
        auto_btn.setEnabled(auto_download_supported)
        if not auto_download_supported:
            auto_btn.setText("Manual only")
        auto_btn.clicked.connect(
            lambda _checked=False, rid=item["id"]: _start_download(rid)
        )
        button_row.addWidget(auto_btn)

        open_folder_btn = QPushButton("Open Storage Folder", dialog)
        open_folder_btn.setEnabled(bool(target_dir))
        open_folder_btn.clicked.connect(
            lambda _checked=False, p=target_dir: _open_folder_dialog(dialog, p)
        )
        button_row.addWidget(open_folder_btn)

        outer.addLayout(button_row)

        target_layout.addWidget(card)
        dialog._resource_rows[item["id"]] = {
            "item": item,
            "name_label": name_label,
            "status_pill": status_pill,
            "progress_bar": progress_bar,
            "progress_wrap": progress_wrap,
            "header_row": header_row,
            "auto_btn": auto_btn,
            "auto_download_supported": auto_download_supported,
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

    def _refresh():
        resources = {item["id"]: item for item in service.list_resources()}
        for resource_id, row in dialog._resource_rows.items():
            item = resources.get(resource_id, row.get("item", {}))
            row["item"] = item
            status = str(item.get("status", "missing")).strip().lower()
            auto_supported = bool(item.get("auto_download_supported", False))
            row["auto_download_supported"] = auto_supported
            if not state["running"] or resource_id != active_resource_id[0]:
                _show_status_pill(row, status)
            _update_buttons_state()

    def _populate():
        for i in reversed(range(content_layout.count())):
            it = content_layout.takeAt(i)
            widget = it.widget() if it is not None else None
            if widget is not None:
                widget.deleteLater()
        dialog._resource_rows = {}
        progress_widgets.clear()

        resources = service.list_resources()
        cpu_items = [r for r in resources if r.get("kind") == "sensevoice"]
        gpu_kinds = {"ai", "whisper", "cuda"}
        gpu_items = [r for r in resources if r.get("kind") in gpu_kinds]
        voice_items = [r for r in resources if r.get("kind") == "voice"]

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
            else:
                for item in gpu_items:
                    _add_card(item, content_layout)

        for item in voice_items:
            _add_card(item, content_layout)

        content_layout.addStretch()

    def _start_download(resource_id: str):
        rid = str(resource_id or "").strip()
        if not rid:
            return
        if state["running"]:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(dialog, "Download in Progress",
                                    "Another resource is already downloading. Please wait for it to finish.")
            return
        if not service.supports_auto_download(rid):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                dialog, "Manual Download",
                "This resource can only be downloaded manually. Use 'Open Download Page' instead."
            )
            return
        row = dialog._resource_rows.get(rid)
        if row is None:
            return
        dialog_ref[0] = dialog
        active_resource_id[0] = rid
        state["resource_id"] = rid
        state["running"] = True
        _show_progress(row, indeterminate=True)
        _update_buttons_state()
        w = ResourceDownloadWorker(workspace_root, rid)
        w.progress.connect(_on_progress)
        w.finished.connect(_on_finished)
        worker[0] = w
        w.start()

    def _on_progress(percent: int, message: str):
        rid = active_resource_id[0]
        row = dialog._resource_rows.get(rid)
        if row is None:
            return
        try:
            value = int(percent)
        except Exception:
            value = -1
        if value < 0:
            _show_progress(row, indeterminate=True)
        else:
            _show_progress(row, indeterminate=False)
            _set_progress_value(row, value, message)

    def _on_finished(resource_id: str, error: str):
        worker[0] = None
        state["running"] = False
        state["resource_id"] = ""
        active_resource_id[0] = ""
        row = dialog._resource_rows.get(resource_id)
        if row is not None:
            row["progress_bar"].setRange(0, 100)
            row["progress_bar"].setValue(100 if not error else 0)
        if not error:
            _refresh()
            if on_finished:
                try:
                    on_finished()
                except Exception:
                    pass
        else:
            if row is not None:
                _show_status_pill(row, "missing")
            _update_buttons_state()
            from PySide6.QtWidgets import QMessageBox
            details = traceback.format_exc() if False else ""
            QMessageBox.warning(
                dialog, "Download Failed",
                f"Could not download resource '{resource_id}'.\n\n{error}"
            )

    _populate()

    footer_row = QHBoxLayout()
    footer_row.setSpacing(8)
    footer_hint = QLabel(
        "Tip: target folders are created automatically when you open them.",
        dialog,
    )
    footer_hint.setObjectName("resourceHint")
    footer_hint.setWordWrap(True)
    footer_row.addWidget(footer_hint, 1)

    refresh_btn = QPushButton("Refresh", dialog)
    refresh_btn.clicked.connect(_refresh)
    footer_row.addWidget(refresh_btn)

    close_btn = QPushButton("Close", dialog)
    close_btn.clicked.connect(dialog.accept)
    footer_row.addWidget(close_btn)

    layout.addLayout(footer_row)

    def _on_dialog_closed():
        w = worker[0]
        if w is not None and w.isRunning():
            print("[ResourceMgr] Dialog closed, terminating active download...")
            w.quit()
            w.wait(3000)
            if w.isRunning():
                w.terminate()
                w.wait(2000)
            state.update({"running": False, "resource_id": ""})
        worker[0] = None
        if on_finished:
            try:
                on_finished()
            except Exception:
                pass

    dialog.accepted.connect(_on_dialog_closed)
    dialog.rejected.connect(_on_dialog_closed)
    dialog.exec()
