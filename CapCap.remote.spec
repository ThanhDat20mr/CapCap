# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules


project_root = Path(r"D:\CodingTime\CapCap")
ui_root = project_root / "ui"
app_root = project_root / "app"

datas = [
    (str(project_root / "assets"), "assets"),
    (str(project_root / "bin" / "ffmpeg"), "bin/ffmpeg"),
    (str(project_root / "bin" / "mpv"), "bin/mpv"),
    (str(project_root / "app" / "voice_preview_catalog.json"), "app"),
    (str(project_root / ".env_example"), "."),
]

# Collect all submodules from heavy packages to exclude them properly
excludes = collect_submodules("torch")
excludes += collect_submodules("scipy")
excludes += collect_submodules("numpy")
excludes += collect_submodules("matplotlib")
excludes += collect_submodules("PIL")
excludes += collect_submodules("cv2")
excludes += collect_submodules("av")
excludes += collect_submodules("aiohttp")
excludes += collect_submodules("uvicorn")
excludes += collect_submodules("faster_whisper")
excludes += collect_submodules("demucs")
excludes += collect_submodules("f5_tts")
excludes += collect_submodules("edge_tts")
excludes += collect_submodules("piper")

# Add more to exclude
excludes += [
    "torch",
    "torchaudio",
    "torchvision",
    "f5_api_server",
    "tools.f5_batch_bridge",
    "llama_cpp",
    "vietnormalizer",
    "cv2",
    "opencv",
    "comtypes",
    "phonenumbers",
    "yarl",
    "msgpack",
    "orjson",
    "safetensors",
    "xxhash",
    "brotli",
    "contourpy",
    "kiwisolver",
    "packaging",
    "cryptography",
    "filelock",
    "propcache",
    "psutil",
    "websockets",
    "httpx",
]


a = Analysis(
    [str(ui_root / "gui_remote.py")],
    pathex=[str(project_root), str(ui_root), str(app_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "gui",
        "main_window",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "mpv",
        "remote_api",
        "services",
        "services.f5_voice_service",
        # Lazy-loaded service modules (services/__init__ uses importlib)
        "services.project_service",
        "services.gui_project_bridge",
        "services.voice_catalog_service",
        "services.resource_download_service",
        "services.engine_runtime",
        "services.workflow_runtime",
        "services.segment_service",
        "services.chunking_service",
        "services.asr_merge_service",
        "services.segment_regroup_service",
        # Dynamically loaded adapters (EngineRuntime uses importlib.import_module)
        "engines.ffmpeg_adapter",
        "engines.preview_adapter",
        "engines.subtitle_adapter",
        "engines.audio_mix_adapter",
        "engines.remote_whisper_adapter",
        "engines.remote_translator_adapter",
        "engines.remote_tts_adapter",
        # Lazy-loaded translation providers (translation/providers/__init__ uses importlib)
        "translation.providers.ai_polisher",
        "translation.providers.gemini_polisher",
        "translation.providers.google_web_translator",
        "translation.providers.local_polisher",
        "translation.providers.microsoft_translator",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CapCapRemote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CapCapRemote",
)