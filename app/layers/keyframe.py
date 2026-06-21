from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Keyframe:
    time: float
    value: Any
    easing: str = "linear"

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "value": self.value, "easing": self.easing}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Keyframe:
        return cls(
            time=float(data.get("time", 0.0)),
            value=data.get("value"),
            easing=str(data.get("easing", "linear")),
        )


@dataclass
class KeyframeTrack:
    property_name: str
    keyframes: list[Keyframe] = None

    def __post_init__(self):
        if self.keyframes is None:
            self.keyframes = []

    def get_value_at(self, time: float) -> Any:
        if not self.keyframes:
            return None
        if len(self.keyframes) == 1:
            return self.keyframes[0].value
        prev = self.keyframes[0]
        for kf in self.keyframes[1:]:
            if kf.time >= time:
                if kf.time == prev.time:
                    return kf.value
                t = (time - prev.time) / (kf.time - prev.time)
                return self._interpolate(prev.value, kf.value, t, kf.easing)
            prev = kf
        return prev.value

    @staticmethod
    def _interpolate(a: float, b: float, t: float, easing: str) -> float:
        if easing == "ease_in":
            t = t * t
        elif easing == "ease_out":
            t = 1 - (1 - t) * (1 - t)
        elif easing == "ease_in_out":
            t = t * t * (3 - 2 * t)
        return a + (b - a) * t

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.property_name,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyframeTrack:
        return cls(
            property_name=str(data.get("property", "")),
            keyframes=[Keyframe.from_dict(k) for k in data.get("keyframes", [])],
        )
