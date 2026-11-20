# sketch

Browser instruments for sketching a song away from Ableton: on a phone or tablet, with
nothing installed. The page synthesizes every sound in the browser's own audio engine and
plays note lists in the same shape as the part files `/push` reads (pitch with C3 = 60,
start and duration in beats, velocity), so a sketch can go into a Session clip later
without being rewritten.

**Status: proof 2.** One page, one built-in test loop (4 bars, three parts), a tape-style
master chain, pads for auditioning, and a sound check (output meter, raw test tone, the
loop rendered to a file player) for telling a muted device from an engine that is not
running. It does not yet load part files, edit notes or export
MIDI.

No song content lives here. The loop in the page is a test pattern.

## Files

- `index.html` is the whole kit: engine, test loop and controls in one file, publishable
  as it stands.
- `check.js` runs the page in headless Chromium: renders the loop offline through the
  same engine (mix and each part alone) and writes WAVs, then presses Play at phone size
  and checks the audio context ran and the playhead moved.

```
NODE_PATH=<playwright's node_modules> node sketch/check.js /tmp/sketch-render
bin/analysis-python bridge/measure.py /tmp/sketch-render/mix.wav
```

## What the check does and does not tell you

It says the page runs in Chromium and what the render measures. It does not say how the
instruments sound, and it does not cover Safari on iOS, where audio starts only after a
tap and the silent switch can mute a web page. Those are checked by ear on the device.

Timbre here is an ear call like anywhere else in this repo. The measurements are for
level and placement: the first render had the bass 6 LU over the drums with almost
nothing above 150 Hz, which a phone speaker would have played as silence.
