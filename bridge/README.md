# Bridge

Python scripts that talk to a running Ableton Live session. These are the connective tissue between a track repo and the DAW.

## Prerequisites

- AbletonOSC installed as a MIDI Remote Script (SETUP.md §2)
- The `abletonosc-ext/` handlers copied in (SETUP.md §3), for arrangement clips and return tracks
- `pip3 install -r bridge/requirements.txt`

## Where the songs live

The scripts hold no assumption that song folders sit inside this repo. Every script that
touches a song folder resolves the songs directory the same way, first hit wins:

1. `--songs-dir` on the command line
2. `$ABLETON_SONGS_DIR`
3. `./songs` under the working directory
4. `<this repo>/songs`

Options 1 and 2 must exist or the script stops and says so. Options 3 and 4 are probed
and skipped when absent, so an explicit setting that points nowhere fails loudly instead
of quietly writing somewhere else.

The usual setup is one export in your shell profile:

```bash
export ABLETON_SONGS_DIR=~/music-studio
```

with each track repo checked out as a folder underneath it. Then `--song <name>` resolves
to `~/music-studio/<name>/`, and this repo never contains song content.

The resolution logic is in `songpath.py`, shared by all three scripts so the flag behaves
identically everywhere.

## Scripts

### osc_client.py

Low-level OSC wrapper. Not called directly; imported by the other scripts.

```bash
python3 bridge/osc_client.py --check
```

Expected: `AbletonOSC connected — tempo: 120.0 BPM`, reading whatever tempo the open set
is at. Anything else means AbletonOSC is not loaded, and SETUP.md §2 is the place to look.

### pull.py

Reads the Ableton arrangement and writes it into a song folder.

```bash
python3 bridge/pull.py --song <name>
python3 bridge/pull.py --song <name> --songs-dir ~/music-studio
python3 bridge/pull.py --song <name> --tracks-only
python3 bridge/pull.py --song <name> --devices-only
```

Writes:

- `<song>/parts/<category>/<clip-name>.md`, note data per arrangement clip
- `<song>/chain/<track-name>.md`, device list and raw parameter values per track

Two things to know about the output:

**It is a cache, not source of truth.** The Ableton session is the truth. Gitignore
`parts/` and `chain/` in the track repo and regenerate them; committing them produces a
large churning diff on every pull for data you can always rebuild.

**Chain files from `pull.py` carry raw values, not UI units.** Raw scaling is
per-parameter, so the numbers are not comparable to each other and not quotable as plugin
settings. Use `device.py --snapshot` when you need real UI units.

Track name to folder mapping is a substring heuristic in `CATEGORY_MAP`; unmatched tracks
land in `fx`. Add the keywords your own sessions use.

### push.py

Writes MIDI notes from a part file into an Ableton **Session** clip slot.

```bash
python3 bridge/push.py --part <song>/parts/bass/verse1-bass.md
python3 bridge/push.py --part /abs/path/to/part.md --track 2 --slot 0
```

A path that exists as given is used as given. A relative path that misses is retried
under the songs directory.

Uses AbletonMCP over TCP 9877 rather than AbletonOSC, because its note-write interface is
the more reliable of the two. The clip lands in a Session slot; drag it to the Arrangement
at the right bar yourself. Unfreeze the target track first, because frozen tracks fail
silently on `create_clip`.

### capture.py

Records a track's output, or the master, to an audio file through a temporary resample
track, so a plugin that publishes nothing over OSC can still be measured. The transport
must already be playing with the clips to capture running; the script retriggers nothing.
Recording starts at the next launch-quantize boundary and runs for `--beats` plus a bar.
The temporary track has monitoring Off before it is armed, so nothing doubles into the
master, and it is deleted afterwards. Several sources record simultaneously and come out
sample-aligned.

```bash
python3 bridge/capture.py --source Pads --beats 96 --out /tmp/pad.aif
python3 bridge/capture.py --source Pads --source master --beats 96 --out /tmp/pad.aif --out /tmp/mix.aif
python3 bridge/capture.py --source Pads --channel "Post FX" --beats 96 --out /tmp/pad-prefader.aif
```

Prints a JSON line with the mixer state at capture time; paste the relevant faders into
the readings entry, because they are one of the five variables a capture has to pin.

