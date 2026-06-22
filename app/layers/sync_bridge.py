from __future__ import annotations

import os
from typing import Any

from app.layers.base import LayerType
from app.layers.subtitle import SubtitleLayer
from app.layers.audio import AudioLayer
from app.layers.blur import BlurLayer
from app.layers.timeline import Timeline, Track


def _get_segment_text(d: dict[str, Any]) -> str:
    return str(d.get("text", d.get("final_text", d.get("subtitle_text", ""))))


def find_or_create_track(
    timeline: Timeline,
    name: str,
    layer_type: LayerType,
    height: int = 80,
) -> Track:
    """Find track by name, or create it."""
    for t in timeline.tracks:
        if t.name == name and t.type == layer_type:
            return t
    track = Track(name=name, type=layer_type, height=height)
    timeline.tracks.append(track)
    return track


def remove_track(timeline: Timeline, name: str) -> None:
    """Remove tracks by name."""
    timeline.tracks[:] = [t for t in timeline.tracks if t.name != name]


def sync_segments_to_subtitle_layers(
    timeline: Timeline,
    segments: list[dict[str, Any]],
) -> None:
    """Convert flat segment dicts to SubtitleLayers on the S1 subtitle track.

    Pipeline writes flat segments -> this makes them visible on timeline.
    Overlapping segments spill to subtitle-2, subtitle-3 etc.

    Each layer's `metadata["_seg_index"]` stores the original (unsorted)
    index in the input `segments` list, so clicking a layer in the timeline
    can map back to the correct row in the segment editor / inspector.
    """
    if not segments:
        return

    # Map: original index -> sorted position
    indexed = list(enumerate(segments))

    # Sort by start time
    indexed.sort(key=lambda kv: float(kv[1].get("start", 0)))

    # Gather existing subtitle tracks, clear their layers
    sub_tracks: list[Track] = []
    for t in timeline.tracks:
        if t.type == LayerType.SUBTITLE:
            t.layers.clear()
            sub_tracks.append(t)
    # Use first subtitle track as primary, create more if needed
    primary = sub_tracks[0] if sub_tracks else find_or_create_track(timeline, "S1", LayerType.SUBTITLE, 100)
    if primary not in sub_tracks:
        sub_tracks.append(primary)
    # Remove extra subtitle tracks beyond first
    for t in sub_tracks[1:]:
        timeline.tracks.remove(t)

    idx_counter = 0
    active_tracks: list[Track] = [primary]

    for orig_idx, d in indexed:
        start = float(d.get("start", 0))
        end = float(d.get("end", 0))
        text = _get_segment_text(d)

        placed = False
        for track in active_tracks:
            overlaps = any(start < l.end and end > l.start for l in track.layers)
            if not overlaps:
                layer = SubtitleLayer(
                    name=f"Sub {idx_counter + 1}",
                    text=text,
                    start=start, end=end,
                )
                layer.z_index = idx_counter
                # Store dict metadata so sync_layers_to_segments can reconstruct
                layer.metadata["_seg_dict"] = {k: v for k, v in d.items() if k != "text"}
                layer.metadata["_seg_index"] = int(orig_idx)
                track.layers.append(layer)
                idx_counter += 1
                placed = True
                break

        if not placed:
            track = Track(
                name=f"Subtitles {len(active_tracks) + 1}",
                type=LayerType.SUBTITLE,
                height=100,
            )
            timeline.tracks.append(track)
            active_tracks.append(track)
            layer = SubtitleLayer(
                name=f"Sub {idx_counter + 1}",
                text=text,
                start=start, end=end,
            )
            layer.z_index = idx_counter
            layer.metadata["_seg_dict"] = {k: v for k, v in d.items() if k != "text"}
            layer.metadata["_seg_index"] = int(orig_idx)
            track.layers.append(layer)
            idx_counter += 1


def sync_layers_to_segments(timeline: Timeline) -> list[dict[str, Any]]:
    """Convert SubtitleLayers back to flat segment dicts for pipeline.

    Reads layers from all subtitle tracks, reconstructs original dict
    (with metadata intact), and applies current text.
    """
    segments: list[dict[str, Any]] = []
    for track in timeline.tracks:
        if track.type != LayerType.SUBTITLE:
            continue
        for layer in track.layers:
            if not isinstance(layer, SubtitleLayer):
                continue
            # Start from stored dict metadata
            d: dict[str, Any] = dict(layer.metadata.get("_seg_dict", {}))
            d["id"] = int(d.get("id", 0))
            d["start"] = layer.start
            d["end"] = layer.end
            d["text"] = layer.text
            # Preserve other text fields if they exist
            if "final_text" in d and d["final_text"]:
                d["final_text"] = layer.text
            segments.append(d)
    segments.sort(key=lambda s: (s["start"], s.get("id", 0)))
    return segments


