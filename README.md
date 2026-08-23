# ableton-scaffold

Tooling for producing music in Ableton Live with Claude Code: a bridge to the running
session, five specialist agents, slash commands, and the conventions that keep their
output trustworthy.

**No song content lives here.** Each song is its own private repo. This one holds method,
and it is the repo you point a new song at.

---

## Starting a new song

One command. It creates the track repo next to this one, fills it with templates, and
wires this repo's agents and commands into it.

```bash
bin/new-song <song-name>
```

Then:

```bash
cd ../<song-name>
# fill in brief.md and structure.md
claude
```

That session reads the track repo's own `CLAUDE.md`, picks up all five agents and all
slash commands, and can reach the bridge scripts. With Ableton open, `/pull` captures the
session into `parts/` and `chain/`.

**Fill in `brief.md` before doing musical work.** Every agent reads it first, and its
"Deliberate choices that look like mistakes" section is what stops a future session
"correcting" an unresolved ending or an intentionally empty track.

### Why the wiring step exists

A Claude Code session started in a track repo sees that repo's `CLAUDE.md`, `.claude/agents/`
and `.claude/commands/`, and nothing from a sibling repo. Without wiring, a new song folder
gets no agents, no commands and no conventions, and the scaffold does nothing for it.

`bin/new-song` writes a `CLAUDE.md` into the track repo and symlinks each agent and command
file back here. Editing an agent in this repo therefore changes it in every song at once,
with no copies to drift. The symlinks are gitignored in the track repo, because the
scaffold's path differs per machine. After cloning a track repo elsewhere:

```bash
<scaffold>/bin/new-song <song-name> --relink
```

`new-song` is safe to re-run. It creates only files that are missing and never overwrites
work you have edited.

---

## Layout

```
~/music-studio/
  ableton-scaffold/     this repo, shareable
  <song-name>/          a track repo, private
  <another-song>/
```

Song folders are resolved by every bridge script the same way, first hit wins:
`--songs-dir`, then `$ABLETON_SONGS_DIR`, then `./songs`, then this repo. Nothing assumes
songs live inside this checkout.

```bash
export ABLETON_SONGS_DIR=~/music-studio
```

---

## What is in it

| Path | What |
|---|---|
| `bin/new-song` | Create or re-wire a track repo |
| `bridge/` | Scripts talking to AbletonOSC and AbletonMCP: pull, push, device parameters |
| `abletonosc-ext/` | Two AbletonOSC handler modules stock does not ship: arrangement clip notes, return tracks |
| `.claude/agents/` | orchestrator, structure, harmony, rhythm, mix-chain |
| `.claude/commands/` | `/pull`, `/push`, `/device`, `/log`, `/song` |
| `templates/song/` | The documents a track repo starts with |
| `templates/track-repo/` | The `CLAUDE.md` written into a new track repo |
| `CLAUDE.md` | Conventions and method, loaded at the start of every session here |
| `SETUP.md` | One-time installation |

---

## Installation

Full steps are in `SETUP.md`. The short version:

```bash
git clone <this-repo> ~/music-studio/ableton-scaffold
cd ~/music-studio/ableton-scaffold
pip3 install --break-system-packages -r bridge/requirements.txt
export ABLETON_SONGS_DIR=~/music-studio
python3 bridge/osc_client.py --check
```

`osc_client.py --check` reporting the open set's tempo means the connection works. It
requires AbletonOSC installed as a MIDI Remote Script and the handlers from
`abletonosc-ext/` applied, both covered in `SETUP.md`.

**Requirements:** Ableton Live 11 or later; Python 3.7+ for the bridge scripts; AbletonOSC,
and AbletonMCP for note writes. The handler modules in `abletonosc-ext/` must themselves
stay 3.7-compatible, because Live embeds CPython 3.7 and newer syntax makes the control
surface fail to load with no error. `bridge/check_py37.py` enforces that; run it before
copying anything into Remote Scripts.

---

## Conventions

**C3 = MIDI 60.** **Arrangement view, not Session view.** **The session is source of truth,
pull output is a cache.** **Plugin parameters in real UI units, never raw values.**

The reasoning behind each, and the method rules the agents work under, are in `CLAUDE.md`.
They are there because each one cost a session to learn: a vendor keymap contradicted by
three loose drum maps, parameter values whose raw scale differs per parameter on the same
device, a hi-hat part written at velocity 1 and therefore silent, and documentation that
disagreed with the session in eight places on the first day anyone checked.

## License

MIT. See `LICENSE`.
