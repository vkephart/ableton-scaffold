# /log

Append a dated decision entry to the active song's `log.md`.

## Usage

```
/log Resolved intro bar count: 10.5 bars, not 8. Verified against arrangement clip boundaries.
```

## What it does

Appends to the song's `log.md`:

```
## [date] — [message]
```

## When to use

- Before ending any session
- When an entry in `conflicts.md` is resolved, including what resolved it
- When a production decision is made that should survive context loss
- When a measurement contradicts a document, so the correction has a reason attached

## Format

Append-only. Oldest at the top, newest at the bottom. Do not edit existing entries; add
new ones. A wrong entry gets a later entry correcting it, which is itself useful history.

Entries should be specific enough that a session with no context understands what was done
and why.

**Good:** "Set Pro-R Decay Rate to 120% on Return A. Previous 80% was too short for the
bloom on the final note. Tested at the outro."

**Bad:** "Updated reverb settings."

The difference matters most for decisions that look like mistakes later. An unusual choice
recorded with its reason is a decision. The same choice recorded without one gets
"corrected" by a future session.
