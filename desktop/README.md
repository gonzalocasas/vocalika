# Vocalika desktop app

A Tauri app that ships **no Python environment**. Instead it bundles `uv`, the
lockfile exported with hashes, and the Vocalika wheel (which now carries the
built web UI). On first start it builds the environment behind a progress
screen. On every start it runs `vocalika serve` on a local port and points its
window at it. It prefers the same port (47615) every launch, because the
webview keys what it remembers (chosen audio devices, the lyrics size, the
microphone permission) by origin, port included; only if that port is taken
does it fall back to any free one for that session.

No ffmpeg is bundled. Decoding, transposition and MP3 export go through PyAV,
whose wheels carry FFmpeg's libraries (an LGPL build), so uv installs them
like any other package and the installer itself contains no FFmpeg code.
yt-dlp keeps YouTube's audio as served (no `--extract-audio`, which needs the
ffmpeg executable), and demucs is handed a WAV decoded by PyAV, since its own
reader shells out to ffmpeg for Opus.

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

Everything the app writes lives in
`~/Library/Application Support/app.vocalika.desktop/` (on Windows,
`%LOCALAPPDATA%\app.vocalika.desktop\`), so deleting that folder removes the
app completely:

| | |
|---|---|
| `runtime/` | Python, the env, uv's download cache, other libraries' caches (`XDG_CACHE_HOME`, `MPLCONFIGDIR`). Rebuilt on update. |
| `models/` | The demucs, RMVPE and MMS weights (`TORCH_HOME`, `HF_HOME`). Kept across updates. |
| `cache/` | Vocalika's analysis cache (`VOCALIKA_CACHE_DIR`). |
| `settings.json` | The chosen data folder (`VOCALIKA_SETTINGS`). |
| `library/`, `server.log` | The start-up library folder and the server's log. |

The one deliberate exception is the singer's projects, which go to the data
folder they choose in the app (`~/Music/Vocalika` by default). The webview's
own caches (`~/Library/WebKit/app.vocalika.desktop`) belong to the system.
The Windows NSIS uninstaller offers to delete the app's data folder; on macOS,
dragging the app to the bin leaves it, as it does for most Mac apps.

## Measured (macOS arm64, fast connection, 2026-11-06)

| | |
|---|---|
| App bundle / DMG | 39 MB / 19 MB (28 MB of the app is uv) |
| `cargo` release build | 10–40 s |
| Python download | 0.9 s |
| Packages, download and install | 6.9 s |
| Warm-up import | 32 s |
| Model download (1.4 GB) | 17 s |
| **First-run install, total** | **57 s** |
| Update (new wheel or lock; models kept) | 42 s |
| Server start, every launch | 1.7 s |
| Disk after install | 1.8 GB runtime + 1.4 GB models |

Verified end to end in the built app, launched with the bare PATH a Finder
launch gets (no Homebrew, so no ffmpeg or deno anywhere): a YouTube import,
demucs separation of the Opus download, RMVPE pitch, waveforms, and
transposition up and down.

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
Chrome. What this has exposed so far: `play()` resolves before audio flows,
which broke the recording studio's sync check (`playMonitor()` now waits for
every stem's clock to move); and WebKit refuses FLAC labelled `audio/x-flac`,
Python's default, so transposed stems failed to play until the server said
`audio/flac`. The webview also shows no `alert`/`confirm`/`prompt` dialogs:
`confirm()` silently returns false, which made deleting a take do nothing.
Confirm in the page instead. Device ids and names stay hidden until the page
has used the microphone, so the app opens it for a moment at start-up when a
device was chosen. Audio entering Web Audio from a media stream (the mic)
passes a fixed 50 ms buffer, measured by digital loopback; the recording
studio's latency calibration includes it. Test new audio features in Safari.

## Open before a release

- **Windows is untested.** Things to check: Defender scanning the freshly
  written env, which may make the warm-up slower; long paths inside torch;
  the server's child process surviving a launcher crash (a Job Object would
  tie their lifetimes together); and the device picker, where WebView2
  (Chromium) should offer output selection.
- **Output device on macOS.** WebKit has `setSinkId` on media elements
  (not on AudioContext) but rejects it outside a user gesture, so the app
  re-routes players at the start of each click or key press, and practice
  tones go through an `<audio>` element. Verified that WebKit accepts the
  calls and keeps playing; routing to a real second device still needs a
  listen on a Mac with one.
- **Keeping yt-dlp current.** YouTube changes often, and a yt-dlp more than a
  few months old stops working. The lock pins it, so today a fix needs an app
  update. Updating just yt-dlp at launch (`uv pip install -U yt-dlp`) would
  decouple the two.
- **Uninstall on macOS** leaves the data folder, as dragging any Mac app to
  the bin does. An "uninstall" action in the app could remove it.
- **Signing and notarization.** The Mac app is signed ad hoc, so macOS
  shows "unidentified developer" and offers **Open Anyway** in System
  Settings → Privacy & Security, instead of calling it damaged. Windows
  shows a SmartScreen warning. Proper signing needs an Apple Developer ID
  (Tauri reads `APPLE_CERTIFICATE`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
  `APPLE_PASSWORD`, `APPLE_TEAM_ID`) and a Windows code-signing
  certificate.

## Releasing

Releases are cut by [Release Please](https://github.com/googleapis/release-please)
(`.github/workflows/release.yml`), from Conventional Commit messages:

1. Every push to main updates an open release pull request: the next
   version (`feat:` bumps minor, `fix:` patch, while below 1.0) and the
   changelog. It bumps the version in `pyproject.toml`, `tauri.conf.json`,
   `Cargo.toml` and both `package.json` files together.
2. Merging that pull request tags the release and publishes it.
3. The same workflow then builds the installers on macOS (Apple Silicon)
   and Windows, and attaches them to the release under fixed names,
   `Vocalika-macOS-AppleSilicon.dmg` and `Vocalika-Windows-x64-setup.exe`,
   so `.../releases/latest/download/<name>` always gets the newest.
4. It also attaches each platform's signed update (on macOS the app bundle
   as `Vocalika-macOS-AppleSilicon.app.tar.gz`; on Windows the installer
   itself) with its `.sig`, and last `latest.json`
   ([update_manifest.py](update_manifest.py)), which installed apps read.

To rebuild the installers of an existing release, run the workflow by hand
with its tag. Intel Macs are not a target: numba, llvmlite and sphn publish
no x86_64 macOS wheels at the locked versions.

## Updates

Once the app is running, the launcher asks
`https://github.com/gonzalocasas/vocalika/releases/latest/download/latest.json`
for a newer version ([tauri-plugin-updater](https://v2.tauri.app/plugin/updater/)),
downloads it in the background and tells the page, which shows **Restart
to update** in the top bar. **Later** installs it on quit instead. Offline,
or with GitHub unreachable, nothing is shown and the next launch tries
again. The first start of the new version rebuilds the Python environment,
as any update does (see above).

The page is served by the local server, so to Tauri it is a remote origin:
[capabilities/local-server.json](src-tauri/capabilities/local-server.json)
lets `http://127.0.0.1:*` call only `update_ready` and `install_update`.

An update installs only if it is signed with the release key and the
signature names the version `latest.json` announces (`requireSignedVersion`,
so an old release cannot be passed off as a new one). The public key is in
`tauri.conf.json`. The private key and its password are the repository
secrets `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`,
with a copy kept outside GitHub. **If the key is lost, installed apps can
no longer update**: everyone would have to install the next version by hand,
and that version would carry a new key.

Only CI signs, so local `tauri build`s need no key: the workflow switches on
`createUpdaterArtifacts` with `--config`. To try an update end to end
locally, build two versions with a throwaway key
(`npx tauri signer generate --ci -p "" -w test.key`), passing
`--config` with that `pubkey`, an `http://127.0.0.1` endpoint,
`dangerousInsecureTransportProtocol: true` and another `identifier` (so the
real install's data is left alone); serve the newer `.app.tar.gz` and a
`latest.json` pointing at it, and run the older app.
