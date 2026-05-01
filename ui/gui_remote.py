import os
import sys

os.environ.setdefault("CAPCAP_RUNTIME_PROFILE", "remote")

from gui import VideoTranslatorGUI, _app_root, _bootstrap_env  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer, QUrl  # noqa: E402


if __name__ == "__main__":
    app_root = _app_root()
    _bootstrap_env(app_root)
    os.chdir(app_root)
    app = QApplication(sys.argv)

    from views.launcher import show_launcher, LauncherWindow
    video_path = show_launcher(None)
    if not video_path:
        sys.exit(0)

    LauncherWindow.add_recent(None, video_path)

    window = VideoTranslatorGUI()
    window.show()

    def _init_video():
        window._current_video_path = os.path.abspath(video_path)
        window.ensure_media_backend_ready()
        window.video_path_edit.setText(video_path)
        window.media_player.setSource(QUrl.fromLocalFile(video_path))
        if hasattr(window, "refresh_video_dimensions"):
            window.refresh_video_dimensions(video_path)
        window.current_project_state = window.ensure_current_project()
        window.load_project_context(window.current_project_state)

    QTimer.singleShot(100, _init_video)
    sys.exit(app.exec())
