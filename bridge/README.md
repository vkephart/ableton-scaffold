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
