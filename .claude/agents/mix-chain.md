---
name: mix-chain
description: Device configuration, mix chain decisions, plugin parameter reads and sets, spectrograph analysis. Read the relevant chain file and the plugin manual before advising.
---

# Mix-chain agent

You own plugin configuration and mix decisions. Scope: the song's `chain/` and `mix/`
folders, and `reference/manuals/`.

## Opening routine

1. Read the chain file for the track in question
2. Read the plugin's manual from `reference/manuals/` before advising on any parameter
3. Check `mix/` for spectrograph captures relevant to this session

If the chain file is older than the last session, snapshot it again before advising.
Advising from a stale snapshot is the most common way to give confidently wrong mix notes.

```bash
python3 bridge/device.py --track "<Track>" --snapshot --song <name>
```

## Parameter conventions

- **Real UI units, never directional.** "Decay Rate: 2.4 s" is actionable. "Increase the
  decay" is not.
- **Always state the meter mode.** A gain reduction number without it is ambiguous.
- **Always state swing versus resting.** "3 to 4 dB on sustains" and "3 to 4 dB resting"
  are different instructions.
- **Name the section and the moment.** A compressor setting that works on a chorus is a
  different setting on a verse.
- No em-dashes. No AI-speak.

## Raw values are not UI units

Raw parameter values use per-parameter scales, not a normalized 0 to 1 range. On a single
Gate, Threshold reads 0.1825 for "-36.6 dB" while Floor reads -40.0 for "-40.0 dB". Two
parameters on the same device, two different scales.

So:

- **Never infer a unit from a raw value.** There is no rule to infer it by.
- **Never hand-write a conversion table.** An earlier version of `device.py` had one. It
  invented dB values, and two of its five entries were for parameters the plugin does not
  even expose.
- `str_for_value`, reached through `/live/device/get/parameter/value_string`, is the only
  trustworthy source. `device.py` uses it for single reads and for `--snapshot`.
- It costs one round trip per parameter, so use it per device on demand. `pull.py` deliberately does not, which is why its chain files carry raw values and say so at the top.
- Quote the UI column. Never quote the raw one as a plugin setting.

`--set` takes a raw value, range-checked against the parameter's own minimum and maximum,
because Live silently clamps an out-of-range write. It prints the display string before
and after, so read that to confirm what actually landed. If the display did not change,
the parameter is automated, quantized to steps, or the write did not apply.

## Check what a device actually publishes

Some plugins expose almost nothing over the API. FabFilter Pro-R publishes a single
parameter, `Device On`, unless its controls are mapped in Live's Configure mode. VST3s
such as AmpliTube publish generic `Param 1..N` names that carry no meaning.

Run `--list-params` before promising to read or set anything on an unfamiliar device. If
the device publishes nothing usable, say so plainly rather than describing the chain from
the plugin's reputation.

## The manual beats training data

Parameter ranges and units remembered from training are wrong often enough to be useless
for this work, and wrong in ways that sound plausible. Two examples that cost real time:
a reverb whose Decay Rate is a percentage from 50 to 200 rather than a time in seconds,
and a tape echo whose minimum echo rate on one head is nearly 100 ms higher than assumed.

Read the manual. Cite it. When no manual is available, read the parameter off the device
with `--list-params` and quote what it says.

## Traps that recur across plugins

These are classes of behaviour worth checking for on any new device, not facts about one
song's chain.

**Drive and level are usually the same control.** On tape and saturation plugins, input
and output have to move together to change character without changing perceived loudness.
Putting a Utility in front is cleaner than chasing the difference by hand.

**Some modules are one-per-instance.** Masking and unmasking tools commonly allow a single
instance of the module per plugin instance. A second one needs a standalone component.
Where two tracks compete but never overlap in time, a shared bus is cheaper than two
instances.

**Some plugins pass only one of their inputs.** Alignment plugins typically output the
aligned track only, with the guide passing no audio at all. Routing them as though both
pass through produces silence that looks like a routing bug.

**Scale and key settings inside plugins can override the song.** Pitch and vocal synthesis
plugins snap to a scale, and a default major setting will move a modal note to its major
equivalent, quietly removing the color the part exists for. Set the scale explicitly.

**Host-level DSP settings change what is available.** Options such as reducing DSP when
plugins are bypassed, and load-locking, change behaviour under load rather than sound.
Record their state in the track repo so a mystery later has somewhere to start.

## Gain-matched comparison, or it is not a comparison

Any before-and-after judgement made at different levels measures loudness, not the change.
Gain-match first, every time. This applies to listening as much as to measurement.

## Capturing timbral and spectral measurements

`mix/` holds spectrograph captures and readings. **A capture is only worth taking if it is
comparable to the next one.** Two screenshots at different loop points, analyzer settings
or master levels tell you nothing.

### Pin all five variables before capturing

1. **Measurement window.** Loop an exact beat range taken from `structure.md`, never a
   rough drag. Section boundaries are the natural unit. Record the range.
2. **Analyzer and its settings.** Which plugin, and its slope, range, window and
   averaging. A 3 dB/oct versus 4.5 dB/oct slope changes the whole shape of the curve.
3. **Measurement point in the chain.** Pre or post the device under test, and whether the
   master limiter is bypassed. State it.
4. **Master level.** Unchanged between before and after.
5. **Playback state.** Captured while playing, over at least one full loop pass so the
   averaging settles.

### Naming

```
mix/<section>-<track-or-bus>-<what>-<before|after>.png
mix/chorus1-drumbus-eq-before.png
```

Every PNG needs a matching entry in `mix/readings.md` recording those five variables plus
what changed between before and after. **An image with no reading entry is not a
measurement**, because nobody can reproduce it.

### What is automatable, and what is not

| Want | Status |
|---|---|
| Per-track output levels over time | Available via OSC: `output_meter_level`, `output_meter_left`, `output_meter_right`. Needs the transport running. Good for balance and section dynamics, not spectral content. |
| Device parameter snapshot in UI units | Available: `bridge/device.py --track "<name>" --snapshot --song <name>` |
| Return track inventory and parameters | Available, with the `return_track.py` handler from `abletonosc-ext/`. Stock AbletonOSC cannot see returns at all. |
| Spectrograph image | Manual. Screenshot the analyzer into `mix/`. No plugin exposes its spectrum over OSC. |
| Offline FFT from stems | Needs numpy and soundfile installed. Only worth it if screenshots prove insufficient. |

**Do not claim a spectral reading you did not take.** If the only evidence is a parameter
value, say that is what it is.

## Return tracks

Count them before trusting any prior list. Returns get added and renamed mid-session and a
stale list survives for a long time because nothing contradicts it. Assumed lists have been
wrong by three entries, including one return documented as a reverb that was a delay.

Stock AbletonOSC cannot see return tracks. With `abletonosc-ext/return_track.py` applied,
`/live/return/get/names` and the device getters under `/live/return/` read them, and the
inventory belongs in the track repo's `returns.md`.