Placing a capture in song time: the CAP files appear on disk when the tracks are armed,
before recording starts, and the start is not a fixed distance from a playhead jump
(three passes in one session started 4, 4 and 0 beats after the jump target). Place the
file by correlating one capture against an audio file whose position is known, such as a
print the source track plays, and quote the correlation.

Repeated audio through an amp or tape simulation is not sample-identical: two passes of
the same file region through one bass chain correlated about 0.5. Before reading a low
correlation as wrong content, measure a control pair the edit did not touch.

### sample.py and measure.py

The sampling tool. `sample.py` captures a bar range of the Arrangement from one or more
tracks (or the master) and hands the files to `measure.py`, which is offline and needs no
Live. Use these before writing a scratch script: every session that measured used to
rebuild the environment, the transport handling and the arithmetic.

```bash
bin/analysis-python bridge/sample.py --from 21 --to 29 --source "<Event track>" --source "<Other>" --anchor 23
bin/analysis-python bridge/measure.py event.aif --against other.aif --tempo 120 --anchor-beat 88
bin/analysis-python bridge/measure.py --self-test
```

It refuses to start while the transport is running: stop playback, then run it. The
files Live writes into the project's recordings folder are left there; when the reading is
filed, check them with `refs.py` (below) and clear them out.

What `sample.py` handles so nobody has to again:

- Everything slow (creating, routing and arming the temporary tracks, the mixer read) is
  done before the transport starts. Each OSC round trip takes longer while Live plays.
- A playhead set while the transport is stopped does not decide where playback begins.
  `continue_playing` resumed from where the transport last stopped, and the first run
  recorded the wrong 20 seconds that way; `start_playing` also began elsewhere on both
  verified passes. What lands is setting the playhead while playing, so the script starts,
  checks where it is, and jumps. It prints a line when it had to. The second or so of
  audio recorded before the jump is why the pre-roll is two bars.
- Launch quantization, the loop and the metronome are switched off for the pass and put
  back. Arm states and the playhead are put back, and the track count is checked.
- A signal or a timeout raises, so the cleanup still runs. A bare `signal.alarm` would
  leave armed temporary tracks in the set.
- It refuses to run if the transport is playing, Arrangement record is on, or Back to
  Arrangement is lit.
- Placement comes from the audio: `--anchor` pins the event's first sound to the ruler
  position its note sits on. The playhead-derived position is printed beside it as a check.

What `measure.py` reports: sample peak, loudest 50 ms RMS, momentary (400 ms) and
short-term (3 s) loudness maxima in LUFS, the start of the sound, the time after the start
at which it has fallen 6, 10, 20, 30, 40 and 60 dB for good, a fitted decay rate, and, with
`--against`, each beat of the event beside the other files. A fall the file ends before
reaching is "not reached", never extrapolated. Integrated loudness is printed but is not
meaningful for a single hit. `--self-test` checks the loudness against a 997 Hz sine (one
channel at full scale is -3.01 LUFS) and the fall times against noise decaying at 20 dB/s.

Reading the result:

- Levels are at the point in the chain named by `--channel` (Post Mixer by default), so a
  track inside a group is read before the group's fader.
- A sampled instrument that alternates samples gives a different hit each pass. Two passes
  of one cymbal differed by about 2 dB in peak and half a second at the -20 dB mark.
- Fall times map onto an envelope: the time to stay within a few dB is a hold or sustain
  time, the rest is the release.

### take.py

What was played in a recorded take, and on which beat, read from the file the clip plays.
No capture, no playback, and no interface needed: it is the way to answer "did I play the
notes I meant, where I meant them" while the session is busy or the rig is off.

```bash
bin/analysis-python bridge/take.py --live "<Track>" <clip start beat> --from-bar 17 --to-bar 24
bin/analysis-python bridge/take.py take.aif --tempo 120 --clip-beat 64 --file-sample 84943.8 --drift 4
bin/analysis-python bridge/take.py --self-test
```

For every struck onset it prints the ruler position (nearest sixteenth), the distance from
that grid line in milliseconds (+ is late), the peak, and the strongest partials as note
name, MIDI number and cents. `--drift N` follows each onset's strongest partial for N
beats, half a beat at a time: a vibrato arm, a bend, a string resting sharp. `--live`
takes the file, the tempo and the placement from the open set through the extension's
`/live/arrangement_clip/get/audio`.

What it will and will not tell you:

