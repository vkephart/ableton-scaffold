"""
take.py: what was played in a recorded take, and where, offline. No capture, no playback.

    bin/analysis-python bridge/take.py take.aif --tempo 120 --clip-beat 64 --file-sample 84943.8
    bin/analysis-python bridge/take.py --live "Guitar" 64 --from-bar 17 --to-bar 24
    bin/analysis-python bridge/take.py take.aif ... --drift 4
    bin/analysis-python bridge/take.py --self-test

Reads the audio file an Arrangement clip plays and reports every picked or struck onset:
its ruler position (bar.beat.sixteenth, nearest sixteenth), how far it sits from that grid
line in milliseconds (played minus grid, so + is late), its peak level, and the pitches
sounding just after it, strongest partials first, as note name, MIDI number and cents.

It answers "did I play the notes I meant, on the beat I meant" from the dry recording, so
it needs neither a capture nor the interface. What it reads is the file: the take before
the track's devices. Pitch and timing hold through an amp or an echo; level and ring length
do not.

An onset has to show an energy step to be listed: the 25 ms after it against the 25 ms
before, in the whole band and above 3 kHz. A ringing note fluctuates, and a detector that
watches the spectrum alone reports those fluctuations as soft strokes at plausible grid
positions. Candidates without the step are counted and dropped; --all lists them, marked.

--live TRACK CLIP_START asks the open set for the file and for the sample that sits at the
clip's left edge (the extension's /live/arrangement_clip/get/audio), and the tempo, so the
three placement flags are not needed. CLIP_START is the clip's start in song beats.
Without it, give --tempo, --clip-beat (song beat of the clip's left edge, bar 1 beat 1 = 0)
and --file-sample (the file sample played there; 0 for an untrimmed take). A warped clip is
assumed to play at the recorded tempo, which is true of a take recorded into the set and
never stretched; the script says so and stops if the clip's length and its samples disagree.

--drift N follows the strongest partial of each onset for up to N beats and prints its
pitch each half beat, in cents against concert pitch: a vibrato arm, a bend, a string
going flat.

Import it for anything else: onsets(), pitches(), drift().
"""
import argparse, math, os, sys

import numpy as np
from scipy import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import load, ruler, db

NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def midi_of(freq):
    return 69 + 12 * math.log2(freq / 440.0)


def note(freq):
    """A frequency as name(MIDI)+cents, C3 = MIDI 60 left to the reader: the number is the fact."""
    m = midi_of(freq)
    r = int(round(m))
    return f"{NAMES[r % 12]}({r}){(m - r) * 100:+.0f}c"


def _rms_db(y, a, b):
    a, b = max(a, 0), min(b, len(y))
    if b <= a:
        return -200.0
    return float(db(np.sqrt(np.mean(y[a:b] ** 2)) + 1e-12))


def onsets(x, sr, min_gap_s=0.09, full_step_db=3.0, high_step_db=6.0):
    """Candidate onsets by spectral flux, each tested for an energy step.

    Returns a list of dicts: sample, full_step_db, high_step_db, struck (True when both
    steps clear their thresholds). The flux alone is not trusted: see the module docstring.
    """
    n_fft, hop = 1024, 128
    f, t, z = signal.stft(x, sr, window="hann", nperseg=n_fft, noverlap=n_fft - hop,
                          boundary=None, padded=False)
    mag = np.abs(z)[f > 150]
    log = np.log1p(200 * mag)
    flux = np.concatenate([[0], np.maximum(log[:, 1:] - log[:, :-1], 0).sum(axis=0)])
    floor = signal.medfilt(flux, 101) + 0.25 * np.percentile(flux, 99.5)
    peaks, _ = signal.find_peaks(flux, height=floor, distance=max(1, int(min_gap_s * sr / hop)))
    high = signal.sosfiltfilt(signal.butter(4, 3000, btype="high", fs=sr, output="sos"), x)
    w, guard = int(0.025 * sr), int(0.005 * sr)
    out = []
    for p in peaks:
        n = int(t[p] * sr)
        a = n - int(0.012 * sr)  # the flux frame's centre sits a little after the rise
        full = _rms_db(x, a, a + w) - _rms_db(x, a - w - guard, a - guard)
        hi = _rms_db(high, a, a + w) - _rms_db(high, a - w - guard, a - guard)
        out.append({"sample": n, "full_step_db": full, "high_step_db": hi,
                    "struck": full >= full_step_db and hi >= high_step_db})
    return out


def _spectrum(seg, sr, n_fft=1 << 17):
    s = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n_fft))
    return np.fft.rfftfreq(n_fft, 1 / sr), s


