"""
device.py — read and set VST parameters by name via AbletonOSC.

Usage:
  python3 bridge/device.py --track "<Track Name>" --device "<Device Name>" --param "<Param>"
  python3 bridge/device.py --track "<Track Name>" --device "<Device Name>" --param "<Param>" --set 120
  python3 bridge/device.py --track "<Track Name>" --device "<Device Name>" --list-params
  python3 bridge/device.py --track "<Track Name>" --snapshot --song <name>

UI units come from Live's own str_for_value() via /live/device/get/parameter/value_string,
so they are exactly what the plugin UI displays. Do not infer units from the raw value:
raw scaling is per-parameter, not per-device. On a single Gate, Threshold reads 0.1825
for "-36.6 dB" while Floor reads -40.0 for "-40.0 dB". An earlier version of this file
guessed at conversion formulas in a KNOWN_CONVERSIONS table and printed the guesses as
if they were real; that table has been removed.

Cost: value_string is one round trip per parameter, so it is used for single-device
reads and snapshots, never for a whole-session pull.

Notes:
  - Track names are case-sensitive and must match Ableton exactly.
  - --snapshot writes to <songs-dir>/<song>/chain/<track-slug>.md. The songs directory
    is resolved by bridge/songpath.py: --songs-dir, then $ABLETON_SONGS_DIR, then
    ./songs, then <bridge-repo>/songs.
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

def slugify(name):
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def resolve_track(client, track_name):
    track_names = client.get_track_names()
    for idx, name in track_names:
        if name == track_name:
            return idx
    # Fuzzy fallback
    for idx, name in track_names:
        if track_name.lower() in name.lower():
            print(f"  (fuzzy match: '{name}' for '{track_name}')")
            return idx
    return None


def resolve_device(client, track_index, device_name):
    device_names = client.get_device_names(track_index)
    for di, name in enumerate(device_names):
        if name == device_name:
            return di, name
    for di, name in enumerate(device_names):
        if device_name.lower() in name.lower():
            print(f"  (fuzzy match: '{name}' for '{device_name}')")
            return di, name
    return None, None


def list_params(client, track_index, device_index, device_name):
    param_names = client.get_device_param_names(track_index, device_index)
    param_values = client.get_device_param_values(track_index, device_index)
    if not param_names:
        print("No parameters returned.")
        return
    print(f"\n{device_name} parameters:")
    print(f"{'#':>4}  {'Parameter':<40}  {'Raw':>10}  UI value")
    print("-" * 78)
    for i, (name, raw) in enumerate(zip(param_names, param_values)):
        ui = client.get_device_param_value_string(track_index, device_index, i)
        print(f"{i:>4}  {name:<40}  {raw:>10.4f}  {ui if ui is not None else ''}")


def get_param(client, track_index, device_index, device_name, param_name):
    param_names = client.get_device_param_names(track_index, device_index)
    param_values = client.get_device_param_values(track_index, device_index)
    for pi, (pname, pval) in enumerate(zip(param_names, param_values)):
        if pname.lower() == param_name.lower() or param_name.lower() in pname.lower():
            ui = client.get_device_param_value_string(track_index, device_index, pi)
            ui_part = f"  ({ui})" if ui is not None else ""
            print(f"{pname}: {pval:.4f} raw{ui_part}")
            return pval, pname
    print(f"Parameter '{param_name}' not found on {device_name}.")
    return None, None


def set_param(client, track_index, device_index, device_name, param_name, value):
    """Set a parameter to a raw Live API value, range-checked, and verify the result.

    The value is raw, not UI units. There is no reliable UI-to-raw conversion: each
    parameter defines its own scale, so the only safe check is the parameter's own
    min/max. Live silently clamps out-of-range writes, so this refuses them instead,
    then reads the value back and prints what the plugin actually displays.
    """
    param_names = client.get_device_param_names(track_index, device_index)
    for pi, pname in enumerate(param_names):
        if pname.lower() == param_name.lower() or param_name.lower() in pname.lower():
            raw = float(value)

            mins = client.get_device_param_min(track_index, device_index)
            maxes = client.get_device_param_max(track_index, device_index)
            before = client.get_device_param_value_string(track_index, device_index, pi)

            if pi < len(mins) and pi < len(maxes):
                pmin, pmax = mins[pi], maxes[pi]
                if not (pmin <= raw <= pmax):
                    print(f"ERROR: {raw} is outside {pname}'s range [{pmin:.4f}, {pmax:.4f}].")
                    print(f"  {pname} is currently {before}. Nothing was changed.")
                    print("  Pass a raw value in that range; --list-params shows raw and UI side by side.")
                    return

            client.send("/live/device/set/parameter/value", track_index, device_index, pi, raw)
            time.sleep(0.1)  # let Live apply the change before reading it back
            after = client.get_device_param_value_string(track_index, device_index, pi)

            print(f"Set {pname}: {before} → {after}   (raw {raw:.4f})")
            if before == after:
                print("  NOTE: the displayed value did not change. The parameter may be "
                      "automated, quantized to steps, or the write may not have applied.")
            return
    print(f"Parameter '{param_name}' not found on {device_name}.")


def snapshot(client, track_index, track_name, song, songs_dir=None):
    song_dir = resolve_song_dir(song, songs_dir)
    chain_dir = os.path.join(song_dir, "chain")
    os.makedirs(chain_dir, exist_ok=True)
    path = os.path.join(chain_dir, f"{slugify(track_name)}.md")

    device_names = client.get_device_names(track_index)
    if not device_names:
        print("No devices found.")
        return

    lines = [
        f"# {track_name} — device chain",
        f"",
        f"Pulled: {time.strftime('%Y-%m-%d')}",
        f"",
        "UI values come from the device itself (Live's str_for_value), so they match the",
        "plugin UI. Raw values use each parameter's own scale and are not comparable",
        "across parameters. Quote the UI column, not the raw one.",
        f"",
    ]

    for di, dname in enumerate(device_names):
        lines.append(f"## {di + 1}. {dname}")
        lines.append("")
        param_names = client.get_device_param_names(track_index, di)
        param_values = client.get_device_param_values(track_index, di)
        if param_names and param_values:
            lines.append("| Parameter | Raw | UI value |")
            lines.append("|-----------|-----|----------|")
            for pi, (pname, pval) in enumerate(zip(param_names, param_values)):
                ui = client.get_device_param_value_string(track_index, di, pi)
                lines.append(f"| {pname} | {pval:.4f} | {ui if ui is not None else ''} |")
        else:
            lines.append("*(no params returned)*")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {display_path(path)}")


def main():
    parser = argparse.ArgumentParser(description="Read/set AbletonOSC device parameters")
    parser.add_argument("--track", required=True, help="Track name (case-sensitive)")
    parser.add_argument("--device", help="Device name (case-sensitive)")
    parser.add_argument("--param", help="Parameter name")
    parser.add_argument("--set", metavar="VALUE",
                        help="Raw Live API value to set. Not UI units; see --list-params "
                             "for the raw and UI columns side by side.")
    parser.add_argument("--list-params", action="store_true", help="List all params on the device")
    parser.add_argument("--snapshot", action="store_true", help="Snapshot full chain to chain/ file")
    parser.add_argument("--song", help="Song name (for --snapshot)")
    add_songs_dir_arg(parser)
    args = parser.parse_args()

    client = OscClient()

    try:
        track_index = resolve_track(client, args.track)
        if track_index is None:
            print(f"ERROR: Track '{args.track}' not found. Check spelling (case-sensitive).")
            sys.exit(1)

        if args.snapshot:
            if not args.song:
                print("ERROR: --snapshot requires --song")
                sys.exit(1)
            try:
                snapshot(client, track_index, args.track, args.song, args.songs_dir)
            except SongPathError as e:
                print(f"ERROR: {e}")
                sys.exit(1)
            return

        if not args.device:
            print("ERROR: --device is required for param operations.")
            sys.exit(1)

        device_index, device_name = resolve_device(client, track_index, args.device)
        if device_index is None:
            print(f"ERROR: Device '{args.device}' not found on '{args.track}'.")
            sys.exit(1)

        if args.list_params:
            list_params(client, track_index, device_index, device_name)
            return

        if args.param and args.set is not None:
            set_param(client, track_index, device_index, device_name, args.param, args.set)
        elif args.param:
            get_param(client, track_index, device_index, device_name, args.param)
        else:
            list_params(client, track_index, device_index, device_name)

    finally:
        client.close()


if __name__ == "__main__":
    main()