def sync_blur_regions_to_layers(
    timeline: Timeline,
    blur_regions: list[dict[str, Any]] | None,
) -> None:
    """Convert blur region data to BlurLayers on the B1 blur track."""
    if not blur_regions:
        remove_track(timeline, "B1")
        return

    blur_track = find_or_create_track(timeline, "B1", LayerType.BLUR, 100)
    blur_track.layers.clear()

    for i, br in enumerate(blur_regions):
        layer = BlurLayer(
            name=f"Blur {i + 1}",
            start=float(br.get("start", 0)),
            end=float(br.get("end", timeline.duration)),
            position_x=float(br.get("x", br.get("position_x", 0))),
            position_y=float(br.get("y", br.get("position_y", 0))),
            width=float(br.get("width", 200)),
            height=float(br.get("height", 80)),
            blur_strength=float(br.get("blur_strength", br.get("intensity", 20))),
        )
        layer.z_index = i
        blur_track.layers.append(layer)


def sync_tts_to_audio_layers(
    timeline: Timeline,
    voice_track_path: str,
    start: float = 0.0,
    end: float = 0.0,
    segments: list[dict[str, Any]] | None = None,
) -> None:
    """Create A2 Dub Audio track from the generated TTS mixed file.

    If `segments` is provided, create one AudioLayer per segment so the
    timeline shows each dubbed chunk separately with gaps for undubbed
    portions. Falls back to a single full-duration layer otherwise.
    """
    if not voice_track_path or not os.path.exists(voice_track_path):
        return

    a2 = find_or_create_track(timeline, "A2 Dub", LayerType.AUDIO, 80)
    a2.layers.clear()

    dub_segs: list[tuple[float, float, int]] = []
    if segments:
        for seg_idx, d in enumerate(segments):
            try:
                seg_start = float(d.get("start", 0.0))
                seg_end = float(d.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            if seg_end <= seg_start:
                continue
            has_dub = bool(
                d.get("dubbing_vi")
                or d.get("tts_text")
                or d.get("text")
                or d.get("voice_edited")
            )
            if has_dub:
                dub_segs.append((seg_start, seg_end, seg_idx))

    if not dub_segs:
        dur = end if end > 0 else timeline.duration if timeline.duration > 0 else 10.0
        a2.layers.append(AudioLayer(
            name="A2 Dub",
            source=voice_track_path,
            start=start,
            end=dur,
            volume=1.0,
        ))
        return

    dub_segs.sort(key=lambda x: x[0])
    for idx, (seg_start, seg_end, seg_idx) in enumerate(dub_segs, start=1):
        layer = AudioLayer(
            name=f"Dub {idx}",
            source=voice_track_path,
            start=seg_start,
            end=seg_end,
            volume=1.0,
        )
        # Store the original segment index so clicking this layer in
        # the timeline can map back to the matching subtitle segment
        # (and update the Dub Voice inspector content).
        layer.metadata["_seg_index"] = int(seg_idx)
        a2.layers.append(layer)


def ensure_v1_a1_tracks(timeline: Timeline, video_path: str, duration: float) -> None:
    """Ensure V1 (video) and A1 (audio) tracks exist after video import."""
    if duration <= 0:
        return
    from app.layers.video import VideoLayer
    from app.layers.transform import Transform

    v1 = find_or_create_track(timeline, "V1 Video", LayerType.VIDEO, 80)
    v1.visible = True
    v1.layers.clear()
    v1.layers.append(VideoLayer(
        name="V1 Video",
        source=video_path,
        start=0.0,
        end=duration,
        transform=Transform(x=0, y=0, scale_x=1.0, scale_y=1.0),
    ))

    a1 = find_or_create_track(timeline, "A1 Audio", LayerType.AUDIO, 80)
    a1.visible = True
    a1.layers.clear()
    a1.layers.append(AudioLayer(
        name="A1 Audio",
        source=video_path,
        start=0.0,
        end=duration,
        volume=1.0,
    ))
