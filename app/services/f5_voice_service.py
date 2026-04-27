from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

import requests


DEFAULT_F5_REPO_ROOT = r"D:\CodingTime\CapCap\f5_tts_voice"
DEFAULT_F5_PYTHON = sys.executable or "python"
DEFAULT_F5_API_URL = "http://127.0.0.1:8766"
PREFERRED_F5_PYTHONS = [
    r"C:\Users\Thach\AppData\Local\Programs\Python\Python311\python.exe",
]


class F5VoiceService:
    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.abspath(str(workspace_root or ""))
        self.data_root = os.path.join(self.workspace_root, "data", "f5_voice")
        self.saved_audio_root = os.path.join(self.data_root, "saved_audio")
        self.saved_registry_path = os.path.join(self.data_root, "saved_clones.json")
        self.temp_registry_path = os.path.join(self.data_root, "temp_clones.json")
        self.bridge_script_path = os.path.join(self.workspace_root, "app", "tools", "f5_batch_bridge.py")
        self._api_health_checked_at = 0.0
        self._api_health_ok = False
        os.makedirs(self.saved_audio_root, exist_ok=True)
        try:
            self.ensure_default_clones()
        except Exception:
            pass

    @staticmethod
    def is_f5_voice_token(token: str) -> bool:
        return str(token or "").strip().lower().startswith("f5:")

    def f5_repo_root(self) -> str:
        return DEFAULT_F5_REPO_ROOT

    def f5_python_command(self) -> str:
        for candidate in PREFERRED_F5_PYTHONS:
            if candidate and os.path.exists(candidate):
                return candidate
        return DEFAULT_F5_PYTHON

    def f5_api_base_url(self) -> str:
        return str(os.getenv("CAPCAP_F5_API_URL", DEFAULT_F5_API_URL) or DEFAULT_F5_API_URL).strip().rstrip("/")

    def f5_api_timeout_seconds(self) -> int:
        raw = str(os.getenv("CAPCAP_F5_API_TIMEOUT", "3600") or "3600").strip()
        try:
            return max(30, int(raw))
        except Exception:
            return 3600

    def _f5_api_is_available(self, *, force: bool = False) -> bool:
        now = time.time()
        if not force and (now - self._api_health_checked_at) < 5.0:
            return self._api_health_ok
        self._api_health_checked_at = now
        base_url = self.f5_api_base_url()
        try:
            response = requests.get(f"{base_url}/health", timeout=1.5)
            response.raise_for_status()
            payload = response.json()
            self._api_health_ok = bool(isinstance(payload, dict) and payload.get("ok", False))
        except Exception:
            self._api_health_ok = False
        return self._api_health_ok

    def get_api_status(self, *, force: bool = False) -> dict:
        base_url = self.f5_api_base_url()
        now = time.time()
        if (
            not force
            and (now - self._api_health_checked_at) < 5.0
            and self._api_health_ok
        ):
            return {
                "ok": True,
                "url": base_url,
            }
        self._api_health_checked_at = now
        try:
            response = requests.get(f"{base_url}/health", timeout=1.5)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload.get("ok", False):
                raise RuntimeError("F5 API returned invalid health response.")
            self._api_health_ok = True
            return {
                "ok": True,
                "url": base_url,
                "loaded": bool(payload.get("loaded", False)),
                "device": str(payload.get("device", "") or "").strip(),
                "gpu": str(payload.get("gpu", "") or "").strip(),
                "python": str(payload.get("python", "") or "").strip(),
            }
        except Exception as exc:
            self._api_health_ok = False
            return {
                "ok": False,
                "url": base_url,
                "error": str(exc),
            }

    def _load_registry(self, path: str) -> dict:
        if not os.path.exists(path):
            return {"schema_version": 1, "voices": []}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                payload.setdefault("schema_version", 1)
                payload.setdefault("voices", [])
                if isinstance(payload.get("voices"), list):
                    return payload
        except Exception:
            pass
        return {"schema_version": 1, "voices": []}

    def _save_registry(self, path: str, payload: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def _slugify(self, value: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
        return text or "voice"

    def _file_signature(self, path: str) -> str:
        normalized = os.path.abspath(str(path or "").strip())
        if not normalized or not os.path.exists(normalized):
            return normalized
        stat = os.stat(normalized)
        return json.dumps(
            {
                "path": normalized,
                "size": int(stat.st_size),
                "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
            },
            ensure_ascii=True,
            sort_keys=True,
        )

    def _find_saved_voice(self, voice_id: str):
        payload = self._load_registry(self.saved_registry_path)
        voices = list(payload.get("voices", []) or [])
        for index, entry in enumerate(voices):
            if str((entry or {}).get("id", "")).strip() == str(voice_id or "").strip():
                return dict(entry), payload, index
        return None, payload, -1

    def _find_temp_voice(self, voice_id: str):
        payload = self._load_registry(self.temp_registry_path)
        voices = list(payload.get("voices", []) or [])
        for index, entry in enumerate(voices):
            if str((entry or {}).get("id", "")).strip() == str(voice_id or "").strip():
                return dict(entry), payload, index
        return None, payload, -1

    def list_saved_voices(self) -> list[dict]:
        print(f"[F5Voice] data_root={self.data_root} registry={self.saved_registry_path}")
        payload = self._load_registry(self.saved_registry_path)
        voices = []
        for entry in list(payload.get("voices", []) or []):
            if not isinstance(entry, dict):
                continue
            voice_id = str(entry.get("id", "")).strip()
            ref_audio_path = os.path.abspath(str(entry.get("ref_audio_path", "")).strip())
            if not voice_id or not ref_audio_path or not os.path.exists(ref_audio_path):
                print(f"[F5Voice] Skip invalid entry: id={voice_id} exists={os.path.exists(ref_audio_path)}")
                continue
            item = dict(entry)
            item["ref_audio_path"] = ref_audio_path
            voices.append(item)
        print(f"[F5Voice] saved_voices={len(voices)}")
        voices.sort(key=lambda item: (str(item.get("name", "")).strip().lower(), str(item.get("created_at", ""))))
        return voices

    def get_default_clone_samples(self) -> list[dict]:
        base_samples = [
            {
                "name": "Sample Male",
                "ref_audio_path": os.path.join(self.workspace_root, "f5_tts_voice", "ref.wav"),
                "ref_text": "Xin chào, đây là giọng nói mẫu cho bản sao tiếng Việt.",
            },
        ]
        return [
            s for s in base_samples
            if os.path.exists(str(s.get("ref_audio_path", "")).strip())
        ]

    def ensure_default_clones(self) -> int:
        existing = self.list_saved_voices()
        if existing:
            return 0
        samples = self.get_default_clone_samples()
        if not samples:
            return 0
        count = 0
        for sample in samples:
            try:
                self.save_clone(
                    name=str(sample.get("name", "")).strip(),
                    ref_audio_path=str(sample.get("ref_audio_path", "")).strip(),
                    ref_text=str(sample.get("ref_text", "")).strip(),
                )
                count += 1
            except Exception:
                pass
        return count

    def save_clone(self, *, name: str, ref_audio_path: str, ref_text: str = "") -> dict:
        normalized_audio = os.path.abspath(str(ref_audio_path or "").strip())
        if not normalized_audio or not os.path.exists(normalized_audio):
            raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")

        base_name = str(name or "").strip() or os.path.splitext(os.path.basename(normalized_audio))[0]
        slug_base = self._slugify(base_name)
        payload = self._load_registry(self.saved_registry_path)
        voices = list(payload.get("voices", []) or [])
        existing_ids = {str((entry or {}).get("id", "")).strip() for entry in voices if isinstance(entry, dict)}
        voice_id = slug_base
        suffix = 2
        while voice_id in existing_ids:
            voice_id = f"{slug_base}-{suffix}"
            suffix += 1

        ext = os.path.splitext(normalized_audio)[1].strip() or ".wav"
        copied_audio_path = os.path.join(self.saved_audio_root, f"{voice_id}{ext}")
        shutil.copy2(normalized_audio, copied_audio_path)

        entry = {
            "id": voice_id,
            "name": base_name,
            "ref_audio_path": copied_audio_path,
            "ref_text": str(ref_text or "").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "engine": "f5",
        }
        voices.append(entry)
        payload["voices"] = voices
        self._save_registry(self.saved_registry_path, payload)
        return dict(entry)

    def create_temporary_clone(self, *, ref_audio_path: str, ref_text: str = "", display_name: str = "") -> dict:
        normalized_audio = os.path.abspath(str(ref_audio_path or "").strip())
        if not normalized_audio or not os.path.exists(normalized_audio):
            raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")

        name = str(display_name or "").strip() or os.path.splitext(os.path.basename(normalized_audio))[0]
        seed = "|".join([self._file_signature(normalized_audio), str(ref_text or "").strip(), name])
        voice_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
        payload = self._load_registry(self.temp_registry_path)
        voices = list(payload.get("voices", []) or [])
        entry = {
            "id": voice_id,
            "name": name,
            "ref_audio_path": normalized_audio,
            "ref_text": str(ref_text or "").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "engine": "f5",
        }
        updated = False
        for index, current in enumerate(voices):
            if str((current or {}).get("id", "")).strip() == voice_id:
                voices[index] = entry
                updated = True
                break
        if not updated:
            voices.append(entry)
        payload["voices"] = voices[-100:]
        self._save_registry(self.temp_registry_path, payload)
        result = dict(entry)
        result["token"] = f"f5:temp:{voice_id}"
        return result

    def resolve_voice_token(self, voice_token: str) -> dict:
        raw = str(voice_token or "").strip()
        parts = raw.split(":")
        if len(parts) < 3 or parts[0].lower() != "f5":
            raise ValueError(f"Unsupported F5 voice token: {voice_token}")
        scope = parts[1].strip().lower()
        voice_id = ":".join(parts[2:]).strip()
        if not voice_id:
            raise ValueError("F5 voice token is missing an id.")

        if scope == "clone":
            entry, _payload, _index = self._find_saved_voice(voice_id)
        elif scope == "temp":
            entry, _payload, _index = self._find_temp_voice(voice_id)
        else:
            raise ValueError(f"Unsupported F5 voice token scope: {scope}")

        if not entry:
            raise FileNotFoundError(f"F5 voice profile not found: {voice_id}")

        entry["scope"] = scope
        entry["token"] = raw
        entry["ref_audio_path"] = os.path.abspath(str(entry.get("ref_audio_path", "")).strip())
        return entry

    def _update_voice_entry(self, *, scope: str, voice_id: str, entry: dict) -> None:
        registry_path = self.saved_registry_path if scope == "clone" else self.temp_registry_path
        payload = self._load_registry(registry_path)
        voices = list(payload.get("voices", []) or [])
        for index, current in enumerate(voices):
            if str((current or {}).get("id", "")).strip() == str(voice_id or "").strip():
                voices[index] = dict(entry)
                payload["voices"] = voices
                self._save_registry(registry_path, payload)
                return

    def ensure_ref_text(self, voice_token: str) -> dict:
        entry = self.resolve_voice_token(voice_token)
        ref_text = str(entry.get("ref_text", "")).strip()
        if ref_text:
            return entry

        raise ValueError(
            "Reference text is required for F5 voice cloning. "
            "Please enter the reference text in the UI."
        )

    def _synthesize_batch_via_api(self, *, entry: dict, request_jobs: list[dict], on_progress: callable | None = None) -> list[str]:
        base_url = self.f5_api_base_url()
        payload = {
            "ref_audio_path": str(entry.get("ref_audio_path", "")).strip(),
            "ref_text": str(entry.get("ref_text", "")).strip(),
            "jobs": request_jobs,
        }
        started_at = time.perf_counter()
        print(f"[F5 API Client] url={base_url}")
        print(f"[F5 API Client] jobs={len(request_jobs)}")
        response = requests.post(
            f"{base_url}/v1/f5/synthesize-batch",
            json=payload,
            timeout=self.f5_api_timeout_seconds(),
        )
        elapsed = time.perf_counter() - started_at
        print(f"[F5 API Client] elapsed={elapsed:.2f}s")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok", False):
            raise RuntimeError(str((payload or {}).get("error") or "F5 API request failed."))
        if on_progress:
            on_progress(f"[F5 API] python={payload.get('python', '')}")
            on_progress(f"[F5 API] device={payload.get('device', '')}")
            gpu = str(payload.get("gpu", "") or "").strip()
            if gpu:
                on_progress(f"[F5 API] gpu={gpu}")
        response_jobs = list(payload.get("jobs", []) or [])
        if len(response_jobs) != len(request_jobs):
            raise RuntimeError("F5 API returned an unexpected number of synthesis results.")
        outputs = []
        for index, response_job in enumerate(response_jobs):
            if not bool(response_job.get("ok", False)):
                raise RuntimeError(str(response_job.get("error", "") or f"F5 API failed for job {index + 1}.").strip())
            wav_path = os.path.abspath(str(response_job.get("wav_path", "")).strip())
            if not wav_path or not os.path.exists(wav_path):
                raise RuntimeError(f"F5 API did not produce expected wav file for job {index + 1}.")
            outputs.append(wav_path)
        return outputs

    def synthesize_batch(self, *, voice_token: str, jobs: list[dict], temp_dir: str = "", on_progress: callable | None = None) -> list[str]:
        repo_root = self.f5_repo_root()
        if not repo_root or not os.path.isdir(repo_root):
            raise FileNotFoundError(f"F5 repo not found: {repo_root}")
        if not os.path.exists(self.bridge_script_path):
            raise FileNotFoundError(f"F5 bridge script not found: {self.bridge_script_path}")

        entry = self.ensure_ref_text(voice_token)
        work_dir = temp_dir or os.path.join(self.data_root, "runtime")
        os.makedirs(work_dir, exist_ok=True)

        request_jobs = []
        for job in list(jobs or []):
            text = str((job or {}).get("text", "")).strip()
            wav_path = os.path.abspath(str((job or {}).get("wav_path", "")).strip())
            speed = float((job or {}).get("speed", 1.0) or 1.0)
            if not text or not wav_path:
                raise ValueError("F5 synth job is missing text or wav_path.")
            os.makedirs(os.path.dirname(wav_path), exist_ok=True)
            request_jobs.append({"text": text, "wav_path": wav_path, "speed": speed})

        if self._f5_api_is_available():
            return self._synthesize_batch_via_api(entry=entry, request_jobs=request_jobs, on_progress=on_progress)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json", dir=work_dir) as request_file:
            json.dump(
                {
                    "ref_audio_path": str(entry.get("ref_audio_path", "")).strip(),
                    "ref_text": str(entry.get("ref_text", "")).strip(),
                    "jobs": request_jobs,
                },
                request_file,
                ensure_ascii=False,
                indent=2,
            )
            request_path = request_file.name

        response_fd, response_path = tempfile.mkstemp(prefix="f5_bridge_response_", suffix=".json", dir=work_dir)
        os.close(response_fd)
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            python_cmd = self.f5_python_command()
            print(f"[F5 Service] python={python_cmd}")
            print(f"[F5 Service] repo={repo_root}")
            print(f"[F5 Service] jobs={len(request_jobs)}")
            started_at = time.perf_counter()
            result = subprocess.run(
                [
                    python_cmd,
                    self.bridge_script_path,
                    "--repo-root",
                    repo_root,
                    "--input-json",
                    request_path,
                    "--output-json",
                    response_path,
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            elapsed = time.perf_counter() - started_at
            print(f"[F5 Service] returncode={result.returncode} elapsed={elapsed:.2f}s")
            if result.stdout and on_progress:
                for line in str(result.stdout).splitlines():
                    line = line.strip()
                    if line:
                        on_progress(f"[F5] {line}")
            payload = {}
            if os.path.exists(response_path):
                try:
                    with open(response_path, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                except Exception:
                    payload = {}
            response_jobs = list(payload.get("jobs", []) or [])
            if result.returncode != 0 and response_jobs:
                for response_job in response_jobs:
                    if not bool(response_job.get("ok", False)):
                        error_text = str(response_job.get("error", "") or "").strip()
                        if error_text:
                            raise RuntimeError(error_text)
            if result.returncode != 0:
                existing_outputs = []
                for request_job in request_jobs:
                    wav_path = os.path.abspath(str((request_job or {}).get("wav_path", "")).strip())
                    if wav_path and os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                        existing_outputs.append(wav_path)
                if len(existing_outputs) == len(request_jobs):
                    if on_progress:
                        on_progress("[F5] Bridge returned non-zero exit, but audio files were created. Using generated output.")
                    return existing_outputs
            if result.returncode != 0:
                error_text = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()
                raise RuntimeError(error_text or f"F5 bridge failed with exit code {result.returncode}.")

            response_jobs = list(payload.get("jobs", []) or [])
            if len(response_jobs) != len(request_jobs):
                raise RuntimeError("F5 bridge returned an unexpected number of synthesis results.")

            outputs = []
            for index, response_job in enumerate(response_jobs):
                if not bool(response_job.get("ok", False)):
                    error_text = str(response_job.get("error", "") or "Unknown F5 generation error.").strip()
                    raise RuntimeError(error_text)
                wav_path = os.path.abspath(str(response_job.get("wav_path", "")).strip())
                if not wav_path or not os.path.exists(wav_path):
                    raise RuntimeError(f"F5 did not produce expected wav file for job {index + 1}.")
                outputs.append(wav_path)
            return outputs
        finally:
            for candidate in (request_path, response_path):
                try:
                    if candidate and os.path.exists(candidate):
                        os.remove(candidate)
                except OSError:
                    pass

    def synthesize_segment(self, *, voice_token: str, text: str, wav_path: str, speed: float = 1.0, temp_dir: str = "", on_progress: callable | None = None) -> str:
        outputs = self.synthesize_batch(
            voice_token=voice_token,
            jobs=[{"text": str(text or "").strip(), "wav_path": str(wav_path or "").strip(), "speed": float(speed or 1.0)}],
            temp_dir=temp_dir,
            on_progress=on_progress,
        )
        return outputs[0] if outputs else ""
