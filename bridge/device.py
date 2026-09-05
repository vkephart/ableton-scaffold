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
  - --track also accepts a return track name. Regular tracks are searched first, then
    returns, through the abletonosc-ext return handler. Everything below works the same
    on either; the snapshot file name carries a "return-" prefix so the two never collide.
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


class Target:
    """A regular track or a return track, behind one interface.

    Return tracks live outside song.tracks, so AbletonOSC reaches them through a
    different address family. Everything in this file that reads or writes a device
    goes through here so it does not have to know which family it is talking to.
    """

    def __init__(self, client, kind, index, name):
        self.client = client
        self.kind = kind          # "track" or "return"
        self.index = index
        self.name = name

    @property
    def label(self):
        return "return '%s'" % self.name if self.kind == "return" else "track '%s'" % self.name

    def device_names(self):
        if self.kind == "return":
            return self.client.get_return_device_names(self.index)
        return self.client.get_device_names(self.index)

    def param_names(self, di):
        if self.kind == "return":
            return self.client.get_return_device_param_names(self.index, di)
        return self.client.get_device_param_names(self.index, di)

    def param_values(self, di):
        if self.kind == "return":
            return self.client.get_return_device_param_values(self.index, di)
        return self.client.get_device_param_values(self.index, di)

    def param_min(self, di):
        if self.kind == "return":
            return self.client.get_return_device_param_min(self.index, di)
        return self.client.get_device_param_min(self.index, di)

    def param_max(self, di):
        if self.kind == "return":
            return self.client.get_return_device_param_max(self.index, di)
        return self.client.get_device_param_max(self.index, di)

    def value_string(self, di, pi):
        if self.kind == "return":
            return self.client.get_return_device_param_value_string(self.index, di, pi)
        return self.client.get_device_param_value_string(self.index, di, pi)

    def set_param(self, di, pi, raw):
        """Write a raw value and return the display string afterwards."""
        if self.kind == "return":
            _, ui, status = self.client.set_return_device_param(self.index, di, pi, raw)
            if status != "ok":
                print(f"  handler reported: {status}")
            return ui
        self.client.send("/live/device/set/parameter/value", self.index, di, pi, raw)
        time.sleep(0.1)  # let Live apply the change before reading it back
        return self.client.get_device_param_value_string(self.index, di, pi)


def _match_name(pairs, wanted):
    for idx, name in pairs:
        if name == wanted:
            return idx, name, False
    for idx, name in pairs:
        if wanted.lower() in name.lower():
            return idx, name, True
    return None, None, False


def resolve_target(client, track_name):
    """Find a regular track by name, then a return track. Exact match beats fuzzy."""
    idx, name, fuzzy = _match_name(client.get_track_names(), track_name)
    if idx is not None:
        if fuzzy:
            print(f"  (fuzzy match: '{name}' for '{track_name}')")
        return Target(client, "track", idx, name)
    try:
        returns = client.get_return_names()
    except TimeoutError:
        returns = []   # extension not installed; returns are simply invisible
    idx, name, fuzzy = _match_name(returns, track_name)
    if idx is not None:
        if fuzzy:
            print(f"  (fuzzy match: return '{name}' for '{track_name}')")
        return Target(client, "return", idx, name)
    return None


def resolve_device(target, device_name):
    device_names = target.device_names()
    for di, name in enumerate(device_names):
        if name == device_name:
            return di, name
    for di, name in enumerate(device_names):
        if device_name.lower() in name.lower():
            print(f"  (fuzzy match: '{name}' for '{device_name}')")
            return di, name
    return None, None


def list_params(target, device_index, device_name):
    param_names = target.param_names(device_index)
    param_values = target.param_values(device_index)
    if not param_names:
        print("No parameters returned.")
        return
    print(f"\n{device_name} parameters:")
    print(f"{'#':>4}  {'Parameter':<40}  {'Raw':>10}  UI value")
    print("-" * 78)
    for i, (name, raw) in enumerate(zip(param_names, param_values)):
        ui = target.value_string(device_index, i)
        print(f"{i:>4}  {name:<40}  {raw:>10.4f}  {ui if ui is not None else ''}")


