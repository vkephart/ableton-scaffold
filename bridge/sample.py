"""
sample.py: capture a bar range of the Arrangement and measure it, in one command.

    bin/analysis-python bridge/sample.py --from 21 --to 29 --source "Crash" --anchor 23
    bin/analysis-python bridge/sample.py --from 21 --to 29 --source "Crash" --source "Lead Vox" --source master --anchor 23
    bin/analysis-python bridge/sample.py --from 21 --to 29 --source "Crash" --dry-run

Positions are Live's ruler: bar, bar.beat or bar.beat.sixteenth. The first --source is the
event, the sound being measured; the others are set beside it beat by beat. --anchor is the
ruler position the event's note sits on: the event's start in the audio is pinned to it,
because a playhead read is not exact enough to place a file. Leave --anchor off and
positions are given from the playhead and labelled approximate.

What it does, in this order, so that nothing slow happens once the transport runs:
  1. Reads the state it is about to rely on or change: playing, loop, solos, Back to
     Arrangement, Arrangement record, launch quantization, metronome, arm states, playhead.
     It stops with a plain message if the transport is running, Arrangement record is on,
     a Session clip is overriding the Arrangement, or a source name is not in the set.
  2. Creates one temporary audio track per source (input = that track, monitoring Off, so
     nothing doubles into the master), armed. "master" records Live's Resampling input.
  3. Moves the playhead to --preroll-bars before the window, starts, and records.
  4. Stops when the playhead passes --to, copies the files to --out-dir, deletes the
     temporary tracks, and puts back the loop, quantization, metronome, arm states and
     playhead. It checks the track count is what it was.
  5. Runs measure.py's report on the files and writes report.txt and report.json beside them.

The transport plays through the monitors while it runs. Tell whoever is at the desk first.
The recorded originals stay in the project's Samples/Recorded folder; their paths are
printed so they can be deleted. Creating and deleting the tracks sits in Live's undo
history and marks the set as changed.

Run it with bin/analysis-python (the scaffold's permanent environment), not python3.
"""
import argparse, json, os, re, shutil, signal, sys, time
from osc_client import OscClient


class Stop(Exception):
    pass


def parse_ruler(s, per_bar):
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+(?:\.\d+)?))?", str(s))
    if not m:
        raise SystemExit(f"not a ruler position: {s!r} (use bar, bar.beat or bar.beat.sixteenth)")
    bar = int(m.group(1)); beat = int(m.group(2) or 1); six = float(m.group(3) or 1)
    return (bar - 1) * per_bar + (beat - 1) + (six - 1) / 4.0


