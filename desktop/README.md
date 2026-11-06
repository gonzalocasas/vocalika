# Vocalika desktop launcher (spike)

A Tauri app that ships **no Python environment**. Instead it bundles `uv`, the
lockfile exported with hashes, and the Vocalika wheel (which now carries the
built web UI). On first start it builds the environment behind a progress
screen. On every start it runs `vocalika serve` on a free port and points its
window at it.

```sh
cd desktop
npm install
npm run build   # prepare_resources.py, then tauri build
```

`prepare_resources.py` fills `src-tauri/resources/`. The launcher logic is
in `src-tauri/src/main.rs`.

## What happens on first start

1. `uv venv --python 3.12 --python-preference only-managed`: a standalone
   Python goes into the app's data folder; any system Python is ignored.
2. `uv pip sync --compile-bytecode requirements.txt`: the exact locked
   versions, hash-checked.
3. `uv pip install --no-deps` the wheel.
4. A warm-up import (see below).
5. `vocalika setup-models`.

The environment is rebuilt whenever the bundled `stamp.txt` (a hash of the
lock export and wheel) differs from the one recorded after the last good
install, so updates and interrupted installs are handled the same way.
"Repair and retry" on the error screen also clears uv's download cache.

Everything lives in `~/Library/Application Support/app.vocalika.desktop/`
(`runtime/` holds Python, the env and uv's cache; `library/` holds projects).
On Windows the equivalent is `%LOCALAPPDATA%\app.vocalika.desktop\`.

## Measured (macOS arm64, fast connection, 2026-11-04)

| | |
|---|---|
| App bundle | 41 MB (28 MB of it is uv) |
| `cargo` release build | 40 s |
| Python download | 0.9 s |
| 80 packages, download and install | 6.3 s |
| Warm-up import | 24.5 s |
| Model download (1.4 GB) | 15.4 s |
| **First-run install, total** | **47 s** |
| Server start, every launch | 1.2–1.6 s |
| Disk after install | 1.7 GB runtime + 1.4 GB models |

Download times scale with the user's connection: about 0.4 GB of packages
plus 1.4 GB of models.

**The warm-up step matters.** The first import of freshly written native
libraries takes about 23 s on macOS, even with precompiled bytecode. Every
later start takes 1.4 s. The install step pays that cost behind the progress
screen, so the first real launch is fast. Any packaging approach has this
cost, PyInstaller included.

**No quarantine.** Files that uv downloads carry no `com.apple.quarantine`
attribute, so Gatekeeper never looks at the torch dylibs. Only the launcher
and the bundled `uv` need signing and notarization.

**The webview is WebKit on macOS.** The window behaves like Safari, not
Chrome. The first thing this exposed: `play()` resolves before audio flows,
which broke the recording studio's sync check. `playMonitor()` now waits
for every stem's clock to move. Test new audio features in Safari.

## Open before a release

- **ffmpeg/ffprobe.** The spike copies whatever is on PATH. The Homebrew
  build links against `/opt/homebrew` dylibs and won't run on other Macs.
  The options are static per-platform builds bundled in `bin/` (LGPL builds
  exist for macOS arm64/x64 and Windows), or decoding through PyAV, which is
  a pip wheel with ffmpeg inside, so uv would handle it too.
- **Windows is untested.** Things to check: Defender scanning the freshly
  written env, which may make the warm-up slower; long paths inside torch;
  and the server's child process surviving a launcher crash. A Job Object
  would tie their lifetimes together; on macOS, quitting already stops the
  server.
- **Microphone picker.** Recording works in the window: macOS asks once,
  thanks to `NSMicrophoneUsageDescription` in `Info.plist`. It uses the
  system's default input, and the UI doesn't show which one.
- **Model cache location.** The models go to torch's default hub dir
  (`~/.cache/torch`) and the analysis cache to `~/Library/Caches/vocalika`,
  outside the app's folder. Setting `TORCH_HOME` would keep an uninstall
  clean.
- **Offline install.** Not supported. If it's ever needed, ship a wheelhouse
  next to `requirements.txt` and pass `--offline --find-links`.
- **Signing and notarization, DMG/NSIS.** The config already lists the
  targets; they haven't been exercised.