def get_param(target, device_index, device_name, param_name):
    param_names = target.param_names(device_index)
    param_values = target.param_values(device_index)
    for pi, (pname, pval) in enumerate(zip(param_names, param_values)):
        if pname.lower() == param_name.lower() or param_name.lower() in pname.lower():
            ui = target.value_string(device_index, pi)
            ui_part = f"  ({ui})" if ui is not None else ""
            print(f"{pname}: {pval:.4f} raw{ui_part}")
            return pval, pname
    print(f"Parameter '{param_name}' not found on {device_name}.")
    return None, None


def set_param(target, device_index, device_name, param_name, value):
    """Set a parameter to a raw Live API value, range-checked, and verify the result.

    The value is raw, not UI units. There is no reliable UI-to-raw conversion: each
    parameter defines its own scale, so the only safe check is the parameter's own
    min/max. Live silently clamps out-of-range writes, so this refuses them instead,
    then reads the value back and prints what the plugin actually displays.
    """
    param_names = target.param_names(device_index)
    for pi, pname in enumerate(param_names):
        if pname.lower() == param_name.lower() or param_name.lower() in pname.lower():
            raw = float(value)

            mins = target.param_min(device_index)
            maxes = target.param_max(device_index)
            before = target.value_string(device_index, pi)

            if pi < len(mins) and pi < len(maxes):
                pmin, pmax = mins[pi], maxes[pi]
                if not (pmin <= raw <= pmax):
                    print(f"ERROR: {raw} is outside {pname}'s range [{pmin:.4f}, {pmax:.4f}].")
                    print(f"  {pname} is currently {before}. Nothing was changed.")
                    print("  Pass a raw value in that range; --list-params shows raw and UI side by side.")
                    return

            after = target.set_param(device_index, pi, raw)

            print(f"Set {pname}: {before} → {after}   (raw {raw:.4f})")
            if before == after:
                print("  NOTE: the displayed value did not change. The parameter may be "
                      "automated, quantized to steps, or the write may not have applied.")
            return
    print(f"Parameter '{param_name}' not found on {device_name}.")


def snapshot(target, song, songs_dir=None):
    song_dir = resolve_song_dir(song, songs_dir)
    chain_dir = os.path.join(song_dir, "chain")
    os.makedirs(chain_dir, exist_ok=True)
    prefix = "return-" if target.kind == "return" else ""
    path = os.path.join(chain_dir, f"{prefix}{slugify(target.name)}.md")
    track_name = target.name

    device_names = target.device_names()
    if not device_names:
        print("No devices found.")
        return

    lines = [
        f"# {track_name}: device chain" + (" (return track)" if target.kind == "return" else ""),
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
        param_names = target.param_names(di)
        param_values = target.param_values(di)
        if param_names and param_values:
            lines.append("| Parameter | Raw | UI value |")
            lines.append("|-----------|-----|----------|")
            for pi, (pname, pval) in enumerate(zip(param_names, param_values)):
                ui = target.value_string(di, pi)
                lines.append(f"| {pname} | {pval:.4f} | {ui if ui is not None else ''} |")
        else:
            lines.append("*(no params returned)*")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {display_path(path)}")


def main():
    parser = argparse.ArgumentParser(description="Read/set AbletonOSC device parameters")
    parser.add_argument("--track", required=True,
                        help="Track or return track name (case-sensitive). Tracks are "
                             "searched first, then returns.")
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
        target = resolve_target(client, args.track)
        if target is None:
            print(f"ERROR: Track '{args.track}' not found among tracks or returns. "
                  "Check spelling (case-sensitive).")
            sys.exit(1)

        if args.snapshot:
            if not args.song:
                print("ERROR: --snapshot requires --song")
                sys.exit(1)
            try:
                snapshot(target, args.song, args.songs_dir)
            except SongPathError as e:
                print(f"ERROR: {e}")
                sys.exit(1)
            return

        if not args.device:
            print("ERROR: --device is required for param operations.")
            sys.exit(1)

        device_index, device_name = resolve_device(target, args.device)
        if device_index is None:
            print(f"ERROR: Device '{args.device}' not found on {target.label}.")
            sys.exit(1)

        if args.list_params:
            list_params(target, device_index, device_name)
            return

        if args.param and args.set is not None:
            set_param(target, device_index, device_name, args.param, args.set)
        elif args.param:
            get_param(target, device_index, device_name, args.param)
        else:
            list_params(target, device_index, device_name)

    finally:
        client.close()


if __name__ == "__main__":
    main()
