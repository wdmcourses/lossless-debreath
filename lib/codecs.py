import math
import os
import shutil
import subprocess
import tempfile

from .config import (
    RAMP_MS, OPUS_TAIL, LOSSLESS_AUDIO, SPLICE_MP3, SPLICE_OPUS, MP3_FRAME_OFFSET,
    MP3_BITRATE_V1L3, MP3_BITRATE_V2L3, MP3_SAMPLERATE, ffmpeg,
)
from .containers import _container_args, _map_args
from .gain import pump_gain


def encode_lossless(path, out, intervals, sr, ch, gain_db, acodec, has_video, progress=None):
    enc = [ffmpeg(), "-v", "error", "-y", "-i", path,
           "-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", "-"]
    enc += _map_args(has_video)
    enc += ["-c:a", acodec, "-ignore_unknown"]
    enc += _container_args(out)
    enc.append(out)
    p_enc = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dec_err = pump_gain(path, sr, ch, intervals, p_enc.stdin, gain_db, progress)
    try:
        p_enc.stdin.close()
    except BrokenPipeError:
        pass
    enc_err = p_enc.stderr.read()
    p_enc.wait()
    if p_enc.returncode != 0:
        raise SystemExit("error: encode/mux failed\n" + enc_err.decode(errors="ignore").strip())
    if dec_err:
        raise SystemExit("error: audio decode failed\n" + dec_err)


def mp3_frames(data):
    out = []
    i = 0
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        h = data[i:i + 4]
        ver = (h[1] >> 3) & 0x03
        layer = (h[1] >> 1) & 0x03
        br_idx = (h[2] >> 4) & 0x0F
        sr_idx = (h[2] >> 2) & 0x03
        pad = (h[2] >> 1) & 0x01
        if layer != 1 or ver == 1 or br_idx == 0 or br_idx == 15 or sr_idx == 3:
            i += 1
            continue
        mpeg1 = (ver == 3)
        br = (MP3_BITRATE_V1L3 if mpeg1 else MP3_BITRATE_V2L3)[br_idx] * 1000
        sr = MP3_SAMPLERATE[ver][sr_idx]
        if not br or not sr:
            i += 1
            continue
        flen = (144 if mpeg1 else 72) * br // sr + pad
        if flen < 4 or i + flen > n:
            i += 1
            continue
        out.append((i, flen, 1152 if mpeg1 else 576))
        i += flen
    return out


def _bits(data, pos, n):
    v = 0
    for i in range(n):
        b = pos + i
        v = (v << 1) | ((data[b >> 3] >> (7 - (b & 7))) & 1)
    return v


def _put_bits(data, pos, n, val):
    for i in range(n):
        b = pos + i
        byte = b >> 3
        mask = 1 << (7 - (b & 7))
        if (val >> (n - 1 - i)) & 1:
            data[byte] |= mask
        else:
            data[byte] &= ~mask


def mp3_gain_offsets(data, frame_off, mpeg1, channels, crc):
    """Bit offsets of every global_gain field in one Layer III frame."""
    base = (frame_off + 4 + (2 if crc else 0)) * 8
    if mpeg1:
        p = 9 + (5 if channels == 1 else 3) + 4 * channels
        ngr, nch = 2, channels
    else:
        p = 8 + (1 if channels == 1 else 2)
        ngr, nch = 1, channels
    offs = []
    for _gr in range(ngr):
        for _c in range(nch):
            p += 12 + 9
            offs.append(base + p)
            ws = _bits(data, base + p + 8 + 4, 1)
            p += 8 + 4 + 1
            if ws:
                p += 2 + 1 + 2 * 5 + 3 * 3
            else:
                p += 3 * 5 + 4 + 3
            p += 3
    return offs


def _mp3_gain_at(t, intervals, depth, ramp):
    g = 1.0
    for a, b, _lvl in intervals:
        if t < a - ramp or t > b + ramp:
            continue
        if t < a:
            f = (t - (a - ramp)) / ramp
        elif t <= b:
            f = 1.0
        else:
            f = 1.0 - (t - b) / ramp
        f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
        gg = 1.0 - depth * f
        if gg < g:
            g = gg
    return g


