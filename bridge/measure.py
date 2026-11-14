"""
measure.py: level, loudness and decay of a captured sound, offline. No OSC, no Live.

    bin/analysis-python bridge/measure.py hit.aif
    bin/analysis-python bridge/measure.py hit.aif --tempo 120 --anchor-beat 64
    bin/analysis-python bridge/measure.py hit.aif --against vocal.aif --against bus.aif --tempo 120 --anchor-beat 64
    bin/analysis-python bridge/measure.py --self-test

The first file is the event: one sound whose level and tail are in question. It reports
sample peak, RMS, loudness (momentary and short-term maxima, BS.1770 K-weighting; the
integrated figure is printed too but is unstable on a single hit), where the sound starts,
and how long after the start it takes to fall 6, 10, 20, 30, 40 and 60 dB for good, in
milliseconds. "For good" means the last moment the 50 ms RMS envelope is above that line,
so a tail that wobbles is not called finished early. A fall the file ends before reaching
is reported as not reached, never extrapolated; the fitted rate in dB per second is given
separately and labelled a fit.

With --tempo and --anchor-beat the start of the event is pinned to that song beat (the
beat its note sits on), and every time is also given as a ruler position, bar.beat.sixteenth.
The anchor comes from the audio, not from a playhead read, which is not exact.

--against files must come from the same capture run as the event (sample-aligned). For
each beat they are set beside the event: level of each, and how far the event sits under or
over, which is the number that says whether a tail is sitting on a voice.

sample.py runs this after a capture. Import it for anything else: load(), levels(),
loudness(), envelope(), event(), beside().
"""
import argparse, json, math, sys
import numpy as np
import soundfile as sf
from scipy import signal

FALLS = (6, 10, 20, 30, 40, 60)


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-12))


def load(path):
    """Audio as float64, always two columns, and the sample rate."""
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return x[:, :2], sr


def ruler(beat, per_bar=4):
    """Song beat (0 = bar 1 beat 1) as Live's ruler: bar.beat.sixteenth."""
    bar = int(math.floor(beat / per_bar)) + 1
    rem = beat - (bar - 1) * per_bar
    b = int(math.floor(rem + 1e-9)) + 1
    six = (rem - (b - 1)) * 4 + 1
    s = f"{six:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return f"{bar}.{b}.{s}"


def levels(x):
    pk = float(db(np.abs(x).max()))
    rms = float(db(np.sqrt((x ** 2).mean())))
    return {"peak_dbfs": round(pk, 2), "rms_dbfs": round(rms, 2), "crest_db": round(pk - rms, 2)}


def _k_weight(x, sr):
    """BS.1770 K-weighting: a high shelf (+4 dB above about 1.5 kHz) then a 38 Hz high-pass."""
    def shelf(g, q, fc):
        a_ = 10 ** (g / 40); w = 2 * math.pi * fc / sr; al = math.sin(w) / (2 * q); c = math.cos(w)
        b = [a_ * ((a_ + 1) + (a_ - 1) * c + 2 * math.sqrt(a_) * al), -2 * a_ * ((a_ - 1) + (a_ + 1) * c),
             a_ * ((a_ + 1) + (a_ - 1) * c - 2 * math.sqrt(a_) * al)]
        a = [(a_ + 1) - (a_ - 1) * c + 2 * math.sqrt(a_) * al, 2 * ((a_ - 1) - (a_ + 1) * c),
             (a_ + 1) - (a_ - 1) * c - 2 * math.sqrt(a_) * al]
        return np.array(b) / a[0], np.array(a) / a[0]

    def highpass(q, fc):
        w = 2 * math.pi * fc / sr; al = math.sin(w) / (2 * q); c = math.cos(w)
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]; a = [1 + al, -2 * c, 1 - al]
        return np.array(b) / a[0], np.array(a) / a[0]

    y = x
    for b, a in (shelf(4.0, 1 / math.sqrt(2), 1500.0), highpass(0.5, 38.0)):
        y = signal.lfilter(b, a, y, axis=0)
    return y


def _block_loudness(y, sr, win_s, hop_s):
    """Loudness of each window of K-weighted audio y, channels summed in power."""
    win = int(round(win_s * sr)); hop = max(1, int(round(hop_s * sr)))
    if len(y) < win:
        return np.array([]), np.array([])
    p = (y ** 2).sum(axis=1)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    starts = np.arange(0, len(y) - win + 1, hop)
    ms = (cs[starts + win] - cs[starts]) / win
    return starts / sr, -0.691 + 10 * np.log10(np.maximum(ms, 1e-20))