- The file is the take before the track's devices. Pitch and timing hold through an amp or
  an echo. Level, ring length and anything a delay adds do not: those need a capture or an
  export.
- An onset is listed only if it shows an energy step, whole band and above 3 kHz. A
  spectral-flux detector on its own reported 52 soft "strokes" at near-sixteenth spacing
  inside the rings of 12 picked notes, with believable grid positions and a smooth run of
  levels. They were the ring fluctuating by under a decibel. A count of strokes, a tempo
  of a run or a timing spread taken from such candidates describes nothing that was
  played. `--all` lists them, marked.
- A listed pitch can be an overtone of the note meant, or a neighbouring string that was
  brushed. Read the set of partials, not the top line.
- A stretched clip stops the script: its file does not sit on the grid at the set's tempo.
- Timing is good to about 10 ms. An offset of an eighth or a quarter is a played beat, not
  latency.

### bounce.py

What a bounced mix came out at: integrated loudness, the short-term maximum and where it
is, sample and true peak per side, left against right, and width (side against mid, and
the correlation of the two channels). With sections, the same per section, so the loudest
section is a measurement.

```bash
bin/analysis-python bridge/bounce.py mix.wav
bin/analysis-python bridge/bounce.py mix.wav --tempo 120 --section Intro:0 --section Verse:32 --section End:256
bin/analysis-python bridge/bounce.py mix.wav --live      # tempo and locators from the open set
bin/analysis-python bridge/bounce.py --self-test
```

A limited bounce cannot say how hard the limiter worked or which section was loudest going
in: the limiter evens the sections out. For that, measure a second bounce with the limiter
bypassed and compare the two section by section. Find the loudest section this way before
pointing a mastering assistant at one; a guess from the arrangement was wrong once.

### refs.py

Does anything in the set play this file? Run it before deleting audio from a project,
capture files included.

```bash
python3 bridge/refs.py "CAP-" --als-dir "<project folder>"
```

It reads the file path of every Arrangement audio clip and every Session clip in the open
set, and with `--als-dir` counts mentions in every saved set under a folder, backups
included. Read-only. Exit status 0 means nothing references the text, 1 means something
does, 2 means part of the open set did not answer. It does not see samples loaded inside
instruments or Live's undo history. Test it once with a file known to be in use, so a
clean result is known to mean something. Even with a clean result, move files to the
Trash in a named folder in place of removing them: a wrong answer then costs nothing.

### spectrum.py

Offline reading of a capture: levels, stereo correlation per band, band powers, centroid,
strongest peaks, brightness and level variation over time, and with `--track-partial` the
pitch and amplitude modulation of one partial. `--png` writes a spectrogram plus long-term
average spectrum for `mix/`. Run it with `bin/analysis-python`.

```bash
python3 bridge/spectrum.py /tmp/pad.aif --against /tmp/mix.aif --track-partial 440 --png mix/<name>-before.png
```

### device.py

Reads and sets device parameters by name, and snapshots a whole chain.

```bash
python3 bridge/device.py --track "<Track>" --device "<Device>" --list-params
python3 bridge/device.py --track "<Track>" --device "<Device>" --param "<Param>"
python3 bridge/device.py --track "<Track>" --device "<Device>" --param "<Param>" --set 120
python3 bridge/device.py --track "<Track>" --snapshot --song <name>
```

UI units come from Live's own `str_for_value()`, so they are exactly what the plugin
displays. `--set` takes a **raw** value, range-checked against the parameter's own min and
max, and prints the before and after display strings so you can see what actually landed.

### check_py37.py

Flags Python 3.8+ syntax in code destined for Ableton's Remote Scripts folder.

```bash
python3 bridge/check_py37.py abletonosc-ext/
python3 bridge/check_py37.py ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonOSC
```

Live 11 embeds CPython 3.7, there is no 3.7 interpreter on a current Mac to test against,
and the failure mode is a control surface that silently does not load. Run this before
copying anything into Remote Scripts.

It catches the walrus operator, positional-only parameters, `list[int]` style generics,
`X | Y` unions, `match`, `except*`, and the `f"{x=}"` debug form. It cannot catch
3.8+ standard library calls that parse fine and fail at runtime; a few common ones are
reported as warnings.

Note that upstream AbletonOSC's own `client/client.py` uses 3.9 generics. That file is a
desktop-side example client, not loaded by Live, so those two hits are expected and
harmless.