def pitches(seg, sr, lo=60.0, hi=2500.0, top=5, floor=0.06):
    """Strongest spectral peaks of a segment, as (Hz, dB under the strongest), low to high."""
    fr, s = _spectrum(seg, sr)
    m = (fr > lo) & (fr < hi)
    sm, fm = s[m], fr[m]
    if not len(sm) or sm.max() <= 0:
        return []
    pk, _ = signal.find_peaks(sm, height=sm.max() * floor, distance=max(1, int(12 / (fr[1] - fr[0]))))
    order = np.argsort(sm[pk])[::-1][:top]
    return sorted((float(fm[pk[i]]), float(db(sm[pk[i]] / sm.max()))) for i in order)


def drift(x, sr, start, freq, seconds, step_s, win_s=0.14):
    """Pitch of the partial near freq from a start sample on: (seconds in, cents, dB).

    Cents are against the equal-tempered pitch nearest freq, so a string that rests sharp
    reads sharp from the first row. Looks from 2.5 semitones under to 1 over.
    """
    ref = 440.0 * 2 ** ((round(midi_of(freq)) - 69) / 12)
    rows, w = [], int(win_s * sr)
    k = 0
    while k * step_s < seconds:
        a = start + int(k * step_s * sr)
        if a + w > len(x):
            break
        fr, s = _spectrum(x[a:a + w], sr)
        m = (fr > ref * 2 ** (-250 / 1200)) & (fr < ref * 2 ** (100 / 1200))
        i = int(np.argmax(s[m]))
        rows.append((k * step_s, 1200 * math.log2(fr[m][i] / ref), float(db(s[m][i] / (w / 4) + 1e-12))))
        k += 1
    return ref, rows


def report(path, tempo, clip_beat, file_sample, per_bar=4, from_bar=None, to_bar=None,
           show_all=False, drift_beats=0.0, out=sys.stdout):
    x2, sr = load(path)
    x = x2.mean(axis=1)
    spb = 60.0 / tempo

    def beat_of(n):
        return clip_beat + (n - file_sample) / sr / spb

    found = onsets(x, sr)
    lo = (from_bar - 1) * per_bar if from_bar else -1e9
    hi = to_bar * per_bar if to_bar else 1e9
    found = [o for o in found if lo <= beat_of(o["sample"]) < hi]
    struck = [o for o in found if o["struck"]]
    print(f"{os.path.basename(path)}: {len(x) / sr:.2f} s at {sr} Hz, peak {db(np.max(np.abs(x))):.1f} dBFS", file=out)
    print("the file is the take before the track's devices: pitch and timing hold through them, level and ring do not", file=out)
    print(f"{len(struck)} onsets with an energy step; {len(found) - len(struck)} candidates without one "
          f"({'listed, marked' if show_all else 'dropped; --all lists them'})", file=out)
    print("position is the nearest sixteenth; off = played minus grid, + is late\n", file=out)
    rows = []
    listed = found if show_all else struck
    for i, o in enumerate(listed):
        n = o["sample"]
        nxt = listed[i + 1]["sample"] if i + 1 < len(listed) else len(x)
        a = n + int(0.03 * sr)
        b = max(a + int(0.05 * sr), min(nxt - int(0.01 * sr), a + int(0.35 * sr)))
        pk = pitches(x[a:b], sr)
        beat = beat_of(n)
        grid = round(beat * 4) / 4
        off_ms = (beat - grid) * spb * 1000
        peak = float(db(np.max(np.abs(x[max(0, n - int(0.01 * sr)):n + int(0.15 * sr)])) + 1e-12))
        mark = "" if o["struck"] else "  (no energy step: not a stroke)"
        notes = "  ".join(f"{note(fq)} {lv:+.0f}" for fq, lv in pk)
        print(f"{ruler(grid, per_bar):>10}  off {off_ms:+4.0f} ms  peak {peak:6.1f} dBFS  | {notes}{mark}", file=out)
        rows.append({"beat": beat, "position": ruler(grid, per_bar), "off_ms": off_ms, "peak_dbfs": peak,
                     "pitches": pk, "struck": o["struck"]})
        if drift_beats and o["struck"] and pk:
            strongest = max(pk, key=lambda p: p[1])[0]
            seconds = min(drift_beats * spb, (nxt - n) / sr - 0.2)  # stop before the next stroke enters the window
            ref, dr = drift(x, sr, n + int(0.02 * sr), strongest, seconds, spb / 2)
            line = "  ".join(f"{c:+.0f}" for _, c, lv in dr if lv > -80)
            print(f"{'':>10}  {note(ref)[:-3]} each half beat, cents: {line}", file=out)
    return rows


