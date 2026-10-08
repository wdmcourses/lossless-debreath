import array
import subprocess

from .config import RAMP_MS, ffmpeg


def gain_segments(intervals, sr, gain_db, ramp_ms):
    depth = 1.0 - 10.0 ** (-gain_db / 20.0)
    ramp = max(1, int(round(ramp_ms * sr / 1000.0)))
    segs = []
    for a, b, _lvl in intervals:
        sa = int(round(a * sr))
        sb = int(round(b * sr))
        if sb > sa:
            segs.append((sa, sb))
    return depth, ramp, segs


def pump_gain(path, sr, ch, intervals, sink, gain_db, progress=None):
    depth, ramp, segs = gain_segments(intervals, sr, gain_db, RAMP_MS)
    dec_cmd = [ffmpeg(), "-v", "error", "-i", path, "-map", "0:a:0",
               "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(sr), "-ac", str(ch), "-"]
    p_dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = ch * 4
    block_samples = 4096
    base = 0
    seg_i = 0
    try:
        while True:
            raw = p_dec.stdout.read(block_samples * frame_bytes)
            if not raw:
                break
            ns = len(raw) // frame_bytes
            if ns == 0:
                break
            raw = raw[:ns * frame_bytes]
            while seg_i < len(segs) and segs[seg_i][1] + ramp <= base:
                seg_i += 1
            hit = seg_i < len(segs) and segs[seg_i][0] - ramp < base + ns
            if not hit:
                sink.write(raw)
            else:
                arr = array.array("f")
                arr.frombytes(raw)
                k = seg_i
                while k < len(segs) and segs[k][0] - ramp < base + ns:
                    sa, sb = segs[k]
                    lo = max(base, sa - ramp)
                    hi = min(base + ns, sb + ramp)
                    for i in range(lo, hi):
                        if i < sa:
                            g = 1.0 - depth * ((i - (sa - ramp)) / float(ramp))
                        elif i < sb:
                            g = 1.0 - depth
                        else:
                            g = 1.0 - depth * (1.0 - ((i - sb) / float(ramp)))
                        if g < 0.0:
                            g = 0.0
                        r = (i - base) * ch
                        for c in range(ch):
                            arr[r + c] *= g
                    k += 1
                sink.write(arr.tobytes())
            base += ns
            if progress:
                progress.update(base)
    except BrokenPipeError:
        pass
    p_dec.stdout.close()
    err = p_dec.stderr.read()
    p_dec.wait()
    if p_dec.returncode != 0:
        return err.decode(errors="ignore").strip()
    return None
