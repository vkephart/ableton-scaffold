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

Bar numbers are derived from the session's own time signature, read over OSC at the
start of every run. If it cannot be read, the run stops rather than assuming 4/4. The
signature and the beats-per-bar it implies go into each part file's frontmatter.

Tracks whose names match no CATEGORY_MAP keyword are listed at the end of the run.
They are filed under parts/fx as a fallback and marked `category_inferred: false`.
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

# Beats-per-bar is read from the session, never assumed. It used to be a module
# constant of 4, which meant every bar number in a 3/4 or 6/8 song was quietly wrong
# and nothing in the output said so. There is deliberately no default anywhere below:
# every function that converts beats to bars takes bpb as a required argument, so a
# missing meter is an error rather than a silent 4.


def beats_per_bar(numerator, denominator):
    """Quarter-note beats per bar for a time signature.

    Live measures clip start times, clip lengths and note positions in quarter notes
    regardless of the meter, so the denominator has to be folded in: 6/8 is six eighth
    notes, which is three of Live's beats, not six.
    """
    return numerator * 4.0 / denominator


def read_meter(client):
    """Read the session's time signature. Exits with a message rather than guessing."""
    try:
        sig = client.get_time_signature()
    except TimeoutError as e:
        print(f"ERROR: could not read the time signature: {e}")
        print("       Bar numbers are derived from it, so this run would produce wrong")
        print("       ones silently. Refusing to guess 4/4.")
        sys.exit(1)

    if sig is None:
        print("ERROR: AbletonOSC returned no time signature.")
        print("       Bar numbers are derived from it, so this run would produce wrong")
        print("       ones silently. Refusing to guess 4/4.")
        sys.exit(1)

    num, den = sig
    if num < 1 or den < 1 or (den & (den - 1)) != 0:
        print(f"ERROR: session reports an unusable time signature: {num}/{den}.")
        print("       Expected a positive numerator and a power-of-two denominator.")
        sys.exit(1)

    bpb = beats_per_bar(num, den)
    print(f"Time signature: {num}/{den} ({bpb:g} beats per bar)")

    if (num, den) != (4, 4):
        print()
        print("  !! NOT 4/4. Bar numbers below are derived from this one global meter.")
        print("  !! Live does not expose arrangement time-signature changes over OSC, so")
        print("  !! if the meter changes anywhere in the song, every bar number after the")
        print("  !! change is wrong. Check structure.md against the arrangement before")
        print("  !! quoting any bar number from this pull.")
        print()

    return num, den, bpb


# Track name → parts category heuristic. Substring match, first hit wins. A track that
# matches nothing is reported at the end of the run, not quietly filed. Track naming is
# per-session, so treat this as a starting point and add the keywords your own sessions
# use.
CATEGORY_MAP = {
    "drum": "drums",
    "kick": "drums",
    "snare": "drums",
    "hi-hat": "drums",
    # Percussion is its own category, matching the rhythm agent's scope. Position
    # matters here: first hit wins, so "Snare Perc" is a snare and stays in drums,
    # while "Splice Perc" is percussion because "perc" is checked before "splice".
    "perc": "percussion",
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

    # Role words, and they must stay last. Every key above names an instrument or a
    # sample source; these name what a part *does*, which is orthogonal to what plays
    # it. Because first hit wins, keeping them at the end means the instrument noun
    # decides: "Harmony Guitar" is a guitar, "Melody Bass" is a bass. Move one of these
    # up and that stops being true.
    #
    # "stack" routes to vocals, not fx: in the one session this was checked against,
    # the Pre-Chorus Stack track held note tables byte-identical to the VocalSynth
    # track, so a stack is a vocal layer.
    #
    # These say nothing about whether a part is programmed or converted. A track named
    # for its role is if anything *more* likely to be audio-to-MIDI output, so the
    # conversion check below is what keeps that visible once these have filed it.
    "melody": "keys",
    "harmony": "vocals",
    "stack": "vocals",
}