def loudness(x, sr):
    """Momentary (400 ms) and short-term (3 s) maxima and the gated integrated figure, LUFS."""
    y = _k_weight(x, sr)
    out = {}
    t, m = _block_loudness(y, sr, 0.4, 0.1)
    out["momentary_max_lufs"] = round(float(m.max()), 2) if len(m) else None
    out["momentary_max_at_s"] = round(float(t[np.argmax(m)]), 3) if len(m) else None
    t3, s3 = _block_loudness(y, sr, 3.0, 0.1)
    out["short_term_max_lufs"] = round(float(s3.max()), 2) if len(s3) else None
    out["integrated_lufs"] = None
    if len(m):
        gated = m[m > -70.0]
        if len(gated):
            rel = 10 * np.log10(np.mean(10 ** ((gated + 0.691) / 10))) - 0.691 - 10.0
            g2 = gated[gated > rel]
            if len(g2):
                out["integrated_lufs"] = round(float(10 * np.log10(np.mean(10 ** ((g2 + 0.691) / 10))) - 0.691), 2)
    return out


def envelope(x, sr, win_ms=50.0, hop_ms=5.0):
    """RMS envelope in dBFS (power averaged over both channels). Returns window-centre times and dB."""
    win = max(1, int(round(win_ms / 1000 * sr))); hop = max(1, int(round(hop_ms / 1000 * sr)))
    p = (x ** 2).mean(axis=1)
    cs = np.concatenate([[0.0], np.cumsum(p)])
    if len(p) < win:
        return np.array([0.0]), np.array([float(db(np.sqrt(p.mean())))])
    starts = np.arange(0, len(p) - win + 1, hop)
    ms = (cs[starts + win] - cs[starts]) / win
    return (starts + win / 2) / sr, 10 * np.log10(np.maximum(ms, 1e-24))


def event(x, sr, onset_under_peak_db=34.0, silent_below_dbfs=-70.0):
    """The one sound in the file: where it starts, its peak, and how long it takes to fall."""
    mag = np.abs(x).max(axis=1)
    pk = float(mag.max())
    out = {"found": bool(db(pk) > silent_below_dbfs)}
    if not out["found"]:
        return out
    on = int(np.argmax(mag >= pk * 10 ** (-onset_under_peak_db / 20)))
    out["onset_s"] = round(on / sr, 4)
    out["peak_s"] = round(int(np.argmax(mag)) / sr, 4)
    t, e = envelope(x, sr, 50.0, 5.0)
    after = t >= on / sr
    if not after.any():
        return out
    ip = int(np.argmax(np.where(after, e, -1e9)))
    epk = float(e[ip]); out["env_peak_dbfs"] = round(epk, 2); out["env_peak_s"] = round(float(t[ip]), 3)
    out["file_length_s"] = round(len(x) / sr, 3)
    out["tail_end_dbfs"] = round(float(e[-20:].mean()), 2)   # last 100 ms
    falls = {}
    for d in FALLS:
        above = np.nonzero((e > epk - d) & (t >= t[ip]))[0]
        last = int(above[-1]) if len(above) else ip
        reached = last < len(e) - 20                      # stays under for the final 100 ms at least
        falls[str(d)] = round(float(t[last] - on / sr) * 1000.0, 0) if reached else None
    out["fall_ms_after_onset"] = falls
    seg = (np.arange(len(e)) > ip) & (e < epk - 5) & (e > epk - 25)
    if seg.sum() >= 10:
        slope = np.polyfit(t[seg], e[seg], 1)[0]
        out["fit_db_per_s"] = round(float(slope), 1)
        out["fit_60db_s"] = round(float(-60.0 / slope), 2) if slope < 0 else None
    return out


def beside(files, sr, file0_beat, tempo, from_beat, to_beat, step_beats=1.0):
    """Per step of the ruler: RMS dBFS of each aligned file. files is {label: samples}."""
    rows = []
    spb = 60.0 / tempo * sr
    b = from_beat
    while b < to_beat - 1e-9:
        s = int(round((b - file0_beat) * spb)); e = int(round((b + step_beats - file0_beat) * spb))
        row = {"beat": b}
        for label, x in files.items():
            if s < 0 or e > len(x) or e <= s:
                row[label] = None
            else:
                row[label] = round(float(db(np.sqrt((x[s:e] ** 2).mean()))), 1)
        rows.append(row); b += step_beats
    return rows


