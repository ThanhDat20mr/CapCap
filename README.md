# CapCap 🦆

![CapCap Editor Preview](assets/preview.PNG)

**One-click video localization.** Vietnamese subtitle & dubbing tool for short-form content. Works on CPU — faster with GPU.

> **Zero setup.** Double-click the `.exe`. No Python, no CUDA Toolkit, no model downloads — everything bundled. Only needs NVIDIA driver for GPU acceleration.

## Core Features

- **Fully offline capable** — all processing runs locally on your PC
- **CPU-first** — works on any Windows PC without GPU
- **GPU-accelerated** — plug in NVIDIA GPU, install driver only, get 3-5x faster
- Three output modes: `subtitle only`, `voice only`, `subtitle + voice`
- Speech-to-text with `faster-whisper` (CPU or GPU)
- AI translation — 3 providers:
  - **OpenAI** (Google AI Studio, cloud, free tier)
  - **Ollama** (local, no internet, `ollama pull qwen2.5:7b`)
  - **Local GGUF** (local, no internet, download `.gguf` model)
- Free Google translate fallback — no API key needed
- Vietnamese voice with `Piper` (fully offline) or `edge-tts` (online)
- Vocal/instrumental separation via ONNX Runtime (CPU, ~9s for 10s audio)
- VAD + denoise + loudness normalization for cleaner transcription
- Smart Generate — one button: transcribe → translate → voice → preview
- Timeline editing, subtitle styling, video filters
- Subtitle + voice export with FFmpeg

## Quick Start

1. Open Settings (More → Settings)
2. Choose translation provider:
   - **OpenAI** — get [free API key](https://aistudio.google.com/apikey), paste it
   - **Ollama** — install [Ollama](https://ollama.com), run `ollama pull qwen2.5:7b`
   - **Local GGUF** — download a `.gguf` model, set path
3. Save → Load video → click **Generate**

No key? Google translate fallback works for free (slower, lower quality).

## CPU vs GPU

| Component | CPU | GPU (NVIDIA) |
|---|---|---|
| faster-whisper | ✅ Works (~30s/10s audio) | ✅ 5x faster (~6s) |
| Vocal separation (ONNX) | ✅ Works (~9s) | CPU only |
| Piper TTS | ✅ Works | CPU only |
| AI translation | ✅ Cloud API | Same |

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
- `Style` — TikTok, YouTube, Short, Custom presets, font, color, alignment, background box, Single-line subtitle (Netflix)
- `Filter` — video filters (blur, brightness, contrast, etc.)
- `Advanced` — audio handling (Fast/Clean), ducking, timing sync

### Center Preview
- Video player with live subtitle overlay
- Play/Pause, Reset, Preview, Blur area controls
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
| `AI_POLISHER_PROVIDER` | `gemini` | AI provider: `gemini` (OpenAI API), `local` (GGUF) |
| `OPENAI_PROVIDER` | `openai` | `openai`, `ollama`, or `local` |
| `OPENAI_API_KEY` | (none) | API key (not needed for Ollama/Local) |
| `OPENAI_MODEL` | `gemma-4-31b-it` | Model name |
| `OPENAI_BASE_URL` | `generativelanguage...` | API endpoint URL |
| `LOCAL_TRANSLATOR_MODEL_PATH` | `models/ai/...` | GGUF model path (local provider only) |
| `CAPCAP_WHISPER_DEVICE` | (auto-detect) | Force `cpu` to avoid CUDA conflicts |
| `CAPCAP_WHISPER_DEVICE` | (auto-detect) | Force `cpu` to avoid CUDA conflicts |
| `CAPCAP_QUIET` | `false` | Set `true` to suppress server logs |
| `CAPCAP_RUNTIME_PROFILE` | `local` | `local` or `remote` |
| `CAPCAP_REMOTE_API_URL` | `http://127.0.0.1:8765` | Remote API address (remote mode) |

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
3. Click **Generate** — runs transcription → AI translation → voice → preview.
4. Review subtitle styling, timing, and voice text in the editor.
5. Fine-tune segments in the subtitle inspector and timeline.
6. Preview the result, then export subtitles, dubbed audio, or the full video.

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
│   │       └── local_polisher.py   # Local GGUF (legacy)
│   ├── whisper_processor.py      # Whisper ASR with CUDA/CPU fallback
│   ├── vocal_processor.py        # ONNX Runtime vocal separation
│   ├── audio_mixer.py            # Voice track builder + time-stretch
│   └── services/                 # Engine runtime, project, chunking, etc.
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

GPU speeds up **whisper transcription only**. Everything else runs on CPU.

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
