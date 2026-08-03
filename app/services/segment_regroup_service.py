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

            # Preserve the recognizer's segmentation. Short words,
            # acknowledgements, and continuation-looking phrases are valid
            # dialogue, not evidence of a transcription artifact. Chunk
            # overlap duplicates are resolved earlier in AsrMergeService,
            # where real timestamp overlap is still available.
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

    def _normalize_sentence_text(self, text: str) -> str:
        value = re.sub(r"\s+", " ", str(text or "").strip())
        return value