## What the session will and will not tell you

Learned against Live 11.3. Each of these produced a wrong answer before it was written
down.

**Writes**

- Rapid parameter writes over OSC can land out of order. A bisection that ended on the
  right display string left an intermediate value in the device a few seconds later. Let
  it settle, write the final value once more, and read the raw value back.
- Neither AbletonOSC nor AbletonMCP can write Arrangement automation. The lanes are drawn
  by hand. Read one back by stepping the stopped playhead and reading the parameter value
  at each stop.
- A stepped read needs the transport left alone, and the person at the desk does not know
  that unless told. Say so before starting (what, how long, do not press play) and say
  when it is done. Guard the script as well: check `/live/song/get/is_playing` before the
  first step, read `/live/song/get/current_song_time` back after every set and compare,
  retry once, stop without touching the playhead if playback has started, and otherwise put
  the playhead back where it was. A read taken during playback returns the value at the
  moving playhead and looks plausible. Quarter-beat steps find a throw; sixteenth-beat
  steps over the throw give its shape. About 0.15 to 0.2 s per step is enough.
- Track sends come back raw (0 to 1) with no display string, and the rule against
  hand-converting raw values holds for them. Quote them as raw and ask for the dB off a
  breakpoint or the knob when a dB is needed.
- Bridge writes sit in Live's undo history. An undo at the desk reverts them, and if the
  device is an editor plugin for outboard hardware, the old values go back to the box.
  Re-read before anything is stored.
- Live offers a group as a track's output only once the track is inside the group, so
  routing to it over OSC fails until the track has been dragged in.
- AbletonMCP's `load_browser_item` loads a Live-native device by URI with nobody at the
  desk, for example `query:Synths#Analog`. The folder segment is required where there is
  one: Utility is `query:AudioFx#Utilities:Utility`.
- A track's output can be set over OSC: `/live/track/set/output_routing_type` (for example
  `Ext. Out`), then `/live/track/set/output_routing_channel`. The channel list only appears
  once the type is set, and the type lands on the first pair, usually the monitors. A new
  track arrives on Master at 0 dB, so pull its fader down before routing it to hardware and
  leave it down for whoever is at the desk to raise.
- Live's external output numbers are the driver's channel numbers, not the numbers printed
  on the interface. On an interface with a dedicated monitor pair, driver channels 1 and 2
  are the monitors and the first line output is channel 3, so "line out 3 and 4" can be
  Live's `5/6`. Read the driver's channel names before routing (on macOS, CoreAudio's
  element-name property on the output scope) and say both numbers when reporting.
- An interface's own mixer can own a line output. If its cue or monitor routing mirrors a
  mix onto a line pair, the DAW's signal to that pair does not arrive and the monitor mix
  comes out there instead. On one rig a hardware sync input fed from such a jack was
  clocked by the drums in the mix. Ask to see the interface mixer's output assignments
  before routing a DAW signal to a line output, and test with the DAW stopped: the jack
  should be silent.
- A clock pulse for a hardware sync input wants one edge per step. A click with several
  cycles in it can advance the box more than once, and so can a single full cycle: on one
  drum machine a one-cycle square (up, down, back to zero) gave an uneven, doubled pattern,
  and a pulse of one polarity only (the first half of a low square, gated by a note half the
  cycle long) stepped it evenly. Build the one-polarity pulse first. Even is not the same as
  one step per pulse: some boxes take two steps per pulse (confirmed on that one: eighth-note
  pulses give sixteenth steps), and a hat on every step sounds
  clean at double speed. Count it, either by the step lights per bar or by recording a few
  bars and counting onsets per pulse, before writing down the rate. A pattern with a hit on
  every step also hides the lateness modulo the hit spacing; measure latency with one hit
  per bar.

**Reads**

- An armed, monitoring audio track's meter reads the input before the devices. A trim
  device on that track is invisible there. Confirm level on the Master meter or with a
  capture. The OSC meter value is not dB-linear and no mapping is documented.
- Native devices publish every parameter with unit strings. Third-party plugins publish
  only what has been added in Configure mode, by hand, and that set is lost if the plugin
  reloads. List the parameters again before promising a control.
- Configured third-party parameters often come back as bare 0 to 1 fractions with no unit
  string, and the curve is per parameter (FabFilter Pro-R: Decay Rate is logarithmic with
  100 % at raw 0.5, Predelay is a curve). Read seconds and decibels off the plugin window
  and say that is where they came from.
