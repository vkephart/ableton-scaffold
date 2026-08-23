"""
pull.py — sync the Ableton arrangement into the repo.

Usage:
  python3 bridge/pull.py --song <name>
  python3 bridge/pull.py --song <name> --songs-dir ~/music-studio/<track-repo>
  python3 bridge/pull.py --song <name> --section intro
  python3 bridge/pull.py --song <name> --tracks-only
  python3 bridge/pull.py --song <name> --devices-only

Writes, under the resolved songs directory:
  <song>/parts/<category>/<clip-name>.md  — note data per arrangement clip
  <song>/chain/<track-name>.md            — device chain snapshot per track

The songs directory is resolved by bridge/songpath.py: --songs-dir, then
$ABLETON_SONGS_DIR, then ./songs, then <bridge-repo>/songs. Song folders do not
have to live in the same repo as these scripts.

Requires AbletonOSC with the arrangement-clip extension from SETUP.md §3.
"""

import argparse
import os
import re
import sys
import time

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BRIDGE_DIR)

from osc_client import OscClient
from songpath import add_songs_dir_arg, resolve_song_dir, display_path, SongPathError

BEATS_PER_BAR = 4

# Track name → parts category heuristic. Substring match, first hit wins, anything
# unmatched lands in fx. Track naming is per-session, so treat this as a starting
# point and add the keywords your own sessions use.
CATEGORY_MAP = {
    "drum": "drums",
    "kick": "drums",
    "snare": "drums",
    "hi-hat": "drums",
    "perc": "drums",
    "bass": "bass",
    "gtr": "guitars",
    "guitar": "guitars",
    "tele": "guitars",
    "vox": "vocals",
    "vocal": "vocals",
    "key": "keys",
    "omni": "keys",
    "pad": "keys",
    "synth": "keys",
    "jun": "keys",
    "fx": "fx",
    "splice": "drums",
    "addictive": "drums",
}


def infer_category(track_name):
    lower = track_name.lower()
    for keyword, cat in CATEGORY_MAP.items():
        if keyword in lower:
            return cat
    return "fx"  # fallback


def slugify(name):
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def beats_to_bars(beats, bpb=BEATS_PER_BAR):
    bar = int(beats / bpb) + 1
    beat = (beats % bpb) + 1
    return f"bar {bar} beat {beat:.2f}"


def clip_position_slug(beats, bpb=BEATS_PER_BAR):
    """Filename-safe clip position, precise enough that two clips never collide.

    Bar number alone is not enough: a clip at beat 200.0 and one at 202.0 are both
    in bar 51, so naming by bar silently overwrote the earlier clip. Clip start times
    are unique within a track, so including the beat offset guarantees uniqueness.
    Bar-aligned clips keep the short 'bar51' form.
    """
    bar = int(beats / bpb) + 1
    offset = beats % bpb
    if abs(offset) < 1e-6:
        return f"bar{bar}"
    beat = f"{offset + 1:.4f}".rstrip("0").rstrip(".").replace(".", "-")
    return f"bar{bar}-beat{beat}"


def write_part_file(path, track_name, track_index, clip_start, clip_length, notes_flat):
    """Write a markdown part file from a flat note list."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    note_rows = []
    for i in range(0, len(notes_flat), 5):
        pitch = int(notes_flat[i])
        start = float(notes_flat[i + 1])
        dur = float(notes_flat[i + 2])
        vel = int(notes_flat[i + 3])
        mute = int(notes_flat[i + 4])
        note_rows.append(f"| {pitch} | {start:.4f} | {dur:.4f} | {vel} | {mute} |")

    header = f"""---
track: {track_name}
track_index: {track_index}
clip_start_beats: {clip_start:.4f}
clip_length_beats: {clip_length:.4f}
clip_start_position: {beats_to_bars(clip_start)}
clip_length_bars: {clip_length / BEATS_PER_BAR:.2f}
pulled: {time.strftime("%Y-%m-%d")}
---

# {track_name} — {beats_to_bars(clip_start)}

