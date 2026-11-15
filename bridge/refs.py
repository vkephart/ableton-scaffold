#!/usr/bin/env python3
"""Does anything in the set play this file? Ask before deleting audio.

Scans the open set over AbletonOSC (every Arrangement audio clip, every Session clip)
and, with --als-dir, every saved set under a folder (an .als is gzip XML) for file
paths containing a piece of text. Read-only: nothing in the set is touched.

    python3 bridge/refs.py "CAP-" --als-dir "<project folder>"

Exit status 0 when nothing references the text, 1 when something does, 2 when part of
the scan got no reply (so the answer is not certain).

What it does not see: samples loaded inside instruments (Simpler, Sampler, drum racks,
third-party samplers), and Live's undo history. A saved set is the state at its last
save, so the open-set scan is the one that counts for work done since.
"""
import argparse
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osc_client import OscClient  # noqa: E402


def scan_open_set(text):
    client = OscClient()
    hits, unanswered, counts = [], [], {"arrangement_audio": 0, "session": 0}

    def ask(address, *args, timeout=4):
        try:
            return list(client.query(address, address, *args, timeout=timeout))
        except Exception:
            return None

    try:
        names = ask("/live/song/get/track_names")
        if names is None:
            raise SystemExit("no reply from Live: is the set open and AbletonOSC loaded?")
        for index, name in enumerate(names):
            clips = ask("/live/arrangement_clip/get/clips", index)
            if clips is None:
                unanswered.append((name, "arrangement clip list"))
            else:
                for start in clips[1::2]:
                    audio = ask("/live/arrangement_clip/get/audio", index, float(start))
                    if audio is None:
                        unanswered.append((name, "arrangement clip at beat %s" % start))
                    elif len(audio) > 4:  # an audio clip; a MIDI clip replies with 3 items
                        counts["arrangement_audio"] += 1
                        if text in str(audio[4]):
                            hits.append((name, "Arrangement, beat %s" % start, str(audio[4])))
            slots = ask("/live/track/get/clips/name", index)
            if slots is None:
                unanswered.append((name, "session slots"))
                continue
            for slot, clip_name in enumerate(slots[1:]):
                if clip_name in (None, ""):
                    continue
                counts["session"] += 1
                path = ask("/live/clip/get/file_path", index, slot, timeout=2)
                if path is None:
                    # A MIDI clip does reply, with an empty value, so silence is a timeout.
                    unanswered.append((name, "session slot %d" % slot))
                elif text in str(path[-1]):
                    hits.append((name, "Session slot %d" % slot, str(path[-1])))
        return len(names), counts, hits, unanswered
    finally:
        client.close()


def scan_saved_sets(text, folder):
    needle = text.encode("utf-8")
    found, read = [], 0
    for root, _dirs, files in os.walk(folder):
        for filename in files:
            if not filename.endswith(".als"):
                continue
            path = os.path.join(root, filename)
            try:
                with gzip.open(path, "rb") as handle:
                    count = handle.read().count(needle)
            except OSError:
                continue
            read += 1
            if count:
                found.append((path, count))
    return read, found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("text", help="piece of the file name or path to look for")
    parser.add_argument("--als-dir", help="also search every .als under this folder")
    parser.add_argument("--no-live", action="store_true", help="skip the open set")
    args = parser.parse_args()

    status = 0
    if not args.no_live:
        tracks, counts, hits, unanswered = scan_open_set(args.text)
        print("open set: %d tracks, %d Arrangement audio clips, %d Session clips read"
              % (tracks, counts["arrangement_audio"], counts["session"]))
        for name, where, path in hits:
            print("  PLAYS IT: %s, %s: %s" % (name, where, path))
        for name, what in unanswered:
            print("  no reply: %s, %s" % (name, what))
        if hits:
            status = 1
        elif unanswered:
            status = 2
    if args.als_dir:
        read, found = scan_saved_sets(args.text, args.als_dir)
        print("saved sets: %d read under %s" % (read, args.als_dir))
        for path, count in found:
            print("  MENTIONS IT %d times: %s" % (count, path))
        if found:
            status = 1
    print({0: "nothing references %r" % args.text,
           1: "%r is referenced: do not delete" % args.text,
           2: "not certain: part of the open set did not answer"}[status])
    return status


if __name__ == "__main__":
    sys.exit(main())
