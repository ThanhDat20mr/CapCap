from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.layers.keyframe import KeyframeTrack


@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    keyframes: list[KeyframeTrack] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "rotation": self.rotation,
            "anchor_x": self.anchor_x,
            "anchor_y": self.anchor_y,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transform:
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            scale_x=float(data.get("scale_x", 1.0)),
            scale_y=float(data.get("scale_y", 1.0)),
            rotation=float(data.get("rotation", 0.0)),
            anchor_x=float(data.get("anchor_x", 0.5)),
            anchor_y=float(data.get("anchor_y", 0.5)),
            keyframes=[KeyframeTrack.from_dict(k) for k in data.get("keyframes", [])],
        )

    def get_value_at(self, time: float) -> Transform:
        result = Transform(
            x=self.x, y=self.y,
            scale_x=self.scale_x, scale_y=self.scale_y,
            rotation=self.rotation,
            anchor_x=self.anchor_x, anchor_y=self.anchor_y,
        )
        for track in self.keyframes:
            val = track.get_value_at(time)
            if val is not None:
                setattr(result, track.property_name, val)
        return result

    def clone(self) -> Transform:
        return Transform(
            x=self.x, y=self.y,
            scale_x=self.scale_x, scale_y=self.scale_y,
            rotation=self.rotation,
            anchor_x=self.anchor_x, anchor_y=self.anchor_y,
            keyframes=[KeyframeTrack.from_dict(kf.to_dict()) for kf in self.keyframes],
        )
