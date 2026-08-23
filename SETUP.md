# Setup guide

One-time steps. Skip any you have already done.

---

## 1. Lay out the two repos

This repo holds tooling and method. Song content lives in separate track repos, one per
song, and those stay private. The layout the scripts expect:

```
~/music-studio/
  ableton-scaffold/     this repo: bridge, agents, commands, setup
  <song-name>/          a track repo: brief, structure, harmony, lyrics, log, parts, chain
  <another-song>/
```

```bash
git clone <this-repo> ~/music-studio/ableton-scaffold
cd ~/music-studio/ableton-scaffold
```

Point the scripts at the songs root once, in your shell profile:

```bash
export ABLETON_SONGS_DIR=~/music-studio
```

Every script also takes `--songs-dir` if you want to override it per invocation. Nothing
here assumes song folders sit inside this checkout.

**Never create a track repo inside this one.** Nested git repos cause trouble later, and
the whole point of the split is that song content and history stay out of the public repo.

---

## 2. Install AbletonOSC

AbletonOSC is a MIDI Remote Script. It coexists with AbletonMCP: separate folders,
separate control surface slots, separate transports (MCP is TCP 9877, OSC is UDP 11000 in
and 11001 out). Live allows multiple control surfaces at once.

**Install:**

```bash
cd ~/Music/Ableton/User\ Library/Remote\ Scripts
git clone https://github.com/ideoforms/AbletonOSC.git AbletonOSC
```

That is the User Library Remote Scripts path, which Live 11 scans. Note it is *not*
`~/Library/Preferences/Ableton/<version>/`. If AbletonOSC is already present but was
dropped in as a source archive rather than cloned, `git pull` will not update it.

**Live imports every directory in `Remote Scripts/` as a Python module.** A backup folder
named `AbletonOSC.bak-2026-08-22` sitting next to the real one throws a SyntaxError at
every launch. Keep backups somewhere else entirely.

**Enable in Ableton:**

1. Preferences, then Link, Tempo & MIDI
2. Under MIDI, find a free Control Surface slot
3. Set it to **AbletonOSC**
4. Leave Input and Output as None. It uses OSC, not MIDI ports.
5. Restart Ableton

**Confirm it loaded.** `~/Library/Preferences/Ableton/Live <version>/Log.txt` lists every
occupied Control Surface slot at launch, and `AbletonOSC/logs/abletonosc.log` records
`Started AbletonOSC on address ('0.0.0.0', 11000)`.

**Verify:**

```bash
python3 bridge/osc_client.py --check
```

Expected: `AbletonOSC connected — tempo: 120.0 BPM`, showing the open set's tempo.

---

## 3. Apply the extension handlers

Stock AbletonOSC reads and writes notes only in Session clip slots, and cannot see return
tracks at all. `abletonosc-ext/` closes both gaps. See `abletonosc-ext/README.md` for what
each handler exposes.

**There is no `AbletonOSC.py` and no `AbletonOSC` class.** The real layout is a package of
per-domain handler classes in `abletonosc/` (`clip.py`, `track.py`, `song.py`, `device.py`),
each subclassing `AbletonOSCHandler` and registering handlers inside `init_api()`,
assembled into a list in `manager.py`.

**Check the syntax first, every time:**

```bash
python3 bridge/check_py37.py abletonosc-ext/
```

**Copy the modules in:**

```bash
OSC=~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonOSC
cp abletonosc-ext/arrangement_clip.py abletonosc-ext/return_track.py "$OSC/abletonosc/"
```

**Register them, two one-line edits to stock files:**

In `abletonosc/__init__.py`, alongside the other handler imports:

```python
from .arrangement_clip import ArrangementClipHandler
from .return_track import ReturnTrackHandler
```

In `manager.py`, add both to the `self.handlers` list in `init_api()`, and to
`reload_imports()`.

Keeping each handler in its own module means no stock file is rewritten, so an upstream
update can only ever conflict on those two registrations.

### Live 11 embeds CPython 3.7

