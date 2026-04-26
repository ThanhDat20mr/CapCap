import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def default_checkpoint(model_dir: Path) -> Path:
    lightweight = model_dir / "model_last_repo_compatible_weights.pt"
    if lightweight.exists():
        return lightweight
    return model_dir / "model_last.pt"


def read_text(gen_text: str | None, gen_text_file: Path) -> str:
    if gen_text:
        return gen_text.strip()
    if not gen_text_file.exists():
        raise FileNotFoundError(f"Gen text file not found: {gen_text_file}")
    value = gen_text_file.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Gen text file is empty: {gen_text_file}")
    return value


def ensure_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def pick_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    workspace_model_dir = root.parent / "models" / "f5"
    model_dir = workspace_model_dir if workspace_model_dir.exists() else root / "model"
    vocoder_dir = root / "checkpoints" / "vocos-mel-24khz"

    parser = argparse.ArgumentParser(description="Minimal infer-only runner for F5-TTS.")
    parser.add_argument("--model", default="F5TTS_Base")
    parser.add_argument("--ref-audio", default=str(root / "ref.wav"))
    parser.add_argument("--ref-text", default="cả hai bên hãy cố gắng hiểu cho nhau")
    parser.add_argument("--gen-text", default=None, help="Direct text to synthesize.")
    parser.add_argument("--gen-text-file", default=str(root / "gen_text.txt"))
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu", "xpu", "mps"], default="auto")
    parser.add_argument("--vocoder-local-dir", default=str(vocoder_dir))
    parser.add_argument("--vocab-file", default=str(model_dir / "vocab.txt"))
    parser.add_argument("--ckpt-file", default=str(default_checkpoint(model_dir)))
    parser.add_argument("--output-wav", default=str(root / "infer_only_out.wav"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    ref_audio = Path(args.ref_audio)
    vocab_file = Path(args.vocab_file)
    ckpt_file = Path(args.ckpt_file)
    gen_text_file = Path(args.gen_text_file)
    vocoder_local_dir = Path(args.vocoder_local_dir)
    output_wav = Path(args.output_wav)

    try:
        ensure_file(ref_audio, "Reference audio")
        ensure_file(vocab_file, "Vocab file")
        ensure_file(ckpt_file, "Checkpoint file")
        ensure_file(vocoder_local_dir / "config.yaml", "Local vocoder config")
        ensure_file(vocoder_local_dir / "pytorch_model.bin", "Local vocoder weights")
        gen_text = read_text(args.gen_text, gen_text_file)
    except (FileNotFoundError, ValueError) as exc:
        print(exc)
        return 1

    try:
        import torch
        from f5_tts.api import F5TTS
    except Exception as exc:
        print(f"Import failed: {exc}")
        return 1

    device = pick_device(args.device)
    print(f"python: {sys.executable}")
    print(f"torch: {torch.__version__}")
    print(f"device: {device}")
    if device == "cuda":
        try:
            print(f"gpu: {torch.cuda.get_device_name(0)}")
        except Exception:
            pass

    try:
        tts = F5TTS(
            model=args.model,
            ckpt_file=str(ckpt_file),
            vocab_file=str(vocab_file),
            vocoder_local_path=str(vocoder_local_dir),
            device=device,
        )
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        tts.infer(
            ref_file=str(ref_audio),
            ref_text=args.ref_text,
            gen_text=gen_text,
            speed=float(args.speed),
            file_wave=str(output_wav),
        )
        print(f"done: {output_wav}")
        return 0
    except Exception as exc:
        print(f"inference failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
