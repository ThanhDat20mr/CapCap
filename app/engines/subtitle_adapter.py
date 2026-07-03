from subtitle_builder import generate_srt


class SubtitleAdapter:
    def generate_srt(self, segments, output_path: str, max_gap_ms: float = 100.0) -> str:
        generate_srt(segments, output_path, max_gap_ms=max_gap_ms)
        return output_path
