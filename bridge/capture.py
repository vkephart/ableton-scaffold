"""
capture.py: record a track's output (or the master) to an audio file through AbletonOSC,
using a temporary resample track. No plugin exposes its spectrum over OSC; this gets the
audio out so spectrum.py can analyse it offline.

    python3 bridge/capture.py --source Pads --beats 96 --out /tmp/pad.aif
    python3 bridge/capture.py --source master --beats 96 --out /tmp/mix.aif
    python3 bridge/capture.py --source Pads --source master --beats 96 --out /tmp/pad.aif --out /tmp/mix.aif

Several --source/--out pairs record simultaneously on separate temporary tracks and are
sample-aligned. The transport must already be playing; the script does not start or
retrigger anything, so the clips the user has running are what gets captured. Recording
starts at the next launch-quantize boundary, runs for --beats plus one bar, then the
temporary tracks are deleted. The recorded .aif stays in the project's Samples/Recorded
folder and is also copied to --out. Prints a JSON line with the mixer state at capture
time, for the readings entry.
"""
import argparse, json, os, shutil, sys, time
from osc_client import OscClient

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', action='append', required=True, help='track name, or "master"')
    ap.add_argument('--out', action='append', required=True, help='destination file, one per --source')
    ap.add_argument('--beats', type=float, default=96)
    ap.add_argument('--channel', default='Post Mixer', help='Pre FX, Post FX or Post Mixer for track sources')
    a = ap.parse_args()
    if len(a.source) != len(a.out):
        sys.exit('one --out per --source')
    c = OscClient()
    q = lambda addr, *args: c.query(addr, addr, *args, timeout=4.0)
    names = lambda: q('/live/song/get/track_names')
    if not q('/live/song/get/is_playing')[0]:
        sys.exit('transport is not playing; start playback with the clips you want captured')
    arm_before = {n: q('/live/track/get/arm', i)[1] for i, n in enumerate(names())}
    created = []
    log = {'sources': a.source, 'tempo': q('/live/song/get/tempo')[0]}
    try:
        for src in a.source:
            c.send('/live/song/create_audio_track', -1); time.sleep(0.8)
            ti = len(names()) - 1
            nm = 'CAP-' + src
            c.send('/live/track/set/name', ti, nm); time.sleep(0.3)
            assert names()[ti] == nm, names()
            created.append(nm)
            c.send('/live/track/set/current_monitoring_state', ti, 2); time.sleep(0.2)   # Off, before arming
            assert q('/live/track/get/current_monitoring_state', ti)[1] == 2
            if src.lower() == 'master':
                c.send('/live/track/set/input_routing_type', ti, 'Resampling'); time.sleep(0.3)
            else:
                c.send('/live/track/set/input_routing_type', ti, src); time.sleep(0.3)
                c.send('/live/track/set/input_routing_channel', ti, a.channel); time.sleep(0.3)
            got = q('/live/track/get/input_routing_type', ti)[1]
            if got not in (src, 'Resampling'):
                sys.exit(f'input routing did not take on {nm}: {got}')
            c.send('/live/track/set/arm', ti, 1); time.sleep(0.2)
            assert q('/live/track/get/arm', ti)[1]
        # exclusive arm may have disarmed something; put it back
        for i, n in enumerate(names()):
            if n in arm_before and arm_before[n] and not q('/live/track/get/arm', i)[1]:
                c.send('/live/track/set/arm', i, 1)
        idxs = [names().index(nm) for nm in created]
        for ti in idxs:
            c.send('/live/clip_slot/fire', ti, 0)
        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                if q('/live/clip/get/is_recording', idxs[0], 0)[2]:
                    break
            except TimeoutError:
                pass
            time.sleep(0.05)
        log['song_time_at_start'] = q('/live/song/get/current_song_time')[0]
        log['mixer_at_capture'] = {}
        for i, n in enumerate(names()):
            if n in created:
                continue
            log['mixer_at_capture'][n] = dict(
                volume=q('/live/track/get/volume', i)[1], mute=q('/live/track/get/mute', i)[1],
                solo=q('/live/track/get/solo', i)[1], playing_slot=q('/live/track/get/playing_slot_index', i)[1],
                send_a=q('/live/track/get/send', i, 0)[2])
        time.sleep((a.beats + 4) * 60.0 / log['tempo'])
        for ti in idxs:
            c.send('/live/clip_slot/stop', ti, 0)
        t0 = time.time()
        while time.time() - t0 < 20 and any(q('/live/clip/get/is_recording', ti, 0)[2] for ti in idxs):
            time.sleep(0.1)
        log['song_time_at_end'] = q('/live/song/get/current_song_time')[0]
        log['files'] = {}
        for ti, dst in zip(idxs, a.out):
            fp = q('/live/clip/get/file_path', ti, 0)[2]
            time.sleep(0.5)
            shutil.copy(fp, dst)
            log['files'][dst] = {'recorded': fp, 'beats': q('/live/clip/get/length', ti, 0)[2]}
    finally:
        for nm in created:
            if nm in names():
                ti = names().index(nm)
                c.send('/live/track/set/arm', ti, 0); time.sleep(0.2)
                c.send('/live/song/delete_track', ti); time.sleep(0.8)
        for i, n in enumerate(names()):
            if n in arm_before and arm_before[n] and not q('/live/track/get/arm', i)[1]:
                c.send('/live/track/set/arm', i, 1)
        c.close()
    print(json.dumps(log))

if __name__ == '__main__':
    main()
