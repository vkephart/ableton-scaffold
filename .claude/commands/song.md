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

Song content lives in its own repo, outside this one. Never create it inside this
checkout: nested git repos cause trouble, and this repo stays free of song content so it
can be shared.

```bash
mkdir -p "$ABLETON_SONGS_DIR/<name>"
cd "$ABLETON_SONGS_DIR/<name>"
git init
cp -r ~/music-studio/ableton-scaffold/templates/song/. .
mkdir -p parts/{drums,bass,guitars,keys,vocals,fx} chain mix
```

Then add a `.gitignore` for the generated cache:

```
parts/**/*.md
chain/*.md
mix/*.png
```

The hand-written files are the ones worth versioning. `parts/` and `chain/` are `/pull`
output and rebuild from the session at any time.

Fill in `brief.md` and `structure.md` before doing musical work in the new song. The
specialist agents read them first, and without them every judgement about whether
something is deliberate has to be asked rather than looked up.
