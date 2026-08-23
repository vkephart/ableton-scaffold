# AbletonOSC extension handlers

Two handler modules that stock [AbletonOSC](https://github.com/ideoforms/AbletonOSC) does
not ship. `bridge/pull.py` depends on the first one; return-track documentation depends on
the second.

They live here so they are versioned somewhere other than
`~/Music/Ableton/User Library/Remote Scripts/`, which is a folder a reinstall can wipe and
which is not a git checkout.

Installation is SETUP.md §3. Run `python3 bridge/check_py37.py abletonosc-ext/` before
copying, every time.

## arrangement_clip.py

Note-level read and write for clips in the Arrangement view.

Stock AbletonOSC exposes arrangement clip *metadata* through
`/live/track/get/arrangement_clips/{name,length,start_time}`, but note access stops at
Session clip slots. Arrangement clips have no slot index, so these handlers address a clip
by its `start_time` on the timeline, matched within 0.001 beats to absorb float rounding
in transit over OSC.

| Address | Returns |
|---|---|
| `/live/arrangement_clip/get/clips <track>` | interleaved `(start_time, length)` per clip |
| `/live/arrangement_clip/get/notes <track> <start_time>` | flat `(pitch, start, duration, velocity, mute)` per note |
| `/live/arrangement_clip/set/notes <track> <start_time> <note data...>` | count of notes written |

`get/clips` exists rather than using the stock pair for two reasons. It is one round trip
per track instead of two, and more importantly, Live raises on `.arrangement_clips` for
Group, Return and Master tracks. The stock handler does not guard that, so the exception
means no reply is ever sent and the client blocks for a full timeout. Bus-heavy sessions
hit this on every group track. Here the refusal is caught and answered with an empty set,
which is the truthful answer: such tracks hold no arrangement clips.

`set/notes` clears the clip's full pitch and time range before writing, so a repeated push
replaces rather than stacking duplicates.

## return_track.py

Read-only access to return tracks.

Stock AbletonOSC cannot see them at all. `song.py` exposes only `create_return_track` and
`delete_return_track`, and return tracks do not appear in `song.tracks`, so
`/live/song/get/track_names` and every track-scoped handler skip them. A session's sends
are undocumentable without this.

| Address | Returns |
|---|---|
| `/live/return/get/num_returns` | count |
| `/live/return/get/names` | every return name |
| `/live/return/get/num_devices <return>` | count |
| `/live/return/get/devices/name <return>` | device names |
| `/live/return/get/devices/class_name <return>` | device class names |
| `/live/return/get/mixer <return>` | volume, panning, mute |
| `/live/return/get/device/parameters/name <return> <device>` | parameter names |
| `/live/return/get/device/parameters/value <return> <device>` | raw values |
| `/live/return/get/device/parameter/value_string <return> <device> <param>` | UI display string |

Every handler here is a getter. Nothing in the module can add, remove or modify a return.

Count the returns before trusting any prior documentation of them. Return tracks are
easy to add and rename mid-session, and a stale list of them is the kind of error that
survives for months because nothing contradicts it.

## Keeping them applied

Both modules register themselves through two one-line edits to stock files
(`abletonosc/__init__.py` and `manager.py`). No stock file is rewritten, so an upstream
AbletonOSC update can only ever conflict on those two registrations.

**Adding a handler class requires a full Ableton restart**, not `/live/api/reload` and not
a control surface toggle. SETUP.md §3 explains why, and how to tell that it has happened.
