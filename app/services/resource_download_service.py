from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

from runtime_paths import app_path, join_root, models_path


class ResourceDownloadService:
    NORMAL_AI_RESOURCE_ID = "ai:local-normal"
    HIGH_AI_RESOURCE_ID = "ai:local-high"
    NORMAL_AI_FILENAME = "Hy-MT2-1.8B-Q4_K_M.gguf"
    HIGH_AI_FILENAME = "gemma-4-E4B-it-Q4_K_M.gguf"

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.repo_id = os.getenv("CAPCAP_RESOURCE_REPO", "Hacht/CapCapResource").strip() or "Hacht/CapCapResource"
        self.revision = os.getenv("CAPCAP_RESOURCE_REVISION", "main").strip() or "main"

    def _catalog_path(self) -> str:
        download_catalog = app_path("voice_download_catalog.json")
        if os.path.exists(download_catalog):
            return download_catalog
        release_catalog = app_path("voice_preview_catalog.release.json")
        if os.path.exists(release_catalog):
            return release_catalog
        return app_path("voice_preview_catalog.json")

    def _read_catalog(self) -> dict:
        path = self._catalog_path()
        if not os.path.exists(path):
            return {"voices": []}
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {"voices": []}

    def _voice_local_paths(self, voice_entry: dict) -> tuple[str, str]:
        provider_voice = str(voice_entry.get("provider_voice", "")).strip().replace("/", os.sep)
        model_name = os.path.basename(provider_voice)
        config_name = f"{model_name}.json"
        return (
            models_path("piper", model_name),
            models_path("piper", config_name),
        )

    def _voice_remote_paths(self, voice_entry: dict) -> tuple[str, str]:
        provider_voice = str(voice_entry.get("provider_voice", "")).strip().replace("\\", "/")
        model_name = os.path.basename(provider_voice)
        return (
            f"piper/{model_name}",
            f"piper/{model_name}.json",
        )

    def _finalize_voice_download(self, downloaded_path: str, voice_entry: dict, *, is_config: bool) -> str:
        source_path = str(downloaded_path or "").strip()
        if not source_path or not os.path.exists(source_path):
            return source_path
        model_path, config_path = self._voice_local_paths(voice_entry)
        target_path = config_path if is_config else model_path
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        normalized_source = os.path.normcase(os.path.abspath(source_path))
        normalized_target = os.path.normcase(os.path.abspath(target_path))
        if normalized_source != normalized_target:
            if os.path.exists(target_path):
                os.remove(target_path)
            shutil.move(source_path, target_path)
            self._cleanup_empty_voice_cache_dirs(os.path.dirname(source_path))
        return target_path

    def _download_hf_file(
        self,
        *,
        repo_id: str,
        revision: str,
        filename: str,
        local_dir: str,
        hf_hub_download,
        hf_hub_url,
        get_hf_file_metadata,
        progress_cb=None,
        start_percent: int = 0,
        end_percent: int = 100,
        label: str = "Downloading file...",
    ) -> str:
        print(f"[DEBUG] _download_hf_file: {repo_id}/{filename} -> {local_dir}")
        expected_path = os.path.join(local_dir, filename.replace("/", os.sep))
        try:
            file_url = hf_hub_url(repo_id=repo_id, filename=filename, revision=revision)
            print(f"[DEBUG] file_url: {file_url}")
            metadata = get_hf_file_metadata(url=file_url)
            expected_size = int(getattr(metadata, "size", 0) or 0)
            print(f"[DEBUG] expected_size: {expected_size}")
        except Exception as e:
            print(f"[DEBUG] metadata fetch failed: {e}")
            expected_size = 0

        stop_event = threading.Event()

        def _emit_progress(raw_percent: int, message: str) -> None:
            if not progress_cb:
                return
            scaled = start_percent + int(((end_percent - start_percent) * max(0, min(100, raw_percent))) / 100)
            progress_cb(scaled, message)

        def _watch_file() -> None:
            last_percent = -1
            while not stop_event.is_set():
                current_size = 0
                try:
                    if os.path.exists(expected_path):
                        current_size = os.path.getsize(expected_path)
                    elif os.path.exists(expected_path + ".incomplete"):
                        current_size = os.path.getsize(expected_path + ".incomplete")
                except Exception:
                    current_size = 0
                if expected_size > 0:
                    raw_percent = int((current_size / expected_size) * 100)
                    raw_percent = max(0, min(99, raw_percent))
                    if raw_percent != last_percent:
                        _emit_progress(raw_percent, f"{label} ({raw_percent}%)")
                        last_percent = raw_percent
                elif last_percent != -2:
                    if progress_cb:
                        progress_cb(-1, label)
                    last_percent = -2
                time.sleep(0.2)

        watcher = threading.Thread(target=_watch_file, daemon=True)
        watcher.start()
        try:
            downloaded = hf_hub_download(
                repo_id=repo_id,
                revision=revision,
                filename=filename,
                local_dir=local_dir,
            )
        finally:
            stop_event.set()
            watcher.join(timeout=1.0)
        _emit_progress(100, f"{label} (100%)")
        return downloaded

    def _cleanup_empty_voice_cache_dirs(self, start_dir: str) -> None:
        base_dir = os.path.normcase(os.path.abspath(join_root("models")))
        current = os.path.abspath(str(start_dir or ""))
        while current and os.path.normcase(current).startswith(base_dir):
            try:
                if os.path.isdir(current) and not os.listdir(current):
                    os.rmdir(current)
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
                    continue
            except Exception:
                break
            break

    def _piper_voice_entries(self) -> list[dict]:
        payload = self._read_catalog()
        items: list[dict] = []
        for voice in payload.get("voices", []) or []:
            if not isinstance(voice, dict):
                continue
            if str(voice.get("provider", "")).strip().lower() != "piper":
                continue
            voice_id = str(voice.get("id", "")).strip()
            if not voice_id:
                continue
            items.append(voice)
        return items

    def _voice_pack_status(self) -> str:
        entries = self._piper_voice_entries()
        if not entries:
            return "missing"
        installed = sum(1 for entry in entries if self.is_resource_installed(f"voice:{str(entry.get('id', '')).strip()}"))
        if installed <= 0:
            return "missing"
        if installed >= len(entries):
            return "installed"
        return "partial"

    def _ai_model_filename(self, tier: str = "normal") -> str:
        return self.HIGH_AI_FILENAME if str(tier or "").strip().lower() == "high" else self.NORMAL_AI_FILENAME

    def _ai_model_local_path(self, tier: str = "normal") -> str:
        return models_path("ai", self._ai_model_filename(tier))

    def _whisper_cache_root(self) -> str:
        return models_path("faster_whisper")

    def _whisper_cache_dirs(self, model_name: str) -> list[str]:
        root = Path(self._whisper_cache_root())
        if not root.exists():
            return []
        normalized = str(model_name or "").strip().lower()
        matches: list[str] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            name = child.name.lower()
            if normalized == name:
                matches.append(str(child))
                continue
            if name.startswith("models--") and normalized in name:
                matches.append(str(child))
        return matches

    _OCR_REQUIRED_MODELS = [
        "ch_PP-OCRv4_det_mobile.onnx",
        "ch_PP-OCRv4_rec_mobile.onnx",
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "ppocr_keys_v1.txt",
    ]

    def _ocr_model_dir(self) -> str:
        try:
            import rapidocr
            return os.path.dirname(rapidocr.__file__)
        except Exception:
            return ""

    def _ocr_model_status(self) -> str:
        models_dir = self._ocr_model_dir()
        if not models_dir:
            return "missing"
        models_path = os.path.join(models_dir, "models")
        missing = [
            m for m in self._OCR_REQUIRED_MODELS
            if not os.path.isfile(os.path.join(models_path, m))
        ]
        return "missing" if missing else "installed"

    def list_resources(self) -> list[dict]:
        resources: list[dict] = [
            {
                "id": self.NORMAL_AI_RESOURCE_ID,
                "name": "Normal Quality AI Model (Hy-MT2)",
                "kind": "ai",
                "status": "installed" if self.is_resource_installed(self.NORMAL_AI_RESOURCE_ID) else "missing",
                "target_dir": os.path.dirname(self._ai_model_local_path("normal")),
                "description": "Default local GGUF model. Faster and lighter. Uses the normal-quality prompt.",
            },
            {
                "id": self.HIGH_AI_RESOURCE_ID,
                "name": "High Quality AI Model (Gemma 4)",
                "kind": "ai",
                "status": "installed" if self.is_resource_installed(self.HIGH_AI_RESOURCE_ID) else "missing",
                "target_dir": os.path.dirname(self._ai_model_local_path("high")),
                "description": "Higher quality local GGUF model. Needs a better GPU or will run slower on CPU. Uses the high-quality prompt.",
            },
            {
                "id": "whisper:medium",
                "name": "Whisper Medium",
                "kind": "whisper",
                "status": "installed" if self.is_resource_installed("whisper:medium") else "missing",
                "target_dir": self._whisper_cache_root(),
                "description": "Higher accuracy, larger download size. Downloaded via faster-whisper.",
            },
            {
                "id": "cuda:whisper",
                "name": "GPU Acceleration Pack (CUDA 12, ~1.6 GB)",
                "kind": "cuda",
                "status": "installed" if self.is_resource_installed("cuda:whisper") else "missing",
                "target_dir": join_root("bin", "cuda12_fw"),
                "description": "CUDA 12 runtime + ONNX GPU provider. Required for GPU acceleration on Whisper, OCR, and local AI.",
            },
        ]

        piper_entries = self._piper_voice_entries()
        if piper_entries:
            resources.append(
                {
                    "id": "voice:pack",
                    "name": "Vietnamese Voice Pack",
                    "kind": "voice",
                    "status": self._voice_pack_status(),
                    "target_dir": models_path("piper"),
                    "description": f"Download all {len(piper_entries)} local Piper voices at once.",
                }
            )
        return resources

    def is_resource_installed(self, resource_id: str) -> bool:
        if resource_id in {self.NORMAL_AI_RESOURCE_ID, "ai:local-gguf"}:
            return os.path.exists(self._ai_model_local_path("normal"))
        if resource_id == self.HIGH_AI_RESOURCE_ID:
            return os.path.exists(self._ai_model_local_path("high"))
        if resource_id == "cuda:whisper":
            fw_dir = join_root("bin", "cuda12_fw")
            cuda_ok = os.path.exists(os.path.join(fw_dir, "cublas64_12.dll"))
            try:
                import onnxruntime
                ort_ok = os.path.isfile(os.path.join(os.path.dirname(onnxruntime.__file__), "capi", "onnxruntime_providers_cuda.dll"))
            except Exception:
                ort_ok = False
            return cuda_ok and ort_ok
        if resource_id.startswith("whisper:"):
            model_name = resource_id.split(":", 1)[1].strip().lower()
            for model_dir in self._whisper_cache_dirs(model_name):
                try:
                    if os.path.isdir(model_dir) and any(Path(model_dir).iterdir()):
                        return True
                except Exception:
                    continue
            return False
        if resource_id == "voice:pack":
            return self._voice_pack_status() == "installed"
        if resource_id.startswith("voice:"):
            voice_id = resource_id.split(":", 1)[1].strip()
            voice_entry = self._find_voice_entry(voice_id)
            if not voice_entry:
                return False
            model_path, config_path = self._voice_local_paths(voice_entry)
            return os.path.exists(model_path) and os.path.exists(config_path)
        if resource_id == "cuda:ort":
            return self._cuda_ort_dll_status() == "installed"
        return False

    def _find_voice_entry(self, voice_id: str) -> dict | None:
        payload = self._read_catalog()
        for voice in payload.get("voices", []) or []:
            if isinstance(voice, dict) and str(voice.get("id", "")).strip() == voice_id:
                return voice
        return None

    def download_resource(self, resource_id: str, progress_cb=None) -> None:
        print(f"[DEBUG] download_resource called: {resource_id}")
        import sys
        print(f"[DEBUG] frozen={getattr(sys, 'frozen', False)} meipass={getattr(sys, '_MEIPASS', 'N/A')}")
        if resource_id.startswith("whisper:"):
            model_name = resource_id.split(":", 1)[1].strip().lower()
            if progress_cb:
                progress_cb(-1, f"Downloading Whisper {model_name} via faster-whisper...")
            from whisper_processor import load_whisper_model

            load_whisper_model(model_name)
            if progress_cb:
                progress_cb(100, f"Whisper {model_name} is ready.")
            return

        print("[DEBUG] importing huggingface_hub...")
        try:
            from huggingface_hub import hf_hub_download, hf_hub_url, snapshot_download
            from huggingface_hub.errors import RemoteEntryNotFoundError
            from huggingface_hub.file_download import get_hf_file_metadata
            print("[DEBUG] huggingface_hub imported OK")
        except Exception as exc:
            print(f"[DEBUG] huggingface_hub import FAILED: {exc}")
            raise ImportError(
                "huggingface_hub is not installed. Run `pip install huggingface_hub` first."
            ) from exc

        if resource_id in {self.NORMAL_AI_RESOURCE_ID, self.HIGH_AI_RESOURCE_ID, "ai:local-gguf"}:
            tier = "high" if resource_id == self.HIGH_AI_RESOURCE_ID else "normal"
            filename = self._ai_model_filename(tier)
            target_path = self._ai_model_local_path(tier)
            print(f"[DEBUG] {resource_id} download start. repo={self.repo_id} file={filename}")
            print(f"[DEBUG] local_dir={join_root('models')} target={target_path}")
            if progress_cb:
                progress_cb(-1, f"Downloading {os.path.basename(filename)} from Hugging Face...")
            try:
                downloaded = self._download_hf_file(
                    repo_id=self.repo_id,
                    revision=self.revision,
                    filename=filename,
                    local_dir=join_root("models"),
                    hf_hub_download=hf_hub_download,
                    hf_hub_url=hf_hub_url,
                    get_hf_file_metadata=get_hf_file_metadata,
                    progress_cb=progress_cb,
                    start_percent=0,
                    end_percent=100,
                    label=f"Downloading {os.path.basename(filename)}",
                )
                print(f"[DEBUG] download returned: {downloaded}")
            except Exception as exc:
                print(f"[DEBUG] _download_hf_file FAILED: {exc}")
                raise
            print(f"[DEBUG] moving to target: {target_path}")
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            normalized_source = os.path.normcase(os.path.abspath(downloaded))
            normalized_target = os.path.normcase(os.path.abspath(target_path))
            if normalized_source != normalized_target:
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.move(downloaded, target_path)
                self._cleanup_empty_voice_cache_dirs(os.path.dirname(downloaded))
            if progress_cb:
                progress_cb(100, f"{os.path.basename(filename)} is ready.")
            return

        if resource_id == "cuda:whisper":
            if progress_cb:
                progress_cb(-1, "Downloading CUDA runtime and ONNX GPU provider from Hugging Face...")
            snapshot_download(
                repo_id=self.repo_id,
                revision=self.revision,
                local_dir=join_root("bin"),
                allow_patterns=["cuda12_fw/*"],
            )
            try:
                from huggingface_hub import hf_hub_download, hf_hub_url
                from huggingface_hub.file_download import get_hf_file_metadata
            except Exception:
                pass
            ort_dir = ""
            try:
                import onnxruntime
                ort_dir = os.path.join(os.path.dirname(onnxruntime.__file__), "capi")
            except Exception:
                pass
            if ort_dir and os.path.isdir(ort_dir):
                target_ort = os.path.join(ort_dir, "onnxruntime_providers_cuda.dll")
                if not os.path.isfile(target_ort):
                    try:
                        downloaded = self._download_hf_file(
                            repo_id=self.repo_id,
                            revision=self.revision,
                            filename="onnxruntime/capi/onnxruntime_providers_cuda.dll",
                            local_dir=os.path.dirname(os.path.dirname(ort_dir)),
                            hf_hub_download=hf_hub_download,
                            hf_hub_url=hf_hub_url,
                            get_hf_file_metadata=get_hf_file_metadata,
                            progress_cb=progress_cb,
                            start_percent=0,
                            end_percent=100,
                            label="Downloading onnxruntime_providers_cuda.dll",
                        )
                        if downloaded and os.path.isfile(downloaded):
                            norm_src = os.path.normcase(os.path.abspath(downloaded))
                            norm_dst = os.path.normcase(os.path.abspath(target_ort))
                            if norm_src != norm_dst:
                                if os.path.exists(target_ort):
                                    os.remove(target_ort)
                                os.makedirs(ort_dir, exist_ok=True)
                                shutil.move(downloaded, target_ort)
                    except Exception as e:
                        print(f"[CUDA] Failed to download ONNX GPU provider: {e}")
            if progress_cb:
                progress_cb(100, "GPU runtime is ready.")
            return

        if resource_id.startswith("voice:"):
            if resource_id == "voice:pack":
                entries = self._piper_voice_entries()
                if not entries:
                    raise ValueError("No Piper voices were found in the local catalog.")
                total = len(entries)
                skipped: list[str] = []
                for index, voice_entry in enumerate(entries, start=1):
                    voice_id = str(voice_entry.get("id", "")).strip()
                    remote_model, remote_config = self._voice_remote_paths(voice_entry)
                    try:
                        model_start = int(((index - 1) / total) * 100)
                        model_end = int((((index - 1) + 0.5) / total) * 100)
                        config_end = int((index / total) * 100)
                        model_download = self._download_hf_file(
                            repo_id=self.repo_id,
                            revision=self.revision,
                            filename=remote_model,
                            local_dir=join_root("models"),
                            hf_hub_download=hf_hub_download,
                            hf_hub_url=hf_hub_url,
                            get_hf_file_metadata=get_hf_file_metadata,
                            progress_cb=progress_cb,
                            start_percent=model_start,
                            end_percent=model_end,
                            label=f"Downloading voice {index}/{total}: {voice_id} (model)",
                        )
                        self._finalize_voice_download(model_download, voice_entry, is_config=False)
                        config_download = self._download_hf_file(
                            repo_id=self.repo_id,
                            revision=self.revision,
                            filename=remote_config,
                            local_dir=join_root("models"),
                            hf_hub_download=hf_hub_download,
                            hf_hub_url=hf_hub_url,
                            get_hf_file_metadata=get_hf_file_metadata,
                            progress_cb=progress_cb,
                            start_percent=model_end,
                            end_percent=config_end,
                            label=f"Downloading voice {index}/{total}: {voice_id} (config)",
                        )
                        self._finalize_voice_download(config_download, voice_entry, is_config=True)
                    except RemoteEntryNotFoundError:
                        skipped.append(voice_id)
                        if progress_cb:
                            progress_cb(
                                int((index / total) * 100),
                                f"Skipping missing voice {index}/{total}: {voice_id}",
                            )
                        continue
                if progress_cb:
                    if skipped:
                        progress_cb(100, f"Voice Pack completed. Skipped missing voices: {', '.join(skipped)}")
                    else:
                        progress_cb(100, "Vietnamese Voice Pack is ready.")
                return

            voice_id = resource_id.split(":", 1)[1].strip()
            voice_entry = self._find_voice_entry(voice_id)
            if not voice_entry:
                raise ValueError(f"Voice '{voice_id}' was not found in catalog.")
            remote_model, remote_config = self._voice_remote_paths(voice_entry)
            if progress_cb:
                progress_cb(10, f"Downloading voice model: {voice_id}...")
            model_download = hf_hub_download(
                repo_id=self.repo_id,
                revision=self.revision,
                filename=remote_model,
                local_dir=join_root("models"),
            )
            self._finalize_voice_download(model_download, voice_entry, is_config=False)
            if progress_cb:
                progress_cb(60, f"Downloading voice config: {voice_id}...")
            config_download = hf_hub_download(
                repo_id=self.repo_id,
                revision=self.revision,
                filename=remote_config,
                local_dir=join_root("models"),
            )
            self._finalize_voice_download(config_download, voice_entry, is_config=True)
            if progress_cb:
                progress_cb(100, f"Voice {voice_id} is ready.")
            return

        raise ValueError(f"Unsupported resource: {resource_id}")