# --- Programmed MIDI vs audio-to-MIDI conversion output ---------------------
#
# CLAUDE.md: conversion tracks mixed into analysis produce confident wrong answers
# about a part. The tell is timing. Programmed notes land on a grid; pitch detection
# returns whatever it measured, so starts like 15.0028 and durations like 0.7930.
#
# A 1/24-beat grid admits 32nd notes and triplets, so ordinary programming, swing and
# humanisation still count as on-grid. Measured over one real session the two
# populations separated cleanly: programmed parts ran 0–34% off-grid, conversion
# output 64–100%, with nothing in between.
GRID = 1.0 / 24.0
GRID_TOLERANCE_BEATS = 1e-3
CONVERTED_THRESHOLD = 0.5


def _is_offgrid(value):
    steps = (value / GRID) % 1.0
    return min(steps, 1.0 - steps) * GRID > GRID_TOLERANCE_BEATS


def offgrid_counts(notes_flat):
    """Return (off_grid_notes, total_notes) so callers can aggregate across clips."""
    total = len(notes_flat) // 5
    off = sum(1 for i in range(0, len(notes_flat), 5)
              if _is_offgrid(float(notes_flat[i + 1])) or _is_offgrid(float(notes_flat[i + 2])))
    return off, total


def offgrid_fraction(notes_flat):
    """Fraction of notes whose start or duration sits off the timing grid.

    Returns 0.0 for an empty note list. This is a measurement, not a verdict: a
    deliberately loose performance played in live will score high too, which is why
    the number goes into the frontmatter next to the flag rather than instead of it.
    """
    off, total = offgrid_counts(notes_flat)
    return off / total if total else 0.0


UNCLASSIFIED_CATEGORY = "fx"


def infer_category(track_name):
    """Return the parts category for a track name, or None if nothing matched.

    None rather than a fallback on purpose. The caller files unmatched tracks under
    parts/fx because they have to go somewhere, but it also collects them and reports
    them at the end: an unmatched track landing in parts/fx is indistinguishable from a
    real FX track once it is on disk, and a whole part quietly filed as FX is the kind
    of thing nobody notices until an agent reads the wrong folder.
    """
    lower = track_name.lower()
    for keyword, cat in CATEGORY_MAP.items():
        if keyword in lower:
            return cat
    return None


def slugify(name):
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def beats_to_bars(beats, bpb):
    bar = int(beats / bpb) + 1
    beat = (beats % bpb) + 1
    return f"bar {bar} beat {beat:.2f}"


def clip_position_slug(beats, bpb):
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


def write_part_file(path, track_name, track_index, clip_start, clip_length, notes_flat,
                    meter, bpb, category_inferred=True):
    """Write a markdown part file from a flat note list.

    meter is (numerator, denominator) as read from the session, and it goes into the
    frontmatter alongside every derived bar number so a reader can check what the bars
    were computed from instead of assuming 4/4.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)

    note_rows = []
    for i in range(0, len(notes_flat), 5):
        pitch = int(notes_flat[i])
        start = float(notes_flat[i + 1])
        dur = float(notes_flat[i + 2])
        vel = int(notes_flat[i + 3])
        mute = int(notes_flat[i + 4])
        note_rows.append(f"| {pitch} | {start:.4f} | {dur:.4f} | {vel} | {mute} |")

    offgrid = offgrid_fraction(notes_flat)
    converted = offgrid >= CONVERTED_THRESHOLD

    # Repeated in the body, not just the frontmatter. Frontmatter gets skimmed, and
    # reading conversion output as if it were a performance is the specific mistake
    # this is here to prevent.
    warning = ""
    if converted:
        warning = (
            f"\n> **Audio-to-MIDI conversion output, probably.** {offgrid * 100:.0f}% of "
            f"these notes sit off\n> the timing grid, which is what pitch detection "
            f"produces and programming does not.\n> Do not read these timings or "
            f"velocities as a performance, and do not \"correct\" them.\n"
        )

    header = f"""---
track: {track_name}
track_index: {track_index}
time_signature: {meter[0]}/{meter[1]}
beats_per_bar: {bpb:g}
clip_start_beats: {clip_start:.4f}
clip_length_beats: {clip_length:.4f}
clip_start_position: {beats_to_bars(clip_start, bpb)}
clip_length_bars: {clip_length / bpb:.2f}
category_inferred: {str(bool(category_inferred)).lower()}
offgrid_fraction: {offgrid:.3f}
likely_converted: {str(converted).lower()}
pulled: {time.strftime("%Y-%m-%d")}
---

