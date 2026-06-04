import os
import threading
import numpy as np
import scipy.io.wavfile as wavfile

_ENABLED = False
_recognizer = None
_current_model_dir = ""
_current_language = ""
_lock = threading.Lock()


def is_available() -> bool:
    global _ENABLED
    if _ENABLED:
        return True
    try:
        import sherpa_onnx
        _ENABLED = True
    except ImportError:
        _ENABLED = False
    return _ENABLED


def _lang_code(code: str) -> str:
    if not code or code in ("auto", ""):
        return "auto"
    m = {"vi": "zh", "en": "en", "ja": "ja", "ko": "ko", "zh": "zh", "yue": "yue"}
    return m.get(code.split("-")[0].strip().lower(), "auto")


def load_model(model_dir: str, language: str = "auto"):
    global _recognizer, _current_model_dir, _current_language
    import sherpa_onnx

    lang = _lang_code(language)
    with _lock:
        if _recognizer is not None and _current_model_dir == model_dir and _current_language == lang:
            return
        tokens_path = os.path.join(model_dir, "tokens.txt")
        if not os.path.exists(tokens_path):
            raise FileNotFoundError(f"SenseVoice tokens not found: {tokens_path}")
        onnx_files = [f for f in os.listdir(model_dir) if f.endswith(".onnx")]
        if not onnx_files:
            raise FileNotFoundError(f"No .onnx model found in {model_dir}")
        pref = "model.int8.onnx" if "model.int8.onnx" in onnx_files else onnx_files[0]
        model_path = os.path.join(model_dir, pref)

        try:
            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_path,
                tokens=tokens_path,
                num_threads=4,
                use_itn=True,
                sense_voice_language=lang,
            )
        except TypeError:
            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_path,
                tokens=tokens_path,
                num_threads=4,
                use_itn=True,
            )
        _current_model_dir = model_dir
        _current_language = lang


def _absorb_tiny_segments(segments):
    if len(segments) < 2:
        return segments
    result = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        dur = seg["end"] - seg["start"]
        text_len = len(seg["text"].replace(" ", ""))
        if (dur < 0.35 or text_len <= 1) and (result or i + 1 < len(segments)):
            gap_prev = seg["start"] - result[-1]["end"] if result else float("inf")
            gap_next = segments[i + 1]["start"] - seg["end"] if i + 1 < len(segments) else float("inf")
            if gap_prev < 0.35 and result:
                result[-1]["end"] = max(result[-1]["end"], seg["end"])
                result[-1]["text"] = (result[-1]["text"] + " " + seg["text"]).strip()
                i += 1
                continue
            elif gap_next < 0.35 and i + 1 < len(segments):
                segments[i + 1]["start"] = min(seg["start"], segments[i + 1]["start"])
                segments[i + 1]["text"] = (seg["text"] + " " + segments[i + 1]["text"]).strip()
                i += 1
                continue
        result.append(seg)
        i += 1
    return result


def transcribe_audio(audio_path: str, model_dir: str, *, language: str = "auto") -> list[dict]:
    import sherpa_onnx

    load_model(model_dir, language=language)
    sr, audio = wavfile.read(audio_path)
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32) / 32768.0
    if sr != 16000:
        from scipy.signal import resample
        target_len = int(len(audio) * 16000 / sr)
        audio = resample(audio, target_len)

    from vad_processor import get_speech_segments

    segments = get_speech_segments(audio, 16000)
    results = []
    for seg in segments:
        start_s = int(seg["start"] * 16000)
        end_s = int(seg["end"] * 16000)
        chunk = audio[start_s:end_s]
        if len(chunk) < 1600:
            continue

        stream = _recognizer.create_stream()
        stream.accept_waveform(16000, chunk)
        _recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        if text:
            results.append({
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "text": text,
            })

    results = _absorb_tiny_segments(results)

    if not results:
        stream = _recognizer.create_stream()
        stream.accept_waveform(16000, audio)
        _recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        if text:
            duration = float(len(audio)) / 16000.0
            results.append({"start": 0.0, "end": round(duration, 3), "text": text})

    return results
