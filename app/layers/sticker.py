from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.base import BaseLayer, LayerType
from app.layers.transform import Transform


@dataclass
class StickerLayer(BaseLayer):
    type: LayerType = field(default=LayerType.STICKER, init=False)
    source: str = ""
    transform: Transform = field(default_factory=Transform)
    animation: str = "none"

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "source": self.source,
            "transform": self.transform.to_dict(),
            "animation": self.animation,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StickerLayer:
        base = super().from_dict(data)
        return cls(
            id=base.id, name=base.name,
            start=base.start, end=base.end,
            z_index=base.z_index,
            visible=base.visible, locked=base.locked,
            opacity=base.opacity, blend_mode=base.blend_mode,
            metadata=base.metadata,
            source=str(data.get("source", "")),
            transform=Transform.from_dict(data.get("transform", {})),
            animation=str(data.get("animation", "none")),
        )
