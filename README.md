# CapCap 🦆

![CapCap Editor Preview](https://github.com/notepower2k1/CapCap/blob/main/assets/preview.JPG)

**Video localization and layered editing.** Create Vietnamese or English subtitles and voice-overs for short-form content. Works on CPU — faster with GPU.

> **Zero setup.** Double-click the `.exe`. No Python, no CUDA Toolkit, no model downloads — everything bundled. Only needs NVIDIA driver for GPU acceleration.

## Core Features

- **Fully offline capable** — all processing runs locally on your PC
- **CPU-first** — works on any Windows PC without GPU
- **GPU-accelerated** — plug in NVIDIA GPU, install driver only, get ~5x faster transcription
- Vietnamese and English output, with automatic Piper voice selection for the chosen output language
- Speech-to-text: `faster-whisper` (CPU/GPU), `SenseVoice` (CPU, multilingual), or `RapidOCR` (video subtitle)
- OCR subtitle region editor with separate show/hide control
- AI translation — 5 providers:
  - **Local GGUF** (default, offline, CPU/GPU, `.gguf` model)
    - **Normal Quality AI Model** — `Hy-MT2-1.8B-Q4_K_M.gguf`
    - **High Quality AI Model** — `gemma-4-E4B-it-Q4_K_M.gguf`
  - **OpenAI** (Google AI Studio, cloud, free tier)
  - **Ollama** (local, no internet, `ollama pull qwen2.5:7b`)
  - **Microsoft Translator** (Azure Cognitive Services, cloud)
  - **OpenRouter** (generic OpenAI-compatible API)
- Free Google translate fallback — no API key needed
- Vietnamese and English voice with `Piper` (fully offline) or `edge-tts` (online)
- Default bundled Piper voice: `ngochuyen`
- Vocal/instrumental separation via ONNX Runtime (CPU, ~9s for 10s audio)
- VAD + denoise + loudness normalization for cleaner transcription
- Guided pipeline: **Prepare → Transcript → Translate → TTS → Export**, with completion badges
- Generate menu for a guided **Step-by-Step** workflow or the **Full Pipeline**
- Timeline editing, subtitle styling, video filters, and timed overlay layers
- Translation-to-TTS cache prefetch to reduce voice generation wait time
- Subtitle + voice export with FFmpeg
- **TTS speed highlighting** — audio timeline segments show predicted voice-over timing fit via 5 color levels (green/cyan/yellow/orange/red)
- **Hybrid DubSubtitle Layer (TS1)** — single track replaces old separate subtitle + dub audio tracks. Each segment holds both display text and TTS voice data. Generated audio shows a speaker glyph on the bar.
- **Audio overlap row stacking** — when TTS audio bleeds past a segment's time window, the bar is pushed down a row in the TS1 track (like blur regions in B1). Overlap is detected via the actual `.wav` duration from `_audio_end`, not the segment window. A dashed border marks overflow-row bars.
- **Timeline Priority sync mode** (Off / Smart / Timeline Priority / Force) — controls what happens when TTS audio is longer than the segment. Smart trims or stretches within safe range. Force uses atempo speed-up. **Timeline Priority** always cuts to the segment window — audio stops at the segment end, next segment plays immediately, and row stacking is disabled. Off = no adjustment.
- **Single-segment Regenerate Voice** — probes the generated `.wav` with ffprobe for the exact duration, updates the segment + layer `_audio_end`, and redraws the timeline immediately so audio bleed is reflected in real time.
- **Per-track inspectors** — clicking a layer opens a dedicated inspector card for Subtitle, Audio, Blur, Logo, Mask, Text, or Video.
- **Drag-to-position overlay layers** — Blur, Logo, Mask, Text, and Subtitle layers can be positioned directly on the video preview when their timeline layer is selected.
- **Timed overlay layers** — Blur, Logo, Mask, and Text layers support start/end times, edge dragging on the timeline, direct timing fields, and Split.
- **TEXT track (T1)** — add multiple editable text layers with content, font family, subtitle-matched font-size presets, text color, optional background color, position, and timing. Text layers are included in Fast Preview and final export.
- **Logo / Watermark track (L1)** — add multiple images and place them independently on the video; pick colour, opacity, rotation, and timing from the inspector.
- **Mask track (M1)** — add multiple solid-colour rectangles to recolour regions (e.g. hide watermarks or redact faces). All mask regions remain visible in the editor; the selected region exposes drag handles and timing controls.
- **Timeline layer visibility** — use the **Layers** menu to temporarily show or hide whole optional tracks in the timeline without affecting preview or export.
- **Runtime logs** — Advanced → Logs shows app messages, console output, and error tracebacks. Export a log file for bug reports or clear the current session log.
- **Blur inspector** — per-region blur radius (1-20), opacity, and pixelate (mosaic) toggle
- **Vietnamese normalizer dictionary manager** (More → Normalizer Dictionary) — CRUD editor for custom acronym/non-Vietnamese word mappings
- **GGUF translator improvements** — automatic enable when provider is local, absolute model paths, smarter CJK quality validation, increased token limit
- **Label mode** — toggles the track label bar visibility

## Quick Start

1. Open the launcher — select **CPU** or **GPU (Recommended)** mode
2. GPU mode: Whisper + local AI models use GPU acceleration
3. CPU mode: SenseVoice (CPU-only ASR) + Google Translate by default
4. Open Settings (More → Settings)
5. Default translator provider is **Local (GGUF)** (offline, CPU/GPU)
6. Optionally switch to:
   - **OpenAI** — get [free API key](https://aistudio.google.com/apikey), paste it
   - **Ollama** — install [Ollama](https://ollama.com), run `ollama pull qwen2.5:7b`
   - **Microsoft Translator** — get [Azure key](https://portal.azure.com), paste it
   - **Google Translate** — free, no key (fallback quality)
7. Save → Load video → choose **Generate → Full Pipeline**, or run each stage from **Generate → Step-by-Step**

If you use OCR mode, the OCR engine ships inside the `rapidocr` package and is used automatically when present.

No key? Google translate fallback works for free (slower, lower quality).

## Launcher

On startup, CapCap shows a launcher with:
- **GPU detection** — auto-detects NVIDIA GPU name using `nvidia-smi`. Shows "CPU only" if no GPU found.
- **CPU / GPU toggle** — segmented switch to choose processing mode. GPU button disabled if no GPU detected.
- **Recent Projects** — grid of recently opened videos with thumbnails.
- **+ New Project** — open any video (up to 2 hours). Shows warning if video is too long.
- **Split Video** — cut a long video (>2h) into segments using stream copy (no re-encode). Choose segment duration, outputs saved alongside original.

### Video Duration Limit
Videos over 2 hours are blocked from opening. Use the **Split Video** button to cut long videos into 2-hour segments first, then open individual parts.

## CPU vs GPU

| Component | CPU | GPU (NVIDIA) |
|---|---|---|
| faster-whisper | ✅ Works (~30s/10s audio) | ✅ 5x faster (~6s) |
| SenseVoice (CPU) | ✅ Works (~8s/10s audio) | ✅ Same |
| RapidOCR | ✅ Works | ✅ Supported |
| Vocal separation (ONNX) | ✅ Works (~9s) | CPU only |
| Piper TTS | ✅ Works | CPU only |
| Local GGUF translation | ✅ Works | ✅ Supported |
| Cloud API translation | ✅ Works | Same |

**GPU requirements:** NVIDIA GPU + driver installed. CUDA runtime bundled — no CUDA Toolkit download needed.

## Editor UI

### Top Header
- `Generate` — opens **Step-by-Step** and **Full Pipeline** generation choices
- `Export` — final video/subtitle export
- `More` — subtitle download, Original script download, Exit (back to launcher), Clean project, Settings

### Left Panel
- `Media` — video, audio, background music, output quality, aspect ratio, canvas (Fit/Fill), Reset Framing
- `Language` — source/target language (Vietnamese or English output), Whisper model
- `Voice` — engine (Fast Voice only, Piper + edge-tts), gender, speed, voice preview
- `Style`
  - `Presets` — TikTok, YouTube, Short, Custom
  - `Text Position` — placement mode, placement, custom X/Y, vertical offset
  - `Text Style` — font, preset font scale (50–150%), colours, outline, bold, and animation
  - `Background` — background box, colour, opacity, and padding
  - `Single Line Subtitle` — enable word-based subtitle splitting and choose **Words per Segment** (default: 4)
  - `Animation & Timing` — animation, duration, text timing
- `Filter` — video filters (blur, brightness, contrast, etc.)
- `Advanced` — audio handling, timing options, and **Logs** (Export Logs / Clear Logs)

### Center Preview
- Video player with live subtitle overlay
- Play/Pause, Reset, Preview
- Overlay toolbar:
  - `Blur` — add / show / hide a blur region (drag-to-place on the video)
  - `Logo` — add a Logo / Watermark image to the video
  - `Mask` — add a solid-colour mask region (see the M1 Mask track below)
  - `Text` — add an editable text layer (see the T1 Text track below)
  - `OCR` button — show/hide OCR region in OCR mode
- Speed and audio track selection

### Track Inspector (Right Panel)
The inspector always stays expanded and swaps its card to match the track type you click. Each card is wrapped in a scroll view so tall content doesn't clip.

- **Subtitle / Dub** (flat single panel, no tabs) — `Rewrite`, `Rewrite Selected`, `Import SRT`, `Regenerate Voice` (top action row), shared `Original text` label, segment timing chips, segment editor (180px height).
- **Audio** (idx 1) — per-track volume (0-200%), gain in dB, speed, fade-in / fade-out, mute / solo, A1 vs A2 (Dub) selection.
- **Blur** (idx 2) — B1 Blur track on/off toggle + per-region controls: `Blur radius` (1-20), `Opacity` (0-100%), `Pixelate` (mosaic) + `Pixel size` (2-60). Multiple regions stack vertically in the timeline so overlapping blurs stay visible.
- **Video** (idx 3) — V1 Video track filter. Preset + intensity sliders, plus per-channel adjust sliders (brightness, contrast, saturation, temperature, gamma, hue), Apply / Revert.
- **Default** (idx 4) — fallback card when no track layer is selected.
- **Logo (L1)** (idx 5) — `Colour` (background swatch), `Opacity` (0-100%), `Rotation` (-180 to 180°). Drag the logo on the video to move; drag a corner to resize; X to delete.
- **Mask (M1)** (idx 6) — `Colour` (background swatch), `Opacity` (0-100%). Drag the mask on the video to move; drag a corner to resize; X to delete. The colour is **only applied while the video is playing** — moving the mask does not trigger any mpv filter update, so dragging stays smooth. The overlay is locked (`set_editable(False)`) while playing so you cannot accidentally move a region during playback.
- **Text (T1)** — edit text content, font family, font-size preset, text colour, optional background colour, and start/end timing. Text cannot be empty; it falls back to `Text`.

Behavior notes:
- By default, TTS reads the same text shown in the subtitle. A separate voice text is only used when you explicitly edit it in the inspector and regenerate voice.
- The "Show original" checkbox is removed — original text is always shown.
- Shared timing chips and "Add highlight" button were removed from the inspector; each segment card shows its own timing info.
- The Logo, Blur, and Mask overlay regions use the same drag/resize/delete UX inherited from the blur overlay.
- Timeline track labels (left strip) are clickable: A1 / A2 / TS1 toggle mute, B1 toggles the blur effect, L1 toggles the logo, M1 toggles the mask.

### Timeline
- Multi-lane: V1 Video, A1 Audio, TS1 Subtitle+Dub, B1 Blur, L1 Logo, M1 Mask, T1 Text
- **Hybrid TS1 track** — single lane replaces the old S1 + A2 two-track layout. Each segment is a `DubSubtitleLayer` holding both display text and TTS voice data. Audio-blending segments stack vertically into child rows (like B1 blur regions).
- **Track label bar** (left strip) — fixed-width column with the track name + icon (▶ V1, ♪ A1, T TS1, ▣ B1, ■ M1, ⬖ L1, etc.) and mute / effect toggle on click. The label bar scrolls in sync with the timeline's vertical scroll. Toggle visibility via **Label mode** button.
- Undo/Redo, Split, Delete, Nudge, Ripple, and **Layers** controls
- **Voice timing sync** combo (Off / Smart / Timeline Priority / Force) — controls TTS timing adjustment strategy
- Time display
- Blur, Logo, Mask, and Text layers are stacked vertically inside their tracks so overlapping layers are all visible.
- The Delete button removes the currently selected Blur, Logo, Mask, or Text layer.
- **Row stacking** — DubSubtitleLayer bars that overlap in audio time (via `_audio_end`) are pushed down a row so both are visible. Overflow-row bars get a dashed border.

## Technical Stack

| Component | Technology |
|---|---|
| UI | PySide6 |
| Video preview | libmpv / Qt Multimedia |
| Workers | QThread |
| Speech-to-text | faster-whisper (CTranslate2, CUDA/CPU), SenseVoice (sherpa-onnx, CPU) |
| OCR subtitle extraction | RapidOCR (PP-OCRv4) via opencv-python-headless |
| Voice activity detection | Silero VAD (sherpa-onnx) |
| Vocal separation | ONNX Runtime + UVR MDX-NET model, Demucs (Hybrid Transformer, optional) |
| Audio post-process | FFmpeg (afftdn denoise, loudnorm) |
| Audio analysis | scipy, librosa, numpy, soundfile |
| Translation | OpenAI API / Ollama / llama-cpp-python (GGUF) / Microsoft Translator |
| Fallback translate | Google web translate (free, no key) |
| TTS | Piper (local), edge-tts (online) |
| Vietnamese normalization | vietnormalizer |
| Audio processing | FFmpeg, pydub |
| Model downloads | manual URL + optional `huggingface_hub` Auto Download |
| Configuration | python-dotenv |
| Packaging | PyInstaller |

## Dependencies

```
requirements-base.txt:
  PySide6, requests, python-dotenv, pydub, python-mpv

requirements-local.txt:
  faster-whisper, onnxruntime-gpu, scipy, librosa, numpy, soundfile
  edge-tts, piper-tts, vietnormalizer
  openai, llama-cpp-python, huggingface_hub
  sherpa-onnx, rapidocr, opencv-python-headless
```

## Key Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIPTION_ENGINE` | `whisper` | ASR engine: `whisper`, `sensevoice`, or `ocr` |
| `CAPCAP_DEVICE` | `cuda` | Processing mode set by launcher: `cuda` or `cpu` |
| `CAPCAP_WHISPER_DEVICE` | (auto-detect) | Force `cpu` to avoid CUDA conflicts |
| `AI_POLISHER_PROVIDER` | `local` | AI provider: `local` (GGUF), `gemini` (OpenAI API) |
| `OPENAI_PROVIDER` | `local` | Translator source: `local`, `openai`, `ollama`, or `google` |
| `OPENAI_API_KEY` | (none) | API key for OpenAI/Ollama/OpenRouter providers |
| `OPENAI_MODEL` | `gemma-4-31b-it` | Model name for OpenAI/Ollama/OpenRouter |
| `OPENAI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | API endpoint URL |
| `LOCAL_TRANSLATOR_MODEL_TIER` | `normal` | Local GGUF quality: `normal` (Hy-MT2) or `high` (Gemma 4) |
| `LOCAL_TRANSLATOR_MODEL_PATH` | `models/ai/Hy-MT2-1.8B-Q4_K_M.gguf` | GGUF model path |
| `LOCAL_TRANSLATOR_GPU_LAYERS` | `0` | GPU layers to offload (0 = CPU-only, -1 = all) |
| `LOCAL_TRANSLATOR_N_CTX` | `8192` | GGUF context size |
| `LOCAL_TRANSLATOR_N_THREADS` | `4` | CPU threads for GGUF inference |
| `LOCAL_TRANSLATOR_MAX_TOKENS` | `2048` | Max output tokens |
| `LOCAL_TRANSLATOR_TEMPERATURE` | `0.1` | Sampling temperature |
| `TRANSLATOR_STYLE` | (empty) | Translation style hint: e.g. `natural`, `funny`, `formal` |
| `OCR_SUBTITLE_REGION` | `bottom` | OCR crop preset: `bottom` or `top` |
| `OCR_SUBTITLE_RECT` | (empty) | Explicit normalized OCR crop rectangle |
| `MS_TRANSLATOR_KEY` | (empty) | Azure Translator API key |
| `MS_TRANSLATOR_REGION` | (empty) | Azure region (e.g. `southeastasia`) |
| `MS_TRANSLATOR_ENDPOINT` | `https://api.cognitive.microsofttranslator.com/` | Azure endpoint |
| `CAPCAP_QUIET` | `false` | Set `true` to suppress server logs |
| `CAPCAP_RUNTIME_PROFILE` | `local` | `local` or `remote` |
| `CAPCAP_REMOTE_API_URL` | `http://127.0.0.1:8765` | Remote API address (remote mode) |

### Local Resources

Open **Manage Resources** from the launcher or `Settings → Manage Resources`. Each card shows a status pill (`Ready` / `Partial` / `Missing`), the target folder, the expected file, and two download paths:

- **Open Download Page** — opens the Hugging Face / GitHub URL in your browser
- **Auto Download** — fetches the file directly into the target folder (uses `huggingface_hub`; only available for some resources)

Per-card progress replaces the status pill during an Auto Download. Click **Refresh** to re-check status without closing the dialog.

| Resource | Target | Auto Download |
|---|---|---|
| Normal AI Model (Hy-MT2) | `models/ai/Hy-MT2-1.8B-Q4_K_M.gguf` | ❌ manual only |
| High AI Model (Gemma 4) | `models/ai/gemma-4-E4B-it-Q4_K_M.gguf` | ❌ manual only |
| Whisper Medium | `models/faster_whisper/medium/` | ✅ |
| GPU Acceleration Pack (CUDA 12) | `bin/cuda12_fw/` | ✅ |
| SenseVoice ASR Model | `models/sensevoice/` | ✅ |
| Local Vietnamese Voices (Piper) | `models/piper/` | ✅ |
| Local English Voices (Piper) | `models/piper-en/` | ✅ |

- **AI Model** (Normal / High)
  - File: `models/ai/Hy-MT2-1.8B-Q4_K_M.gguf` (default) or `models/ai/gemma-4-E4B-it-Q4_K_M.gguf`
  - Download manually from the [CapCapResource HF repo](https://huggingface.co/Hacht/CapCapResource).
- **Whisper Medium**
  - Folder: `models/faster_whisper/medium/`
  - Manual: [`Hacht/CapCapResource/faster_whisper`](https://huggingface.co/Hacht/CapCapResource/tree/main/faster_whisper)
  - `faster-whisper` will also auto-download on first use if the folder is empty.
- **GPU Acceleration Pack (CUDA 12)**
  - Folder: `bin/cuda12_fw/`
  - Manual: [`Hacht/CapCapResource/cuda12_fw`](https://huggingface.co/Hacht/CapCapResource/tree/main/cuda12_fw)
- **SenseVoice ASR Model**
  - Folder: `models/sensevoice/`
  - Manual: [`csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17)
- **Local Vietnamese Voices (Piper)**
  - Folder: `models/piper/`
  - Manual: [`Hacht/CapCapResource/piper`](https://huggingface.co/Hacht/CapCapResource/tree/main/piper)
  - Drop each `.onnx` file together with its `.onnx.json` config.
- **Local English Voices (Piper)**
  - Folder: `models/piper-en/`
  - Download through **Manage Resources** or install the supplied English Piper `.onnx` files with their `.onnx.json` configs.

## Run From Source

```bash
git clone https://github.com/notepower2k1/CapCap.git
cd CapCap
python -m venv venv
venv\Scripts\activate
pip install -r requirements-local.txt
python ui/gui.py
```

> **CPU-only?** `onnxruntime-gpu` requires CUDA DLLs to import. Replace with `onnxruntime` in requirements-local.txt, or set `CUDA_VISIBLE_DEVICES=` to bypass.

### Remote Server
```bash
python app/remote_api_server.py
```

## Workflow

1. Load a video. **Prepare** is marked complete once the video is ready.
2. Choose the source and target language, then select audio handling.
3. Open **Generate** and either:
   - choose **Full Pipeline** to run Transcript → Translate → TTS, or
   - choose **Step-by-Step** to run stages in order. Each next stage unlocks after the preceding stage completes.
4. To translate manually, run to Transcript, export the subtitle file from **More**, translate it externally, then use **Generate → Step-by-Step → Import Translated File** and continue with TTS.
5. Review subtitle styling, timing, voice text, and optional overlay layers in the editor.
6. Use **Fast Preview** to render a five-second sample of the final subtitle, TEXT, and overlay output before exporting.
7. Export the finished video.

Performance notes:
- Heavy preview assets such as exact-frame preview, waveform, and timeline thumbnails are intentionally deferred to keep long-video loading responsive.
- `Translate -> TTS` overlap is enabled to reduce waiting time before voice preview/export.
- Piper TTS currently runs on CPU.

## Project Structure

```
CapCap/
├── ui/
│   ├── gui.py                        # Main app entry point
│   ├── main_window.py                # Main window, controllers, signal wiring
│   ├── controllers/                  # Pipeline, preview, subtitle controllers
│   ├── views/                        # UI layout builders
│   │   ├── launcher.py               # Startup launcher (CPU/GPU, recent projects)
│   │   ├── main_window.py            # Main window layout + signal connections
│   │   ├── start_panel.py            # Left panel (media, voice, style, etc.)
│   │   ├── preview_panel.py          # Right panel (preview + per-track inspector + timeline)
│   │   ├── resource_manager.py       # Resource status dialog (manual URL + optional Auto Download)
│   │   ├── advanced_tabs.py          # Advanced settings tab
│   │   └── editor/                   # Timeline + track label bar
│   │       ├── timeline.py            # Multi-lane timeline (V1/A1/A2/B1/L1/M1/S1)
│   │       └── track_labels.py        # Left-strip track label bar (mute / effect toggles)
│   ├── widgets/                      # Custom widgets (timeline, video, overlay)
│   │   ├── video_view.py             # Video/audio playback via libmpv
│   │   ├── mpv_video_view.py         # MPV-backed preview + blur/logo/mask overlay
│   │   ├── subtitle_overlay.py       # Live subtitle overlay on video
│   │   └── progress_dialog.py        # Progress dialog with file size display
│   ├── worker_adapters/              # QThread worker classes
│   │   ├── processing_workers.py     # Extraction, vocal, transcription, TTS workers
│   │   └── preview_workers.py        # Frame preview, waveform workers
│   ├── helpers/                      # SRT helpers, presentation helpers
│   └── utils/                        # Icon, media, settings, file dialog utilities
├── app/
│   ├── remote_api_server.py          # Backend API server (remote mode only)
│   ├── remote_api.py                 # Remote API client
│   ├── runtime_paths.py              # Runtime path resolution (assets, models, bins)
│   ├── runtime_profile.py            # Runtime profile (local/remote) management
│   ├── workflows/                    # Prepare, voice, export workflows
│   │   ├── prepare_workflow.py       # Extract → separate → transcribe → translate → TTS cache
│   │   ├── voice_workflow.py         # TTS + timing sync + retry logic
│   │   └── export_workflow.py        # Subtitle burn, audio mux, final export
│   ├── translation/                  # Translation orchestrator + providers
│   │   ├── orchestrator.py           # Main translation pipeline
│   │   ├── models.py                 # Translation data models
│   │   ├── srt_utils.py              # SRT parsing/formatting
│   │   └── providers/
│   │       ├── gemini_polisher.py        # OpenAI-compatible API (Google AI Studio, Ollama)
│   │       ├── google_web_translator.py  # Free Google web translate fallback
│   │       ├── local_polisher.py         # Local GGUF provider (CPU + GPU)
│   │       ├── microsoft_translator.py   # Azure Cognitive Services Translator
│   │       └── ai_polisher.py            # OpenRouter generic API provider
│   ├── engines/                      # Engine adapters (whisper, sensevoice, OCR, TTS, etc.)
│   │   ├── whisper_adapter.py        # Whisper ASR adapter
│   │   ├── sensevoice_adapter.py     # SenseVoice ASR adapter
│   │   ├── ocr_adapter.py            # RapidOCR adapter
│   │   ├── tts_adapter.py            # TTS orchestration (Piper + edge-tts)
│   │   ├── translator_adapter.py     # Translation provider router
│   │   ├── demucs_adapter.py         # Demucs vocal separation (optional)
│   │   ├── ffmpeg_adapter.py         # FFmpeg audio/video processing
│   │   ├── audio_mix_adapter.py      # Voice track builder + time-stretch
│   │   ├── subtitle_adapter.py       # Subtitle formatting/burning
│   │   ├── preview_adapter.py        # Video preview processing
│   │   └── remote_*.py               # Remote mode adapters (whisper, TTS, translator)
│   ├── core/                         # Core domain models and state
│   │   ├── models/                   # Segment, chunk data classes
│   │   └── state/                    # Project state manager
│   ├── services/                     # Business logic services
│   │   ├── project_service.py        # Project CRUD, recent projects
│   │   ├── segment_service.py        # Subtitle segment management
│   │   ├── chunking_service.py       # Audio segmentation
│   │   ├── engine_runtime.py         # Engine initialization and lifecycle
│   │   ├── resource_download_service.py  # Resource catalog + status checks + Auto Download backend
│   │   └── ...                       # + GPU scheduling, ASR merge, etc.
│   ├── utils/                        # Voice preview utilities
   │   ├── layers/                       # Track / clip / layer domain model
   │   │   ├── base.py                   # BaseLayer + LayerType + BlendMode
   │   │   ├── video.py                  # V1 Video layer
   │   │   ├── audio.py                  # A1 Audio layer
   │   │   ├── subtitle.py               # S1 Subtitle layer (legacy)
   │   │   ├── dub_subtitle.py           # TS1 hybrid subtitle+dub layer (current)
   │   │   ├── image.py                  # L1 Logo / image layer
   │   │   ├── blur.py                   # B1 Blur layer
   │   │   ├── mask.py                   # M1 Mask layer (solid colour region)
   │   │   ├── transform.py              # Transform (x/y/scale/rotation/keyframes)
   │   │   ├── keyframe.py              # Keyframe animation
   │   │   ├── timeline.py               # Timeline + Track + Clip containers
   │   │   ├── text.py / sticker.py      # Text / sticker layers
   │   │   └── sync_bridge.py            # Timeline <-> track layer sync helpers
│   ├── ocr_processor.py             # RapidOCR subtitle extraction + cleanup
│   ├── whisper_processor.py         # Whisper ASR with CUDA/CPU fallback
│   ├── sensevoice_processor.py      # SenseVoice ASR (sherpa-onnx, CPU)
│   ├── vad_processor.py             # Silero VAD speech segmentation
│   ├── vocal_processor.py           # ONNX Runtime vocal separation
│   ├── tts_processor.py             # TTS generation (Piper + edge-tts)
│   ├── translator.py                # Translation orchestrator (legacy)
│   ├── subtitle_builder.py          # Subtitle assembly
│   ├── video_processor.py           # Video/audio post-processing
│   └── preview_processor.py         # Preview asset generation
├── bin/
│   ├── ffmpeg/                       # Bundled FFmpeg (ffmpeg.exe, ffprobe.exe)
│   ├── mpv/                          # Bundled libmpv-2.dll
│   ├── cuda12_fw/                    # CUDA runtime DLLs (cuBLAS, cuDNN — driver only needed)
│   ├── UVR-MDX-NET-Inst_HQ_3.onnx   # Vocal separation model (ONNX Runtime)
│   └── silero_vad.onnx               # Silero VAD model (sherpa-onnx)
├── models/
│   ├── sensevoice/                   # SenseVoice ONNX model + tokens
│   ├── vietnormalizer/               # Custom dict CSV files (acronyms, non-VN words)
│   ├── faster_whisper/               # CTranslate2 Whisper models (cached)
│   ├── piper/                        # Piper voice models (12+ Vietnamese voices)
│   └── ai/                           # GGUF translation models
│       ├── Hy-MT2-1.8B-Q4_K_M.gguf      # Normal quality (default)
│       └── gemma-4-E4B-it-Q4_K_M.gguf   # High quality
├── assets/                           # App assets (icon, preview images)
├── .env                              # Environment configuration
└── .env_example                      # Example environment config
```

## CUDA / GPU

GPU can accelerate:
- `faster-whisper`
- `RapidOCR`
- local GGUF translation (if the bundled `llama-cpp-python` build supports GPU offload)

CPU-only paths in the current app:
- SenseVoice ASR
- Piper TTS
- vocal separation

| What you need | Where to get |
|---|---|
| NVIDIA GPU | Any GTX/RTX card |
| NVIDIA driver | [nvidia.com/drivers](https://www.nvidia.com/download/) |

**No CUDA Toolkit download.** The `bin/cuda12_fw/` folder bundles cuBLAS + cuDNN. Driver is enough.

*CPU-only?* Set `CAPCAP_WHISPER_DEVICE=cpu` in `.env`. Everything still works — just slower transcription.

## License

Apache License 2.0. See [LICENSE](./LICENSE).

## References

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech-to-text (CTranslate2)
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — Multilingual ASR model
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — ONNX ASR runtime (SenseVoice, Silero VAD)
- [Silero VAD](https://github.com/snakers4/silero-vad) — Voice activity detection
- [RapidOCR](https://github.com/RapidAI/RapidOCR) — OCR subtitle extraction (PP-OCRv4)
- [UVR MDX-NET](https://github.com/TRvlvr/model_repo) — Vocal separation model
- [Demucs](https://github.com/facebookresearch/demucs) — Alternative vocal separation (Hybrid Transformer)
- [piper](https://github.com/rhasspy/piper) — Local text-to-speech
- [edge-tts](https://github.com/rany2/edge-tts) — Online TTS fallback
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) — GGUF local translation
- [vietnormalizer](https://github.com/nghimestudio/vietnormalizer) — Vietnamese text normalization
- [PyInstaller](https://github.com/pyinstaller/pyinstaller) — Windows .exe packaging
