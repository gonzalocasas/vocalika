"""RMVPE, the neural vocal pitch estimator Vocalika measures singing with.

RMVPE (Wei et al., "RMVPE: A Robust Model for Vocal Pitch Estimation in
Polyphonic Music", Interspeech 2023) reads a 128-band log-mel spectrogram
through a deep U-Net and a BiGRU and outputs, every 10 ms, a posterior over
360 pitch bins 20 cents apart. The pitch is a weighted average around the
strongest bin, so it resolves well below the bin spacing.

It replaced pyin because pyin is a single-periodicity detector: wherever two
people sing at once, or the vocal stem carries residue of the band, it
decides nothing is being sung. On Vocalika's benchmark (bench/pitch) RMVPE
placed 98% of solo frames within 50 cents against pyin's 86%, with a median
error of 3 cents against 11, and covered 90-96% of the sung lines of every
library song where pyin dropped as low as 27%.

The network below is the inference half of the version in
RVC-Project/Retrieval-based-Voice-Conversion-WebUI (MIT), which is what the
published weights were trained as.
"""

from __future__ import annotations

import hashlib
import threading
from functools import cache
from pathlib import Path

import numpy as np
import torch
from librosa.filters import mel as mel_filters
from numpy.typing import NDArray
from torch import nn

SAMPLE_RATE = 16_000
HOP_LENGTH = 160  # 10 ms
WINDOW_LENGTH = 1024
N_MELS = 128
N_BINS = 360
# Bin 0 sits 1997.38 cents above 10 Hz (~31.7 Hz); bins are 20 cents apart.
_CENTS = np.pad(20.0 * np.arange(N_BINS) + 1997.3794084376191, (4, 4))

# Pinned to one commit of the publisher's repository, and checked on arrival.
WEIGHTS_URL = (
    "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/"
    "e6d0c1a17da07c33557852f9dfa2bd44cc75737d/rmvpe.pt"
)
WEIGHTS_SHA256 = "6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193"
WEIGHTS_FILENAME = "rmvpe.pt"

FloatArray = NDArray[np.float64]


class _ConvBlockRes(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_channels, momentum=0.01),
            nn.ReLU(),
            nn.Conv2d(out_channels, out_channels, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_channels, momentum=0.01),
            nn.ReLU(),
        )
        self.shortcut: nn.Module | None = (
            nn.Conv2d(in_channels, out_channels, (1, 1)) if in_channels != out_channels else None
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x if self.shortcut is None else self.shortcut(x)
        out: torch.Tensor = self.conv(x) + residual
        return out


class _ResBlock(nn.Module):
    """A stack of residual conv blocks, optionally followed by pooling."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        n_blocks: int,
        pool: tuple[int, int] | None,
    ) -> None:
        super().__init__()
        self.conv = nn.ModuleList(
            [_ConvBlockRes(in_channels, out_channels)]
            + [_ConvBlockRes(out_channels, out_channels) for _ in range(n_blocks - 1)]
        )
        self.pool = nn.AvgPool2d(kernel_size=pool) if pool is not None else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for block in self.conv:
            x = block(x)
        return x

    def forward_pooled(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.forward(x)
        assert self.pool is not None
        pooled: torch.Tensor = self.pool(x)
        return x, pooled


class _Encoder(nn.Module):
    def __init__(self, layers: int, n_blocks: int, out_channels: int) -> None:
        super().__init__()
        self.bn = nn.BatchNorm2d(1, momentum=0.01)
        self.layers = nn.ModuleList()
        in_channels = 1
        for _ in range(layers):
            self.layers.append(_ResBlock(in_channels, out_channels, n_blocks, (2, 2)))
            in_channels, out_channels = out_channels, out_channels * 2
        self.out_channels = out_channels

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, list[torch.Tensor]]:
        skips: list[torch.Tensor] = []
        x = self.bn(x)
        for layer in self.layers:
            assert isinstance(layer, _ResBlock)
            skip, x = layer.forward_pooled(x)
            skips.append(skip)
        return x, skips


class _DecoderBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, n_blocks: int) -> None:
        super().__init__()
        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(
                in_channels, out_channels, (3, 3), (2, 2), (1, 1), (1, 1), bias=False
            ),
            nn.BatchNorm2d(out_channels, momentum=0.01),
            nn.ReLU(),
        )
        self.conv2 = nn.ModuleList(
            [_ConvBlockRes(out_channels * 2, out_channels)]
            + [_ConvBlockRes(out_channels, out_channels) for _ in range(n_blocks - 1)]
        )

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        x = torch.cat((self.conv1(x), skip), dim=1)
        for block in self.conv2:
            x = block(x)
        return x


class _DeepUnet(nn.Module):
    def __init__(self, n_blocks: int = 4, layers: int = 5, inter_layers: int = 4) -> None:
        super().__init__()
        self.encoder = _Encoder(layers, n_blocks, 16)
        channels = self.encoder.out_channels
        self.intermediate = nn.Module()
        self.intermediate.layers = nn.ModuleList(
            [_ResBlock(channels // 2, channels, n_blocks, None)]
            + [_ResBlock(channels, channels, n_blocks, None) for _ in range(inter_layers - 1)]
        )
        self.decoder = nn.Module()
        self.decoder.layers = nn.ModuleList()
        for _ in range(layers):
            self.decoder.layers.append(_DecoderBlock(channels, channels // 2, n_blocks))
            channels //= 2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x, skips = self.encoder(x)
        for layer in self.intermediate.layers:
            x = layer(x)
        for index, layer in enumerate(self.decoder.layers):
            x = layer(x, skips[-1 - index])
        return x


class _BiGRU(nn.Module):
    def __init__(self, input_features: int, hidden_features: int) -> None:
        super().__init__()
        self.gru = nn.GRU(input_features, hidden_features, batch_first=True, bidirectional=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.gru(x)[0]
        return out


class _Network(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.unet = _DeepUnet()
        self.cnn = nn.Conv2d(16, 3, (3, 3), padding=(1, 1))
        self.fc = nn.Sequential(
            _BiGRU(3 * N_MELS, 256), nn.Linear(512, N_BINS), nn.Dropout(0.25), nn.Sigmoid()
        )

    def forward(self, mel: torch.Tensor) -> torch.Tensor:
        x = self.cnn(self.unet(mel.transpose(-1, -2).unsqueeze(1)))
        out: torch.Tensor = self.fc(x.transpose(1, 2).flatten(-2))
        return out


def weights_path() -> Path:
    """Where the weights live: torch's hub cache, beside demucs and MMS."""
    hub = torch.hub.get_dir()  # type: ignore[no-untyped-call]
    return Path(hub) / "checkpoints" / WEIGHTS_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_download_lock = threading.Lock()


def ensure_weights() -> Path:
    """Download the weights once, refusing any file that is not the pinned one."""
    path = weights_path()
    with _download_lock:
        if path.is_file() and _sha256(path) == WEIGHTS_SHA256:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        torch.hub.download_url_to_file(WEIGHTS_URL, str(partial), progress=False)
        actual = _sha256(partial)
        if actual != WEIGHTS_SHA256:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                f"RMVPE weights failed verification (sha256 {actual}, expected {WEIGHTS_SHA256})"
            )
        partial.replace(path)
        return path


