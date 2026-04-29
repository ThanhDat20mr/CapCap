# CapCap 🦆

![CapCap Editor Preview](assets/preview.jpg)

CapCap is a Windows desktop app for short-form video localization and dubbing. It brings transcription, translation, subtitle styling, voice generation, timeline editing, preview, and export into a single project workflow for Vietnamese-focused content production.

## Current Preview

The current editor combines workflow controls, subtitle style presets, a centered video preview, a subtitle inspector, and a multi-lane timeline in one screen so subtitle and voiceover work can be reviewed side by side.

## Core Features

- Project-based workflow with resume support
- Three output modes:
  - `subtitle only`
  - `voice only`
  - `subtitle + voice`
- Speech-to-text with `faster-whisper` (local or remote backend)
- Subtitle translation and rewrite with local / remote AI support
- AI polish and subtitle rewrite tools for timing-friendly phrasing
- Vietnamese voice generation with `Piper`, `edge-tts`, and `F5` voice cloning
- Separate subtitle text and voice text editing
- Subtitle highlight styling and preset-driven subtitle looks
- Video filter support for preview and export workflows
- Audio mix and export with `FFmpeg`
- Live video preview with subtitle overlay
- Timeline editing for subtitle, audio, and video alignment
- **Remote mode** for offloading ALL heavy processing (Whisper + AI + TTS + Export) to a backend API server

## Editor UI / Tools

The current desktop editor includes:

- Top header actions:
  - `Generate`
  - `Export`
  - `More`
- Left workflow panel:
  - `Media`
  - `Language`
  - `Voice`
  - `Style`
  - `Filter`
  - `Advanced`
- Always-visible `Status` summary card
- Subtitle style preset cards for `TikTok`, `YouTube`, `Short`, and `Custom`
- Center video preview with live subtitle overlay
- Playback and framing controls under the preview
- Right-side `Subtitle Inspector` with rewrite, import, highlight, subtitle, and voice editing tools
- Multi-lane timeline for:
  - `Subtitle`
  - `Audio`
  - `Video`

Current editor interactions:

- Preview subtitle timing directly against the rendered video
- Select subtitle blocks from the timeline or inspector
- Rewrite the full script or a selected subtitle block
- Edit subtitle and voice text independently
- Add highlight styling from the selected subtitle text
- Split, delete, nudge, zoom, and fit timeline segments before export
- Switch subtitle style presets while reviewing the live preview
- Prepare export-ready subtitle timing without leaving the main editor

`More` menu actions include project utilities such as subtitle/script visibility, cleanup, and settings.

## Technical Stack

- `PySide6` for desktop UI
- `libmpv` / media backend for preview
- `QThread` workers for background processing
- `faster-whisper` for local ASR
- `FFmpeg` for extract, mix, mux, export
- `Demucs` for vocal/background separation
- `Piper TTS`, `edge-tts`, and `F5-TTS`
- `llama-cpp-python` for local AI rewrite / polish
- `requests` for remote integrations
- `PyInstaller` for packaging

## Architecture

### Local Mode (Full Desktop)
Everything runs on the local machine. Requires all heavy ML dependencies (whisper, demucs, piper, F5-TTS, AI models).

### Remote Mode (Thin Client + Backend API)
The remote GUI is a thin client. All heavy processing runs on a backend API server:

- **Remote GUI** (`CapCap.remote.spec`) — bundles only UI + FFmpeg + MPV. No heavy ML models.
- **Backend API** (`app/remote_api_server.py`) — handles Whisper, translation, TTS, and export workflows.

Backend endpoints:
- `POST /v1/prepare` — runs PrepareWorkflow (extract, transcribe, translate)
- `POST /v1/voice` — runs VoiceWorkflow (TTS synthesis + audio mix)
- `POST /v1/export` — runs ExportWorkflow (video mux)
- `POST /v1/tts/synthesize` — single-segment TTS
- `POST /v1/transcribe` — speech-to-text
- `POST /v1/translate-*` — translation endpoints

Set `CAPCAP_REMOTE_API_URL` (default `http://127.0.0.1:8765`) and `CAPCAP_REMOTE_API_TOKEN` to connect.

In remote mode:
- Voice catalog is bundled with the GUI (no local `.onnx` files needed)
- F5 clone voices are cached locally in `data/f5_voice/` on the GUI machine
- The backend owns Piper models and synthesizes audio remotely

## Workflow

1. Load a video and choose the source and target language.
2. Generate subtitles, translation, or voiceover assets.
3. Review subtitle styling, timing, and voice text in the editor.
4. Fine-tune segments in the subtitle inspector and timeline.
5. Preview the result, then export subtitles, dubbed audio, or the full video.

## Run From Source

Clone the repo:

```bash
git clone https://github.com/notepower2k1/CapCap.git
cd CapCap
```

Install a profile:

### Local

```bash
pip install -r requirements-local.txt
python ui/gui.py
```

### Remote Client

```bash
pip install -r requirements-remote.txt
python ui/gui_remote.py
```

### Remote Server

```bash
pip install -r requirements-server.txt
python app/remote_api_server.py
```

## Packaging

### Local release

```bash
python -m PyInstaller CapCap.spec --noconfirm --clean
```

### Local debug

```bash
python -m PyInstaller CapCap.debug.spec --noconfirm --clean
```

### Remote client

```bash
python -m PyInstaller CapCap.remote.spec --noconfirm --clean
```

### Server

```bash
python -m PyInstaller CapCap.server.spec --noconfirm --clean
```

## Repo Guide

See [structure.md](./structure.md) for a codebase map and important entrypoints.

## References

This project builds on and references the following open-source projects:

- [F5-TTS-Vietnamese](https://github.com/nguyenthienhy/F5-TTS-Vietnamese) — Vietnamese voice cloning
- [llama-cpp-python](https://github.com/JamePeng/llama-cpp-python) — Local LLM inference
- [vietnormalizer](https://github.com/nghimestudio/vietnormalizer) — Vietnamese text normalization
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech-to-text transcription
- [piper](https://github.com/rhasspy/piper) — Local text-to-speech synthesis
- [demucs](https://github.com/facebookresearch/demucs) — Vocal/background audio separation

## CUDA Requirements

GPU acceleration is **strongly recommended** for a smooth experience but not strictly required.

| Component | GPU recommended | Notes |
|---|---|---|
| **faster-whisper** | Optional | CPU works but is much slower; GPU (CUDA 11/12) speeds up transcription significantly |
| **Demucs** | Recommended | Vocal separation on CPU is very slow; GPU inference is preferred |
| **F5-TTS** | **Required** for cloning | F5 voice cloning is practically unusable on CPU; needs CUDA-capable GPU |
| **llama-cpp-python** | Optional | Local LLM inference can use CPU; GPU (CUDA) speeds up translation/polish |

**Minimum:** NVIDIA GPU with Compute Capability >= 5.0 (e.g., GTX 1050 Ti) and CUDA toolkit installed.
**Recommended:** RTX 2060 or better with at least 6GB VRAM.

For CPU-only setups, expect transcription and voice synthesis to be significantly slower.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](./LICENSE).

## Resource
[Hugging Face](https://huggingface.co/Hacht/CapCapResource)
## Notes

- The app is currently optimized for Windows.
- Some AI, ASR, separation, and voice synthesis steps can be slow on weaker machines.
- **Remote mode** offloads the entire processing pipeline to the backend API server. The remote GUI only needs UI dependencies (PySide6, FFmpeg, MPV).
- F5 voice cloning requires reference audio + reference text. The backend synthesizes cloned voices using the cached reference data.
