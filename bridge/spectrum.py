"""
spectrum.py: offline spectral reading of a capture.py bounce, for mix/readings.md.

    python3 bridge/spectrum.py pad.aif --png mix/<name>-before.png
    python3 bridge/spectrum.py pad.aif --against mix.aif --png mix/<name>-before.png
    python3 bridge/spectrum.py pad.aif --track-partial 440

Prints: peak and RMS per channel, crest, L/R correlation broadband and per band, band
powers, spectral centroid, the strongest peaks, brightness and level variation over time,
and the amplitude-modulation spectrum of a partial when --track-partial is given. With
--against, the second file is subtracted sample for sample (both must come from one
capture.py run, so they are aligned) and the remainder is plotted as the other curve.
Writes a PNG with spectrogram (Hann 4096, hop 1024, -110 to -40 dB), long-term average
spectrum (Welch 16384, Hann, 50 percent overlap, mono sum, 0 dB = full-scale sine) and,
with --track-partial, the tracked partial in cents. Quote those settings in the readings
entry. Needs numpy, scipy, soundfile, matplotlib.
"""
import argparse, os, sys
import numpy as np, soundfile as sf
from scipy import signal

def db(x): return 20*np.log10(np.maximum(x, 1e-12))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file'); ap.add_argument('--against'); ap.add_argument('--png')
    ap.add_argument('--track-partial', type=float, help='Hz of a partial to track for pitch and amplitude modulation')
    ap.add_argument('--title', default=None)
    ap.add_argument('--marks', default='', help='comma list of Hz[:label] lines to draw')
    a = ap.parse_args()
    x, sr = sf.read(a.file, dtype='float64')
    if x.ndim == 1: x = np.stack([x, x], 1)
    m = x.mean(1)
    print(f'{a.file}: {sr} Hz, {len(x)/sr:.1f} s')
    pk = db(np.abs(x).max(0)); rms = db(np.sqrt((x**2).mean(0)))
    print(f'peak L/R {pk[0]:.1f}/{pk[1]:.1f} dBFS, RMS L/R {rms[0]:.1f}/{rms[1]:.1f} dBFS, crest {pk.mean()-rms.mean():.1f} dB')
    L, R = x[:,0], x[:,1]
    side = (L-R)/2; mid = (L+R)/2
    print(f'L/R correlation {np.corrcoef(L, R)[0,1]:.3f}; side under mid {db(np.sqrt((mid**2).mean()))-db(np.sqrt((side**2).mean())):.1f} dB')
    for lo, hi in [(60,200),(200,800),(800,3000),(3000,12000)]:
        b, aa = signal.butter(4, [lo, hi], btype='band', fs=sr)
        l = signal.filtfilt(b, aa, L); r = signal.filtfilt(b, aa, R)
        with np.errstate(invalid='ignore'):
            print(f'  {lo}-{hi} Hz correlation {np.corrcoef(l, r)[0,1]:.3f}')
    nfft = 16384
    f, P = signal.welch(m, sr, 'hann', nfft, nfft//2, scaling='spectrum')
    other = None
    if a.against:
        y, sr2 = sf.read(a.against, dtype='float64'); assert sr2 == sr
        ym = y.mean(1) if y.ndim > 1 else y
        n = min(len(ym), len(m)); rest = ym[:n] - m[:n]
        _, other = signal.welch(rest, sr, 'hann', nfft, nfft//2, scaling='spectrum')
    def bandpow(Q, lo, hi):
        mm = (f>=lo)&(f<hi); return 10*np.log10(Q[mm].sum()+1e-20)
    print('band power dB' + (' | remainder (against minus file) | difference' if other is not None else ''))
    for lo, hi in [(20,80),(80,160),(160,320),(320,640),(640,1280),(1280,2560),(2560,5120),(5120,10240),(10240,20000)]:
        line = f'  {lo:5d}-{hi:5d}: {bandpow(P,lo,hi):6.1f}'
        if other is not None: line += f' | {bandpow(other,lo,hi):6.1f} | {bandpow(P,lo,hi)-bandpow(other,lo,hi):+6.1f}'
        print(line)
    print(f'spectral centroid {(f*P).sum()/P.sum():.0f} Hz')
    Pd = 10*np.log10(P+1e-20)
    pks = signal.find_peaks(Pd, prominence=6)[0]
    top = sorted(sorted(pks, key=lambda i: -P[i])[:20])
    print('strongest peaks Hz:dB ' + ', '.join(f'{f[i]:.0f}:{Pd[i]:.0f}' for i in top))
    hop = int(0.25*sr); win = int(1.0*sr); t = []; ratio = []; lvl = []
    for s in range(0, len(m)-win, hop):
        seg = m[s:s+win]*np.hanning(win); X = np.abs(np.fft.rfft(seg))**2; fx = np.fft.rfftfreq(win, 1/sr)
        lo = X[(fx>150)&(fx<1000)].sum(); hi = X[(fx>2000)&(fx<10000)].sum()
        t.append(s/sr); ratio.append(10*np.log10(hi/lo+1e-20)); lvl.append(db(np.sqrt((m[s:s+win]**2).mean())))
    ratio = np.array(ratio); lvl = np.array(lvl)
    print(f'over time (1 s windows): brightness 2-10k over 150-1k swings {ratio.max()-ratio.min():.1f} dB; RMS {lvl.min():.1f} to {lvl.max():.1f} dBFS')
    pitch = None
    if a.track_partial:
        f0 = a.track_partial; lo, hi = f0*0.94, f0*1.06
        b, aa = signal.butter(4, [lo, hi], btype='band', fs=sr)
        yb = signal.filtfilt(b, aa, m); env = np.abs(signal.hilbert(yb)); env = signal.decimate(env, 100); env -= env.mean()
        fe = sr/100; F = np.abs(np.fft.rfft(env*np.hanning(len(env)))); fx = np.fft.rfftfreq(len(env), 1/fe)
        tops = sorted(signal.find_peaks(F, prominence=F.max()*0.05)[0], key=lambda k: -F[k])[:5]
        print(f'amplitude modulation of the {f0:.0f} Hz band, strongest rates: ' + ', '.join(f'{fx[k]:.2f} Hz ({F[k]/F.max():.2f})' for k in tops))
        w2 = 8192; h2 = 1024; fr = []; tt = []
        for s in range(0, len(m)-w2, h2):
            seg = m[s:s+w2]*np.hanning(w2); X = np.abs(np.fft.rfft(seg, n=w2*4)); fq = np.fft.rfftfreq(w2*4, 1/sr)
            mm = (fq>lo)&(fq<hi); fr.append(fq[mm][np.argmax(X[mm])]); tt.append(s/sr)
        fr = np.array(fr); tt = np.array(tt)
        print(f'tracked partial: mean {fr.mean():.2f} Hz, spread {1200*np.log2(fr.max()/fr.min()):.0f} cents peak to peak')
        pitch = (tt, 1200*np.log2(fr/f0))
    if a.png:
        import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap
        BLUE, ORANGE, INK, MUTED, GRID, SURF = '#2a78d6', '#eb6834', '#0b0b0b', '#898781', '#e1e0d9', '#fcfcfb'
        ramp = LinearSegmentedColormap.from_list('blue1', [SURF, '#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])
        plt.rcParams.update({'font.size':9,'axes.edgecolor':'#c3c2b7','axes.labelcolor':INK,'xtick.color':MUTED,'ytick.color':MUTED,'axes.titlecolor':INK,'axes.titleweight':'bold','figure.facecolor':SURF,'axes.facecolor':SURF,'grid.color':GRID,'grid.linewidth':0.6})
        fr_, ts, Z = signal.stft(m, sr, 'hann', 4096, 3072); Zd = 20*np.log10(np.abs(Z)+1e-9)
        rows = 3 if pitch else 2
        fig = plt.figure(figsize=(11, 8.5 if pitch else 7), dpi=130)
        gs = fig.add_gridspec(rows, 1, height_ratios=[3, 2, 1.2][:rows], hspace=0.38)
        ax = fig.add_subplot(gs[0]); mk = fr_ > 30
        ax.pcolormesh(ts, fr_[mk], Zd[mk], cmap=ramp, vmin=-110, vmax=-40, shading='nearest', rasterized=True)
        ax.set_yscale('log'); ax.set_ylim(30, 20000); ticks = [50,100,200,500,1000,2000,5000,10000,20000]
        ax.set_yticks(ticks); ax.set_yticklabels(['50','100','200','500','1k','2k','5k','10k','20k'])
        ax.set_xlabel('seconds'); ax.set_ylabel('Hz'); ax.set_title((a.title or a.file) + ' | spectrogram, Hann 4096, hop 1024, dB scale -110 to -40')
        marks = []
        for item in filter(None, a.marks.split(',')):
            hz, _, lab = item.partition(':'); marks.append((float(hz), lab or hz))
        for y, lab in marks:
            ax.axhline(y, color=ORANGE, lw=0.7, ls=':'); ax.text(ts[-1]*1.005, y, lab, color=ORANGE, fontsize=7, va='center')
        ax2 = fig.add_subplot(gs[1])
        ax2.semilogx(f[1:], Pd[1:], color=BLUE, lw=1.4, label=a.title or os.path.basename(a.file))
        if other is not None: ax2.semilogx(f[1:], 10*np.log10(other[1:]+1e-20), color=ORANGE, lw=1.4, label=f'{os.path.basename(a.against)} minus this')
        ax2.set_xlim(30, 20000); ax2.set_ylim(-110, -30); ax2.grid(True, which='both'); ax2.set_xticks(ticks); ax2.set_xticklabels(['50','100','200','500','1k','2k','5k','10k','20k'])
        ax2.set_xlabel('Hz'); ax2.set_ylabel('dB (sine = 0)'); ax2.set_title('Long-term average spectrum, Welch 16384, Hann, 50% overlap, whole capture, mono sum')
        ax2.legend(frameon=False, loc='upper right')
        for y, _ in marks: ax2.axvline(y, color=ORANGE, lw=0.6, ls=':')
        if pitch:
            ax3 = fig.add_subplot(gs[2]); ax3.plot(pitch[0], pitch[1], color=BLUE, lw=1.2)
            ax3.set_ylabel(f'cents from {a.track_partial:.0f}'); ax3.set_xlabel('seconds'); ax3.grid(True)
            ax3.set_title('Tracked partial, 8192-point STFT peak, hop 1024: pitch modulation')
        fig.savefig(a.png, facecolor=SURF, bbox_inches='tight'); print('wrote', a.png)

if __name__ == '__main__':
    main()
