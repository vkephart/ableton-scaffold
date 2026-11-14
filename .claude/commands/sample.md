# /sample

Capture a bar range of the Arrangement and measure it: level, loudness, how long a sound
takes to die away, and how it sits beside other tracks beat by beat.

Only when the user says to sample. A sound's identity is an ear call; this is for level and
placement after.

## Usage

```
/sample <from> <to> "<event track>" [--anchor <position>] ["<other track>" ...]
```

Positions are Live's ruler: bar, bar.beat or bar.beat.sixteenth. The first track is the
event, the sound in question. `--anchor` is the ruler position its note sits on.

## Script

```bash
# Read the state only, change nothing
bin/analysis-python bridge/sample.py --from <bar> --to <bar> --source "<Track>" --dry-run

# Capture and measure
bin/analysis-python bridge/sample.py --from <bar> --to <bar> --source "<Event track>" \
    --source "<Other track>" --source master --anchor <bar.beat> --out-dir <folder>

# Measure files that already exist
bin/analysis-python bridge/measure.py event.aif --against other.aif --tempo <bpm> --anchor-beat <beat>
```

`bin/analysis-python` is the scaffold's permanent environment; it builds itself on first
use (`bin/setup-analysis`).

## Before running

Say that the transport is about to play and for how long, and wait for nothing else: the
script stops by itself if the transport is running, Arrangement record is on, or a Session
clip is overriding the Arrangement.

## After

- Quote the numbers with their window, the point in the chain (`--channel`, Post Mixer by
  default) and what was soloed or muted. Put them in the song's `mix/readings.md`.
- Give fall times both in milliseconds and as ruler positions.
- Two passes of a sampled instrument can differ by a couple of dB if it alternates samples.
  Say so; do not average silently.
- The recorded originals stay in the project's `Samples/Recorded`. List them for deletion.