# {track_name} — {beats_to_bars(clip_start, bpb)}
{warning}
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
    unclassified = []
    offgrid_by_track = {}   # track name -> [off_grid_notes, total_notes]

    try:
        tempo = client.get_tempo()
        if tempo is None:
            print("ERROR: could not read tempo. Is AbletonOSC running?")
            sys.exit(1)
        print(f"Connected — tempo: {tempo:.1f} BPM")

        meter = read_meter(client)[:2]
        bpb = beats_per_bar(*meter)

        track_names = client.get_track_names()
        print(f"Session has {len(track_names)} tracks.")

        for track_index, track_name in track_names:
            if not track_name.strip():
                continue

            print(f"\nTrack {track_index}: {track_name}")

            # --- Notes (arrangement clips) ---
            if not devices_only:
                category = infer_category(track_name)
                category_inferred = category is not None
                if not category_inferred:
                    category = UNCLASSIFIED_CATEGORY
                    unclassified.append((track_index, track_name))
                    print(f"  UNCLASSIFIED: no CATEGORY_MAP keyword matches this name. "
                          f"Filing under parts/{category}/ as a fallback.")
                parts_dir = os.path.join(song_dir, "parts", category)
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
                    filename = f"{clip_slug}-{clip_position_slug(clip_start, bpb)}.md"
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
                                    clip_start, clip_length, notes,
                                    meter, bpb, category_inferred)

                    off, total = offgrid_counts(notes)
                    tally = offgrid_by_track.setdefault(track_name, [0, 0])
                    tally[0] += off
                    tally[1] += total

            # --- Device chain ---
            if not tracks_only:
                chain_dir = os.path.join(song_dir, "chain")
                chain_path = os.path.join(chain_dir, f"{slugify(track_name)}.md")
                write_chain_file(chain_path, track_name, track_index, client)

    finally:
        client.close()

    print(f"\nDone. Files written to {display_path(song_dir)}/")
    report_unclassified(unclassified)
    report_converted(offgrid_by_track)


def report_converted(offgrid_by_track):
    """Name the tracks whose note timing reads as audio-to-MIDI conversion output.

    These are filed under a real category like any other part, so nothing about their
    location says what they are. CLAUDE.md's rule is that mixing them into analysis
    produces confident wrong answers, and that only holds if the pull says which ones
    they are. Their part files carry `likely_converted: true` and the measurement.
    """
    flagged = []
    for track_name, (off, total) in offgrid_by_track.items():
        if total and off / total >= CONVERTED_THRESHOLD:
            flagged.append((off / total, track_name))
    if not flagged:
        return

    flagged.sort(reverse=True)
    print()
    print(f"{len(flagged)} track(s) read as audio-to-MIDI conversion output, not programmed "
          f"or performed MIDI:")
    for frac, track_name in flagged:
        print(f"  - {track_name}  ({frac * 100:.0f}% of notes off the timing grid)")
    print()
    print("Their timings and velocities are pitch-detection results. Do not analyse them")
    print("as a performance, and do not \"correct\" them. A loose live performance can")
    print("score this way too, so confirm against the session before treating one as")
    print("converted.")


def report_unclassified(unclassified):
    """Print the tracks no CATEGORY_MAP keyword matched.

    These were filed under parts/fx because the files have to go somewhere, but the
    fallback is a guess and it is invisible once the run finishes: a bass DI named
    "DI 2" ends up alongside real FX and the rhythm or harmony agent never looks there.
    Naming them here is what makes the guess reviewable.
    """
    if not unclassified:
        return

    print()
    print(f"{len(unclassified)} track(s) matched no CATEGORY_MAP keyword and were filed "
          f"under parts/{UNCLASSIFIED_CATEGORY}/ by fallback,")
    print("not because they are FX. Their part files carry `category_inferred: false`.")
    for track_index, track_name in unclassified:
        print(f"  - track {track_index}: {track_name}")
    print()
    print("Either rename the track in the session, or add a keyword for it to")
    print(f"CATEGORY_MAP in {display_path(os.path.abspath(__file__))}, then re-run.")
    print(f"Move or delete anything already misfiled in parts/{UNCLASSIFIED_CATEGORY}/ — "
          f"a re-run adds the correct file but does not remove the old one.")


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
