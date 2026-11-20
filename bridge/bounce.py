"""
bounce.py: what a bounced mix came out at, offline. No Live needed unless --live is given.

    bin/analysis-python bridge/bounce.py mix.wav
    bin/analysis-python bridge/bounce.py mix.wav --tempo 120 --section Intro:0 --section Verse:32 --section End:256
    bin/analysis-python bridge/bounce.py mix.wav --live
    bin/analysis-python bridge/bounce.py --self-test

For the whole file: integrated loudness (BS.1770, gated), the short-term maximum and where
it is, sample peak and true peak (4x oversampled) per side, left against right, and width
as the side signal's level against the mid's, with the correlation of the two channels.

With sections (name:song beat, the last one closing the one before it) the same figures
per section, so the loudest section is a measurement and not a guess, plus crest (peak
minus RMS): a section whose crest is several dB under the others is where a limiter
worked hardest. --live takes the tempo and the locators from the open set.

--start-beat is the song beat of the file's first sample (0 when the bounce starts at 1.1.1).
"""
import argparse, sys
import numpy as np
from scipy import signal

from measure import load, db, ruler, _k_weight, _block_loudness


def integrated(m):
    """Gated integrated loudness from momentary blocks, LUFS, or None."""
    g = m[m > -70.0]
    if not len(g):
        return None
    rel = 10 * np.log10(np.mean(10 ** ((g + 0.691) / 10))) - 0.691 - 10.0
    g = g[g > rel]
    if not len(g):
        return None
    return float(10 * np.log10(np.mean(10 ** ((g + 0.691) / 10))) - 0.691)


def true_peak(x, sr):
    """Per-channel true peak in dBTP, 4x oversampled."""
    up = signal.resample_poly(x, 4, 1, axis=0)
    return [float(db(np.abs(up[:, c]).max())) for c in range(x.shape[1])]


def figures(x, sr):
    out = {}
    y = _k_weight(x, sr)
    t, m = _block_loudness(y, sr, 0.4, 0.1)
    out["lufs"] = integrated(m) if len(m) else None
    t3, s3 = _block_loudness(y, sr, 3.0, 0.1)
    out["st_max"] = float(s3.max()) if len(s3) else None
    out["st_max_at"] = float(t3[np.argmax(s3)]) if len(s3) else None
    pk = np.abs(x).max(axis=0)
    out["peak"] = [float(db(pk[0])), float(db(pk[1]))]
    rms = np.sqrt((x ** 2).mean(axis=0))
    out["lr"] = float(db(rms[0]) - db(rms[1]))
    tot = float(np.sqrt((x ** 2).mean()))
    out["crest"] = float(db(pk.max()) - db(tot))
    mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2
    out["side_mid"] = float(db(np.sqrt((side ** 2).mean())) - db(np.sqrt((mid ** 2).mean())))
    den = np.sqrt((x[:, 0] ** 2).sum() * (x[:, 1] ** 2).sum())
    out["corr"] = float((x[:, 0] * x[:, 1]).sum() / den) if den > 0 else 0.0
    return out


def f(v, w=6, p=1):
    return ("%*.*f" % (w, p, v)) if v is not None else " " * (w - 1) + "-"


