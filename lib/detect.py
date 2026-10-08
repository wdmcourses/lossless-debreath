import math
import os
import subprocess

from .config import (
    SR, N_FFT, HOP, N_MELS, MODEL_WINDOW, MODEL_HOP,
    THRESHOLD, MIN_DUR, MAX_DUR, MERGE_GAP, RAMP_MS,
    BREATH_MODEL, MEL_BASIS, RESOURCES_DIR, ffmpeg,
)

try:
    import numpy as np
    import onnxruntime as ort
    HAVE_AI = True
except Exception:
    HAVE_AI = False


def decode_16k_mono(path):
    cmd = [ffmpeg(), "-v", "error", "-i", path, "-map", "0:a:0",
           "-f", "f32le", "-acodec", "pcm_f32le", "-ar", str(SR), "-ac", "1", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit("error: audio decode failed\n" + r.stderr.decode(errors="ignore").strip())
    return np.frombuffer(r.stdout, dtype=np.float32)


def _hann(n):
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)).astype(np.float32)


def _mel_power(x, mel_basis):
    win = _hann(N_FFT)
    y = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="constant")
    t = 1 + (len(y) - N_FFT) // HOP
    mel = np.empty((t, N_MELS), dtype=np.float32)
    step = 4000
    for s in range(0, t, step):
        e = min(t, s + step)
        idx = np.arange(N_FFT)[None, :] + (np.arange(s, e) * HOP)[:, None]
        spec = np.abs(np.fft.rfft(y[idx] * win[None, :], n=N_FFT, axis=1)) ** 2
        mel[s:e] = spec @ mel_basis.T
    return mel, y, t


def _zcr(y, t):
    sign = np.sign(y)
    d = np.abs(sign[1:] - sign[:-1]) * 0.5
    cs = np.concatenate([[0.0], np.cumsum(d, dtype=np.float64)])
    starts = np.arange(t) * HOP
    return ((cs[starts + N_FFT - 1] - cs[starts]) / N_FFT).astype(np.float32)


def breath_probabilities(path, progress=None):
    if not HAVE_AI:
        raise SystemExit("error: numpy/onnxruntime not available")
    if not os.path.isfile(BREATH_MODEL) or not os.path.isfile(MEL_BASIS):
        raise SystemExit("error: breath model not found in %s" % RESOURCES_DIR)
    mel_basis = np.load(MEL_BASIS)
    sess = ort.InferenceSession(BREATH_MODEL, providers=["CPUExecutionProvider"])
    x = decode_16k_mono(path)
    mel, y, t = _mel_power(x, mel_basis)
    if progress:
        progress.start(t)
    logref = 10.0 * math.log10(max(1e-10, float(mel.max())))
    zcr = _zcr(y, t)
    probs = np.zeros(t, dtype=np.float32)
    wsum = np.zeros(t, dtype=np.float32)
    s = 0
    while s < t:
        e = min(t, s + MODEL_WINDOW)
        L = e - s
        md = 10.0 * np.log10(np.maximum(1e-10, mel[s:e])) - logref
        md = np.maximum(md, -80.0)
        vms = np.var(md, axis=1, ddof=1)
        feat = np.empty((3, N_MELS, L), dtype=np.float32)
        feat[0] = md.T
        feat[1] = np.broadcast_to(vms, (N_MELS, L))
        feat[2] = np.broadcast_to(zcr[s:e], (N_MELS, L))
        if L < MODEL_WINDOW:
            feat = np.pad(feat, ((0, 0), (0, 0), (0, MODEL_WINDOW - L)))
        out = sess.run(None, {"feature": feat[None], "length": np.array([L], dtype=np.int64)})[0][0][:L]
        probs[s:e] += out
        wsum[s:e] += 1
        if progress:
            progress.update(e)
        if e >= t:
            break
        s += MODEL_HOP
    probs = np.where(wsum > 0, probs / np.maximum(wsum, 1), 0.0)
    rms = np.sqrt(np.mean(np.pad(x, (0, (-len(x)) % HOP)).reshape(-1, HOP) ** 2, axis=1))
    rms_db = 20.0 * np.log10(rms + 1e-9)
    return probs, rms_db


def merge_intervals(intervals, gap):
    intervals = sorted(intervals)
    out = []
    for a, b in intervals:
        if out and a - out[-1][1] <= gap:
            if b > out[-1][1]:
                out[-1][1] = b
        else:
            out.append([a, b])
    return out


def detect(probs, rms_db):
    frame_s = HOP / float(SR)
    pred = np.where(probs > THRESHOLD)[0]
    runs = []
    i = 0
    while i < len(pred):
        j = i
        while j + 1 < len(pred) and pred[j + 1] == pred[j] + 1:
            j += 1
        runs.append((int(pred[i]), int(pred[j])))
        i = j + 1
    min_frames = int(round(MIN_DUR / frame_s))
    runs = [(a, b) for a, b in runs if (b - a) >= min_frames]
    kept = []
    for a, b in runs:
        start = a * frame_s
        end = (b + 1) * frame_s
        if end - start > MAX_DUR:
            continue
        lvl = float(np.max(rms_db[a:b + 1])) if b >= a and b < len(rms_db) else -120.0
        kept.append([start, end, lvl])
    simple = merge_intervals([[s, e] for s, e, _l in kept], max(MERGE_GAP, 2.0 * RAMP_MS / 1000.0))
    levels = {}
    for s, e in simple:
        best = -120.0
        for iv in kept:
            if iv[0] < e and iv[1] > s:
                best = max(best, iv[2])
        levels[(s, e)] = best
    return [[s, e, levels.get((s, e), -120.0)] for s, e in simple]
