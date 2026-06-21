from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.base import BaseLayer, LayerType
from app.layers.transform import Transform


@dataclass
class ImageLayer(BaseLayer):
    type: LayerType = field(default=LayerType.IMAGE, init=False)
    source: str = ""
    transform: Transform = field(default_factory=Transform)
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "source": self.source,
            "transform": self.transform.to_dict(),
            "filters": self.filters,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageLayer:
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
            filters=dict(data.get("filters", {}) or {}),
        )