def _mp3_frame_gain(t0, t1, intervals, depth, ramp, n=16):
    s = 0.0
    for i in range(n):
        s += _mp3_gain_at(t0 + (t1 - t0) * (i + 0.5) / n, intervals, depth, ramp)
    return s / n


def _gain_to_steps(g):
    if g >= 1.0:
        return 0
    if g <= 0.0:
        return -255
    return int(round(4.0 * math.log(g, 2.0)))


def splice_mp3(path, out, intervals, sr, ch, gain_db, has_video, progress=None):
    tmp = tempfile.mkdtemp(prefix="debreath_")
    try:
        orig = os.path.join(tmp, "orig.mp3")
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", path, "-vn", "-c:a", "copy", "-f", "mp3", orig], check=True)
        data = bytearray(open(orig, "rb").read())
        frames = mp3_frames(data)
        if not frames:
            raise SystemExit("error: no MP3 frames found")
        h = data[frames[0][0]:frames[0][0] + 4]
        ver = (h[1] >> 3) & 0x03
        chan = (h[3] >> 6) & 0x03
        crc = (h[1] & 0x01) == 0
        mpeg1 = (ver == 3)
        channels = 1 if chan == 3 else 2
        depth = 1.0 - 10.0 ** (-gain_db / 20.0)
        ramp = RAMP_MS / 1000.0
        if progress:
            progress.start(len(frames))
        for f, (o, _l, spf) in enumerate(frames):
            if progress:
                progress.update(f + 1)
            if b"Xing" in data[o:o + 44] or b"Info" in data[o:o + 44]:
                continue
            t0 = (f - MP3_FRAME_OFFSET) * spf / float(sr)
            t1 = (f + 1 - MP3_FRAME_OFFSET) * spf / float(sr)
            steps = _gain_to_steps(_mp3_frame_gain(t0, t1, intervals, depth, ramp))
            if steps == 0:
                continue
            for bo in mp3_gain_offsets(data, o, mpeg1, channels, crc):
                _put_bits(data, bo, 8, max(0, _bits(data, bo, 8) + steps))
        spl = os.path.join(tmp, "spl.mp3")
        with open(spl, "wb") as f:
            f.write(bytes(data))
        cmd = [ffmpeg(), "-v", "error", "-y", "-i", path, "-i", spl]
        cmd += _map_args(has_video)
        cmd += ["-c:a", "copy", "-ignore_unknown"]
        cmd += _container_args(out)
        cmd.append(out)
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            raise SystemExit("error: mux failed\n" + r.stderr.decode(errors="ignore").strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_OPUS_FS = (10, 20, 40, 60)


def _ogg_crc(data):
    crc = 0
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def ogg_pages(data):
    pages = []
    i = 0
    n = len(data)
    while i + 27 <= n:
        if data[i:i + 4] != b"OggS":
            i += 1
            continue
        seg = data[i + 26]
        hdr = 27 + seg
        if i + hdr > n:
            break
        lace = list(data[i + 27:i + 27 + seg])
        body_len = sum(lace)
        if i + hdr + body_len > n:
            break
        pages.append({"off": i, "granule": int.from_bytes(data[i + 6:i + 14], "little"),
                      "serial": int.from_bytes(data[i + 14:i + 18], "little"),
                      "seq": int.from_bytes(data[i + 18:i + 22], "little"),
                      "flags": data[i + 5], "lace": lace, "hdr": hdr, "total": hdr + body_len})
        i += hdr + body_len
    return pages


def ogg_page_packets(data, page):
    body = data[page["off"] + page["hdr"]:page["off"] + page["total"]]
    pk = []
    cur = bytearray()
    o = 0
    for l in page["lace"]:
        cur += body[o:o + l]
        o += l
        if l < 255:
            pk.append(bytes(cur))
            cur = bytearray()
    return pk


def ogg_build_page(packets, granule, serial, seq, flags):
    lace = bytearray()
    body = bytearray()
    for pk in packets:
        l = len(pk)
        while l >= 255:
            lace.append(255)
            l -= 255
        lace.append(l)
        body += pk
    hdr = bytearray(27)
    hdr[0:4] = b"OggS"
    hdr[5] = flags
    hdr[6:14] = (granule & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    hdr[14:18] = serial.to_bytes(4, "little")
    hdr[18:22] = seq.to_bytes(4, "little")
    hdr[26] = len(lace)
    page = bytes(hdr) + bytes(lace) + bytes(body)
    crc = _ogg_crc(page)
    return page[:22] + crc.to_bytes(4, "little") + page[26:]


def opus_packet_samples(p):
    toc = p[0]
    cfg = toc >> 3
    c = toc & 3
    if c == 0:
        nf = 1
    elif c in (1, 2):
        nf = 2
    else:
        nf = p[1] & 0x3F if len(p) > 1 else 1
    if cfg < 12:
        ms = _OPUS_FS[cfg & 3]
    elif cfg < 16:
        ms = (10, 20)[cfg & 1]
    else:
        ms = (2.5, 5, 10, 20)[cfg & 3]
    return int(ms * 48) * nf


def splice_opus(path, out, intervals, sr, ch, gain_db, has_video, progress=None):
    tmp = tempfile.mkdtemp(prefix="debreath_")
    try:
        orig = os.path.join(tmp, "orig.ogg")
        reenc = os.path.join(tmp, "reenc.ogg")
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", path, "-vn", "-c:a", "copy", "-f", "ogg", orig], check=True)
        enc_cmd = [ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
                   "-i", "-", "-c:a", "libopus", "-b:a", "160k", "-frame_duration", "20", "-f", "ogg", reenc]
        p_enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        dec_err = pump_gain(path, sr, ch, intervals, p_enc.stdin, gain_db, progress)
        try:
            p_enc.stdin.close()
        except BrokenPipeError:
            pass
        enc_err = p_enc.stderr.read()
        p_enc.wait()
        if p_enc.returncode != 0:
            raise SystemExit("error: Opus encode failed\n" + enc_err.decode(errors="ignore").strip())
        if dec_err:
            raise SystemExit("error: audio decode failed\n" + dec_err)

        od = open(orig, "rb").read()
        rd = open(reenc, "rb").read()
        spages = ogg_pages(od)
        rpages = ogg_pages(rd)

        def audio_packets(pages, data):
            out = []
            idx = 0
            for pg in pages:
                for pk in ogg_page_packets(data, pg):
                    if idx >= 2 and len(pk) > 0:
                        out.append(pk)
                    idx += 1
            return out

        spk = audio_packets(spages, od)
        rpk = audio_packets(rpages, rd)
        if not spk or not rpk:
            raise SystemExit("error: no Opus packets found")
        dur = opus_packet_samples(spk[0]) or 960
        rate = float(sr)
        sec = dur / rate

        # Replace the breath packets, plus a short tail margin (OPUS_TAIL packets).
        # Opus is a lapped transform: splicing a re-encoded packet right before a
        # source packet makes the decoder overlap-add with the wrong state, which
        # bleeds a few frames past the boundary.  Extending into the (unity-gain)
        # tail lets the decoder state reconverge before we switch back to source.
        repl = {}
        for a, b, _l in intervals:
            i0 = max(0, int(math.floor(a / sec)))
            i1 = int(math.ceil(b / sec)) + OPUS_TAIL
            for i in range(i0, i1):
                if i < len(rpk):
                    repl[i] = rpk[i]

        ai = 0
        parts = []
        for pg in spages:
            new = []
            for pk in ogg_page_packets(od, pg):
                if ai >= 2 and (ai - 2) in repl:
                    new.append(repl[ai - 2])
                else:
                    new.append(pk)
                ai += 1
            parts.append(ogg_build_page(new, pg["granule"], pg["serial"], pg["seq"], pg["flags"]))
        spl = os.path.join(tmp, "spl.ogg")
        with open(spl, "wb") as f:
            f.write(b"".join(parts))

        cmd = [ffmpeg(), "-v", "error", "-y", "-i", path, "-i", spl]
        cmd += _map_args(has_video)
        cmd += ["-c:a", "copy", "-ignore_unknown"]
        cmd += _container_args(out)
        cmd.append(out)
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            raise SystemExit("error: mux failed\n" + r.stderr.decode(errors="ignore").strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def adts_frames(path):
    data = open(path, "rb").read()
    out = []
    i = 0
    n = len(data)
    while i + 7 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xF0) != 0xF0:
            i += 1
            continue
        fl = ((data[i + 3] & 0x03) << 11) | (data[i + 4] << 3) | (data[i + 5] >> 5)
        if fl < 7:
            break
        out.append(data[i:i + fl])
        i += fl
    return out


def encode_gain_aac(path, intervals, sr, ch, gain_db, bitrate, out_aac, progress=None):
    enc_cmd = [ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
               "-i", "-", "-c:a", "aac", "-b:a", str(bitrate), "-f", "adts", out_aac]
    p_enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dec_err = pump_gain(path, sr, ch, intervals, p_enc.stdin, gain_db, progress)
    try:
        p_enc.stdin.close()
    except BrokenPipeError:
        pass
    enc_err = p_enc.stderr.read()
    p_enc.wait()
    if p_enc.returncode != 0:
        raise SystemExit("error: AAC encode failed\n" + enc_err.decode(errors="ignore").strip())
    if dec_err:
        raise SystemExit("error: audio decode failed\n" + dec_err)


def splice_aac(path, out, intervals, sr, ch, gain_db, bitrate, has_video, progress=None):
    tmp = tempfile.mkdtemp(prefix="debreath_")
    try:
        orig = os.path.join(tmp, "orig.aac")
        reenc = os.path.join(tmp, "reenc.aac")
        spl = os.path.join(tmp, "spliced.aac")
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", path, "-vn", "-c:a", "copy", "-f", "adts", orig], check=True)
        encode_gain_aac(path, intervals, sr, ch, gain_db, bitrate, reenc, progress)
        of = adts_frames(orig)
        rf = adts_frames(reenc)
        if not of or not rf:
            raise SystemExit("error: could not parse AAC frames")
        off = len(rf) - len(of)
        if off < 0:
            off = 0
        fr = 1024.0 / sr
        breath = set()
        for a, b, _lvl in intervals:
            i0 = int(a / fr)
            i1 = int(math.ceil(b / fr))
            for i in range(i0, i1):
                breath.add(i)
        sp = list(of)
        for i in range(len(of)):
            j = i + off
            if i in breath and 0 <= j < len(rf):
                sp[i] = rf[j]
        with open(spl, "wb") as f:
            f.write(b"".join(sp))
        cmd = [ffmpeg(), "-v", "error", "-y", "-i", path, "-i", spl]
        cmd += _map_args(has_video)
        cmd += ["-c:a", "copy", "-ignore_unknown"]
        cmd += _container_args(out)
        cmd.append(out)
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            raise SystemExit("error: mux failed\n" + r.stderr.decode(errors="ignore").strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process(path, out, intervals, sr, ch, gain_db, acodec, bitrate, has_video, duration, progress=None):
    if acodec == "aac":
        splice_aac(path, out, intervals, sr, ch, gain_db, bitrate, has_video, progress)
    elif acodec.startswith("pcm_") or acodec in LOSSLESS_AUDIO:
        encode_lossless(path, out, intervals, sr, ch, gain_db, acodec, has_video, progress)
    elif acodec == SPLICE_MP3:
        splice_mp3(path, out, intervals, sr, ch, gain_db, has_video, progress)
    elif acodec == SPLICE_OPUS:
        splice_opus(path, out, intervals, sr, ch, gain_db, has_video, progress)
    else:
        raise SystemExit("error: unsupported audio codec '%s' - refusing (only breaths must be re-encoded)" % acodec)
