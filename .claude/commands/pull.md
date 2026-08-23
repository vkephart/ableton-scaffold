# /pull

Sync the Ableton arrangement into the active song's folder. Runs `bridge/pull.py` and
writes into that song's `parts/` and `chain/` directories.

## Usage

```
/pull
/pull --tracks
/pull --devices
```

## What it does

1. Queries AbletonOSC for tempo and transport state
2. Reads all track names and arrangement clip positions and lengths
3. For each arrangement clip on a MIDI track, reads note data (needs the
   `arrangement_clip.py` handler from `abletonosc-ext/`)
4. Writes note data to `<song>/parts/<category>/<clip-name>.md`
5. Writes device chains to `<song>/chain/<track-name>.md`
6. Reports discrepancies against `structure.md`

## Script

```bash
python3 bridge/pull.py --song <name>
python3 bridge/pull.py --song <name> --songs-dir ~/music-studio
```

The songs directory comes from `--songs-dir`, then `$ABLETON_SONGS_DIR`, then `./songs`,
then this repo. Song folders do not live in this repo.

## When to run

- At the start of every session, to confirm the session matches the documents
- After changing anything in Ableton
- When resolving an entry in `conflicts.md`

## Reading the output

**It is a cache.** The Ableton session is the truth. `parts/` and `chain/` are gitignored
in the track repo and can always be rebuilt.

**Chain files from `/pull` carry raw values, not UI units.** Raw scaling is per-parameter,
so the numbers are not comparable to each other and must not be quoted as plugin settings.
Use `/device ... --snapshot` when you need real UI units.

**Clip files are named by track and beat-precise position.** Two clips in the same bar do
not collide. A collision warning in the output means a naming change broke that guarantee
and a clip would have been lost.
