import argparse
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive import make_tar, make_zip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(ROOT, "resources")
RUNTIMES = os.path.join(ROOT, "python")
DIST = os.path.join(ROOT, "dist")

PBS_TAG = "20261003"
PBS_VER = "3.13.16"
PBS_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/" + PBS_TAG
PBS_ASSET = "cpython-{ver}+{tag}-{triple}-install_only_stripped.tar.gz"

DEPS = ["numpy", "onnxruntime"]

TARGETS = {
    "win-x64": {
        "platform_key": "win64",
        "triple": "x86_64-pc-windows-msvc",
        "pip_platform": "win_amd64",
        "site": ("Lib", "site-packages"),
        "ffmpeg": "ffmpeg.exe",
        "launcher": "debreath.cmd",
        "archive": "zip",
    },
    "linux-x64": {
        "platform_key": "lin64",
        "triple": "x86_64-unknown-linux-gnu",
        "pip_platform": "manylinux_2_28_x86_64",
        "site": ("lib", "python3.13", "site-packages"),
        "ffmpeg": "ffmpeg",
        "launcher": "debreath",
        "archive": "tar.gz",
    },
    "mac-arm64": {
        "platform_key": "mac",
        "triple": "aarch64-apple-darwin",
        "pip_platform": "macosx_14_0_arm64",
        "site": ("lib", "python3.13", "site-packages"),
        "ffmpeg": "ffmpeg",
        "launcher": "debreath",
        "archive": "zip",
    },
}


def log(msg):
    print("[pack] " + msg, flush=True)


def download(url, dest):
    log("downloading " + os.path.basename(dest))
    with urllib.request.urlopen(url) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)


def extract_runtime(tar_path, dest):
    os.makedirs(dest, exist_ok=True)
    links = {}
    with tarfile.open(tar_path, "r:gz") as tf:
        for m in tf.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            name = parts[1]
            if m.issym() or m.islnk():
                links[name] = m.linkname[7:] if m.linkname.startswith("python/") else m.linkname
                continue
            m.name = name
            tf.extract(m, dest, filter="fully_trusted")
    for name in links:
        _materialize(dest, name, links)


def _materialize(dest, name, links):
    target = os.path.join(dest, *name.split("/"))
    if os.path.exists(target):
        return
    seen = set()
    cur = name
    while cur in links and cur not in seen:
        seen.add(cur)
        link = links[cur]
        if link.startswith("/"):
            cur = link.lstrip("/")
        else:
            cur = posixpath.normpath(posixpath.join(posixpath.dirname(cur), link))
    src = os.path.join(dest, *cur.split("/"))
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
    elif os.path.isdir(src):
        os.makedirs(target, exist_ok=True)


def pip_install(site, pip_platform):
    os.makedirs(site, exist_ok=True)
    log("installing deps into " + os.path.relpath(site, ROOT))
    cmd = [sys.executable, "-m", "pip", "install",
           "--target", site,
           "--platform", pip_platform,
           "--python-version", "3.13",
           "--only-binary=:all:",
           "--upgrade",
           "--no-warn-script-location",
           "--disable-pip-version-check"] + DEPS
    subprocess.run(cmd, check=True)


def ensure_runtime(target):
    key = target["platform_key"]
    py = os.path.join(RUNTIMES, key)
    marker = os.path.join(py, ".debreath-ready")
    if os.path.isfile(marker):
        return py
    asset = PBS_ASSET.format(ver=PBS_VER, tag=PBS_TAG, triple=target["triple"])
    log("fetching runtime %s" % key)
    shutil.rmtree(py, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="debreath-pbs-")
    try:
        tar_path = os.path.join(tmp, asset)
        download(PBS_URL + "/" + asset, tar_path)
        extract_runtime(tar_path, py)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    pip_install(os.path.join(py, *target["site"]), target["pip_platform"])
    with open(marker, "w") as f:
        f.write(PBS_VER + "+" + PBS_TAG + "\n")
    return py


def assemble(target, runtime, out_dir):
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "debreath.py"), out_dir)
    shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(out_dir, "lib"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(os.path.join(ROOT, target["launcher"]), out_dir)
    res = os.path.join(out_dir, "resources")
    os.makedirs(res, exist_ok=True)
    shutil.copy2(os.path.join(RESOURCES, "respiro-en.onnx"), res)
    shutil.copy2(os.path.join(RESOURCES, "mel_basis.npy"), res)
    shutil.copy2(os.path.join(RESOURCES, target["platform_key"], target["ffmpeg"]), res)
    shutil.copytree(runtime, os.path.join(out_dir, "python"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def archive(target, out_dir):
    label = os.path.basename(out_dir)
    if target["archive"] == "zip":
        dst = os.path.join(DIST, label + ".zip")
        make_zip(out_dir, dst)
    else:
        dst = os.path.join(DIST, label + ".tar.gz")
        make_tar(out_dir, dst)
    log("archive " + os.path.relpath(dst, ROOT))


def main():
    ap = argparse.ArgumentParser(description="Assemble portable debreath builds.")
    ap.add_argument("--platform", choices=list(TARGETS) + ["all"], default="all")
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()

    names = list(TARGETS) if args.platform == "all" else [args.platform]
    os.makedirs(DIST, exist_ok=True)
    for name in names:
        target = TARGETS[name]
        log("=== %s ===" % name)
        runtime = ensure_runtime(target)
        out_dir = os.path.join(DIST, "debreath-" + name)
        assemble(target, runtime, out_dir)
        log("built " + os.path.relpath(out_dir, ROOT))
        if not args.no_archive:
            archive(target, out_dir)


if __name__ == "__main__":
    main()