- Soundtoys plugins publish `Bypass` as 1 when inserted, and 1 means bypassed. Set it to
  0. EchoBoy's note value and sync are settable only in its own window in practice.
- Addictive Drums 2 publishes only `Device On` and one send level to Live. Every kit,
  cymbal, level, pitch and envelope setting is made in its window by the person at the
  desk, so give exact control names from the manual and ask for the values back. Facts
  that cost time once: cymbals have no close-mic channel, they sound only through the
  overhead and room mics, so a cymbal's level is the Kit Piece Volume slider in its slot
  on the Kit page or its own `OH Level` and `Room Level` on the Edit page; the Edit
  page's darkened sections switch on when a control in them is moved; Shift gives fine
  steps; a kit piece swapped from the slot's own menu kept that slot's Edit settings (seen
  once); loading a preset swaps the kit pieces too. The key map has second keys marked
  "(dbl)" for common hits (46 is the same Cymbal 1 hit as 77), so a note found on the
  lower key is not a mistake. Two captures of the same note differed by about 2 dB in peak
  and half a second in decay, most likely alternating samples: say so when reporting one
  pass, and `No Alts` in the Kit Piece Controls or a print to audio is the cure.
- A note read of several thousand notes gets no reply. Read in windows of about 16 beats.
- The saved set file answers what the bridge cannot, with nothing touched. An `.als` is
  gzip XML. Copy it out of the project, unzip the copy and parse that. It holds every
  Arrangement clip with its markers and loop, every note with its mute flag
  (`MidiNoteEvent`, `IsEnabled`), every Arrangement automation lane (`AutomationEnvelope`,
  matched to its parameter through the `AutomationTarget` ids), and the mixer. No
  transport, no playhead, no reply-size limit, so it suits a whole-song read with nobody
  at the desk. Four things to know. It is the state at the last save: check the file time
  and cross-check the clip list and one small clip over OSC before trusting it. A looped
  Arrangement clip plays note time t at clip start + t - (loop start + start offset),
  wrapping at the loop length; an unlooped one uses the loop start field as its start
  marker. Faders and sends are stored as linear gain (1.0 is 0 dB, 0.000316 is the -70 dB
  floor), not as the raw 0 to 1 the bridge returns, so the file gives the dB that a raw
  send read cannot. Third-party plugin state is opaque in it.
- Before writing a planned change into a clip, read the track's clip list again with end
  times (`/live/arrangement_clip/get/info`) and compare it with the last documented read.
  A Session clip launched on any track while the Arrangement is recording is recorded over
  that track's Arrangement clip, from the launch to the stop, and nobody at the desk need
  notice: the tell is a clip named like a Session slot, matching it note for note, with an
  end that is off the grid by a fraction of a beat, and a neighbour whose left edge was cut
  by the same fraction. Live's `Backup` folder dates it: scan the dated saves for the first
  one that has the edge. Everything judged by ear after that save was judged against the
  overwritten part, so say which rulings want hearing again.
- A clip cut short by an overwrite keeps every note behind its edge. A note write into the
  hidden part replies with the right count and makes no sound, so check the clip's
  `end_time` covers the target beat before `add/notes`. A short looped clip cannot take a
  figure that does not repeat at its loop length. Dragging the cut clip's edge back out by
  hand restores the original notes; a rebuild from the bridge does not reach a left edge
  that sits a fraction of a beat off the bar.
- A send's raw value hides how low it is. Read from one set file against the bridge: raw
  0.75 is -10 dB, 0.45 is -22 dB and 0.25 is about -35 dB. A send parked at a low
  "starting level" may be far under every other feed into the same return, while a
  document that lists it reads as if the effect were plainly in the song. A send gain is
  still not a level: say what the send reads, and call the effect audible or not only
  after listening to the return or measuring it.

**Capture**

- `capture.py` can take tens of beats to start recording, because its per-track arm and
  mixer queries are slow. Start the transport well ahead of the window, launch the
  capture, wait for the new files to appear in the project's `Samples/Recorded`, then jump
  the playhead with a send-only client (the capture holds the reply port).
- Check `/live/song/get/loop` first. A transport loop wraps the pass.
- `spectrum.py --against` needs both files at the same sample rate. Captures follow the
  interface's rate, which may have changed since the reference was made.

