from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.base import BaseLayer, LayerType
from app.layers.transform import Transform


# Shared Text-layer preview/export calibration.
TEXT_LAYER_PADDING_X = 6
TEXT_LAYER_PADDING_Y = 5
TEXT_LAYER_EXPORT_SCALE = 0.85


@dataclass
class TextLayer(BaseLayer):
    type: LayerType = field(default=LayerType.TEXT, init=False)
    text: str = ""
    font_name: str = "Arial"
    font_size: int = 48
    font_color: str = "#FFFFFF"
    font_bold: bool = False
    font_italic: bool = False
    font_underline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 0.0
    background_color: str = ""
    background_opacity: float = 0.5
    alignment: str = "center"
    line_spacing: float = 1.2
    letter_spacing: float = 0.0
    transform: Transform = field(default_factory=Transform)

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "text": self.text,
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
            "line_spacing": self.line_spacing,
            "letter_spacing": self.letter_spacing,
            "transform": self.transform.to_dict(),
        })
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextLayer:
        base = super().from_dict(data)
        return cls(
            id=base.id, name=base.name,
            start=base.start, end=base.end,
            z_index=base.z_index,
            visible=base.visible, locked=base.locked,
            opacity=base.opacity, blend_mode=base.blend_mode,
            metadata=base.metadata,
            text=str(data.get("text", "")),
            font_name=str(data.get("font_name", "Arial")),
            font_size=int(data.get("font_size", 48)),
            font_color=str(data.get("font_color", "#FFFFFF")),
            font_bold=bool(data.get("font_bold", False)),
            font_italic=bool(data.get("font_italic", False)),
            font_underline=bool(data.get("font_underline", False)),
            outline_color=str(data.get("outline_color", "#000000")),
            outline_width=float(data.get("outline_width", 0.0)),
            background_color=str(data.get("background_color", "")),
            background_opacity=float(data.get("background_opacity", 0.5)),
            alignment=str(data.get("alignment", "center")),
            line_spacing=float(data.get("line_spacing", 1.2)),
            letter_spacing=float(data.get("letter_spacing", 0.0)),
            transform=Transform.from_dict(data.get("transform", {})),
        )