def report(event_path, against=(), tempo=None, anchor_beat=None, file0_beat=None, per_bar=4,
           from_beat=None, to_beat=None, step_beats=1.0, labels=None, out=sys.stdout):
    """Measure and print. Returns everything as a dict (the same content as --json)."""
    x, sr = load(event_path)
    labels = labels or {}
    name = labels.get(event_path, event_path)
    res = {"event_file": event_path, "sample_rate": sr, "levels": levels(x), "loudness": loudness(x, sr), "event": event(x, sr)}
    ev = res["event"]
    p = lambda *a: print(*a, file=out)
    p(f"EVENT  {name}   ({sr} Hz, {len(x) / sr:.2f} s)")
    if not ev.get("found"):
        p("  no sound found in this file (peak under -70 dBFS). Nothing measured.")
        return res
    if tempo and anchor_beat is not None:
        file0_beat = anchor_beat - ev["onset_s"] * tempo / 60.0
        res["anchored_on"] = "onset pinned to the anchor beat"
    elif tempo and file0_beat is not None:
        res["anchored_on"] = "file start beat given by the caller (a playhead read, approximate)"
    res["file0_beat"] = file0_beat
    at = (lambda s: " = " + ruler(file0_beat + s * tempo / 60.0, per_bar)) if (tempo and file0_beat is not None) else (lambda s: "")
    lv, lo = res["levels"], res["loudness"]
    p(f"  sample peak        {lv['peak_dbfs']:7.1f} dBFS   at {ev['peak_s']:.3f} s{at(ev['peak_s'])}")
    p(f"  starts             {ev['onset_s']:.3f} s{at(ev['onset_s'])}")
    p(f"  loudest 50 ms RMS  {ev['env_peak_dbfs']:7.1f} dBFS")
    if lo["momentary_max_lufs"] is not None:
        p(f"  momentary max      {lo['momentary_max_lufs']:7.1f} LUFS   (400 ms)")
    if lo["short_term_max_lufs"] is not None:
        p(f"  short-term max     {lo['short_term_max_lufs']:7.1f} LUFS   (3 s)")
    if lo["integrated_lufs"] is not None:
        p(f"  integrated         {lo['integrated_lufs']:7.1f} LUFS   (unstable on one hit; for the record only)")
    p("  fall after the start, for good (50 ms RMS envelope):")
    for d in FALLS:
        ms = ev["fall_ms_after_onset"][str(d)]
        if ms is None:
            p(f"    -{d:2d} dB   not reached in this file (tail still {ev['tail_end_dbfs']:.1f} dBFS at the end)")
        else:
            p(f"    -{d:2d} dB   {ms:6.0f} ms{at(ev['onset_s'] + ms / 1000.0)}")
    if "fit_db_per_s" in ev:
        p(f"  fitted decay rate  {ev['fit_db_per_s']:.1f} dB/s between -5 and -25 dB"
          + (f"   (a fit: 60 dB would take {ev['fit_60db_s']:.2f} s at that rate)" if ev.get("fit_60db_s") else ""))
    if against and tempo and file0_beat is not None:
        files = {name: x}
        for a in against:
            y, sr2 = load(a)
            if sr2 != sr:
                p(f"  {a}: sample rate {sr2} differs from the event's {sr}; left out"); continue
            files[labels.get(a, a)] = y
        p(""); p("OTHERS  whole file: sample peak, loudest 50 ms RMS, momentary max")
        res["others"] = {}
        for label, y in files.items():
            if label == name:
                continue
            _, e2 = envelope(y, sr, 50.0, 5.0)
            lo2 = loudness(y, sr)
            res["others"][label] = dict(peak_dbfs=levels(y)["peak_dbfs"], env_peak_dbfs=round(float(e2.max()), 2),
                                        momentary_max_lufs=lo2["momentary_max_lufs"])
            mm = lo2["momentary_max_lufs"]
            p(f"  {label[:28].ljust(28)} peak {levels(y)['peak_dbfs']:7.1f} dBFS   50 ms RMS {float(e2.max()):7.1f} dBFS   momentary "
              + (f"{mm:7.1f} LUFS" if mm is not None else "      -"))
        fb = from_beat if from_beat is not None else math.floor(file0_beat + ev["onset_s"] * tempo / 60.0 + 1e-6)
        tb = to_beat if to_beat is not None else file0_beat + len(x) / sr * tempo / 60.0
        rows = beside(files, sr, file0_beat, tempo, fb, tb, step_beats)
        res["beside"] = rows
        others = [k for k in files if k != name]
        p(""); p("BESIDE  RMS dBFS per step; 'under' is how far the event sits below each other file")
        p("  " + "position".ljust(12) + name[:22].rjust(22) + "".join(o[:20].rjust(22) + "under".rjust(8) for o in others))
        for r in rows:
            line = "  " + ruler(r["beat"], per_bar).ljust(12) + (f"{r[name]:.1f}" if r[name] is not None else "-").rjust(22)
            for o in others:
                v = r.get(o)
                line += (f"{v:.1f}" if v is not None else "-").rjust(22)
                line += (f"{v - r[name]:+.1f}" if (v is not None and r[name] is not None) else "-").rjust(8)
            p(line)
    return res


