"""Run basic-pitch on one file and save its contour posteriorgram.

Executed with the basic-pitch environment's interpreter (see trackers.py):
python -I basic_pitch_worker.py input.wav output.npz
"""

import sys

import numpy as np
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.constants import (
    ANNOTATIONS_BASE_FREQUENCY,
    AUDIO_SAMPLE_RATE,
    CONTOURS_BINS_PER_SEMITONE,
    FFT_HOP,
)
from basic_pitch.inference import predict

source, target = sys.argv[1], sys.argv[2]
model_output, _, _ = predict(source, ICASSP_2022_MODEL_PATH)
contour = np.asarray(model_output["contour"], dtype=np.float32)
frames, bins = contour.shape
times = np.arange(frames) * FFT_HOP / AUDIO_SAMPLE_RATE
freqs = ANNOTATIONS_BASE_FREQUENCY * 2.0 ** (np.arange(bins) / (12.0 * CONTOURS_BINS_PER_SEMITONE))
np.savez(target, contour=contour, times=times, freqs=freqs)