| pitch | start_time | duration | velocity | mute |
|-------|-----------|---------|---------|------|
"""
    content = header + "\n".join(note_rows) + "\n"
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {display_path(path)}")


def write_chain_file(path, track_name, track_index, client):
    """Write a device chain snapshot for a track."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    device_names = client.get_device_names(track_index)
    if not device_names:
        return

    lines = [
        f"# {track_name} — device chain",
        f"",
        f"Pulled: {time.strftime('%Y-%m-%d')}",
        f"",
        "Values are raw Live API values, not UI display units. Live's built-in devices",
        "report native units (dB, ms, Hz); many VST/AU plugins report normalized 0.0–1.0.",
        "Which one a given row is depends on the device, so do not quote these as plugin",
        "settings without confirming against the plugin UI.",
        f"",
    ]

    for di, dname in enumerate(device_names):
        lines.append(f"## {di + 1}. {dname}")
        lines.append("")
        param_names = client.get_device_param_names(track_index, di)
        param_values = client.get_device_param_values(track_index, di)
        if param_names and param_values:
            lines.append("| Parameter | Raw value |")
            lines.append("|-----------|-----------|")
            for pname, pval in zip(param_names, param_values):
                lines.append(f"| {pname} | {pval:.4f} |")
        else:
            lines.append("*(no params returned)*")
        lines.append("")

    content = "\n".join(lines)
    with open(path, "w") as f:
        f.write(content)
    print(f"  wrote {display_path(path)}")


def pull(song, songs_dir=None, section_filter=None, tracks_only=False, devices_only=False):
    try:
        song_dir = resolve_song_dir(song, songs_dir)
    except SongPathError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"Song folder: {song_dir}")

    client = OscClient()
    written_paths = set()

    try:
        tempo = client.get_tempo()
        if tempo is None:
            print("ERROR: could not read tempo. Is AbletonOSC running?")
            sys.exit(1)
        print(f"Connected — tempo: {tempo:.1f} BPM")

        track_names = client.get_track_names()
        print(f"Session has {len(track_names)} tracks.")

        for track_index, track_name in track_names:
            if not track_name.strip():
                continue

            print(f"\nTrack {track_index}: {track_name}")
            category = infer_category(track_name)
            parts_dir = os.path.join(song_dir, "parts", category)

            # --- Notes (arrangement clips) ---
            if not devices_only:
                clips = client.get_arrangement_clips(track_index)
                for clip_start, clip_length in clips:
                    if section_filter:
                        # Crude filter: skip clips clearly outside the section
                        # (section boundaries would need to be read from structure.md)
                        pass

                    notes = client.get_arrangement_clip_notes(track_index, clip_start)
                    if not notes:
                        continue

                    clip_slug = slugify(track_name)
                    filename = f"{clip_slug}-{clip_position_slug(clip_start)}.md"
                    path = os.path.join(parts_dir, filename)

                    # Two clips must never collapse onto one filename. Clip starts are
                    # unique per track, so a beat-precise name cannot collide; this guard
                    # is here so any future naming change fails loudly instead of
                    # silently dropping a clip.
                    if path in written_paths:
                        print(f"  WARNING: filename collision on {os.path.basename(path)} "
                              f"(clip at beat {clip_start}) — previous clip would be lost, skipping")
                        continue
                    written_paths.add(path)

                    write_part_file(path, track_name, track_index,
                                    clip_start, clip_length, notes)

            # --- Device chain ---
            if not tracks_only:
                chain_dir = os.path.join(song_dir, "chain")
                chain_path = os.path.join(chain_dir, f"{slugify(track_name)}.md")
                write_chain_file(chain_path, track_name, track_index, client)

    finally:
        client.close()

    print(f"\nDone. Files written to {display_path(song_dir)}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Ableton arrangement to repo")
    parser.add_argument("--song", required=True, help="Song folder name")
    add_songs_dir_arg(parser)
    parser.add_argument("--section", help="Section name to filter (e.g. intro)")
    parser.add_argument("--tracks-only", action="store_true", help="Skip device chain pull")
    parser.add_argument("--devices-only", action="store_true", help="Skip note pull")
    args = parser.parse_args()

    pull(args.song, songs_dir=args.songs_dir, section_filter=args.section,
         tracks_only=args.tracks_only, devices_only=args.devices_only)
