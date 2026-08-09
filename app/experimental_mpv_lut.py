"""GPU-native LUT preview support for MPV ``gpu-next``.

MPV's libplacebo renderer can load a .cube LUT through the ``lut`` option.
To keep the existing 0-100% intensity semantics, this module creates a
cached identity/LUT blend .cube and swaps the GPU LUT option in place.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


class CubeLutCache:
    def __init__(self, cache_dir: str | os.PathLike):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._parsed: dict[str, tuple[list[str], int, tuple[float, float, float], tuple[float, float, float], list[tuple[float, float, float]]]] = {}

    def _parse(self, path: str):
        path = os.path.abspath(path)
        cached = self._parsed.get(path)
        if cached is not None:
            return cached
        headers: list[str] = []
        size = 0
        domain_min = (0.0, 0.0, 0.0)
        domain_max = (1.0, 1.0, 1.0)
        values = []
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#"):
                    headers.append(raw.rstrip("\r\n"))
                    continue
                parts = line.split()
                key = parts[0].upper()
                if key == "LUT_3D_SIZE" and len(parts) >= 2:
                    size = int(parts[1])
                    headers.append(raw.rstrip("\r\n"))
                elif key == "DOMAIN_MIN" and len(parts) >= 4:
                    domain_min = tuple(float(v) for v in parts[1:4])
                    headers.append(raw.rstrip("\r\n"))
                elif key == "DOMAIN_MAX" and len(parts) >= 4:
                    domain_max = tuple(float(v) for v in parts[1:4])
                    headers.append(raw.rstrip("\r\n"))
                elif len(parts) >= 3:
                    values.append(tuple(float(v) for v in parts[:3]))
        if size < 2 or len(values) != size ** 3:
            raise ValueError(f"Unsupported .cube LUT: {path}")
        parsed = (headers, size, domain_min, domain_max, values)
        self._parsed[path] = parsed
        return parsed

    def blended_path(self, path: str, strength: float) -> str:
        path = os.path.abspath(path)
        strength = max(0.0, min(1.0, float(strength)))
        if strength >= 0.9995:
            return path
        if strength <= 0.0005:
            return ""
        stamp = f"{path}|{os.path.getmtime(path):.6f}|{strength:.5f}".encode()
        target = self.cache_dir / f"{hashlib.sha1(stamp).hexdigest()}.cube"
        if target.exists():
            return str(target)
        headers, size, domain_min, domain_max, values = self._parse(path)
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for header in headers:
                handle.write(header + "\n")
            index = 0
            for r in range(size):
                for g in range(size):
                    for b in range(size):
                        identity = (
                            domain_min[0] + (domain_max[0] - domain_min[0]) * r / (size - 1),
                            domain_min[1] + (domain_max[1] - domain_min[1]) * g / (size - 1),
                            domain_min[2] + (domain_max[2] - domain_min[2]) * b / (size - 1),
                        )
                        lut = values[index]
                        blended = tuple(identity[i] * (1.0 - strength) + lut[i] * strength for i in range(3))
                        handle.write("%.8f %.8f %.8f\n" % blended)
                        index += 1
        return str(target)


class MpvGpuLutPrototype:
    """Apply cached blended LUTs through MPV's gpu-next/libplacebo path."""

    def __init__(self, mpv_player, cache_dir: str | os.PathLike):
        self.player = mpv_player
        self.cache = CubeLutCache(cache_dir)

    def apply(self, lut_path: str, strength_percent: float) -> str:
        target = self.cache.blended_path(lut_path, float(strength_percent) / 100.0)
        self.player.command("set", "lut", target)
        return target

    def clear(self) -> None:
        self.player.command("set", "lut", "")
