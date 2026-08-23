"""
push.py — write MIDI notes from a part file into an Ableton Session clip.

Usage:
  python3 bridge/push.py --part <songs-dir>/<song>/parts/bass/verse1-bass.md
  python3 bridge/push.py --part <song>/parts/drums/chorus1-drums.md --track 2 --slot 0

A --part path is used as given when it exists. A relative path that does not is
retried under the songs directory, resolved by bridge/songpath.py: --songs-dir,
then $ABLETON_SONGS_DIR, then ./songs, then <bridge-repo>/songs. Part files do not
have to live in the same repo as these scripts.

Uses AbletonMCP (TCP port 9877) for note writes because it has the most
reliable note-write interface. The clip lands in a Session slot.
Drag it to the Arrangement manually at the correct bar position.

Requires AbletonMCP running in Ableton (MIDI Remote Script, port 9877).
"""

import argparse
import json
import os
import re
import socket
import sys
import time

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BRIDGE_DIR)

from songpath import add_songs_dir_arg, resolve_songs_dir, display_path, SongPathError

ABLETON_MCP_HOST = "127.0.0.1"
ABLETON_MCP_PORT = 9877
DEFAULT_TIMEOUT = 10.0


def mcp_call(tool_name, args):
    """Send a single tool call to AbletonMCP and return the result."""
    payload = json.dumps({
        "tool": tool_name,
        "arguments": args
    }) + "\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(DEFAULT_TIMEOUT)
    try:
        sock.connect((ABLETON_MCP_HOST, ABLETON_MCP_PORT))
        sock.sendall(payload.encode("utf-8"))
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if response.endswith(b"\n"):
                break
        return json.loads(response.decode("utf-8"))
    except ConnectionRefusedError:
        print(f"ERROR: Cannot connect to AbletonMCP on port {ABLETON_MCP_PORT}.")
        print("Is AbletonMCP running in Ableton?")
        sys.exit(1)
    finally:
        sock.close()


def parse_part_file(path):
    """Read a part markdown file. Returns (meta, notes)."""
    with open(path) as f:
        content = f.read()

    # Parse YAML frontmatter
    meta = {}
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        import yaml
        meta = yaml.safe_load(fm_match.group(1)) or {}

    # Parse note table
    notes = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        try:
            pitch = int(parts[0])
            start = float(parts[1])
            dur = float(parts[2])
            vel = int(parts[3])
            mute = int(parts[4])
            notes.append({
                "pitch": pitch,
                "start_time": start,
                "duration": dur,
                "velocity": vel,
                "mute": bool(mute)
            })
        except ValueError:
            continue  # header row or malformed line

    return meta, notes


def locate_part(part_path, songs_dir=None):
    """Return the part file's real path, or exit with what was tried.

    A path that exists as given always wins, so absolute paths and paths typed from
    the track repo itself behave exactly as before. Only a relative path that misses
    is retried under the songs directory, which is what makes `--part <song>/parts/...`
    work from a checkout that holds the scripts but not the songs.
    """
    if os.path.exists(part_path):
        return part_path

    tried = [part_path]
    if not os.path.isabs(part_path):
        try:
            candidate = os.path.join(resolve_songs_dir(songs_dir), part_path)
        except SongPathError as e:
            print(f"ERROR: Part file not found: {part_path}")
            print(f"  Also could not check the songs directory: {e}")
            sys.exit(1)
        if os.path.exists(candidate):
            return candidate
        tried.append(candidate)

    print("ERROR: Part file not found. Tried:")
    for path in tried:
        print(f"  {path}")
    sys.exit(1)


def push(part_path, track_index_override=None, slot_override=None, songs_dir=None):
    part_path = locate_part(part_path, songs_dir)
    print(f"Part file: {display_path(part_path)}")

    meta, notes = parse_part_file(part_path)

    if not notes:
        print("ERROR: No notes found in part file.")
        sys.exit(1)

    track_index = track_index_override if track_index_override is not None else meta.get("track_index", 0)
    slot = slot_override if slot_override is not None else meta.get("slot", 0)
    clip_length = meta.get("clip_length_beats", max(n["start_time"] + n["duration"] for n in notes))
    track_name = meta.get("track", f"Track {track_index}")

    print(f"Pushing {len(notes)} notes to '{track_name}' (index {track_index}), slot {slot}")
    print(f"Clip length: {clip_length:.2f} beats")

    # 1. Create clip
    print("  create_clip...")
    result = mcp_call("create_clip", {
        "track_index": track_index,
        "clip_index": slot,
        "length": clip_length
    })
    print(f"  → {result}")
    time.sleep(0.2)

    # 2. Add notes
    print(f"  add_notes_to_clip ({len(notes)} notes)...")
    result = mcp_call("add_notes_to_clip", {
        "track_index": track_index,
        "clip_index": slot,
        "notes": notes
    })
    print(f"  → {result}")
    time.sleep(0.1)

    # 3. Name the clip
    clip_name = os.path.splitext(os.path.basename(part_path))[0]
    print(f"  set_clip_name: '{clip_name}'...")
    result = mcp_call("set_clip_name", {
        "track_index": track_index,
        "clip_index": slot,
        "name": clip_name
    })
    print(f"  → {result}")

    print(f"\nDone. Clip '{clip_name}' is in Session slot {slot} on track {track_index}.")
    print("Drag it to the Arrangement at the correct bar position.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push MIDI notes to Ableton Session clip")
    parser.add_argument("--part", required=True, help="Path to the part .md file")
    add_songs_dir_arg(parser)
    parser.add_argument("--track", type=int, default=None, help="Override track index (0-based)")
    parser.add_argument("--slot", type=int, default=None, help="Override clip slot index (0-based)")
    args = parser.parse_args()

    push(args.part, track_index_override=args.track, slot_override=args.slot,
         songs_dir=args.songs_dir)
