# CapCap 🦆

![CapCap Editor Preview](assets/preview.PNG)

**One-click video localization.** Vietnamese subtitle & dubbing tool for short-form content. Works on CPU — faster with GPU.

> **Zero setup.** Double-click the `.exe`. No Python, no CUDA Toolkit, no model downloads — everything bundled. Only needs NVIDIA driver for GPU acceleration.

## Core Features

- **Fully offline capable** — all processing runs locally on your PC
- **CPU-first** — works on any Windows PC without GPU
- **GPU-accelerated** — plug in NVIDIA GPU, install driver only, get 3-5x faster
- Three output modes: `subtitle only`, `voice only`, `subtitle + voice`
- Speech-to-text: `faster-whisper` (CPU or GPU) or `RapidOCR` (video subtitle)
- OCR subtitle region editor with separate show/hide control
- AI translation — 3 providers:
  - **Local GGUF** (default, offline, CPU/GPU, `.gguf` model)
    - **Normal Quality AI Model** — `Hy-MT2-1.8B-Q4_K_M.gguf`
    - **High Quality AI Model** — `gemma-4-E4B-it-Q4_K_M.gguf`
  - **OpenAI** (Google AI Studio, cloud, free tier)
  - **Ollama** (local, no internet, `ollama pull qwen2.5:7b`)
- Free Google translate fallback — no API key needed
- Vietnamese voice with `Piper` (fully offline) or `edge-tts` (online)
- Default bundled Piper voice: `ngochuyen`
- Vocal/instrumental separation via ONNX Runtime (CPU, ~9s for 10s audio)
- VAD + denoise + loudness normalization for cleaner transcription
- Smart Generate — one button: transcribe → translate → voice → preview
- Timeline editing, subtitle styling, video filters
- Translation-to-TTS cache prefetch to reduce voice generation wait time
- Subtitle + voice export with FFmpeg

## Quick Start

1. Open Settings (More → Settings)
2. Default provider is **Local (GGUF)** — works offline with a `.gguf` model
3. For Local provider, choose:
   - **Normal Quality AI Model** — lighter, faster, lower hardware requirement
   - **High Quality AI Model** — better output quality, needs a better GPU or runs slower on CPU
