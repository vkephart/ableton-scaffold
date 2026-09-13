"""Send the Ganzflicker noise-swell sheet to the Moog Sub 37 as MIDI CC (MSB only, channel 1).
Values are 0-127 knob positions. Continuous ones are estimates over unknown curves; see the table.
Usage: python send_patch.py        (send the sheet)
       python send_patch.py test   (one 2.5 s test note at velocity 64, meter read, cutoff-closed read)
"""
import time, rtmidi, sys
sys.path.insert(0, '/Users/vernonkephart/music-studio/Post-Punk-Art-Rock-Ethereal/.claude/scaffold/bridge')
from osc_client import OscClient

CH = 0  # MIDI channel 1
SHEET = [
    # (name, cc, value, note)
    ("OSC 1 LEVEL",          114,   0, "off"),
    ("OSC 1 SUB LEVEL",      115,   0, "off"),
    ("OSC 2 LEVEL",          116,   0, "off"),
    ("NOISE LEVEL",          117,  64, "5 of 10, unity"),
    ("FEEDBACK/EXT LEVEL",   118,   0, "0"),
    ("FILTER SLOPES",        109,  96, "-24 dB"),
    ("FILTER CUTOFF",         19,  57, "estimate for about 450 Hz, 20 Hz to 20 kHz assumed log"),
    ("FILTER RESONANCE",      21,  25, "2 of 10"),
    ("FILTER MULTIDRIVE",     18,   8, "about 0.6 of 10"),
    ("FILTER KB AMT",         22,   0, "KB TRACK off"),
    ("FILTER EG AMT",         27, 104, "bipolar, 64 centre; 89 crested near 1.8 kHz on the first capture, 104 aims the crest at 4 kHz"),
    ("FILTER EG ATTACK",      23, 117, "estimate for 5 s over 1 ms to 10 s log"),
    ("FILTER EG DECAY",       24, 114, "estimate for 4 s"),
    ("FILTER EG SUSTAIN",     25,  38, "3 of 10"),
    ("FILTER EG RELEASE",     26, 120, "estimate for 6 s"),
    ("FILTER EG RESET",       82,   0, "off"),
    ("FILTER EG DELAY",      103,   0, "0"),
    ("FILTER EG HOLD",       105,   0, "0"),
    ("FILTER EG VEL AMT",     86,   0, "velocity off"),
    ("FILTER EG KB AMT",      79,   0, "no key tracking of times"),
    ("AMP EG ATTACK",         28, 114, "estimate for 4 s"),
    ("AMP EG DECAY",          29, 110, "estimate for 3 s"),
    ("AMP EG SUSTAIN",        30,  51, "4 of 10"),
    ("AMP EG RELEASE",        31, 117, "estimate for 5 s"),
    ("AMP EG RESET",          83,   0, "off"),
    ("AMP EG DELAY",         104,   0, "0"),
    ("AMP EG HOLD",          106,   0, "0"),
    ("AMP EG VEL AMT",        87,   0, "velocity off"),
    ("AMP EG KB AMT",         80,   0, "no key tracking of times"),
    ("MOD 2 SOURCE",          72,   0, "triangle LFO"),
    ("LFO 2 RANGE",           78,  43, "Med, 0.1 to 100 Hz"),
    ("LFO 2 RATE",             8,   0, "knob floor, manual pins 0.1 Hz"),
    ("LFO 2 KB RESET",        95,   0, "off"),
    ("MOD 2 PITCH AMT",       15,  64, "bipolar centre, zero"),
    ("MOD 2 FILTER AMT",      16,  80, "bipolar, small positive (corrects the 10 o'clock note)"),
]

out = rtmidi.MidiOut()
ports = out.get_ports()
idx = next(i for i, p in enumerate(ports) if 'Sub 37' in p)
out.open_port(idx)
print("opened", ports[idx])


def cc(n, v):
    out.send_message([0xB0 | CH, n, v])
    time.sleep(0.012)


osc = OscClient()


def meter():
    r = osc.query('/live/track/get/output_meter_level', '/live/track/get/output_meter_level', 12)
    return r[1] if len(r) > 1 else r


try:
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print("meter idle:", meter())
        out.send_message([0x90 | CH, 60, 64])
        time.sleep(2.5)
        print("meter with note (cutoff as set):", meter())
        cc(19, 0)
        time.sleep(1.0)
        print("meter with cutoff 0:", meter())
        cc(19, 57)
        out.send_message([0x80 | CH, 60, 0])
        time.sleep(0.2)
        print("meter after note off:", meter())
    else:
        for name, n, v, note in SHEET:
            cc(n, v)
            print(f"CC {n:3d} = {v:3d}  {name}  ({note})")
finally:
    out.close_port()
    osc.close()
