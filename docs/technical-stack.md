# Technical Stack

| Area | Technology |
| --- | --- |
| Desktop UI | PySide6 |
| Video preview | libmpv with Qt Multimedia fallback |
| Background work | QThread workers |
| Audio transcription | Faster-Whisper / CTranslate2, SenseVoice / Sherpa-ONNX |
| OCR | RapidOCR PP-OCRv4 with OpenCV and ONNX Runtime |
| Speaker diarization | Sherpa-ONNX |
| VAD | Silero VAD via Sherpa-ONNX |
| Translation | Google Translate, OpenAI, Google AI Studio, and Ollama |
| TTS | Piper and Edge TTS |
| Video/audio processing | FFmpeg, pydub, NumPy, SciPy, librosa, soundfile |
| Packaging | PyInstaller |

## Processing notes

- GPU Faster-Whisper uses CUDA when available, with standard inference as the safe path and optional batched inference controls.
- RapidOCR uses one GPU inference worker to avoid competing CUDA sessions.
- Timeline waveforms and thumbnails are generated once, cached per project/video, and reused during editing.
- Speaker diarization runs only for audio-based transcription and is optional.

## References

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [RapidOCR](https://github.com/RapidAI/RapidOCR)
- [Piper](https://github.com/rhasspy/piper)
- [Edge TTS](https://github.com/rany2/edge-tts)
- [FFmpeg](https://ffmpeg.org/)
- [PyInstaller](https://pyinstaller.org/)
