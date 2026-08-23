# reference/manuals/

Plugin and hardware documentation. This directory is meant to be a symlink to wherever you
keep vendor PDFs.

```bash
rm -rf reference/manuals
ln -s ~/Manuals ~/music-studio/ableton-scaffold/reference/manuals
```

The contents are gitignored. Vendor PDFs are not ours to redistribute and some are large.

## What belongs here

- The manual for every plugin in a mix chain you expect to configure
- The vendor keymap for every sampled instrument you program MIDI into
- Music theory references, if you want them in reach

## Why the mix-chain and rhythm agents insist on these

Parameter ranges, units and note maps remembered from training data are wrong often
enough to be useless, and wrong in ways that sound plausible. Two examples that cost real
time: a reverb whose decay parameter is a percentage rather than a time in seconds, and a
tape echo whose minimum rate on one head was nearly 100 ms off the assumed value.

A vendor keymap PDF also beats every secondary drum map. Screenshots, spreadsheets and
"reference" tables of note mappings have been found to contradict the vendor map, to
contradict each other, and to contain internal duplicates, all while the real keymap sat
in the manuals folder unused.

Cite the manual. Where no manual exists, read the value off the device itself with
`bridge/device.py --list-params` and quote that.
