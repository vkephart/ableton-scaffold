# Song templates

Starting files for a new track repo. Copy the contents of this folder into the new song
folder, then fill them in.

```bash
mkdir -p "$ABLETON_SONGS_DIR/<name>"
cd "$ABLETON_SONGS_DIR/<name>"
git init
cp -r ~/music-studio/ableton-scaffold/templates/song/. .
rm README.md
mkdir -p parts/{drums,bass,guitars,keys,vocals,fx} chain mix
```

`brief.md` and `structure.md` are the two to fill in first. Every specialist agent reads
them before doing anything, and without them each judgement about whether something is
deliberate has to be asked rather than looked up.

Everything here uses **C3 = MIDI 60**.
