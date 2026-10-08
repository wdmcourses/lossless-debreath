# lossless-debreath

Remove breaths (inhalations) from audio and video. The video is copied as-is; only the breaths are made quieter.

## What it does

- Finds the breaths automatically.
- Lowers each breath by 30 dB (or your value with `-l`).
- Copies the video as-is and re-encodes only the breaths.
- Keeps the original container and codec.

## Supported formats

- **Video** - any container (MOV, MP4, MKV, WebM and similar).
- **Audio** - MP3, WAV/PCM, FLAC, ALAC, AAC, Opus.

Everything outside the breaths stays bit-for-bit identical.

Unsupported audio codecs are refused.

## Usage

Download the latest release for your platform from
[Releases](https://github.com/wdmcourses/lossless-debreath/releases/latest),
then make `debreath` available in your terminal:

- **Windows** - extract `debreath-win-x64.zip` and add the folder to `PATH`.
- **Linux** - extract `debreath-linux-x64.tar.gz` and symlink it, e.g.
  `ln -s "$PWD/debreath-linux-x64/debreath" ~/.local/bin/debreath`.
- **macOS** - extract `debreath-mac-arm64.zip`, run `xattr -cr debreath-mac-arm64`
  once, and symlink it, e.g.
  `ln -s "$PWD/debreath-mac-arm64/debreath" /usr/local/bin/debreath`.

Then:

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

## Building

Assemble the portable builds (runtimes are already bundled):

```
python scripts/pack.py
python scripts/pack.py --platform linux-x64
```

Output goes to `dist/debreath-<platform>/` plus an archive
(`debreath-win-x64.zip`, `debreath-linux-x64.tar.gz`, `debreath-mac-arm64.zip`).

## Credits

- [Respiro-en](https://github.com/ydqmkkx/Respiro-en) - breath detection (MIT).
- [FFmpeg](https://ffmpeg.org).
- This tool is MIT-licensed.
