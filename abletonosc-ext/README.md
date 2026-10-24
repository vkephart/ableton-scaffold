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

### Clip envelopes (Session clips), in the same module

Stock AbletonOSC cannot write automation. These live in `arrangement_clip.py` only because
adding a module reloads in place and adding a class needs an Ableton restart.

| Address | Does |
|---|---|
| `/live/clip/set/envelope/send <track> <slot> <send> <t0> <v0> <t1> <v1> ...` | replaces the clip's envelope for that send with flat steps; each value holds until the next time, the last to clip end |
| `/live/clip/set/envelope/param <track> <slot> <device> <param> <t0> <v0> ...` | same for a device parameter |
| `/live/clip/clear/envelope/send <track> <slot> <send>` | removes that send envelope |

Times are beats from clip start, values raw (sends 0 to 1). A ramp is many short steps;
two-beat steps read as a ramp at any normal tempo. The reply echoes the addressing and
the number of points written. There is no getter; check the envelope in the clip view.
The envelope is on the Session clip, so it travels with the clip when dragged to the
Arrangement.

### Locators (cue points), in the same module

Stock AbletonOSC reads locators (`/live/song/get/cue_points`) and jumps to them, but cannot
make, name or remove one. Added 2026-10-04.

| Address | Does |
|---|---|
| `/live/song/cue_point/add <beat> <name>` | makes a locator at the playhead, which must already sit on `<beat>`; a locator already there is left alone |
| `/live/song/cue_point/set/name <beat> <name>` | names the locator at that beat, where Live allows it |
| `/live/song/cue_point/delete <beat>` | removes the locator at that beat; the playhead must sit on it |

Each refuses while the transport plays. Replies echo the beat (and name) and a status.
Three Live 11.3 facts shaped this, all found by testing on 2026-10-04:

- **Locator names are read-only from a script.** `CuePoint.name` raises "can't set
  attribute", so locators come out numbered in time order and are renamed by hand
  (select, Cmd+R). The handlers try the name anyway and say when it did not take.
- **Moving the playhead does not land inside the same call.** Setting `current_song_time`
  and toggling the cue in one handler put the locator at the old playhead. So the client
  sends the stock `/live/song/set/current_song_time`, waits about half a second, reads the
  playhead back, then calls `add`.
- **The playhead cannot pass the song end, and the song end follows the playhead.** Live
  refuses a `current_song_time` beyond `song_length`, which sits a little past the furthest
  of the last clip, the last locator and the playhead. To place locators past the last clip,
  walk the playhead forward in steps of about 12 beats, rereading `song_length` each step,
  and add the locators in time order.

### Arrangement layout, in the same module

Added 2026-10-04 to lay a whole song out from its loop clips. Live 11.3 exposes
`Track.duplicate_clip_to_arrangement(clip, time)` and `Track.delete_clip(clip)`; these wrap
them, addressing Arrangement clips by start time like the note handlers.

| Address | Does |
|---|---|
| `/live/arrangement_clip/get/capabilities` | whether this Live has the two methods |
| `/live/arrangement_clip/get/info <track>` | `(start_time, end_time, name)` per clip; `end_time`, not `length`, which is the loop on a looped clip |
| `/live/arrangement_clip/duplicate <track> <src_start> <dest>` | copies that clip to `<dest>` on the same track; replies with the new start and end |
| `/live/clip_slot/duplicate_to_arrangement <track> <slot> <dest>` | copies a Session clip onto the timeline (one loop length) |
| `/live/arrangement_clip/delete <track> <start>` | deletes that clip |
| `/live/arrangement_clip/set/name <track> <start> <name>` | names it |

Found while using them:

- **A copy placed over an existing clip trims the one underneath**, as a paste by hand
  does. Place left to right and each placement cuts the previous one's tail. To shorten a
  clip, place a temporary copy where it should end, then delete the temporary one.
- **There is no trim or split.** A part of a clip comes from a clip split by hand, or from a
  copy cut short by the trim trick above.
- **A clip split by hand keeps all its notes**; the split only moves its start marker. Note
  reads on the second half return the hidden notes before the marker too, so judge a moved
  piece by its position, not by its first note.
- **A note read of thousands of notes gets no reply**: the answer is too big for one OSC
  packet. `/live/clip/get/notes <track> <slot> 0 127 <start> <span>` reads a time window;
  count in 16-beat windows. The same limit applies to `/live/arrangement_clip/get/notes`.
- **Long MIDI parts are cleanest as one clip:** build it in a spare Session slot
  (`create_clip`, then `/live/clip/add/notes` in chunks of about 60 notes), copy it to the
  Arrangement, and delete the Session clip.

### Reversible edits, in the same module

Added 2026-10-17 for auditioning a stripped section without deleting anything.

| Address | Does |
|---|---|
| `/live/arrangement_clip/get/props <track> <start>` | `(start_marker, end_marker, loop_start, loop_end, looping, length, muted, is_midi)` |
| `/live/arrangement_clip/set/muted <track> <start> <0/1>` | mutes or unmutes the clip; replies with the new state |
| `/live/arrangement_clip/set/notes_muted <track> <start> <from_pitch> <pitch_span> <from_time> <time_span> <0/1>` | sets the mute flag on the notes starting in that window; replies with the count |
| `/live/arrangement_clip/add/notes <track> <start> <note data...>` | adds notes without clearing the clip, for clips too large to read back and rewrite |
| `/live/arrangement_clip/remove/notes <track> <start> <from_pitch> <pitch_span> <from_time> <time_span>` | removes the notes starting in that window; replies with how many there were |

Note windows are clip time. Convert from song time with `song beat - start_time +
start_marker`, so read `get/props` first. Muted clips and notes show greyed and come back
with the 0 key. Unmuting a window also unmutes notes that were muted before, so back up
the notes (or count the muted ones) first.

## return_track.py

Read and set access to return tracks.

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
| `/live/return/get/device/parameters/min <return> <device>` | raw minimums |
| `/live/return/get/device/parameters/max <return> <device>` | raw maximums |
| `/live/return/set/device/parameter/value <return> <device> <param> <raw>` | `(value, display string, "ok" or "refused")` |

One writer, `set/device/parameter/value`. It takes a raw Live API value, never UI units,
checks it against the parameter's own min and max, and refuses rather than lets Live clamp
silently, because a clamped write hides a wrong scale. The reply carries the display string
so the caller verifies in the same round trip. Nothing in the module can add, remove or
rename a return. `bridge/device.py` uses all of this when `--track` names a return.

Count the returns before trusting any prior documentation of them. Return tracks are
easy to add and rename mid-session, and a stale list of them is the kind of error that
survives for months because nothing contradicts it.

## Keeping them applied

Both modules register themselves through two one-line edits to stock files
(`abletonosc/__init__.py` and `manager.py`). No stock file is rewritten, so an upstream
AbletonOSC update can only ever conflict on those two registrations.

**Adding a handler class requires a full Ableton restart**, not `/live/api/reload` and not
a control surface toggle. SETUP.md §3 explains why, and how to tell that it has happened.
**Changing a module whose class is already registered does not.** Copy the file in and
send `/live/api/reload`: `reload_imports()` reloads every module, then clears and re-runs
`init_api()`, so new addresses in an existing handler register on the spot. Confirm with a
read of one of the new addresses before trusting it.
