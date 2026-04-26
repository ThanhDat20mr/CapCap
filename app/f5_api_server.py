from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import faulthandler
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    faulthandler.enable()
except Exception:
    pass

os.environ.setdefault("CAPCAP_RUNTIME_PROFILE", "local")


def _workspace_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _json_response(handler: BaseHTTPRequestHandler, status_code: int, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class F5Runtime:
    def __init__(self) -> None:
        self.workspace_root = _workspace_root()
        self.repo_root = os.path.join(self.workspace_root, "f5_tts_voice")
        self.model_root = os.path.join(self.workspace_root, "models", "f5")
        self.vocoder_root = os.path.join(self.repo_root, "checkpoints", "vocos-mel-24khz")
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()
        self._tts = None
        self._device = ""
        self._gpu_name = ""
        self._loaded_at = 0.0

    def _ensure_ffmpeg_env(self) -> None:
        ffmpeg_bin = os.path.join(self.workspace_root, "bin", "ffmpeg", "ffmpeg.exe")
        ffprobe_bin = os.path.join(self.workspace_root, "bin", "ffmpeg", "ffprobe.exe")
        if os.path.exists(ffmpeg_bin):
            os.environ.setdefault("FFMPEG_BINARY", ffmpeg_bin)
            os.environ["PATH"] = os.path.dirname(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
        if os.path.exists(ffprobe_bin):
            os.environ.setdefault("FFPROBE_BINARY", ffprobe_bin)

    def _resolve_model_root(self) -> str:
        if os.path.isdir(self.model_root):
            return self.model_root
        return os.path.join(self.repo_root, "model")

    def ensure_loaded(self):
        with self._lock:
            if self._tts is not None:
                return self._tts
            self._ensure_ffmpeg_env()
            if self.repo_root not in sys.path:
                sys.path.insert(0, self.repo_root)
            import torch
            from f5_tts.api import F5TTS

            device = "cuda" if torch.cuda.is_available() else "cpu"
            gpu_name = ""
            if device == "cuda":
                try:
                    gpu_name = torch.cuda.get_device_name(0)
                except Exception:
                    gpu_name = ""
            model_root = self._resolve_model_root()
            ckpt_file = os.path.join(model_root, "model_last_repo_compatible_weights.pt")
            if not os.path.exists(ckpt_file):
                fallback_ckpt = os.path.join(model_root, "model_last.pt")
                if os.path.exists(fallback_ckpt):
                    ckpt_file = fallback_ckpt
            vocab_file = os.path.join(model_root, "vocab.txt")
            started = time.perf_counter()
            self._tts = F5TTS(
                model="F5TTS_Base",
                ckpt_file=ckpt_file,
                vocab_file=vocab_file,
                vocoder_local_path=self.vocoder_root,
                device=device,
            )
            self._device = device
            self._gpu_name = gpu_name
            self._loaded_at = time.time()
            elapsed = time.perf_counter() - started
            print(f"[F5 API] Loaded runtime in {elapsed:.2f}s")
            print(f"[F5 API] python={sys.executable}")
            print(f"[F5 API] device={device}")
            if gpu_name:
                print(f"[F5 API] gpu={gpu_name}")
            return self._tts

    def status(self) -> dict:
        return {
            "loaded": self._tts is not None,
            "device": self._device,
            "gpu": self._gpu_name,
            "python": sys.executable,
            "repo_root": self.repo_root,
            "loaded_at": self._loaded_at,
        }

    @staticmethod
    def _log_info(*parts) -> None:
        try:
            text = " ".join(str(part) for part in parts)
        except Exception:
            text = str(parts)
        print(text)

    def synthesize_batch(self, *, ref_audio_path: str, ref_text: str, jobs: list[dict]) -> list[dict]:
        with self._synth_lock:
            tts = self.ensure_loaded()
            ref_audio_path = os.path.abspath(str(ref_audio_path or "").strip())
            if not ref_audio_path or not os.path.exists(ref_audio_path):
                raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")
            ref_text = str(ref_text or "").strip()
            if not ref_text:
                raise ValueError("ref_text is required.")

            results = []
            for index, job in enumerate(list(jobs or []), start=1):
                text = str((job or {}).get("text", "")).strip()
                wav_path = os.path.abspath(str((job or {}).get("wav_path", "")).strip())
                speed = float((job or {}).get("speed", 1.0) or 1.0)
                if not text or not wav_path:
                    results.append({"ok": False, "wav_path": wav_path, "error": "Job is missing text or wav_path."})
                    continue
                os.makedirs(os.path.dirname(wav_path), exist_ok=True)
                started = time.perf_counter()
                try:
                    print(f"[F5 API] Synth {index}/{len(jobs)} start")
                    tts.infer(
                        ref_file=ref_audio_path,
                        ref_text=ref_text,
                        gen_text=text,
                        speed=speed,
                        file_wave=wav_path,
                        show_info=self._log_info,
                        progress=None,
                    )
                    elapsed = time.perf_counter() - started
                    print(f"[F5 API] Synth {index}/{len(jobs)} done in {elapsed:.2f}s")
                    results.append({"ok": True, "wav_path": wav_path, "elapsed": elapsed})
                except Exception as exc:
                    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
                    results.append({"ok": False, "wav_path": wav_path, "error": details or str(exc)})
            return results


RUNTIME = F5Runtime()


class F5ApiHandler(BaseHTTPRequestHandler):
    server_version = "CapCapF5Api/1.0"

    def do_GET(self):
        try:
            if self.path == "/health":
                _json_response(self, 200, {"ok": True, "service": "capcap-f5-api", **RUNTIME.status()})
                return
            _json_response(self, 404, {"ok": False, "error": "Not found"})
        except Exception as exc:
            _json_response(self, 500, {"ok": False, "error": str(exc)})

    def do_POST(self):
        try:
            payload = self._read_json_body()
            if self.path == "/v1/f5/synthesize-batch":
                jobs = RUNTIME.synthesize_batch(
                    ref_audio_path=str(payload.get("ref_audio_path", "") or ""),
                    ref_text=str(payload.get("ref_text", "") or ""),
                    jobs=list(payload.get("jobs") or []),
                )
                _json_response(self, 200, {"ok": True, "jobs": jobs, **RUNTIME.status()})
                return
            _json_response(self, 404, {"ok": False, "error": "Not found"})
        except Exception as exc:
            print("[F5 API] Request failed:")
            print("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip())
            _json_response(self, 500, {"ok": False, "error": str(exc)})

    def log_message(self, format, *args):
        print(f"[F5 API] {self.address_string()} - {format % args}")

    def _read_json_body(self) -> dict:
        raw_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(raw_length) if raw_length > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload


def main() -> None:
    host = str(os.getenv("CAPCAP_F5_API_HOST", "127.0.0.1") or "127.0.0.1").strip()
    port_raw = str(os.getenv("CAPCAP_F5_API_PORT", "8766") or "8766").strip()
    try:
        port = int(port_raw)
    except Exception:
        port = 8766
    try:
        server = HTTPServer((host, port), F5ApiHandler)
        print(f"[F5 API] Listening on http://{host}:{port}")
        server.serve_forever()
    except Exception as exc:
        print("[F5 API] Fatal server error:")
        print("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip())
        raise


if __name__ == "__main__":
    main()
