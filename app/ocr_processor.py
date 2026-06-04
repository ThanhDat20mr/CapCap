import os
import re
import subprocess

import cv2
import numpy as np

from runtime_paths import bin_path

_OCR_ENGINE = None
_OCR_ENGINE_LOCK = None

MAX_CROP_WIDTH = 960
EMPTY_TOLERANCE = 2
EXACT_HASH_THRESHOLD = 5.0
_OCR_HANDLE_RE = re.compile(r"@\s*[A-Za-z0-9_\-\u3400-\u9fff]{1,24}")
_OCR_NOISE_RE = re.compile(r"^[A-Za-z0-9@#&*_\-+=/\\|~`'.:;!?()\[\]{}<>]{1,16}$")
_OCR_WATERMARK_PATTERNS = [
    re.compile(r"[\u3400-\u9fff]{1,6}漫(?:剧|居|刷)"),
    re.compile(r"专店"),
]


def _get_lock():
    global _OCR_ENGINE_LOCK
    if _OCR_ENGINE_LOCK is None:
        import threading
        _OCR_ENGINE_LOCK = threading.Lock()
    return _OCR_ENGINE_LOCK


def _ffmpeg_path():
    return os.path.join(bin_path("ffmpeg"), "ffmpeg.exe")


def _load_ocr_engine():
    global _OCR_ENGINE
    with _get_lock():
        if _OCR_ENGINE is not None:
            return _OCR_ENGINE

        from runtime_paths import join_root
        cuda_bin = join_root("bin", "cuda12_fw")
        if os.path.isdir(cuda_bin):
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(cuda_bin)
                except Exception:
                    pass
            os.environ["PATH"] = cuda_bin + os.pathsep + os.environ.get("PATH", "")

        try:
            import rapidocr
            models_dir = os.path.join(os.path.dirname(rapidocr.__file__), "models")
        except Exception:
            models_dir = ""

        import sys
        if not models_dir or not os.path.isdir(models_dir):
            meipass = getattr(sys, "_MEIPASS", "") or ""
            if meipass:
                bundled = os.path.join(meipass, "rapidocr", "models")
                if os.path.isdir(bundled):
                    models_dir = bundled

        required_models = [
            "ch_PP-OCRv4_det_mobile.onnx",
            "ch_PP-OCRv4_rec_mobile.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        ]
        missing = [m for m in required_models if not models_dir or not os.path.isfile(os.path.join(models_dir, m))]
        if missing:
            raise RuntimeError(
                "OCR models not found. Please open Settings → Manage Resources and download "
                "'OCR Engine (RapidOCR PP-OCRv4)' before using OCR mode.\n\n"
                f"Missing: {', '.join(missing)}\n"
                f"Looked in: {models_dir or 'rapidocr package directory'}"
            )

        from rapidocr import RapidOCR
        params = {
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.use_cuda": True,
        }
        try:
            _OCR_ENGINE = RapidOCR(params=params)
            print("[OCR] RapidOCR engine loaded (PP-OCRv4 ONNX, CUDA GPU)")
        except Exception:
            _OCR_ENGINE = RapidOCR()
            print("[OCR] RapidOCR engine loaded (PP-OCRv4 ONNX, CPU fallback)")
        return _OCR_ENGINE


def _open_video(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"[OCR] Cannot open video: {video_path}")
    return cap


def crop_subtitle_region(image, region="bottom"):
    h, w = image.shape[:2]
    rect_str = os.getenv("OCR_SUBTITLE_RECT", "")
    if rect_str:
        try:
            parts = [float(x) for x in rect_str.split(",")]
            if len(parts) == 4:
                rx, ry, rw_val, rh = parts
                x1 = int(rx * w)
                y1 = int(ry * h)
                x2 = int((rx + rw_val) * w)
                y2 = int((ry + rh) * h)
                return image[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        except Exception:
            pass
    effective_region = (os.getenv("OCR_SUBTITLE_REGION") or region or "bottom").strip().lower()
    if effective_region == "bottom":
        ratio = float(os.getenv("OCR_CROP_RATIO", "0.25"))
        top = int(h * (1.0 - ratio))
        return image[top:h, 0:w]
    elif effective_region == "top":
        ratio = float(os.getenv("OCR_CROP_RATIO", "0.25"))
        return image[0:int(h * ratio), 0:w]
    else:
        return image


def preprocess_for_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    return cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)


def _crop_hash(image):
    small = cv2.resize(image, (64, 64), interpolation=cv2.INTER_NEAREST)
    return small.astype(np.float32).mean(axis=(0, 1))


def _hamming_distance(h1, h2):
    return float(np.sum(np.abs(h1.astype(np.float32) - h2.astype(np.float32))))


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def _sanitize_ocr_line(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split()).strip()
    if not cleaned:
        return ""
    cleaned = _OCR_HANDLE_RE.sub(" ", cleaned)
    for pattern in _OCR_WATERMARK_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -_.,;:!?|/\\[]{}()<>'\"`~")
    if not cleaned:
        return ""

    visible = [ch for ch in cleaned if not ch.isspace()]
    if not visible:
        return ""
    ascii_visible = [ch for ch in visible if ord(ch) < 128]

    if _OCR_NOISE_RE.fullmatch(cleaned):
        return ""
    if len(cleaned) <= 2 and not _contains_cjk(cleaned):
        return ""
    if ascii_visible and len(ascii_visible) / max(1, len(visible)) >= 0.85:
        compact_ascii = "".join(ascii_visible)
        if len(compact_ascii) <= 16:
            return ""
    return cleaned


def _is_blank_region(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    if float(lap.var()) < 30.0:
        return True
    bright_ratio = float(np.sum(gray > 180)) / gray.size
    if bright_ratio > 0.002:
        return False
    return True


def ocr_frame(engine, image):
    h, w = image.shape[:2]
    if w > MAX_CROP_WIDTH:
        scale = MAX_CROP_WIDTH / w
        new_w = MAX_CROP_WIDTH
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    result = engine(image, use_cls=False, text_score=0.6, box_thresh=0.5)
    texts = []
    for raw_text in (result.txts or []):
        cleaned = _sanitize_ocr_line(raw_text)
        if cleaned:
            texts.append(cleaned)
    return texts


def _texts_equal(current_texts, prev_texts):
    if len(current_texts) != len(prev_texts):
        return False
    return all(a == b for a, b in zip(current_texts, prev_texts))


def transcribe_video_ocr(video_path, *, region="bottom", fps=None, ocr_engine=None):
    duration = 0
    if fps is None:
        try:
            result = subprocess.run(
                [_ffmpeg_path(), "-i", video_path, "-f", "null", "-"],
                capture_output=True, text=True,
            )
            for line in (result.stderr or "").splitlines():
                if "Duration:" in line:
                    parts = line.split("Duration:")[1].strip().split(",")[0].strip().split(":")
                    duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    break
            else:
                duration = 60
        except Exception:
            duration = 60
        if duration <= 180:
            fps = 1.5
        elif duration <= 360:
            fps = 1.0
        elif duration <= 600:
            fps = 0.75
        else:
            fps = 0.5
        print(f"[OCR] Video duration: {duration:.0f}s, auto fps: {fps}")

    frame_interval = 1.0 / fps
    cap = _open_video(video_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_step = max(1, round(video_fps / fps))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    total_steps = total_frames // frame_step if total_frames else 0
    if total_steps <= 0:
        total_steps = int(duration * fps) if duration > 0 else 300
    print(f"[OCR] Seeking {total_steps} frames at {fps} fps from video directly...")
    try:
        if ocr_engine is None:
            ocr_engine = _load_ocr_engine()

        segments = []
        prev_texts = None
        prev_hash = None
        seg_start = None
        seg_text_lines = []
        empty_streak = 0
        ocr_count = 0
        skip_count = 0
        step = 0

        while True:
            frame_idx = step * frame_step
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, img = cap.read()
            if not ret or img is None:
                break
            timestamp = frame_idx / video_fps
            cropped = crop_subtitle_region(img, region=region)
            cur_hash = _crop_hash(cropped)

            if prev_hash is not None and _hamming_distance(cur_hash, prev_hash) < EXACT_HASH_THRESHOLD:
                skip_count += 1
                texts = list(prev_texts) if prev_texts else []
            elif _is_blank_region(cropped):
                skip_count += 1
                texts = []
            else:
                texts = ocr_frame(ocr_engine, cropped)
                ocr_count += 1
                prev_hash = cur_hash

            step += 1

            if step % 30 == 0:
                pct = step * 100 // total_steps if total_steps > 0 else 0
                print(f"[OCR] Frame {step}/{total_steps} ({pct}%, OCR: {ocr_count}, skip: {skip_count})")

            if not texts:
                empty_streak += 1
                if empty_streak >= EMPTY_TOLERANCE and seg_start is not None:
                    end_ts = max(seg_start + frame_interval, timestamp - frame_interval * 0.5)
                    combined = " ".join(seg_text_lines).strip()
                    if combined:
                        segments.append({
                            "start": seg_start,
                            "end": end_ts,
                            "text": combined,
                            "words": [],
                        })
                    seg_start = None
                    seg_text_lines = []
                    prev_texts = None
                continue

            empty_streak = 0

            if prev_texts is not None and _texts_equal(texts, prev_texts):
                continue

            if seg_start is not None and seg_text_lines:
                end_ts = max(seg_start + frame_interval, timestamp - frame_interval * 0.5)
                combined = " ".join(seg_text_lines).strip()
                if combined:
                    segments.append({
                        "start": seg_start,
                        "end": end_ts,
                        "text": combined,
                        "words": [],
                    })
            seg_start = timestamp - frame_interval * 0.5
            if step == 1:
                seg_start = 0.0
            seg_text_lines = texts
            prev_texts = texts

    finally:
        cap.release()

    if seg_start is not None and seg_text_lines:
        combined = " ".join(seg_text_lines).strip()
        if combined:
            video_duration = total_frames / video_fps if total_frames and video_fps else (total_steps * frame_interval)
            end_ts = max(seg_start + frame_interval, video_duration)
            segments.append({
                "start": seg_start,
                "end": end_ts,
                "text": combined,
                "words": [],
            })

    merged = _merge_adjacent(segments)
    merged = _dedup_identical(merged)
    print(f"[OCR] Extracted {len(merged)} subtitle segments from {total_steps} frames (OCR: {ocr_count}, skip: {skip_count})")
    return merged


def _dedup_identical(segments):
    if len(segments) < 2:
        return segments
    result = [segments[0]]
    for seg in segments[1:]:
        prev = result[-1]
        gap = seg["start"] - prev["end"]
        prev_dur = prev["end"] - prev["start"]
        seg_dur = seg["end"] - seg["start"]
        both_short = prev_dur < 1.0 and seg_dur < 1.0 and len(prev["text"]) <= 3 and len(seg["text"]) <= 5
        same_text = seg["text"] == prev["text"]
        similar = not same_text and gap < 0.5 and _texts_similar(
            seg["text"].split(), prev["text"].split()
        )
        should_merge = (same_text or similar or (both_short and gap < 0.3)) and gap < 2.0
        if should_merge:
            prev["end"] = max(prev["end"], seg["end"])
            if both_short and not same_text:
                prev["text"] = _sanitize_ocr_line(prev["text"] + seg["text"])
            elif not same_text and len(seg["text"]) > len(prev["text"]):
                prev["text"] = seg["text"]
        else:
            result.append(seg)
    return result


def _texts_similar(a, b):
    if not a or not b:
        return False
    a_set = set(a)
    b_set = set(b)
    overlap = len(a_set & b_set)
    min_len = min(len(a_set), len(b_set))
    if min_len > 0 and overlap / min_len >= 0.75:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if not shorter:
        return False
    matched = 0
    for sw in shorter:
        for lw in longer:
            if sw == lw:
                matched += 1
                break
            if len(sw) < 2 or len(lw) < 2:
                continue
            sw_short, lw_long = (sw, lw) if len(sw) <= len(lw) else (lw, sw)
            if sw_short in lw_long:
                matched += 1
                break
            common = sum(c1 == c2 for c1, c2 in zip(sw, lw))
            if common / max(len(sw), len(lw)) >= 0.8:
                matched += 1
                break
    return matched / len(shorter) >= 0.7


def _merge_adjacent(segments, max_gap=0.5):
    if not segments:
        return []
    merged = []
    current = dict(segments[0])
    current["text"] = _sanitize_ocr_line(current.get("text", ""))
    for seg in segments[1:]:
        seg = dict(seg)
        seg["text"] = _sanitize_ocr_line(seg.get("text", ""))
        if not seg["text"]:
            continue
        gap = seg["start"] - current["end"]
        if gap <= max_gap and _texts_similar(seg["text"].split(), current["text"].split()):
            current["end"] = seg["end"]
        else:
            if current.get("text"):
                merged.append(current)
            current = dict(seg)
    if current.get("text"):
        merged.append(current)
    return merged


def unload_ocr_engine():
    global _OCR_ENGINE
    with _get_lock():
        _OCR_ENGINE = None
        print("[OCR] Engine unloaded")
