import os
import shutil
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication

from main_window import VideoTranslatorGUI

__all__ = ["VideoTranslatorGUI"]


def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _bootstrap_env(app_root: str) -> None:
    env_path = os.path.join(app_root, ".env")
    env_example_path = os.path.join(app_root, ".env_example")

    if not os.path.exists(env_path) and os.path.exists(env_example_path):
        shutil.copyfile(env_example_path, env_path)

    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, value.strip())


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
