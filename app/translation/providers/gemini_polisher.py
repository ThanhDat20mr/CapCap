import os
import time

from openai import OpenAI

from ..errors import TranslationConfigError, TranslationProviderError, TranslationValidationError
from ..srt_utils import parse_numbered_line_items, validate_texts


class GeminiPolisherProvider:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model_name = os.getenv("OPENAI_MODEL", "gemma-4-31b-it").strip()
        self.base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).strip()
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def polish_batch(
        self,
        *,
        source_texts: list[str],
        translated_texts: list[str] = None,
        src_lang: str,
        target_lang: str,
        style_instruction: str = "",
        timeout: int = 120,
        max_retries: int = 2,
        max_tokens: int = 4096,
    ) -> tuple[list[str], list[str], str]:
        if not self.is_configured():
            raise TranslationConfigError("OPENAI_API_KEY is not set in .env")

        system_msg, user_msg = self._build_messages(
            source_texts=source_texts,
            translated_texts=translated_texts,
            src_lang=src_lang,
            target_lang=target_lang,
            style_instruction=style_instruction,
        )

        client = self._get_client()
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.2,
                    max_tokens=max(1024, int(max_tokens or 4096)),
                    timeout=timeout,
                )
                text = response.choices[0].message.content.strip()
                if not text:
                    raise Exception("Empty response text")

                numbered_items = parse_numbered_line_items(text)
                expected = len(source_texts)
                expected_ids = list(range(1, expected + 1))
                actual_ids = [number for number, _line in numbered_items]
                if actual_ids != expected_ids:
                    raise TranslationValidationError(
                        f"Malformed or incomplete numbered output: expected IDs 1..{expected}, got {actual_ids[:8]}..."
                    )
                lines = [line for _number, line in numbered_items]
                if not validate_texts(lines, expected):
                    raise TranslationValidationError(
                        f"Expected {expected} lines, got {len(lines)}"
                    )
                return lines, [], "openai"
            except TranslationValidationError:
                # Retrying the exact same oversized request cannot restore a
                # truncated numbered response.  The orchestrator can instead
                # recover by switching immediately to ordered batches.
                raise
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(attempt)
                    continue

        raise TranslationProviderError(f"Gemini failed: {last_error}")

    def _build_messages(
        self, source_texts, translated_texts, src_lang, target_lang, style_instruction
    ) -> tuple[str, str]:
        is_direct = not translated_texts
        style_part = f" Style: {style_instruction}" if style_instruction else ""
        dubbing_mode = "[mode=dubbing_rewrite]" in str(style_instruction or "").lower()

        if is_direct:
            lines = [f"{i+1}. {s}" for i, s in enumerate(source_texts)]
            header = f"Translate these {src_lang}->{target_lang} subtitles directly.{style_part}"
        else:
            lines = [
                f"{i+1}. {s} ||| {t}"
                for i, (s, t) in enumerate(zip(source_texts, translated_texts))
            ]
            if dubbing_mode:
                header = f"Rewrite these {src_lang}->{target_lang} dubbing drafts for TTS timing rescue.{style_part}"
            else:
                header = f"Refine these {src_lang}->{target_lang} subtitle translations.{style_part}"

        rules = (
            "IMPORTANT: Output ONLY the translation. Do NOT think, explain, or comment. "
            "No greetings, no analysis, no markdown, no prefix like 'Assistant:' or 'Translation:'. "
            "Return EXACTLY numbered lines, one per input item. Nothing else.\n"
            "Format: N. translated text\n"
            f"Quality: Natural, spoken {target_lang}. Short sentences. "
            "Preserve names, numbers, brands, products exactly. "
            f"Adapt idioms naturally to {target_lang}, not literal. "
            "Keep each line readable as a single subtitle cue. "
            "Treat this numbered batch as one continuous scene: keep names, terms, "
            "formality, and speaker tone consistent across all cues. "
            "Never merge, omit, reorder, or split cue numbers."
        )
        if dubbing_mode:
            rules = (
                "IMPORTANT: Output ONLY the rewritten line. Do NOT think, explain, or comment. "
                "No greetings, no analysis, no markdown, no prefix. "
                "Return EXACTLY numbered lines, one per input item. Nothing else.\n"
                "Format: N. short spoken line\n"
                f"Quality: Natural spoken {target_lang}. Very concise. "
                "Fit the timing constraints strictly. "
                "Preserve names, numbers, brands, products exactly. "
                "Each line must be speakable within the given duration. "
                "Keep names, terms, and speaker tone consistent across the whole batch. "
                "Never merge, omit, reorder, or split cue numbers."
            )

        system_msg = f"{header}\n{rules}"
        user_msg = "\n".join(lines)
        return system_msg, user_msg