class Rmvpe:
    """One loaded RMVPE network; ``salience`` is safe to call from several threads."""

    def __init__(self, weights: Path) -> None:
        self.network = _Network()
        # weights_only: the checkpoint is a pickle; refuse anything but tensors.
        state = torch.load(weights, map_location="cpu", weights_only=True)
        self.network.load_state_dict(state)
        self.network.eval()
        basis = mel_filters(
            sr=SAMPLE_RATE, n_fft=WINDOW_LENGTH, n_mels=N_MELS, fmin=30, fmax=8000, htk=True
        )
        self.mel_basis = torch.from_numpy(basis).float()
        self.window = torch.hann_window(WINDOW_LENGTH)

    def salience(self, audio: NDArray[np.float32]) -> NDArray[np.float32]:
        """Per-frame (10 ms, centred) posterior over the 360 pitch bins."""
        samples = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        with torch.inference_mode():
            spectrum = torch.stft(
                samples.unsqueeze(0),
                n_fft=WINDOW_LENGTH,
                hop_length=HOP_LENGTH,
                win_length=WINDOW_LENGTH,
                window=self.window,
                center=True,
                return_complex=True,
            )
            mel = torch.log(torch.clamp(self.mel_basis @ spectrum.abs(), min=1e-5))
            frames = mel.shape[-1]
            # The U-Net halves the time axis five times.
            padding = 32 * ((frames - 1) // 32 + 1) - frames
            if padding:
                mel = torch.nn.functional.pad(mel, (0, padding))
            result: NDArray[np.float32] = self.network(mel)[0, :frames].numpy()
            return result


def decode(salience: NDArray[np.float32], threshold: float) -> tuple[FloatArray, FloatArray]:
    """(f0 in Hz with 0 where unvoiced, peak salience) per frame.

    The pitch is the salience-weighted average of the nine bins around the
    strongest one, which is what gives RMVPE its sub-bin resolution.
    """
    centre = np.argmax(salience, axis=1) + 4
    padded = np.pad(salience.astype(np.float64), ((0, 0), (4, 4)))
    window = centre[:, None] + np.arange(-4, 5)[None, :]
    weights = np.take_along_axis(padded, window, axis=1)
    cents = (weights * _CENTS[window]).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-12)
    peak = salience.max(axis=1).astype(np.float64)
    f0 = 10.0 * 2.0 ** (cents / 1200.0)
    f0[peak <= threshold] = 0.0
    return f0, peak


@cache
def load_rmvpe() -> Rmvpe:
    return Rmvpe(ensure_weights())
