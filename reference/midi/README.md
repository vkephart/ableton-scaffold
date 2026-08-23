# reference/midi/

MIDI reference material: keymaps, piano roll screenshots, template MIDI files.

The contents are gitignored. This folder is a working area, not a versioned asset store.

## Drum note maps

**The authority is always the vendor keymap PDF in `reference/manuals/`.** Not a PNG, not
a spreadsheet, not a table in an older document, not training data.

Loose drum-map files accumulate in Downloads and Documents folders and they are routinely
wrong. On one machine, three of them disagreed with the vendor PDF and with each other,
each contained internal duplicates, and between them they misidentified a side-stick as a
closed hi-hat, a closed hi-hat as a high tom, and a cymbal as a closed hi-hat. Programming
from any of them writes a whole song onto the wrong articulations, and nothing reports an
error.

When you find files like that, move them somewhere out of reach rather than ignoring them,
and record where they went. Otherwise the next session finds them again and has to
re-derive that they are wrong.

**Check the keymap's octave convention.** This workspace uses C3 = 60, so a vendor PDF
listing C5 = 84 agrees with it. One that disagrees shifts every note by twelve.

## MIDI files

Canonical `.mid` files belong in the Ableton project folder, not here. A song's `files.md`
should inventory them.

After a `/pull`, note data is captured as markdown in the song's `parts/`, and those files
push back with `/push`.