def main():
    ap = argparse.ArgumentParser(description="Capture a bar range of the Arrangement and measure it.")
    ap.add_argument("--from", dest="start", required=True, help="ruler position where the window starts")
    ap.add_argument("--to", dest="end", required=True, help="ruler position where it ends")
    ap.add_argument("--source", action="append", required=True, help='track name, or "master"; the first is the event')
    ap.add_argument("--anchor", help="ruler position of the event's note")
    ap.add_argument("--channel", default="Post Mixer", help="Pre FX, Post FX or Post Mixer for track sources")
    ap.add_argument("--preroll-bars", type=float, default=2.0)
    ap.add_argument("--out-dir", help="where the copies and the report go (default: a new folder under the system temp dir)")
    ap.add_argument("--step-beats", type=float, default=1.0, help="step of the beside table")
    ap.add_argument("--dry-run", action="store_true", help="read and report the state, change nothing")
    ap.add_argument("--no-measure", action="store_true")
    a = ap.parse_args()

    def on_signal(signum, frame):
        raise Stop(f"interrupted by signal {signum}")
    for sg in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, on_signal)

    try:
        c = OscClient()
    except OSError as e:
        sys.exit(f"cannot open the OSC reply port (another bridge script still running?): {e}")
    q = lambda addr, *args, t=4.0: c.query(addr, addr, *args, timeout=t)

    def names():
        r = q("/live/song/get/track_names")
        return [n[1] if isinstance(n, (list, tuple)) else n for n in r]

    state = {}; created = []; log = {"sources": a.source, "channel": a.channel}
    copied = []; restored = []
    try:
        signal.alarm(60)
        tempo = q("/live/song/get/tempo")[0]
        per_bar = int(q("/live/song/get/signature_numerator")[0])
        start, end = parse_ruler(a.start, per_bar), parse_ruler(a.end, per_bar)
        anchor = parse_ruler(a.anchor, per_bar) if a.anchor else None
        if end <= start:
            raise Stop("--to is not after --from")
        pre = start - a.preroll_bars * per_bar
        if pre < 0:
            pre = 0.0
        nm = names(); n_before = len(nm)
        for s in a.source:
            if s.lower() != "master" and s not in nm:
                raise Stop(f"no track named {s!r}. Tracks: {', '.join(nm)}")
        state["playing"] = bool(q("/live/song/get/is_playing")[0])
        state["loop"] = bool(q("/live/song/get/loop")[0])
        state["song_time"] = q("/live/song/get/current_song_time")[0]
        state["back_to_arranger"] = bool(q("/live/song/get/back_to_arranger")[0])
        for key, addr in (("record_mode", "/live/song/get/record_mode"), ("metronome", "/live/song/get/metronome"),
                          ("quantization", "/live/song/get/clip_trigger_quantization")):
            try:
                state[key] = q(addr, t=2.0)[0]
            except TimeoutError:
                state[key] = None
        state["arm"] = {}; state["solo"] = []
        for i, n in enumerate(nm):
            try:
                state["arm"][n] = bool(q("/live/track/get/arm", i, t=2.0)[1])
            except Exception:
                state["arm"][n] = None          # group tracks cannot be armed
            if q("/live/track/get/solo", i)[1]:
                state["solo"].append(n)
        log.update(tempo=tempo, per_bar=per_bar, window_beats=[start, end], preroll_from_beat=pre, state_before=state)
        mixer = {}
        for s in a.source:
            if s.lower() == "master":
                continue
            i = nm.index(s)
            mixer[s] = dict(volume=q("/live/track/get/volume", i)[1], mute=bool(q("/live/track/get/mute", i)[1]),
                            sends=[q("/live/track/get/send", i, k)[2] for k in range(int(q("/live/return/get/num_returns")[0]))])
        log["mixer"] = mixer
        secs = (end - pre + 1) * 60.0 / tempo
        print(f"tempo {tempo:.2f}, {per_bar} beats per bar; window beats {start:g} to {end:g}, pre-roll from {pre:g}; about {secs:.0f} s of playback")
        print("state:", json.dumps({k: v for k, v in state.items() if k != "arm"}), "| armed:", [n for n, v in state["arm"].items() if v])
        if state["playing"]:
            raise Stop("the transport is running; stop it and run again")
        if state["record_mode"]:
            raise Stop("Arrangement record is on; switch it off and run again")
        if state["back_to_arranger"]:
            raise Stop("a Session clip is overriding the Arrangement (Back to Arrangement is lit); press it and run again")
        if a.dry_run:
            print("dry run: nothing changed"); return

        # ---- everything slow happens here, before the transport starts ----
        signal.alarm(int(secs) + 150)
        for s in a.source:
            c.send("/live/song/create_audio_track", -1); time.sleep(0.8)
            cur = names(); ti = len(cur) - 1; label = "CAP-" + s
            c.send("/live/track/set/name", ti, label); time.sleep(0.3)
            if names()[ti] != label:
                raise Stop(f"could not name the temporary track for {s}")
            created.append(label)
            c.send("/live/track/set/current_monitoring_state", ti, 2); time.sleep(0.2)     # Off, before arming
            if q("/live/track/get/current_monitoring_state", ti)[1] != 2:
                raise Stop(f"monitoring did not go Off on {label}")
            if s.lower() == "master":
                c.send("/live/track/set/input_routing_type", ti, "Resampling"); time.sleep(0.3)
                want = "Resampling"
            else:
                c.send("/live/track/set/input_routing_type", ti, s); time.sleep(0.3)
                c.send("/live/track/set/input_routing_channel", ti, a.channel); time.sleep(0.3)
                want = s
            got = q("/live/track/get/input_routing_type", ti)[1]
            if got != want:
                raise Stop(f"input routing did not take on {label}: got {got!r}")
            c.send("/live/track/set/arm", ti, 1); time.sleep(0.2)
            if not q("/live/track/get/arm", ti)[1]:
                raise Stop(f"{label} did not arm")
        cur = names()
        for i, n in enumerate(cur):                      # exclusive arm may have disarmed something
            if state["arm"].get(n) and not q("/live/track/get/arm", i)[1]:
                c.send("/live/track/set/arm", i, 1)
        idxs = [cur.index(lb) for lb in created]
        if state["loop"]:
            c.send("/live/song/set/loop", 0)
        if state["quantization"]:
            c.send("/live/song/set/clip_trigger_quantization", 0)
        if state["metronome"]:
            c.send("/live/song/set/metronome", 0)
        c.send("/live/song/set/current_song_time", float(pre)); time.sleep(0.4)
        at = q("/live/song/get/current_song_time")[0]
        if abs(at - pre) > 0.01:
            c.send("/live/song/set/current_song_time", float(pre)); time.sleep(0.6)
            at = q("/live/song/get/current_song_time")[0]
            if abs(at - pre) > 0.01:
                raise Stop(f"the playhead did not move to beat {pre:g} (it reads {at:g})")

        # ---- transport ----
        # A playhead set while the transport is stopped does not decide where playback begins:
        # continue_playing resumed from the last stop, and start_playing also began elsewhere
        # on both verified passes. What lands is the jump while playing, just below.
        c.send("/live/song/start_playing")
        for ti in idxs:
            c.send("/live/clip_slot/fire", ti, 0)
        t0 = time.time(); seen = None
        while time.time() - t0 < 10:
            try:
                if q("/live/clip/get/is_recording", idxs[0], 0, t=1.0)[2]:
                    seen = q("/live/song/get/current_song_time")[0]; break
            except TimeoutError:
                pass
            time.sleep(0.03)
        if seen is None:
            raise Stop("recording did not start within 10 s")
        if not (pre - 0.5 <= seen <= start - 0.25):
            # playback began somewhere else: a jump while playing does land
            c.send("/live/song/set/current_song_time", float(pre)); time.sleep(0.3)
            seen = q("/live/song/get/current_song_time")[0]
            log["jumped_while_playing"] = True
            print(f"playback began away from the pre-roll; jumped while playing, now at beat {seen:.2f}")
        log["recording_seen_at_beat"] = seen
        if not (pre - 0.5 <= seen <= start - 0.25):
            raise Stop(f"recording was not running before the window (playhead at beat {seen:.2f}, window starts at {start:g}); raise --preroll-bars")
        while True:
            now = q("/live/song/get/current_song_time")[0]
            if now >= end + 0.25:
                break
            if not q("/live/song/get/is_playing")[0]:
                raise Stop(f"playback was stopped at beat {now:.2f}, before the window ended")
            time.sleep(0.08)
        c.send("/live/song/stop_playing"); time.sleep(0.5)
        t0 = time.time()
        while time.time() - t0 < 10 and any(q("/live/clip/get/is_recording", ti, 0)[2] for ti in idxs):
            time.sleep(0.1)
        log["stopped_at_beat"] = q("/live/song/get/current_song_time")[0]
        out_dir = a.out_dir or os.path.join(os.environ.get("TMPDIR", "/tmp"), "ableton-samples", time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(out_dir, exist_ok=True)
        log["out_dir"] = out_dir; log["files"] = []
        time.sleep(0.5)
        for k, (ti, s) in enumerate(zip(idxs, a.source)):
            fp = q("/live/clip/get/file_path", ti, 0)[2]
            dst = os.path.join(out_dir, f"{k + 1}-{re.sub(r'[^A-Za-z0-9._-]+', '_', s)}{os.path.splitext(fp)[1]}")
            shutil.copy(fp, dst)
            copied.append((s, dst)); log["files"].append(dict(source=s, copy=dst, recorded=fp))
    except Stop as e:
        print("STOPPED:", e); log["stopped"] = str(e)
    finally:
        signal.alarm(60)
        try:
            if q("/live/song/get/is_playing")[0]:
                c.send("/live/song/stop_playing"); time.sleep(0.4)
            for label in created:
                cur = names()
                if label in cur:
                    ti = cur.index(label)
                    c.send("/live/track/set/arm", ti, 0); time.sleep(0.2)
                    c.send("/live/song/delete_track", ti); time.sleep(0.8)
            if created:
                cur = names()
                for i, n in enumerate(cur):
                    if state.get("arm", {}).get(n) and not q("/live/track/get/arm", i)[1]:
                        c.send("/live/track/set/arm", i, 1)
                if state.get("loop"):
                    c.send("/live/song/set/loop", 1)
                if state.get("quantization"):
                    c.send("/live/song/set/clip_trigger_quantization", int(state["quantization"]))
                if state.get("metronome"):
                    c.send("/live/song/set/metronome", 1)
                c.send("/live/song/set/current_song_time", float(state.get("song_time", 0.0))); time.sleep(0.4)
                left = [n for n in names() if n.startswith("CAP-") and n in created]
                n_after = len(names())
                restored = [f"tracks {n_after} (was {n_before})", f"temporary tracks left: {left or 'none'}",
                            f"playhead {q('/live/song/get/current_song_time')[0]:.2f}", f"loop {bool(q('/live/song/get/loop')[0])}",
                            f"playing {bool(q('/live/song/get/is_playing')[0])}"]
                for key, addr in (("quantization", "/live/song/get/clip_trigger_quantization"), ("metronome", "/live/song/get/metronome")):
                    try:
                        restored.append(f"{key} {q(addr, t=2.0)[0]} (was {state.get(key)})")
                    except TimeoutError:
                        pass
                print("restored:", "; ".join(restored))
                log["restored"] = restored
        finally:
            signal.alarm(0)
            c.close()

    if not copied:
        sys.exit(1)
    for f in log["files"]:
        print(f"captured {f['source']}: {f['copy']}\n   original (delete when done): {f['recorded']}")
    if a.no_measure:
        json.dump(log, open(os.path.join(log["out_dir"], "report.json"), "w"), indent=1); return
    import io
    import soundfile as sf
    import measure
    ev_src, ev_file = copied[0]
    labels = {dst: s for s, dst in copied}
    dur_beats = sf.info(ev_file).duration * tempo / 60.0
    playhead_file0 = log["stopped_at_beat"] - dur_beats          # approximate: from the playhead at stop
    buf = io.StringIO()
    kw = dict(tempo=tempo, per_bar=per_bar, from_beat=None, to_beat=end, step_beats=a.step_beats, labels=labels)
    if anchor is not None:
        res = measure.report(ev_file, [d for _, d in copied[1:]], anchor_beat=anchor, out=buf, **kw)
        if res["event"].get("found"):
            diff = res["file0_beat"] - playhead_file0
            buf.write(f"\nplacement: start of the event pinned to {measure.ruler(anchor, per_bar)}; the playhead read puts it {diff:+.2f} beats from there"
                      + ("" if abs(diff) < 0.5 else "  <-- more than half a beat apart: check the anchor is the right note") + "\n")
    else:
        res = measure.report(ev_file, [d for _, d in copied[1:]], file0_beat=playhead_file0, out=buf, **kw)
        buf.write("\nplacement: from the playhead at stop, approximate (no --anchor given)\n")
    text = buf.getvalue(); print(); print(text)
    log["measure"] = res
    open(os.path.join(log["out_dir"], "report.txt"), "w").write(text)
    json.dump(log, open(os.path.join(log["out_dir"], "report.json"), "w"), indent=1, default=str)
    print("report:", os.path.join(log["out_dir"], "report.txt"))
    if not res["event"].get("found"):
        sys.exit("the event file is silent: the capture missed the sound, or the source is muted")


if __name__ == "__main__":
    main()
