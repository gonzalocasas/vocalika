# Appliance hardware: minimum requirements

## Purpose

Size the hardware for selling Vocalika as a self-contained appliance. The device would ship with a
factory image that has everything installed, so a board's install complexity counts only as a
one-time engineering cost. It is never a reason to rule a board out.

Measured 2026-10-17. Board prices and software versions checked 2026-10-18.

## Conclusion

**Memory, not CPU speed, sets the floor.** RMVPE runs a whole song through its network in one
pass, so its peak memory grows with song length. A normal 4-minute song needs about 9 GB.

**Shortlist**

| Option | Runs the current code? | Song import | Notes |
|---|---|---|---|
| Jetson Orin Nano Super, 8 GB ($249 dev kit) | No: needs chunked RMVPE | estimated tens of seconds (GPU) | Best experience at this price. Needs a torch upgrade and a check that GPU output matches CPU |
| Intel N100/N150 mini PC, 16 GB (~$150–200, complete) | Yes | estimated 2–5 min | Cheapest to build; off-the-shelf case, SSD and power supply; plain x86 Linux |
| Raspberry Pi 5, 16 GB (~$120 board) | Yes | estimated 4–8 min | Good for prototyping |
| Jetson Orin NX, 16 GB (~£750 module) | Yes | faster than Orin Nano | Headroom, at three times the price |

Not recommended:

- **NPU boards (e.g. RK3588).** They need quantized, converted models, which puts pitch accuracy
  at risk.

Times on the Jetson, N100 and Pi are **estimates** scaled from the measurements below. None of
these boards has been benchmarked yet.

## Measurements

M3 Max, CPU only, on a 4-minute song ("Almendra – Plegaria para un niño dormido", reference
mix). Each stage ran in its own process at 1, 2, 4 and 14 threads using
[`bench/appliance/stage.py`](../bench/appliance/stage.py).

| Stage | Runs | Time, 1 thread → best | Peak RAM |
|---|---|---|---|
| Demucs `htdemucs` separation | once per song | 144 s → 73 s (4 threads) | 2.6 GB |
| RMVPE, reference (`louder`, two passes) | once per song | 19 s → 13 s | 8.6–9.3 GB |
| MMS lyric timing | once per song | 31 s → 10.5 s | 4.3 GB |
| RMVPE, the singer's take (`single`) | every take | 9 s → 6.5 s | 7–8.5 GB |

What follows from the numbers:

- **Song preparation is where the time goes.** Separation, reference pitch and lyric timing run
  once per song. A take only needs one RMVPE pass plus alignment, which takes seconds. On a slow
  board the user waits when importing a song, not for feedback on each take.
- **More threads stop helping at about 4.** 14 threads were no faster than 4, so a quad-core
  board loses little against a large desktop chip.
- **RMVPE memory is linear in song length:** about 1.3 GB plus about 30 MB per second of audio.

  | Clip length | Peak RAM |
  |---|---|
  | 30 s | 1.9 GB |
  | 60 s | 3.0 GB |
  | 120 s | 4.3 GB |
  | 221 s | 8.3–8.6 GB |

  A 7-minute song would need about 14 GB, the limit for a 16 GB board.
- **Model sizes:** RMVPE has 90 M parameters (173 MB of weights). MMS has 315 M parameters
  (1.2 GB). `htdemucs` is about 80 MB.

## Chunked RMVPE

Running RMVPE over overlapping windows instead of the whole song would cap its memory near 2 GB.
Peak memory would then be set by Demucs at 2.6 GB, which makes 8 GB boards (Jetson Orin Nano,
Pi 5 8 GB) workable, and it also helps the desktop app with long songs.

The risk is that the network's final layer is a bidirectional GRU, which reads the whole sequence.
Chunks with overlap should give near-identical results, but this ships only if the pitch
benchmark (`bench/pitch/`) and the golden artifacts (`tests/golden/`) show no change.

## Jetson

Its strength is speed. Demucs and MMS run on the GPU, so a song could be ready by the time the
user has picked a microphone. Ease of use comes first in Vocalika's priorities, which is what
justifies the price over an N100. Orin modules are guaranteed available until January 2032.

Work it requires:

1. **Upgrade torch.** Vocalika pins `torch==2.2.2`. Jetson needs NVIDIA's own builds for its
   JetPack release (2.6 and 2.8 are reported for JetPack 6.2). torchaudio must stay below 2.9,
   because releases from 2.9 on drop `forced_align`, which the lyric aligner uses. The desktop app
   would move to the same version.
2. **Prove GPU output matches CPU output.** On this GPU generation, PyTorch lets convolutions use
   TF32 (reduced-precision math) by default. Disable it
   (`torch.backends.cudnn.allow_tf32 = False`), then check the GPU output against the CPU output
   on the pitch benchmark. Pitch output must be unchanged.
3. **Chunked RMVPE** is required on the 8 GB Orin Nano: CPU and GPU share that memory.

## Other bill-of-materials items

- **USB audio interface.** The Pi has no analog input. A proper interface also gives better
  takes than an on-board line input.
- **Storage:** an SSD of at least 32 GB. Models and runtime take about 3 GB, and each song adds
  about 80 MB of separated stems as WAV.
- **Network access** if users fetch reference songs from YouTube (`yt-dlp`).

## Next steps

1. Benchmark on real boards: a Pi 5 16 GB and a Jetson Orin Nano Super. Run `stage.py` there with
   `/usr/bin/time -v` and replace the estimates above.
2. Implement chunked RMVPE and validate it against the pitch benchmark and the golden artifacts.
3. For the Jetson, move torch to a JetPack-compatible version and validate GPU output against
   CPU output.

## Sources

- [Jetson product lifecycle (NVIDIA)](https://www.developer.nvidia.com/embedded/lifecycle)
- [Orin lifecycle extension to 2032 (NVIDIA forum)](https://forums.developer.nvidia.com/t/product-lifecycle-extension-of-jetson-xavier-nx-and-jetson-orin-family/312589)
- [Orin Nano Super at $249 (HWBusters)](https://hwbusters.com/news/nvidias-jetson-orin-nano-super-developer-kit-power-affordability-and-ai-innovation-at-249/)
- [Orin NX 16 GB listing (Scan)](https://www.scan.co.uk/products/nvidia-jetson-orin-nx-module-16gb-lpddr5-cortex-a78ae-1024-cuda-cores-157-ai-tops-1gbe-nvme-ampere)
- [torch/torchaudio for JetPack 6.2 (NVIDIA forum)](https://forums.developer.nvidia.com/t/no-torch-and-torchaudio-package-available-for-cuda-12-6-jetpack-6-2/350683)
