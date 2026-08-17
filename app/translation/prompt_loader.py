from __future__ import annotations

import json
import re
from pathlib import Path


_PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}")


class PromptTemplateError(RuntimeError):
    """Raised when a translation prompt template cannot be loaded or rendered."""


def prompt_directory() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def load_prompt(template_name: str) -> str:
    safe_name = str(template_name or "").strip()
    if not safe_name or Path(safe_name).name != safe_name:
        raise PromptTemplateError(f"Invalid translation prompt name: {template_name!r}")

    path = prompt_directory() / safe_name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PromptTemplateError(f"Could not read translation prompt: {path}") from exc


def load_prompt_options(template_name: str) -> list[tuple[str, str]]:
    try:
        catalog = json.loads(load_prompt(template_name))
    except json.JSONDecodeError as exc:
        raise PromptTemplateError(
            f"Translation prompt catalog {template_name!r} contains invalid JSON"
        ) from exc
    if not isinstance(catalog, list):
        raise PromptTemplateError(f"Translation prompt catalog {template_name!r} must be a JSON array")
    options = []
    for item in catalog:
        if not isinstance(item, dict):
            raise PromptTemplateError(f"Translation prompt catalog {template_name!r} contains an invalid item")
        label = str(item.get("label", "") or "").strip()
        instruction = str(item.get("instruction", "") or "").strip()
        if not label or not instruction:
            raise PromptTemplateError(f"Translation prompt catalog {template_name!r} requires label and instruction")
        options.append((label, instruction))
    return options


def render_prompt(template_name: str, **values) -> str:
    template = load_prompt(template_name)
    required = set(_PLACEHOLDER_RE.findall(template))
    missing = sorted(key for key in required if key not in values)
    if missing:
        raise PromptTemplateError(
            f"Translation prompt {template_name!r} is missing values for: {', '.join(missing)}"
        )

    return _PLACEHOLDER_RE.sub(lambda match: str(values[match.group(1)]), template).strip()
