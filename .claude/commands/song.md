# /song

Switch active song context, or scaffold a new track repo.

## Usage

```
/song <name>
```

## What it does

Sets the active song for `/pull`, `/push`, `/device` and `/log`. The active song
determines which folder under the songs directory is read and written.

The songs directory resolves from `--songs-dir`, then `$ABLETON_SONGS_DIR`, then `./songs`,
then this repo. The usual setup is `export ABLETON_SONGS_DIR=~/music-studio`.

## Creating a new song

Song content lives in its own repo, outside this one, and a new one is created by the
scaffold's bootstrap script rather than by hand:

```bash
<scaffold>/bin/new-song <name>
```

It creates the track repo, fills it from `templates/song/`, writes its `CLAUDE.md`, and
symlinks the agents and commands into its `.claude/` so a session started there picks them
up. It refuses to create the repo inside the scaffold, and is safe to re-run.

Fill in `brief.md` and `structure.md` before doing musical work. The specialist agents read
them first, and without them every judgement about whether something is deliberate has to
be asked rather than looked up.
