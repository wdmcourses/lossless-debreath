import os

from .config import MOV_VIDEO, MP4_VIDEO, MOVENC_EXT, WEBM_VIDEO, WEBM_AUDIO


def container_supports(ext, vcodec, acodec):
    if not vcodec:
        return ext in (".m4a", ".wav", ".mp3", ".ogg", ".oga", ".opus", ".flac", ".aac", ".ac3", ".eac3", ".alac")
    if ext == ".mov":
        return vcodec in MOV_VIDEO
    if ext in (".mp4", ".m4v"):
        return vcodec in MP4_VIDEO and acodec == "aac"
    if ext == ".webm":
        return vcodec in WEBM_VIDEO and acodec in WEBM_AUDIO
    if ext == ".mkv":
        return True
    return False


def pick_output_ext(vcodec, acodec, src_ext):
    ext = (src_ext or "").lower()
    if not vcodec:
        if container_supports(ext, None, acodec):
            return ext
        return ".m4a" if acodec == "aac" else ".wav"
    if container_supports(ext, vcodec, acodec):
        return ext
    for cand in (".mov", ".mp4", ".mkv"):
        if container_supports(cand, vcodec, acodec):
            return cand
    return ".mkv"


def default_output(path, vcodec, acodec):
    root, ext = os.path.splitext(os.path.basename(path))
    name = root + "_debreath" + pick_output_ext(vcodec, acodec, ext)
    return os.path.join(os.getcwd(), name)


def unique_output(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        cand = "%s (%d)%s" % (root, n, ext)
        if not os.path.exists(cand):
            print("warning: %s exists, writing to %s"
                  % (os.path.basename(path), os.path.basename(cand)))
            return cand
        n += 1


def _container_args(out):
    if out.lower().endswith(MOVENC_EXT):
        return ["-movflags", "+faststart"]
    return []


def _map_args(has_video):
    if has_video:
        return ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-map_metadata", "0", "-map_chapters", "0"]
    return ["-map", "1:a:0", "-map_metadata", "0"]
