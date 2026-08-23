# /push

Write MIDI notes from a part file into an Ableton Session clip.

## Usage

```
/push <song>/parts/bass/verse1-bass.md
/push <song>/parts/drums/chorus1-drums.md --track 2 --slot 0
```

## What it does

1. Reads the part file
2. Extracts note data: pitch, start_time, duration, velocity, mute
3. Calls AbletonMCP: `create_clip`, then `add_notes_to_clip`, then `set_clip_name`
4. Reports the clip name and slot used

## Script

```bash
python3 bridge/push.py --part <song>/parts/bass/verse1-bass.md
```

A path that exists as given is used as given. A relative path that misses is retried under
the songs directory.

## Ableton targets

The clip lands in a **Session clip slot**, which is an AbletonMCP limitation. Drag it to
the Arrangement at the correct bar yourself.

**Unfreeze the target track first.** Frozen tracks fail silently on `create_clip`: no
error, no clip.

Track indexing is zero-based, so a track is one lower than its number in the UI.

## Part file format

Markdown with a YAML header and a note table. Start times are relative to the clip, not
the arrangement.

```markdown
---
track: Electric Damped Bass
track_index: 8    # 0-based
slot: 0
clip_length_beats: 64
---

| pitch | start_time | duration | velocity | mute |
|-------|-----------|---------|---------|------|
| 39    | 0.0       | 3.9     | 78      | 0    |
| 39    | 4.0       | 3.9     | 72      | 0    |
```

This is the same format `/pull` writes, so a pulled part can be edited and pushed back.
