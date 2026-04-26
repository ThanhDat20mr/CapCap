from tts_processor import synthesize_text_to_wav_16k_mono
from runtime_paths import workspace_root
from services import F5VoiceService


class TTSAdapter:
    def __init__(self):
        self._f5_service = F5VoiceService(workspace_root())

    def synthesize_segment(
        self,
        *,
        text: str,
        wav_path: str,
        voice: str = "vi_VN-vais1000-medium",
        speed: float = 1.0,
        tmp_dir: str | None = None,
        on_progress: callable = None,
    ) -> str:
        if self._f5_service.is_f5_voice_token(voice):
            return self._f5_service.synthesize_segment(
                voice_token=voice,
                text=text,
                wav_path=wav_path,
                speed=speed,
                temp_dir=tmp_dir or "",
                on_progress=on_progress,
            )
        return synthesize_text_to_wav_16k_mono(
            text=text,
            wav_path=wav_path,
            voice=voice,
            speed=speed,
            tmp_dir=tmp_dir,
            on_progress=on_progress,
        )