4. Optionally switch to:
   - **OpenAI** — get [free API key](https://aistudio.google.com/apikey), paste it
   - **Ollama** — install [Ollama](https://ollama.com), run `ollama pull qwen2.5:7b`
5. Save → Load video → click **Generate**

If you use OCR mode, open **Settings → Manage Resources** and download **OCR Engine (RapidOCR PP-OCRv4)** first.

No key? Google translate fallback works for free (slower, lower quality).

## CPU vs GPU

| Component | CPU | GPU (NVIDIA) |
|---|---|---|
| faster-whisper | ✅ Works (~30s/10s audio) | ✅ 5x faster (~6s) |
| RapidOCR | ✅ Works | ✅ Supported |
| Vocal separation (ONNX) | ✅ Works (~9s) | CPU only |
| Piper TTS | ✅ Works | CPU only |
| Local GGUF translation | ✅ Works | ✅ Supported |
| Cloud API translation | ✅ Works | Same |

**GPU requirements:** NVIDIA GPU + driver installed. CUDA runtime bundled — no CUDA Toolkit download needed.

## Editor UI

### Top Header
- `Generate` — smart button: runs transcription + translation (if needed), then voice + preview
- `Export` — final video/subtitle export
- `More` — Subtitle download, Original script download, Exit (back to launcher), Clean project, Settings

### Left Panel
- `Media` — video, audio, background music, output quality, aspect ratio, canvas (Fit/Fill), Reset Framing
- `Language` — source/target language, Whisper model
- `Voice` — engine (Fast Voice only, Piper + edge-tts), gender, speed, voice preview
- `Style`
  - `Presets` — TikTok, YouTube, Short, Custom
  - `Text Position` — placement mode, placement, custom X/Y, vertical offset
  - `Text Style` — font, font size, colors, background box, outline, bold, single-line subtitle
  - `Animation & Timing` — animation, duration, text timing
- `Filter` — video filters (blur, brightness, contrast, etc.)
- `Advanced` — audio handling (Fast/Clean), ducking, timing sync

### Center Preview
- Video player with live subtitle overlay
- Play/Pause, Reset, Preview
- Blur controls split into:
  - `Blur` — effect on/off
  - `BOX` — show/hide blur edit region
- `OCR` button — show/hide OCR region in OCR mode
- Speed and audio track selection

### Subtitle Inspector (Right Panel)
- `Rewrite` — open dialog with style presets and AI prompt for full script
- `Rewrite Selected Subtitle` — open dialog with style presets for current segment only
- `Import SRT`
- `Show original` checkbox
- Prev/Next navigation with block counter
- Card with timing info, original text, and tabbed editor:
  - `Subtitle` tab — text editor, highlight selection
  - `Voice` tab — spoken text editor, `Use voice for subtitle`, `Regenerate voice`

Behavior note:
- By default, TTS reads the same text shown in the subtitle.
- A separate voice text is only used when you explicitly edit it in the inspector and regenerate voice.

### Timeline
- Multi-lane: Subtitle, Audio, Video
- Undo/Redo, Split, Delete, Nudge, Ripple controls
- Zoom and Fit controls
- **Voice timing sync** combo (Off/Smart/Force Fit)
- Time display

## Technical Stack

| Component | Technology |
|---|---|
| UI | PySide6 |
| Video preview | libmpv / Qt Multimedia |
| Workers | QThread |
| Speech-to-text | faster-whisper (CT2, CUDA/CPU) |
| Vocal separation | ONNX Runtime + UVR MDX-NET model |
| Audio post-process | FFmpeg (afftdn denoise, loudnorm) |
| Translation | OpenAI API / Ollama / llama-cpp-python (GGUF) |
| Fallback translate | Google web translate (free, no key) |
| TTS | Piper (local), edge-tts (online) |
| Audio processing | FFmpeg, pydub, soundfile |
| Packaging | PyInstaller |

## Dependencies

```
requirements-base.txt:
  PySide6, requests, python-dotenv, pydub, python-mpv

requirements-local.txt:
  faster-whisper, onnxruntime, scipy, librosa, numpy, soundfile
  edge-tts, piper-tts, vietnormalizer
  openai, llama-cpp-python, huggingface_hub
```

## Key Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `AI_POLISHER_PROVIDER` | `local` | AI provider: `local` (GGUF), `gemini` (OpenAI API) |
| `OPENAI_PROVIDER` | `local` | `local`, `openai`, or `ollama` |
| `OPENAI_API_KEY` | (none) | API key (only needed for OpenAI provider) |
| `OPENAI_MODEL` | (GGUF path) | Model name (OpenAI/Ollama only) |
| `OPENAI_BASE_URL` | (empty for local) | API endpoint URL (OpenAI/Ollama only) |
| `LOCAL_TRANSLATOR_MODEL_TIER` | `normal` | Local GGUF quality tier: `normal` (Hy-MT2) or `high` (Gemma 4) |
| `LOCAL_TRANSLATOR_MODEL_PATH` | `models/ai/Hy-MT2...` | GGUF model path (local provider) |
| `OCR_SUBTITLE_REGION` | `bottom` | OCR crop preset: `bottom` or `top` |
| `OCR_SUBTITLE_RECT` | (empty) | Explicit normalized OCR crop rectangle from preview editor |
| `CAPCAP_WHISPER_DEVICE` | (auto-detect) | Force `cpu` to avoid CUDA conflicts |
| `CAPCAP_QUIET` | `false` | Set `true` to suppress server logs |
| `CAPCAP_RUNTIME_PROFILE` | `local` | `local` or `remote` |
| `CAPCAP_REMOTE_API_URL` | `http://127.0.0.1:8765` | Remote API address (remote mode) |

### Local AI Models

- **Normal Quality AI Model**
  - File: `models/ai/Hy-MT2-1.8B-Q4_K_M.gguf`
  - Default option
  - Faster and lighter
- **High Quality AI Model**
  - File: `models/ai/gemma-4-E4B-it-Q4_K_M.gguf`
  - Download: [Gemma 4 GGUF](https://huggingface.co/Hacht/CapCapResource/blob/main/gemma-4-E4B-it-Q4_K_M.gguf)
  - Better quality, but needs a better GPU or runs slower on CPU

## Run From Source

```bash
git clone https://github.com/notepower2k1/CapCap.git
cd CapCap
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

## Workflow

1. Load a video and choose the source and target language.
2. Select audio handling mode: **Fast** (full audio) or **Clean** (vocal separation + VAD + denoise).
3. Click **Generate**.
   - Subtitle/OCR preparation runs first
   - AI translation runs next
   - TTS cache prefetch can start during translation for voice modes
4. Review subtitle styling, timing, and voice text in the editor.
5. Fine-tune segments in the subtitle inspector and timeline.
6. Preview the result, then export subtitles, dubbed audio, or the full video.

Performance notes:
- Heavy preview assets such as exact-frame preview, waveform, and timeline thumbnails are intentionally deferred to keep long-video loading responsive.
- `Translate -> TTS` overlap is enabled to reduce waiting time before voice preview/export.
- Piper TTS currently runs on CPU.

## Project Structure

```
CapCap/
├── ui/
│   ├── gui.py                    # Main app entry point
│   ├── gui_remote.py             # Remote client entry point
│   ├── main_window.py            # Main window, controllers, signal wiring
│   ├── controllers/              # Pipeline, preview, subtitle controllers
│   ├── views/                    # UI layout builders
│   │   ├── main_window.py        # Main window layout + signal connections
│   │   ├── start_panel.py        # Left panel (media, voice, style, etc.)
│   │   ├── preview_panel.py      # Right panel (preview + inspector + timeline)
│   │   └── advanced_tabs.py      # Advanced settings tab
│   ├── widgets/                  # Custom widgets (timeline, video, overlay)
│   ├── worker_adapters/          # QThread worker classes
│   ├── helpers/                  # SRT helpers, presentation helpers
│   └── utils/                    # Icon, media, settings utilities
├── app/
│   ├── remote_api_server.py      # Backend API server (remote mode only)
│   ├── workflows/                # Prepare, voice, export workflows
│   │   ├── prepare_workflow.py   # Extract → separate → transcribe → translate
│   │   ├── voice_workflow.py     # TTS + timing sync + retry logic
│   │   └── export_workflow.py    # Subtitle burn, audio mux, final export
│   ├── translation/              # Translation orchestrator + providers
│   │   ├── orchestrator.py       # Main translation pipeline
│   │   └── providers/
│   │       ├── gemini_polisher.py    # OpenAI-compatible API provider
│   │       ├── google_web_translator.py  # Free fallback translator
│   │       └── local_polisher.py   # Local GGUF provider + output validation
│   ├── ocr_processor.py          # RapidOCR subtitle extraction + OCR cleanup
│   ├── whisper_processor.py      # Whisper ASR with CUDA/CPU fallback
│   ├── vocal_processor.py        # ONNX Runtime vocal separation
│   ├── audio_mixer.py            # Voice track builder + time-stretch
│   └── services/                 # Engine runtime, project, chunking, scheduler, etc.
├── bin/
│   ├── ffmpeg/                   # Bundled FFmpeg
│   ├── mpv/                      # Bundled libmpv
│   ├── cuda12_fw/                # CUDA runtime DLLs (optional GPU accel)
│   └── UVR-MDX-NET-Inst_HQ_3.onnx  # Vocal separation model
├── .env                          # Environment configuration
├── .env_example                  # Example environment config
└── test_vocal_separation.py      # Test script for vocal separation
```

## CUDA / GPU

GPU can accelerate:
- `faster-whisper`
- `RapidOCR`
- local GGUF translation (if the bundled `llama-cpp-python` build supports GPU offload)

CPU-only paths in the current app:
- Piper TTS
- vocal separation in the current setup

| What you need | Where to get |
|---|---|
| NVIDIA GPU | Any GTX/RTX card |
| NVIDIA driver | [nvidia.com/drivers](https://www.nvidia.com/download/) |

**No CUDA Toolkit download.** The `bin/cuda12_fw/` folder bundles cuBLAS + cuDNN. Driver is enough.

*CPU-only?* Set `CAPCAP_WHISPER_DEVICE=cpu` in `.env`. Everything still works — just slower transcription.

## License

Apache License 2.0. See [LICENSE](./LICENSE).

## References

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech-to-text
- [UVR MDX-NET](https://github.com/TRvlvr/model_repo) — Vocal separation model
- [piper](https://github.com/rhasspy/piper) — Local text-to-speech
- [vietnormalizer](https://github.com/nghimestudio/vietnormalizer) — Vietnamese text normalization
