# /device

Read or set a device parameter by name via AbletonOSC.

## Usage

```
/device "<Track>" "<Device>" "<Param>"
/device "<Track>" "<Device>" "<Param>" 120
```

Arguments: `<track name>` `<device name>` `<param name>` `[value]`

Without a value it reads and returns the current value with its range. With a value it
sets the parameter and confirms what actually landed.

## Script

```bash
# Read
python3 bridge/device.py --track "<Track>" --device "<Device>" --param "<Param>"

# Set (raw value, range-checked)
python3 bridge/device.py --track "<Track>" --device "<Device>" --param "<Param>" --set 120

# List every param on a device, raw and UI side by side
python3 bridge/device.py --track "<Track>" --device "<Device>" --list-params

# Snapshot a whole chain into the song's chain/ folder, in UI units
python3 bridge/device.py --track "<Track>" --snapshot --song <name>
```

## Notes

- Track and device names are case-sensitive. A fuzzy substring fallback exists and reports
  when it fires, so read that line rather than assuming an exact match.
- Run `--list-params` on an unfamiliar device before setting anything by name.
- **UI units come from the device itself** through Live's `str_for_value`, so they match
  the plugin display exactly.
- **`--set` takes a raw value, not UI units.** Raw scaling is per-parameter, so there is
  no general conversion. `--list-params` shows both columns; pick the raw value from
  there. Out-of-range writes are refused rather than silently clamped.
- If the printed before and after are identical, the write did not take effect. The
  parameter is automated, quantized to steps, or not writable.
- Some plugins publish almost nothing. A device showing only `Device On`, or generic
  `Param 1..N`, cannot be configured this way. Say so instead of guessing.

## Where documented values live

Per-track parameter snapshots go in the song's `chain/<track>.md`. Song-specific known-good
values belong in the track repo, not here.
