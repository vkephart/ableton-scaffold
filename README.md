# ableton-scaffold

Tooling for producing music in Ableton Live with Claude Code: a bridge to the running
session, specialist agents, slash commands, and the conventions that keep their output
trustworthy.

**No song content lives here.** Songs live in their own repos, one per track, outside this
one. This repo holds method.

## What is in it

| Path | What |
|---|---|
| `bridge/` | Python scripts talking to AbletonOSC and AbletonMCP: pull, push, device parameters |
| `abletonosc-ext/` | Two AbletonOSC handler modules stock does not ship: arrangement clip notes, return tracks |
| `.claude/agents/` | Five specialist agents: orchestrator, structure, harmony, rhythm, mix-chain |
| `.claude/commands/` | `/pull`, `/push`, `/device`, `/log`, `/song` |
| `templates/song/` | Starting files for a new track repo |
| `CLAUDE.md` | Conventions and method, loaded at the start of every session |
| `SETUP.md` | One-time installation |

## Quick start

```bash
git clone <this-repo> ~/music-studio/ableton-scaffold
cd ~/music-studio/ableton-scaffold
pip3 install --break-system-packages -r bridge/requirements.txt
export ABLETON_SONGS_DIR=~/music-studio
python3 bridge/osc_client.py --check
```

Full installation, including the AbletonOSC remote script and the extension handlers, is
in `SETUP.md`.

## Layout

Song folders are resolved from `--songs-dir`, then `$ABLETON_SONGS_DIR`, then `./songs`,
then this repo. Nothing assumes songs live inside this checkout.

```
~/music-studio/
  ableton-scaffold/     this repo
  <song-name>/          a track repo, private
  <another-song>/
```

## Requirements

- Ableton Live 11 or later
- Python 3.7 or later for the bridge scripts. Note that the remote script handlers in
  `abletonosc-ext/` must themselves stay 3.7-compatible, because Live embeds CPython 3.7.
  `bridge/check_py37.py` enforces that.
- AbletonOSC, and AbletonMCP for note writes

## Conventions

**C3 = MIDI 60.** **Arrangement view, not Session view.** **Plugin parameters in real UI
units.** The reasoning behind these, and the method rules the agents work under, are in
`CLAUDE.md`.
