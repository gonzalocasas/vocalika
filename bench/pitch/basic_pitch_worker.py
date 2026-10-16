"""Run basic-pitch on one file and save its contour posteriorgram.

Executed with the basic-pitch environment's interpreter (see trackers.py):
python -I basic_pitch_worker.py input.wav output.npz
"""

import sys

import numpy as np
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.constants import (
    ANNOT_N_FRAMES,
    ANNOTATIONS_BASE_FREQUENCY,
    AUDIO_N_SAMPLES,
    AUDIO_SAMPLE_RATE,
    CONTOURS_BINS_PER_SEMITONE,
)
from basic_pitch.inference import predict

source, target = sys.argv[1], sys.argv[2]
model_output, _, _ = predict(source, ICASSP_2022_MODEL_PATH)
contour = np.asarray(model_output["contour"], dtype=np.float32)
frames, bins = contour.shape
# The model's real frame spacing (~254.9 samples, as basic-pitch's own
# sonification uses), not the nominal FFT_HOP of 256: the nominal one drifts
# ~130 ms out of time over 30 s.
times = np.arange(frames) * (AUDIO_N_SAMPLES / ANNOT_N_FRAMES) / AUDIO_SAMPLE_RATE
# Measured on steady tones, a pitch peaks one bin above FREQ_BINS_CONTOURS'
# label for it (exactly +33.3 cents), so bin k is centred on label k - 1.
freqs = ANNOTATIONS_BASE_FREQUENCY * 2.0 ** (
    (np.arange(bins) - 1) / (12.0 * CONTOURS_BINS_PER_SEMITONE)
)
np.savez(target, contour=contour, times=times, freqs=freqs)
