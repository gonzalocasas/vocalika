"""Time one heavy pipeline stage in isolation, for sizing appliance hardware.

Run each stage in its own process under ``/usr/bin/time`` (``-l`` on macOS,
``-v`` on Linux) so peak resident memory belongs to that stage alone:

    OMP_NUM_THREADS=4 /usr/bin/time -l uv run --extra real-input \
        python bench/appliance/stage.py demucs 4 song.mp3 /tmp/separated
    OMP_NUM_THREADS=4 /usr/bin/time -l uv run --extra real-input \
        python bench/appliance/stage.py rmvpe_louder 4 vocals.wav

Stages: ``demucs`` (takes an output directory), ``rmvpe_single`` (a take),
``rmvpe_louder`` (a reference, two passes), ``mms`` (lyric timing). Model
loading is excluded from the reported seconds except for demucs, whose CLI
loads its own model.
"""

import sys
import time
from pathlib import Path

import torch

stage, threads, path = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
torch.set_num_threads(threads)
start = time.perf_counter()
if stage == "demucs":
    from demucs.separate import main

    main(
        ["--two-stems", "vocals", "-n", "htdemucs", "-d", "cpu", "-j", "1"]
        + ["--out", sys.argv[4], "--filename", "{stem}.{ext}", str(path)]
    )
elif stage in ("rmvpe_single", "rmvpe_louder"):
    from vocalika.analysis.rmvpe import load_rmvpe
    from vocalika.config import AnalysisConfig

    load_rmvpe()
    start = time.perf_counter()
    config = AnalysisConfig()
    voice = "single" if stage == "rmvpe_single" else "louder"
    config.pitch_extractor(voice).extract(path)
elif stage == "mms":
    from vocalika.lyrics.alignment import MmsLyricsAligner

    aligner = MmsLyricsAligner()
    aligner._load()
    start = time.perf_counter()
    # Cost is dominated by the acoustic model over the audio, not the text, so
    # placeholder lyrics of a typical song's length are enough for timing.
    words = ("duerme duerme negrito que tu mama esta en el campo " * 25).split()
    aligner.align(path, words, set(range(0, len(words), 8)))
else:
    raise SystemExit(f"Unknown stage: {stage}")
print(f"RESULT {stage} threads={threads} seconds={time.perf_counter() - start:.1f}", flush=True)