**Recording a hardware track from the bridge**

`/live/clip_slot/fire` on an armed audio track's empty slot starts recording, and a second
fire switches to playback at the next launch-quantize boundary. With quantization at 1 bar,
a fire sent one to three beats before the target length ends the clip exactly. Restore the
set's own quantization afterwards. Stop MIDI clips on the same bar line and confirm the
meter reads zero before starting, or a hung note's release lands in the take.

**Plugins that live outside the computer**

- Plugins hosted on an audio interface's processor go offline when the interface is
  switched off or unplugged. The set still opens and the bridge still reads faders, sends
  and native devices, but any track through one of those plugins sounds and measures
  different, and Live falls back to another audio device. Before the interface goes off,
  export every track and return as its own file with the processing printed (Rendered
  Track: All Individual Tracks). Mix, level and tone questions can then be answered from
  the files with nothing switched on.
- A file under `Samples/Recorded` is the input as recorded, before the track's devices. It
  answers pitch and timing. It does not answer tone.
- A third-party amp or instrument plugin may publish only unassigned placeholders
  (`Param 1` to `Param 16`, all zero) until parameters are assigned inside the plugin.
  Its settings then have to come from a screenshot or the user, and the chain file should
  say so in place of a table of zeros.
- Whether a plugin is licensed cannot be read from disk when the vendor's installer puts
  every plugin on the machine. Ask, or have the user open the vendor's own licence
  manager.

**A mastering suite on the Master, for a listening bounce.** Learned with iZotope Ozone 12
Advanced on Live 11.3.

- Read the Master first (`/live/master/get/devices`). An empty Master and an old loudness
  reading mean the target is a guess until a bounce is measured (`bounce.py`).
- For a bounce meant for judging the mix, the limiter alone is the honest setting: the
  other modules re-tone and re-balance. If the user wants some width, that is their call;
  keep it small and say what it widens (whatever is already stereo, usually the returns).
- Ozone 12's Master Assistant has a Custom flow: a module list with Disable All, a
  Loudness knob, Output Level and a True Peak switch. After it runs, the Assistant view's
  Width Match is the Imager's Amount. The band handles keep the full values the Assistant
  chose; the coloured bars beside them show what is applied. The plugin published one
  parameter to Live unasked, `IMG: Global Amount`, so that scaling can be read back.
- Do not name the loudest section from the arrangement. Ask the user's ear or measure a
  bounce by section. The bounce with the limiter on cannot answer it afterwards, since the
  limiter evens the sections out.
- A bounce can land a couple of LU from the target the user was given. Never having seen
  the loudness control in a screenshot is the gap to close before the export, not after.
- Live's export dialog keeps its own sample rate, which can differ from the set's
  recordings. Check it against a recorded file's rate, and render a few bars past the end
  locator: tails were still at speaking level a full bar after it.
- Live's export writes a zero-byte file named for the rendered track in the project's
  recorded-samples folder while it renders; the bounce itself appears at the target only
  when it is done. Watch the target folder for a file whose size has stopped changing.

**The reply port**

A hung OSC script keeps UDP 11001 bound and every later client fails with "Address already
in use". Find it with `lsof -nP -iUDP:11001` and kill that PID; a venv interpreter shows
up as the framework `Python.app` binary, so matching on the venv path misses it.
`OscClient.close()` shuts the reply server down but leaves the port bound, so a script
that holds a client must call `client._server.server_close()` before launching
`capture.py` in a subprocess. Put `signal.alarm` on long OSC scripts.

## Ports

| Protocol | Tool | Port |
|---|---|---|
| TCP (MCP) | AbletonMCP | 9877 |
| OSC listen | AbletonOSC | 11000 |
| OSC reply | AbletonOSC | 11001 |

Both drive the same Live object model. Avoid an MCP write and an OSC write at the same
instant.

## Reply format, and the mistake it causes

Every AbletonOSC handler echoes its addressing arguments at the head of its reply.
Track-scoped handlers prepend `track_index`, device-scoped handlers prepend
`(track_index, device_index)`, and the arrangement handlers prepend
`(track_index, clip_start_time)`.

`osc_client.py` strips these in `_track_query` and `_device_query`. Forgetting to strip
them does not raise; it shifts every field by one or two positions and produces data that
looks plausible and is wrong. Any new handler needs the same treatment.
