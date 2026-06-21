from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.base import BaseLayer, LayerType


@dataclass
class AudioLayer(BaseLayer):
    type: LayerType = field(default=LayerType.AUDIO, init=False)
    source: str = ""
    source_start: float = 0.0
    speed: float = 1.0
    volume: float = 1.0
    muted: bool = False
    pan: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "source": self.source,
            "source_start": self.source_start,
            "speed": self.speed,
            "volume": self.volume,
            "muted": self.muted,
            "pan": self.pan,
            "fade_in": self.fade_in,
            "fade_out": self.fade_out,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioLayer:
        base = super().from_dict(data)
        return cls(
            id=base.id, name=base.name,
            start=base.start, end=base.end,
            z_index=base.z_index,
            visible=base.visible, locked=base.locked,
            opacity=base.opacity, blend_mode=base.blend_mode,
            metadata=base.metadata,
            source=str(data.get("source", "")),
            source_start=float(data.get("source_start", 0.0)),
            speed=float(data.get("speed", 1.0)),
            volume=float(data.get("volume", 1.0)),
            muted=bool(data.get("muted", False)),
            pan=float(data.get("pan", 0.0)),
            fade_in=float(data.get("fade_in", 0.0)),
            fade_out=float(data.get("fade_out", 0.0)),
        )
