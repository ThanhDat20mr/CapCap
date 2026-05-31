from __future__ import annotations

import re


class SegmentRegroupService:
    def regroup(self, segments: list[dict], *, max_gap_seconds: float = 0.35, max_duration_seconds: float = 8.0) -> list[dict]:
        regrouped: list[dict] = []
        for segment in segments or []:
            text = str(segment.get("text", "") or "").strip()
            if not text:
                continue
            if not regrouped:
                regrouped.append(self._clone_segment(segment))
                continue

            previous = regrouped[-1]
            gap = float(segment.get("start", 0.0)) - float(previous.get("end", 0.0))
            proposed_duration = float(segment.get("end", 0.0)) - float(previous.get("start", 0.0))
            if self._should_absorb_echo(previous, segment, gap_seconds=gap):
                regrouped[-1] = self._absorb_echo(previous, segment)
                continue
            if self._should_merge(previous, segment, gap_seconds=gap, proposed_duration_seconds=proposed_duration, max_gap_seconds=max_gap_seconds, max_duration_seconds=max_duration_seconds):
                regrouped[-1] = self._merge_pair(previous, segment)
            else:
                regrouped.append(self._clone_segment(segment))

        normalized = []
        for index, segment in enumerate(regrouped, start=1):
            payload = self._clone_segment(segment)
            payload["id"] = index
            payload["text"] = self._normalize_sentence_text(payload.get("text", ""))
            normalized.append(payload)
        return normalized

    def _clone_segment(self, segment: dict) -> dict:
        payload = {
            "start": float(segment.get("start", 0.0)),
            "end": float(segment.get("end", 0.0)),
            "text": str(segment.get("text", "") or "").strip(),
        }
        if segment.get("words"):
            payload["words"] = list(segment.get("words") or [])
        if segment.get("chunk_id"):
            payload["chunk_id"] = segment.get("chunk_id")
        return payload

    def _should_merge(
        self,
        left: dict,
        right: dict,
        *,
        gap_seconds: float,
        proposed_duration_seconds: float,
        max_gap_seconds: float,
        max_duration_seconds: float,
    ) -> bool:
        if gap_seconds > max_gap_seconds:
            return False
        if proposed_duration_seconds > max_duration_seconds:
            return False
        left_text = str(left.get("text", "") or "").strip()
        right_text = str(right.get("text", "") or "").strip()
        if not left_text or not right_text:
            return False
        if left_text.endswith((".", "!", "?", "...", "…")):
            return False
        if right_text[:1].islower():
            return True
        continuation_prefixes = (
            "và",
            "nhưng",
            "rồi",
            "để",
            "khi",
            "nếu",
            "vì",
            "thì",
            "mà",
            "là",
        )
        return right_text.lower().startswith(continuation_prefixes)

    def _should_absorb_echo(self, left: dict, right: dict, *, gap_seconds: float) -> bool:
        if gap_seconds > 0.08:
            return False
        if not self._is_adjacent_chunk_boundary(left, right):
            return False
        left_text = str(left.get("text", "") or "").strip()
        right_text = str(right.get("text", "") or "").strip()
        if not left_text or not right_text:
            return False
        right_duration = max(0.0, float(right.get("end", 0.0)) - float(right.get("start", 0.0)))
        if right_duration > 0.9 and len(right_text) > 14:
            return False

        left_norm = self._normalize_compare_text(left_text)
        right_norm = self._normalize_compare_text(right_text)
        if len(right_norm) < 3:
            return False

        if right_norm in left_norm:
            return True

        min_overlap = max(4, min(len(right_norm), 6))
        for width in range(len(right_norm), min_overlap - 1, -1):
            for start in range(0, len(right_norm) - width + 1):
                candidate = right_norm[start:start + width]
                if candidate and candidate in left_norm:
                    coverage = width / max(1, len(right_norm))
                    if coverage >= 0.6:
                        return True
        return False

    def _absorb_echo(self, left: dict, right: dict) -> dict:
        payload = self._clone_segment(left)
        payload["end"] = max(float(left.get("end", 0.0)), float(right.get("end", 0.0)))
        merged_words = list(left.get("words") or [])
        if not merged_words and right.get("words"):
            payload["words"] = list(right.get("words") or [])
        else:
            payload["words"] = merged_words
        return payload

    def _merge_pair(self, left: dict, right: dict) -> dict:
        merged_text = f"{str(left.get('text', '')).strip()} {str(right.get('text', '')).strip()}".strip()
        payload = {
            "start": float(left.get("start", 0.0)),
            "end": float(right.get("end", 0.0)),
            "text": merged_text,
        }
        merged_words = list(left.get("words") or []) + list(right.get("words") or [])
        if merged_words:
            payload["words"] = merged_words
        payload["chunk_id"] = right.get("chunk_id") or left.get("chunk_id", "")
        return payload

    def _normalize_sentence_text(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip())
        if not value:
            return ""
        return value[:1].upper() + value[1:]

    def _is_adjacent_chunk_boundary(self, left: dict, right: dict) -> bool:
        left_chunk = str(left.get("chunk_id", "") or "").strip()
        right_chunk = str(right.get("chunk_id", "") or "").strip()
        if not left_chunk or not right_chunk or left_chunk == right_chunk:
            return False
        left_index = self._chunk_index(left_chunk)
        right_index = self._chunk_index(right_chunk)
        if left_index is None or right_index is None:
            return False
        return right_index == left_index + 1

    def _chunk_index(self, chunk_id: str) -> int | None:
        match = re.search(r"(\d+)$", str(chunk_id or "").strip())
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _normalize_compare_text(self, text: str) -> str:
        value = str(text or "").strip().lower()
        if not value:
            return ""
        translate_map = str.maketrans(
            {
                "蘋": "苹",
                "國": "国",
                "個": "个",
                "這": "这",
                "標": "标",
                "準": "准",
                "絲": "丝",
                "續": "续",
                "測": "测",
                "黨": "党",
                "為": "为",
                "與": "与",
                "臺": "台",
                "鐘": "钟",
                "錶": "表",
                "機": "机",
                "茲": "兹",
                "戶": "户",
            }
        )
        value = value.translate(translate_map)
        value = re.sub(r"[0-9a-z]+", "", value)
        value = re.sub(r"\s+", "", value)
        value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value, flags=re.UNICODE)
        return value
