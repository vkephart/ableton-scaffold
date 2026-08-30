# Song templates

The documents a track repo starts with. Do not copy these by hand; the bootstrap script
places them, along with the track repo's `CLAUDE.md` and the symlinks that make the agents
and slash commands available there:

```bash
<scaffold>/bin/new-song <name>
```

`brief.md` and `structure.md` are the two to fill in first. Every specialist agent reads
them before doing anything, and without them each judgement about whether something is
deliberate has to be asked rather than looked up.

`structure.md` is canonical for section names. `harmony.md` and `lyrics.md` name their
sections by matching it, so none of the three ships a section list of its own: a prefilled
form would be a claim about a song that does not exist yet, and the three copies would
drift apart the first time one was edited alone.

Everything here uses **C3 = MIDI 60**.

Editing a file in this folder changes what future songs start with. It does not change any
existing track repo, because these are copied once at creation rather than symlinked. The
agents and commands are the opposite: symlinked, so an edit reaches every song at once.
