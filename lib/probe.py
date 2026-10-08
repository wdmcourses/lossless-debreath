import re
import subprocess

from .config import ffmpeg

_STREAM_RE = re.compile(r"\bStream #\d+:\d+[^:]*: (Video|Audio|Subtitle|Data|Attachment): ([A-Za-z0-9_]+)")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_RATE_RE = re.compile(r"\b(\d+)\s*Hz\b")
_LAYOUT_RE = re.compile(r"\b(\d+)\s*Hz,\s*([^,]+)")
_BITRATE_RE = re.compile(r"\b(\d+)\s*kb/s\b")
_NAMED_LAYOUTS = {"mono": 1, "stereo": 2, "quad": 4, "hexagonal": 6, "octagonal": 8}


def _channels(layout):
    layout = layout.strip()
    if layout in _NAMED_LAYOUTS:
        return _NAMED_LAYOUTS[layout]
    m = re.match(r"(\d+)\s+channels?", layout)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)(?:\.(\d+))?", layout)
    if m:
        n = int(m.group(1)) + (int(m.group(2)) if m.group(2) else 0)
        if n > 0:
            return n
    return 2


def probe_media(path):
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True)
    err = r.stderr
    streams = []
    for line in err.splitlines():
        m = _STREAM_RE.search(line)
        if not m:
            continue
        kind = m.group(1).lower()
        if kind not in ("video", "audio"):
            continue
        st = {"codec_type": kind, "codec_name": m.group(2).lower()}
        if kind == "video":
            size = _SIZE_RE.search(line)
            if size:
                st["width"] = int(size.group(1))
                st["height"] = int(size.group(2))
        else:
            rate = _RATE_RE.search(line)
            if rate:
                st["sample_rate"] = int(rate.group(1))
            layout = _LAYOUT_RE.search(line)
            if layout:
                st["channels"] = _channels(layout.group(2))
            br = _BITRATE_RE.search(line)
            if br:
                st["bit_rate"] = int(br.group(1)) * 1000
        streams.append(st)
    if not streams:
        raise SystemExit("error: ffmpeg could not read %s\n%s" % (path, err.strip()))
    dur = _DURATION_RE.search(err)
    duration = 0.0
    if dur:
        duration = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    return {"streams": streams, "format": {"duration": duration}}
