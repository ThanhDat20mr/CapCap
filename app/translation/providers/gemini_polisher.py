import os
import time

from openai import OpenAI

from ..errors import TranslationConfigError, TranslationProviderError, TranslationValidationError
from ..srt_utils import parse_numbered_line_items, validate_texts


class OpenAICompatiblePolisherProvider:
    """Reusable numbered-subtitle provider for OpenAI-compatible services."""

    def __init__(self, *, provider_id: str, display_name: str, env_prefix: str,
                 default_base_url: str, default_model: str = ""):
        self.provider_id = provider_id
        self.display_name = display_name
        self.api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
        self.model_name = os.getenv(f"{env_prefix}_MODEL", default_model).strip()
        self.base_url = os.getenv(f"{env_prefix}_BASE_URL", default_base_url).strip()
        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model_name and self.base_url)

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
            raise TranslationConfigError(f"{self.display_name} is not configured. Set its API key and model in Settings.")

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
                return lines, [], self.provider_id
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

        raise TranslationProviderError(f"{self.display_name} failed: {last_error}")

    def _build_messages(
        self, source_texts, translated_texts, src_lang, target_lang, style_instruction
    ) -> tuple[str, str]:
        is_direct = not translated_texts
        style_part = f" Style: {style_instruction}" if style_instruction else ""
        dubbing_mode = "[mode=dubbing_rewrite]" in str(style_instruction or "").lower()
        ocr_capture_mode = "[mode=ocr_capture]" in str(style_instruction or "").lower()

        if is_direct:
            if ocr_capture_mode:
                # A visual OCR capture can contain real line breaks and list
                # numbers. They are content, not separate subtitle cue IDs.
                lines = [
                    f"{i+1}. <OCR_TEXT>{' '.join(str(s or '').splitlines())}</OCR_TEXT>"
                    for i, s in enumerate(source_texts)
                ]
                header = f"Translate these {src_lang}->{target_lang} OCR text blocks.{style_part}"
            else:
                lines = [f"{i+1}. {s}" for i, s in enumerate(source_texts)]
                header = f"Translate these {src_lang}->{target_lang} subtitles with scene-level context.{style_part}"
        else:
            lines = [
                f"{i+1}. {s} ||| {t}"
                for i, (s, t) in enumerate(zip(source_texts, translated_texts))
            ]
            if dubbing_mode:
                header = f"Rewrite these {src_lang}->{target_lang} dubbing drafts for TTS timing rescue.{style_part}"
            else:
                header = f"Refine these {src_lang}->{target_lang} subtitle translations.{style_part}"

        context_rules = (
            "Translation contract: Translate every meaningful cue faithfully and completely. Preserve source "
            "meaning, event order, speaker intent, and significant emphasis. Do not omit, summarize, sanitize, "
            "intensify, or add information. "
            "Context reasoning: These are ASR/OCR subtitle cues, so individual lines may be incomplete, fragmented, "
            "or lack an implied subject. Read the entire numbered scene before translating any cue. Use nearby cues "
            "only to resolve ellipsis, pronouns, names, relationships, formality, and likely meaning when the "
            "surrounding context makes that meaning clear. Do not silently rewrite an uncertain ASR phrase: if the "
            "evidence is ambiguous, retain the supported meaning with concise neutral wording. "
            "Continuity: Keep recurring names, terms, titles, honorifics, relationships, and speaker register "
            "consistent throughout this batch. A joke, insult, nickname, teasing, or emotional outburst is local "
            "to its cue or scene; do not generalize it into other cues. "
            "Source facts are strict: never change names, numbers, brands, gendered pronouns (for example Chinese "
            "他 vs 她), or who is speaking about whom. Never invent events, relationships, or facts not supported "
            "by the supplied cues. "
        )
        rules = (
            "IMPORTANT: Output ONLY the translation. Do NOT think, explain, or comment. "
            "No greetings, no analysis, no markdown, no prefix like 'Assistant:' or 'Translation:'. "
            "Return EXACTLY numbered lines, one per input item. Nothing else.\n"
            "Format: N. translated text\n"
            "Priority order: (1) exact numbered output and source-supported facts; "
            "(2) fidelity and completeness; (3) continuity of names, terminology, and register; "
            f"(4) natural spoken {target_lang} localization. "
            f"Adapt idioms and word order naturally to {target_lang}; do not translate mechanically. "
            "Keep each result readable as one subtitle cue. "
        ) + context_rules + "Never merge, omit, reorder, or split cue numbers."
        if ocr_capture_mode:
            rules += (
                " Each <OCR_TEXT> tag is exactly one input item. Its embedded line breaks, "
                "labels, bullets, and numbers are ordinary text, never new cue numbers. "
                "Treat UI labels, signs, and product text as visual text, not spoken dialogue. Preserve their "
                "meaning and practical wording; keep brand names and product identifiers unchanged. "
                "Return exactly one numbered translation line for each tag."
            )
        if dubbing_mode:
            rules = (
                "IMPORTANT: Output ONLY the rewritten line. Do NOT think, explain, or comment. "
                "No greetings, no analysis, no markdown, no prefix. "
                "Return EXACTLY numbered lines, one per input item. Nothing else.\n"
                "Format: N. short spoken line\n"
                f"Priority order: source-supported facts and names first; then timing; then natural spoken {target_lang}. "
                "Translate every meaningful cue without adding or omitting claims. Very concise. "
                "Fit the timing constraints strictly. "
                "Preserve names, numbers, brands, products exactly. "
                "Each line must be speakable within the given duration and retain the source speaker's register. "
                "Keep names and terminology consistent across the whole batch. "
            ) + context_rules + "Never merge, omit, reorder, or split cue numbers."

        system_msg = f"{header}\n{rules}"
        user_msg = "\n".join(lines)
        return system_msg, user_msg
