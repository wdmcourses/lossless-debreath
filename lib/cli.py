import argparse
import os
import sys

from .config import GAIN_DB, MEDIA_EXTS, SPLICE_MP3, ffmpeg
from .probe import probe_media
from .detect import breath_probabilities, detect
from .containers import default_output, unique_output
from .codecs import process
from .progress import Progress


def fmt_time(t):
    return "%.3f" % t


def run_file(path, gain_db, verbose=False, detail=True):
    probe = probe_media(path)
    streams = probe.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if astream is None:
        raise SystemExit("no audio stream")
    has_video = vstream is not None
    vcodec = vstream.get("codec_name") if has_video else None
    sr = int(astream["sample_rate"])
    ch = int(astream["channels"])
    acodec = astream.get("codec_name", "")
    bitrate = astream.get("bit_rate")
    bitrate = int(bitrate) if (bitrate and str(bitrate).isdigit() and int(bitrate) > 0) else 256000
    duration = float(probe.get("format", {}).get("duration", 0.0) or 0.0)

    if detail:
        print("input      : %s" % path)
        if has_video:
            print("video      : %s %sx%s (copied bit-for-bit)" % (vcodec, vstream.get("width"), vstream.get("height")))
        else:
            print("video      : none (audio-only)")
        print("audio      : %s %s Hz, %s ch" % (acodec, sr, ch))
        print("detector   : Respiro-en (breath detection, ONNX)")

    name = os.path.basename(path)
    det = Progress("detect " + name)
    try:
        probs, rms_db = breath_probabilities(path, det)
    finally:
        det.close()
    intervals = detect(probs, rms_db)

    total = sum(b - a for a, b, _ in intervals)
    pct = (100.0 * total / duration) if duration else 0.0
    if detail:
        print("breaths    : %d region(s), %.2f s (%.1f%% of audio), attenuated by %.0f dB"
              % (len(intervals), total, pct, gain_db))
        if verbose:
            for idx, (a, b, lvl) in enumerate(intervals, 1):
                print("  %3d  %8s - %8s  dur %6.3f  level %6.1f dB" % (idx, fmt_time(a), fmt_time(b), b - a, lvl))

    out = unique_output(os.path.abspath(default_output(path, vcodec, acodec)))
    wr = Progress("write " + name)
    if acodec != SPLICE_MP3 and duration:
        wr.start(int(duration * sr))
    try:
        process(path, out, intervals, sr, ch, gain_db, acodec, bitrate, has_video, duration, wr)
    finally:
        wr.close()

    if detail:
        print("output     : %s" % out)
        parts = []
        if has_video:
            parts.append("video copied bit-for-bit")
        parts.append("live audio copied bit-for-bit")
        parts.append("breaths -%.0f dB" % gain_db)
        print("done       : " + ", ".join(parts))
    else:
        print("  %-40s %d breath(s), %.2f s (%.1f%%) -> %s"
              % (name, len(intervals), total, pct, os.path.basename(out)))
    return {"breaths": len(intervals), "removed": total, "duration": duration}


def collect_inputs(path):
    files = []
    for root, dirs, names in os.walk(path):
        dirs.sort()
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in MEDIA_EXTS:
                files.append(os.path.join(root, name))
    return files


def main():
    ap = argparse.ArgumentParser(prog="debreath", description="Remove breaths from a video or audio file. Video is copied bit-for-bit; live audio is copied bit-for-bit (only breath frames are re-encoded).")
    ap.add_argument("input", help="input media file or folder (with -r)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="process every supported file in a folder, recursively")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show every breath region")
    ap.add_argument("-l", type=float, default=GAIN_DB, metavar="DB",
                    help="breath attenuation in dB (default %(default)s)")
    args = ap.parse_args()
    gain_db = abs(args.l)
    ffmpeg()

    path = os.path.abspath(args.input)
    if not args.recursive:
        if not os.path.isfile(path):
            raise SystemExit("error: input not found: %s" % path)
        run_file(path, gain_db, args.verbose, detail=True)
        return

    if not os.path.isdir(path):
        raise SystemExit("error: -r requires a folder: %s" % path)
    inputs = collect_inputs(path)
    if not inputs:
        raise SystemExit("error: no supported files found in %s" % path)

    processed = 0
    skipped = 0
    breaths = 0
    removed = 0.0
    for i, item in enumerate(inputs, 1):
        print("[%d/%d] %s" % (i, len(inputs), item))
        try:
            stats = run_file(item, gain_db, args.verbose, detail=args.verbose)
            processed += 1
            breaths += stats["breaths"]
            removed += stats["removed"]
        except SystemExit as exc:
            skipped += 1
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "failed"
            print("skipped    : %s (%s)" % (item, reason))
    print("summary    : %d processed, %d skipped, %d breath(s) removed, %.2f s"
          % (processed, skipped, breaths, removed))
    if processed == 0:
        sys.exit(1)
