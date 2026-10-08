# lossless-debreath

Remove breaths (inhalations) from audio and video. The video is copied as-is; only the breaths are made quieter.

[Download (zip)](https://github.com/wdmcourses/lossless-debreath/archive/refs/heads/main.zip)

## What it does

- Finds the breaths automatically.
- Lowers each breath by 30 dB (or your value with `-l`).
- Copies the video as-is and re-encodes only the breaths.
- Keeps the original container and codec.

## Supported formats

- **Video** - any container (MOV, MP4, MKV, WebM and similar); the video is copied as-is.
- **Audio** - MP3, WAV/PCM, FLAC, ALAC, AAC, Opus (WebM/Ogg).

MP3, WAV, FLAC and ALAC stay bit-for-bit identical outside the breaths. For AAC and Opus the difference next to a breath is inaudible.

Unsupported audio codecs are refused.

## Usage

```
debreath <file>
debreath -r <folder>
```

The result is saved in the current folder as `<name>_debreath.<ext>`.

To change how much the breaths are lowered:

```
debreath interview.mov -l 20
```

To process a whole folder (unsupported files are skipped):

```
debreath -r recordings/
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-r` | off | Process every supported file in a folder, recursively. |
| `-v` | off | Print every detected breath region. |
| `-l DB` | `30` | How much to lower the breaths, in dB. |

Tip: add this folder to your PATH to run `debreath` from anywhere.

## Requirements

Windows (x64), Linux (x64) or macOS (Apple Silicon). Everything is bundled - no
system Python or FFmpeg is needed.

### Platform notes

- **Windows:** extract and run `debreath.cmd`.
- **Linux:** extract the tarball and run `./debreath`.
- **macOS:** the build is unsigned, so after downloading run
  `xattr -cr debreath-mac-arm64` once (or right-click → Open).

## Building

Assemble the portable builds (runtimes are already bundled):

```
python scripts/pack.py                 # all platforms
python scripts/pack.py --platform linux-x64
```

Output goes to `dist/debreath-<platform>/` plus an archive
(`debreath-win-x64.zip`, `debreath-linux-x64.tar.gz`, `debreath-mac-arm64.zip`).

## Credits

- [Respiro-en](https://github.com/ydqmkkx/Respiro-en) - breath detection (MIT).
- [FFmpeg](https://ffmpeg.org).
- This tool is MIT-licensed.
