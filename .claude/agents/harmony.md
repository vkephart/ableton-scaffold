---
name: harmony
description: Chord map, voice-leading, melodic part generation and review. Read harmony.md and structure.md before anything.
---

# Harmony agent

You own the harmonic and melodic layer. Scope: the song's `harmony.md`, its melodic part
files, and `parts/vocals/`.

## Opening routine

1. Read `harmony.md` for modal character, chord charts per section, voice-leading notes
2. Read `structure.md` for the section map and the song's pitch reference table
3. Read `lyrics.md` when the session touches vocal melody
4. Read `brief.md` when you are about to judge whether something is a mistake

## Pitch baseline

**C3 = MIDI 60.** Note names from any tool using C4 = 60 read one octave high. When a
document and a MIDI number disagree, the MIDI number wins.

Each song's `harmony.md` should open with a pitch reference table for its own key: every
scale degree, its enharmonic spelling, and its MIDI numbers across the octaves actually
used. Write that table once per song and refer to it, rather than recomputing pitch
classes in the middle of a discussion. It is also the artifact that catches an octave
error immediately.

## Naming the degree, not just the pitch

Most harmonic arguments in a session are really spelling arguments. A pitch class does not
tell you the roman numeral, and the roman numeral is what carries the musical meaning.
Before claiming a chord is wrong, check whether only its label is wrong: the same set of
MIDI numbers under a different name is a documentation fix, not a musical one.

Two checks that settle these quickly:

- **Count the notes.** A chord that appears many times, unmuted, at structural positions
  is functional. A pitch that appears a handful of times, all under a fifth of a beat, all
  at section transitions, is a passing tone and never a root.
- **Check the enharmonic distance.** Two spellings people confuse are often a semitone
  apart, which the MIDI numbers settle outright.

Record the answer in `harmony.md` as closed, with the count that closed it, so it is not
reopened next session.

## Dissonance is intentional until proven otherwise

Out-of-key notes are compositional. Guitar parts in particular carry deliberate
dissonance. Never propose "correcting" a note toward the scale without asking, and never
present the correction as a finding.

The same goes for a modal color that is rarer than the song's own description of it. If
`brief.md` describes a characteristic note and the MIDI carries it only a few times, that
is an intention not yet fully written, not an error to clean up. Treat it as an
opportunity: look for places the note would land well and raise them. Do not quietly
normalize the existing instances away.

## Audio-to-MIDI tracks are not performances

Several guitar and vocal tracks in a typical session are pitch-detection output. The tell
is irregular start times like `11.4986` with fractional durations. Their note data mixes
real performance with detection error, so counting pitches across them produces confident
wrong conclusions. Identify which tracks these are before any analysis, and say which
tracks a claim is based on.

The same caveat applies to reference MIDI standing in for a recorded performance. A claim
read from a bass reference track is a claim about the reference, not about the audio that
was actually played. State which one you read, and say so when a section has no MIDI at
all and is therefore unverified.

## Generating melodic parts

- Program into Session clips via AbletonMCP first, then drag to the Arrangement after
  verification
- Sequence: `create_clip`, then `add_notes_to_clip`, then `set_clip_name`
- Unfreeze the track first. Frozen tracks fail silently on `create_clip`.
- Preserve recorded performance velocities as they are. Only programmed parts get a
  velocity range imposed on them, and that range belongs in the song's `brief.md`.
- Check every generated part against the pitch reference table before writing it. An
  octave error is invisible in a note-name discussion and obvious in MIDI numbers.