def from_live(track_name, clip_start):
    """File, tempo and placement of an Arrangement audio clip, asked of the open set."""
    from osc_client import OscClient
    c = OscClient()
    try:
        index = next((i for i, n in c.get_track_names() if n == track_name), None)
        if index is None:
            raise SystemExit(f"no track named {track_name!r} in the open set")
        tempo = float(c.query("/live/song/get/tempo", "/live/song/get/tempo")[0])
        a = list(c.query("/live/arrangement_clip/get/audio", "/live/arrangement_clip/get/audio",
                         index, float(clip_start), timeout=4))
    finally:
        c.close()
    if len(a) < 14:
        raise SystemExit(f"no audio clip starts at beat {clip_start} on {track_name!r}: {a[2:]}")
    # track, start, end, name, path, gain, gain string, start marker, end marker, warping,
    # warp mode, file samples, sample rate, sample at the start marker, sample at the end marker
    path, start_marker, end_marker, warping = str(a[4]), float(a[7]), float(a[8]), bool(a[9])
    sr = float(a[12])
    if warping:
        s0, s1 = float(a[13]), float(a[14])
        played = (s1 - s0) / sr
        meant = (end_marker - start_marker) * 60.0 / tempo
        if abs(played - meant) > 0.02:
            raise SystemExit(f"the clip is stretched ({played:.2f} s of file for {meant:.2f} s of song): "
                             "its file does not sit on the grid at the set's tempo, so positions would be wrong")
    else:
        s0 = start_marker * sr  # an unwarped clip counts its markers in seconds
    return path, tempo, float(clip_start), s0


def self_test():
    """Three struck tones at known beats and a slow fluctuation that must not be listed."""
    sr, tempo = 44100, 120.0
    spb = 60.0 / tempo
    x = np.zeros(int(8 * spb * sr))
    rng = np.random.default_rng(1)
    want = [(1.0, 440.0), (3.5, 587.33), (6.0, 349.23)]
    for beat, f0 in want:
        n = int(beat * spb * sr)
        t = np.arange(len(x) - n) / sr
        tone = 0.3 * np.exp(-t * 1.2) * (np.sin(2 * np.pi * f0 * t) + 0.3 * np.sin(2 * np.pi * 2 * f0 * t))
        click = np.zeros(len(t))
        k = int(0.004 * sr)
        click[:k] = 0.2 * rng.standard_normal(k) * np.linspace(1, 0, k)
        # a ring that wavers by a decibel: fluctuation, no new stroke
        x[n:] += tone * (1 + 0.1 * np.sin(2 * np.pi * 7.5 * t)) + click
    got = [o for o in onsets(x, sr) if o["struck"]]
    ok = len(got) == len(want)
    for o, (beat, f0) in zip(got, want):
        b = o["sample"] / sr / spb
        pk = pitches(x[o["sample"] + int(0.03 * sr):o["sample"] + int(0.3 * sr)], sr)
        strongest = max(pk, key=lambda p: p[1])[0]
        ok = ok and abs(b - beat) * spb < 0.02 and abs(1200 * math.log2(strongest / f0)) < 10
    print("self-test:", "ok" if ok else "FAILED", f"({len(got)} struck onsets, {len(want)} expected)")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Onsets, positions and pitches of a recorded take.")
    ap.add_argument("file", nargs="?", help="the audio file the clip plays")
    ap.add_argument("--live", nargs=2, metavar=("TRACK", "CLIP_START"),
                    help="ask the open set for the file and its placement")
    ap.add_argument("--tempo", type=float, help="BPM")
    ap.add_argument("--clip-beat", type=float, help="song beat of the clip's left edge (bar 1 beat 1 = 0)")
    ap.add_argument("--file-sample", type=float, default=0.0, help="file sample played at the clip's left edge")
    ap.add_argument("--per-bar", type=int, default=4)
    ap.add_argument("--from-bar", type=int)
    ap.add_argument("--to-bar", type=int, help="last bar to include")
    ap.add_argument("--all", action="store_true", help="also list candidates that show no energy step")
    ap.add_argument("--drift", type=float, default=0.0, metavar="BEATS",
                    help="follow each onset's strongest partial this many beats")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    if a.live:
        path, tempo, clip_beat, file_sample = from_live(a.live[0], float(a.live[1]))
        print(f"from the open set: {path}\ntempo {tempo:.2f}, clip at beat {clip_beat:g}, file sample {file_sample:.1f} at its left edge\n")
    else:
        if not a.file or a.tempo is None or a.clip_beat is None:
            ap.error("give a file with --tempo and --clip-beat, or --live TRACK CLIP_START")
        path, tempo, clip_beat, file_sample = a.file, a.tempo, a.clip_beat, a.file_sample
    report(path, tempo, clip_beat, file_sample, per_bar=a.per_bar, from_bar=a.from_bar, to_bar=a.to_bar,
           show_all=a.all, drift_beats=a.drift)


if __name__ == "__main__":
    main()