def self_test():
    sr = 48000; ok = True
    t = np.arange(sr * 5) / sr
    x = np.zeros((len(t), 2)); x[:, 0] = np.sin(2 * np.pi * 997 * t)
    lo = loudness(x, sr)
    print(f"997 Hz full-scale sine, left only: integrated {lo['integrated_lufs']} LUFS (expect -3.01), momentary max {lo['momentary_max_lufs']}")
    ok &= abs(lo["integrated_lufs"] + 3.01) < 0.15 and abs(lo["momentary_max_lufs"] + 3.01) < 0.15
    lv = levels(x); print(f"  sample peak {lv['peak_dbfs']} dBFS (expect 0.0), RMS {lv['rms_dbfs']} (expect -6.02: one channel of two at -3.01)")
    ok &= abs(lv["peak_dbfs"]) < 0.01 and abs(lv["rms_dbfs"] + 6.02) < 0.05
    rng = np.random.default_rng(1)
    n = sr * 6; tt = np.arange(n) / sr
    y = np.zeros((n, 2)); on = int(0.5 * sr)
    burst = rng.standard_normal((n - on, 2)) * 0.25 * (10 ** (-20.0 * tt[: n - on] / 20))[:, None]   # 20 dB per second
    y[on:] = burst
    ev = event(y, sr)
    print(f"noise falling 20 dB/s from 0.5 s: starts {ev['onset_s']} s (expect 0.500), fitted {ev.get('fit_db_per_s')} dB/s (expect -20.0)")
    print("  fall times ms:", ev["fall_ms_after_onset"], "(expect about 300, 500, 1000, 1500, 2000, 3000)")
    ok &= abs(ev["onset_s"] - 0.5) < 0.005 and abs(ev["fit_db_per_s"] + 20.0) < 1.0
    for d, want in ((20, 1000), (40, 2000), (60, 3000)):
        got = ev["fall_ms_after_onset"][str(d)]
        ok &= got is not None and abs(got - want) < 120
    z = y[: int(1.5 * sr)]
    ev2 = event(z, sr)
    print("  same sound cut off at 1.5 s: -40 dB is", ev2["fall_ms_after_onset"]["40"], "(expect None, not reached)")
    ok &= ev2["fall_ms_after_onset"]["40"] is None
    print(f"ruler: beat 488 -> {ruler(488)} (expect 123.1.1), beat 191.5 -> {ruler(191.5)} (expect 48.4.3), beat 30.625 -> {ruler(30.625)} (expect 8.3.3.5)")
    ok &= ruler(488) == "123.1.1" and ruler(191.5) == "48.4.3" and ruler(30.625) == "8.3.3.5"
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Level, loudness and decay of a captured sound.")
    ap.add_argument("file", nargs="?", help="the event: the one sound being measured")
    ap.add_argument("--against", action="append", default=[], help="another file from the same capture run, to set beside it")
    ap.add_argument("--tempo", type=float, help="BPM, for ruler positions")
    ap.add_argument("--anchor-beat", type=float, help="song beat the event's note sits on (bar 1 beat 1 = 0)")
    ap.add_argument("--file-start-beat", type=float, help="song beat of the file's first sample, if no anchor")
    ap.add_argument("--per-bar", type=int, default=4)
    ap.add_argument("--from-beat", type=float); ap.add_argument("--to-beat", type=float)
    ap.add_argument("--step-beats", type=float, default=1.0)
    ap.add_argument("--json", help="also write the numbers to this file")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    if not a.file:
        ap.error("give a file, or --self-test")
    res = report(a.file, a.against, a.tempo, a.anchor_beat, a.file_start_beat, a.per_bar, a.from_beat, a.to_beat, a.step_beats)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