def report(path, tempo=None, sections=(), start_beat=0.0, per_bar=4, out=sys.stdout):
    x, sr = load(path)
    w = lambda s="": print(s, file=out)
    dur = len(x) / sr
    w("%s: %.1f s at %d Hz" % (path.split("/")[-1], dur, sr))
    a = figures(x, sr)
    tp = true_peak(x, sr)
    w("integrated   %s LUFS" % f(a["lufs"]))
    where = ""
    if tempo and a["st_max_at"] is not None:
        where = " (3 s window from %s)" % ruler(start_beat + a["st_max_at"] * tempo / 60, per_bar)
    w("short-term   %s LUFS at most%s" % (f(a["st_max"]), where))
    w("sample peak  L %s  R %s dBFS" % (f(a["peak"][0], 5, 2), f(a["peak"][1], 5, 2)))
    w("true peak    L %s  R %s dBTP" % (f(tp[0], 5, 2), f(tp[1], 5, 2)))
    top = np.abs(x).max()
    w("at the top   %d samples within 0.1 dB of the highest peak" % int((np.abs(x) >= top * 10 ** (-0.1 / 20)).sum()))
    w("left - right %s dB RMS (+ is left louder)" % f(a["lr"], 5, 2))
    w("side - mid   %s dB, correlation %.2f (mono is 1.00; lower and a higher side figure are wider)"
      % (f(a["side_mid"]), a["corr"]))
    rows = []
    if tempo and len(sections) > 1:
        w()
        w("%-12s %-9s %7s %7s %7s %6s %7s %8s %5s" % ("section", "from", "LUFS", "st max", "peak", "crest", "L - R", "side-mid", "corr"))
        spb = sr * 60.0 / tempo
        for (name, b0), (_, b1) in zip(sections[:-1], sections[1:]):
            i0, i1 = int(round((b0 - start_beat) * spb)), int(round((b1 - start_beat) * spb))
            i0, i1 = max(0, i0), min(len(x), i1)
            if i1 - i0 < sr:
                continue
            s = figures(x[i0:i1], sr)
            rows.append((name, s))
            w("%-12s %-9s %s %s %s %s %s %s %5.2f" % (
                name[:12], ruler(b0, per_bar), f(s["lufs"], 7), f(s["st_max"], 7), f(max(s["peak"]), 7),
                f(s["crest"], 6), f(s["lr"], 7, 2), f(s["side_mid"], 8), s["corr"]))
        have = [(n, s) for n, s in rows if s["lufs"] is not None]
        if have:
            loud = max(have, key=lambda r: r[1]["lufs"]); quiet = min(have, key=lambda r: r[1]["lufs"])
            w()
            w("loudest section %s (%.1f LUFS), quietest %s (%.1f LUFS), %.1f LU apart"
              % (loud[0], loud[1]["lufs"], quiet[0], quiet[1]["lufs"], loud[1]["lufs"] - quiet[1]["lufs"]))
    return a, tp, rows


def from_live():
    from osc_client import OscClient
    c = OscClient()
    try:
        tempo = float(c.query("/live/song/get/tempo", "/live/song/get/tempo")[0])
        cues = list(c.query("/live/song/get/cue_points", "/live/song/get/cue_points"))
    finally:
        c.close()
    secs = sorted(((str(n), float(b)) for n, b in zip(cues[0::2], cues[1::2])), key=lambda s: s[1])
    return tempo, secs


def self_test():
    import io, os, tempfile
    import soundfile as sf
    sr = 44100
    t = np.arange(sr * 8) / sr
    quiet = 0.05 * np.sin(2 * np.pi * 997 * t[: sr * 4])
    loud = 0.5 * np.sin(2 * np.pi * 997 * t[: sr * 4])
    left = np.concatenate([quiet, loud])
    x = np.stack([left, left * 0.5], axis=1)           # right 6.02 dB under left, fully correlated
    p = os.path.join(tempfile.mkdtemp(), "t.wav")
    sf.write(p, x, sr, subtype="PCM_24")
    buf = io.StringIO()
    a, tp, rows = report(p, tempo=120.0, sections=[("A", 0.0), ("B", 8.0), ("End", 16.0)], out=buf)
    assert abs(a["lr"] - 6.02) < 0.05, a["lr"]
    assert a["corr"] > 0.999
    assert abs(a["side_mid"] - (-9.54)) < 0.1, a["side_mid"]   # (1-0.5)/(1+0.5)
    assert abs(a["peak"][0] - (-6.02)) < 0.05
    assert len(rows) == 2 and abs((rows[1][1]["lufs"] - rows[0][1]["lufs"]) - 20.0) < 0.3
    assert "loudest section B" in buf.getvalue()
    # a 997 Hz sine at -6.02 dBFS on one channel alone reads -9.03 LUFS; here L plus R at half
    assert abs(rows[1][1]["lufs"] - (-9.03 + 10 * np.log10(1.25))) < 0.3, rows[1][1]["lufs"]
    print("ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--tempo", type=float)
    ap.add_argument("--section", action="append", default=[], help="name:song beat; give the end as the last one")
    ap.add_argument("--start-beat", type=float, default=0.0)
    ap.add_argument("--per-bar", type=int, default=4)
    ap.add_argument("--live", action="store_true", help="tempo and locators from the open set")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.file:
        ap.error("a file is needed")
    tempo, secs = a.tempo, []
    for s in a.section:
        name, beat = s.rsplit(":", 1)
        secs.append((name, float(beat)))
    if a.live:
        tempo, secs = from_live()
    report(a.file, tempo=tempo, sections=secs, start_beat=a.start_beat, per_bar=a.per_bar)


if __name__ == "__main__":
    main()