Any 3.8+ syntax (walrus, positional-only parameters, builtin generics like `list[int]`,
`match`, `X | Y` unions) makes the control surface fail to load, with no useful error.
There is no 3.7 interpreter on a current Mac to test against, which is why
`bridge/check_py37.py` exists. Use `typing.Tuple` and `typing.Any` and `%` formatting,
matching the stock modules.

### Reloading has three levels, and the difference matters

| Change | What is needed |
|---|---|
| Edit inside an existing `abletonosc/*.py` | `/live/api/reload`. No restart. |
| Add a **new handler class** (new module plus `manager.py` registration) | **Full Ableton restart.** |

`/live/api/reload` reloads module bodies but never reloads `manager.py`, so the running
Manager keeps its old `init_api`. **A control surface toggle does not fix this either.**
Toggling re-runs the script object but does not drop `manager` from the process's imported
modules, so Python never recompiles it and the stale
`__pycache__/manager.cpython-37.pyc` keeps being used. Only quitting Ableton clears
`sys.modules`.

The failure is silent and misleading. The reload logs success, the new class imports
without error, every other handler keeps working, and the new address just answers
"Unknown OSC address". Diagnose it by timestamp: a `manager.py` whose source is newer than
its `.pyc` is the tell.

```bash
cd ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonOSC
stat -f "%Sm %N" -t "%H:%M:%S" manager.py __pycache__/manager.cpython-37.pyc
```

Clear the caches before restarting so the recompile is guaranteed:

```bash
find . -name __pycache__ -type d -not -path "./pythonosc/*" -exec rm -rf {} +
```

### Reply format

Every handler echoes its addressing arguments at the head of its reply. Track-scoped
handlers prepend `track_index`, device-scoped handlers prepend
`(track_index, device_index)`, and the arrangement handlers prepend
`(track_index, clip_start_time)`. `bridge/osc_client.py` strips these in `_track_query`
and `_device_query`. Forgetting to strip does not raise, it shifts every field and yields
data that looks plausible and is wrong.

### One more trap

`get_notes_extended` takes `(from_pitch, pitch_span, from_time, time_span)`. Written as
`(0, 0, clip.length, 128)` it reads as `pitch_span=0` and returns nothing, with no error.
The correct call is `(0, 128, 0, clip.length)`. `remove_notes_extended` takes the same
order.

---

## 4. Install bridge Python dependencies

```bash
pip3 install --break-system-packages -r bridge/requirements.txt
```

---

## 5. Connect AbletonMCP

`push.py` writes notes through AbletonMCP rather than AbletonOSC, because its note-write
interface is the more reliable of the two. It is a separate MIDI Remote Script listening
on TCP 9877.

In your Claude Code config:

```json
{
  "mcpServers": {
    "AbletonMCP": {
      "command": "uvx",
      "args": ["ableton-mcp"]
    }
  }
}
```

---

## 6. Symlink your manuals folder

The mix-chain agent reads vendor documentation before advising on parameters. Point
`reference/manuals/` at wherever you keep the PDFs. The symlink is gitignored, so nothing
large or vendor-owned lands in the repo.

```bash
rm -rf reference/manuals
ln -s ~/Manuals ~/music-studio/ableton-scaffold/reference/manuals
```

Recreate `reference/manuals/README.md` afterwards if the symlink replaced it, or keep the
manuals inside a subfolder of the symlink target.

---

## 7. Start a track repo

```bash
bin/new-song <song-name>
```

That creates `$ABLETON_SONGS_DIR/<song-name>` as its own git repo, fills it with the
documents from `templates/song/`, writes a `CLAUDE.md` into it, and symlinks this repo's
agents and slash commands into its `.claude/` so a Claude Code session started there picks
them up. Without that last step a track repo gets no agents, no commands and no
conventions.

Pass `--songs-dir` to put it somewhere other than this repo's parent. The script refuses
to create a track repo inside this one, and is safe to re-run: it creates only missing
files and never overwrites work you have edited.

Fill in `brief.md` and `structure.md` before doing musical work. Every agent reads them
first.

Then confirm the round trip with Ableton open:

```bash
python3 bridge/pull.py --song <song-name>
```

After cloning a track repo on another machine, rebuild its symlinks:

```bash
<scaffold>/bin/new-song <song-name> --relink
```
