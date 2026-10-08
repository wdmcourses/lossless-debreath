import os
import shutil
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES_DIR = os.path.join(APP_DIR, "resources")


def platform_key():
    if sys.platform.startswith("win"):
        return "win64"
    if sys.platform == "darwin":
        return "mac"
    return "lin64"


PLATFORM_DIR = os.path.join(RESOURCES_DIR, platform_key())
BREATH_MODEL = os.path.join(RESOURCES_DIR, "respiro-en.onnx")
MEL_BASIS = os.path.join(RESOURCES_DIR, "mel_basis.npy")

SR = 16000
N_FFT = 400
HOP = 160
N_MELS = 128
MODEL_WINDOW = 2000
MODEL_HOP = 1800

GAIN_DB = 30.0
THRESHOLD = 0.5
MIN_DUR = 0.05
MAX_DUR = 1.5
MERGE_GAP = 0.05
RAMP_MS = 6.0
OPUS_TAIL = 3

MOV_VIDEO = frozenset({
    "h264", "hevc", "h265", "mpeg4", "mpeg2video", "mpeg1video", "mjpeg",
    "prores", "dnxhd", "dvvideo", "vc1", "wmv1", "wmv2", "wmv3",
    "msmpeg4v2", "msmpeg4v3", "h263", "flv1", "svq3", "cinepak",
    "rawvideo", "ffv1", "huffyuv", "png", "qtrle", "targa", "v210",
})
MP4_VIDEO = MOV_VIDEO | {"av1"}
MOVENC_EXT = (".mov", ".mp4", ".m4v")
WEBM_VIDEO = frozenset({"vp8", "vp9", "av1"})
WEBM_AUDIO = frozenset({"opus", "vorbis"})

MEDIA_EXTS = frozenset({
    ".mov", ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".ts", ".mts", ".m2ts",
    ".m4a", ".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".aac", ".ac3", ".eac3",
})

LOSSLESS_AUDIO = ("flac", "alac")
SPLICE_MP3 = "mp3"
SPLICE_OPUS = "opus"
MP3_FRAME_OFFSET = 1.5

MP3_BITRATE_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
MP3_BITRATE_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
MP3_SAMPLERATE = {3: [44100, 48000, 32000, 0], 2: [22050, 24000, 16000, 0], 0: [11025, 12000, 8000, 0]}

_FFMPEG = None


def tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    for cand in (os.path.join(PLATFORM_DIR, exe), os.path.join(RESOURCES_DIR, exe)):
        if os.path.isfile(cand):
            return cand
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit("error: %s not found (expected in %s or on PATH)" % (name, PLATFORM_DIR))


def ffmpeg():
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = tool("ffmpeg")
    return _FFMPEG
