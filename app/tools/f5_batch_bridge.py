import argparse
import json
import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="CapCap F5-TTS bridge")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = os.path.abspath(str(args.repo_root))
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ffmpeg_bin = os.path.join(workspace_root, "bin", "ffmpeg", "ffmpeg.exe")
    ffprobe_bin = os.path.join(workspace_root, "bin", "ffmpeg", "ffprobe.exe")
    if os.path.exists(ffmpeg_bin):
        os.environ.setdefault("FFMPEG_BINARY", ffmpeg_bin)
        os.environ["PATH"] = os.path.dirname(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
    if os.path.exists(ffprobe_bin):
        os.environ.setdefault("FFPROBE_BINARY", ffprobe_bin)
    repo_src = os.path.join(repo_root, "src")
    for candidate in (repo_src, repo_root):
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)

    with open(args.input_json, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    import torch
    from f5_tts.api import F5TTS

    bundled_model_root = os.path.join(workspace_root, "models", "f5")
    repo_model_root = os.path.join(repo_root, "model")
    model_root = bundled_model_root if os.path.isdir(bundled_model_root) else repo_model_root
    ckpt_file = os.path.join(model_root, "model_last_repo_compatible_weights.pt")
    if not os.path.exists(ckpt_file):
        fallback_ckpt = os.path.join(model_root, "model_last.pt")
        if os.path.exists(fallback_ckpt):
            ckpt_file = fallback_ckpt
    vocab_file = os.path.join(model_root, "vocab.txt")
    vocoder_local_path = os.path.join(repo_root, "checkpoints", "vocos-mel-24khz")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[F5 Bridge] python={sys.executable}")
    print(f"[F5 Bridge] device={device}")
    if device == "cuda":
        try:
            print(f"[F5 Bridge] gpu={torch.cuda.get_device_name(0)}")
        except Exception:
            pass

    tts = F5TTS(
        model="F5TTS_Base",
        ckpt_file=ckpt_file,
        vocab_file=vocab_file,
        vocoder_local_path=vocoder_local_path,
        device=device,
    )

    ref_audio_path = os.path.abspath(str(payload.get("ref_audio_path", "")).strip())
    ref_text = str(payload.get("ref_text", "")).strip()
    jobs = list(payload.get("jobs", []) or [])
    results = []
    for index, job in enumerate(jobs):
        text = str((job or {}).get("text", "")).strip()
        wav_path = os.path.abspath(str((job or {}).get("wav_path", "")).strip())
        speed = float((job or {}).get("speed", 1.0) or 1.0)
        if not text or not wav_path:
            results.append({"ok": False, "wav_path": wav_path, "error": "Job is missing text or wav_path."})
            continue
        os.makedirs(os.path.dirname(wav_path), exist_ok=True)
        try:
            print(f"Generating F5 audio {index + 1}/{len(jobs)}...")
            tts.infer(ref_file=ref_audio_path, ref_text=ref_text, gen_text=text, speed=speed, file_wave=wav_path)
            results.append({"ok": True, "wav_path": wav_path})
        except Exception as exc:
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            results.append({"ok": False, "wav_path": wav_path, "error": details or str(exc) or exc.__class__.__name__})

    with open(args.output_json, "w", encoding="utf-8") as handle:
        json.dump({"jobs": results}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 1 if any(not bool(item.get("ok", False)) for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
