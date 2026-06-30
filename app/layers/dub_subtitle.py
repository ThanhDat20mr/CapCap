from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.base import BaseLayer, LayerType


@dataclass
class DubSubtitleLayer(BaseLayer):
    """Single-layer replacement for the old TS1 subtitle + A2 Dub audio
    pair. One layer = one segment. Holds both the display text (subtitle)
    and the voice text (TTS), plus the generated wav path when voice
    generation has run.
    """

    type: LayerType = field(default=LayerType.DUB_SUBTITLE, init=False)
    text: str = ""
    dub_text: str = ""
    audio_path: str = ""
    muted: bool = False
    tts_settings: dict[str, Any] = field(default_factory=dict)
    font_name: str = "Arial"
    font_size: int = 30
    font_color: str = "#FFFFFF"
    font_bold: bool = False
    font_italic: bool = False
    font_underline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 2.0
    background_color: str = ""
    background_opacity: float = 0.5
    alignment: str = "center"
    position_x: float = 50.0
    position_y: float = 90.0
    animation: str = "none"
    single_line: bool = False

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "text": self.text,
            "dub_text": self.dub_text,
            "audio_path": self.audio_path,
            "muted": self.muted,
            "tts_settings": self.tts_settings,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "font_color": self.font_color,
            "font_bold": self.font_bold,
            "font_italic": self.font_italic,
            "font_underline": self.font_underline,
            "outline_color": self.outline_color,
            "outline_width": self.outline_width,
            "background_color": self.background_color,
            "background_opacity": self.background_opacity,
            "alignment": self.alignment,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "animation": self.animation,
            "single_line": self.single_line,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DubSubtitleLayer":
        base = super().from_dict(data)
        return cls(
            id=base.id, name=base.name,
            start=base.start, end=base.end,
            z_index=base.z_index,
            visible=base.visible, locked=base.locked,
            opacity=base.opacity, blend_mode=base.blend_mode,
            metadata=base.metadata,
            text=str(data.get("text", "")),
            dub_text=str(data.get("dub_text", data.get("text", ""))),
            audio_path=str(data.get("audio_path", "")),
            muted=bool(data.get("muted", False)),
            tts_settings=dict(data.get("tts_settings", {}) or {}),
            font_name=str(data.get("font_name", "Arial")),
            font_size=int(data.get("font_size", 30)),
            font_color=str(data.get("font_color", "#FFFFFF")),
            font_bold=bool(data.get("font_bold", False)),
            font_italic=bool(data.get("font_italic", False)),
            font_underline=bool(data.get("font_underline", False)),
            outline_color=str(data.get("outline_color", "#000000")),
            outline_width=float(data.get("outline_width", 2.0)),
            background_color=str(data.get("background_color", "")),
            background_opacity=float(data.get("background_opacity", 0.5)),
            alignment=str(data.get("alignment", "center")),
            position_x=float(data.get("position_x", 50.0)),
            position_y=float(data.get("position_y", 90.0)),
            animation=str(data.get("animation", "none")),
            single_line=bool(data.get("single_line", False)),
        )
