# TS1 Timeline & Sync Mode Specification

## Overview

After generating voice/video, the application creates a single **TS1** track.

Each TS1 segment contains:
- Start / End time
- Subtitle text
- Generated TTS audio
- Voice speed
- Volume

The subtitle displayed on the video always uses the segment text.

If the actual audio duration extends beyond the next segment, the overlapping segment is automatically displayed on the next row (row stacking).

---

## Timeline Editing

### Edit Subtitle

When the subtitle text is changed and **Regenerate Voice** is executed:

- Regenerate TTS for that segment.
- Update the audio duration.
- Update the timeline.
- Recalculate row stacking.

If the regenerated audio becomes shorter and no longer overlaps, the segment automatically moves back to the first row.

---

### Edit Duration

Users can resize a segment to increase or decrease its duration.

Resizing only changes the timeline duration.

The audio is regenerated only when **Regenerate Voice** is executed.

---

### Voice Speed

Each segment can have its own voice speed.

---

### Volume

Volume is applied to the entire TS1 track.

---

# Sync Modes

## OFF

**Priority:** Preserve original TTS.

- No timing adjustment.
- No silence trimming.
- No speed adjustment.
- No audio trimming.
- Audio always plays completely.
- Overlapping segments are displayed using row stacking.

---

## SMART (Recommended)

**Priority:** Balance speech quality and timeline accuracy.

Processing order:

1. Trim trailing silence.
2. Slightly increase speech speed (within a safe limit).
3. If only a very small overflow remains, trim the remaining audio.
4. If the overflow is still significant, keep the original audio and allow overlap.

Result:

- Most segments fit naturally.
- Speech remains natural.
- Minor overlaps may still occur.

---

## Timeline Priority

**Priority:** Keep the timeline clean.

- Audio playback is limited to the segment duration.
- When the segment reaches its end, playback immediately switches to the next segment.
- Subtitle remains unchanged.

Result:

- No overlapping segments.
- Timeline always stays on a single row.
- The end of the speech may be skipped if it exceeds the segment duration.

---

## Force Fit

**Priority:** Preserve complete speech.

- Increase speech speed as much as allowed.
- Try to fit the entire audio into the segment duration.
- If it still cannot fit, keep the full audio and allow overlap.

Result:

- Speech is preserved.
- Less overlap than OFF.
- May still overlap in extreme cases.