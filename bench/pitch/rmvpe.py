"""Inference-only RMVPE (Wei et al., Interspeech 2023), for the pitch benchmark.

Rewritten from the network in RVC-Project/Retrieval-based-Voice-Conversion-WebUI
(infer/rmvpe.py, MIT), which matches the published ``rmvpe.pt`` weights: a
deep U-Net over a 128-band log-mel spectrogram, a BiGRU, and 360 pitch bins
20 cents apart. Training code, half precision and CUDA graph plumbing are
dropped; nothing here changes what the network computes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from librosa.filters import mel as mel_filters
from torch import nn

SAMPLE_RATE = 16_000
HOP_LENGTH = 160  # 10 ms
N_MELS = 128
N_BINS = 360
# Bin 0 sits at 1997.38 cents above 10 Hz (~31.7 Hz); bins are 20 cents apart.
CENTS_MAPPING = np.pad(20.0 * np.arange(N_BINS) + 1997.3794084376191, (4, 4))


class _ConvBlockRes(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, momentum: float = 0.01) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
            nn.Conv2d(out_channels, out_channels, (3, 3), (1, 1), (1, 1), bias=False),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
        )
        if in_channels != out_channels:
            self.shortcut = nn.Conv2d(in_channels, out_channels, (1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if hasattr(self, "shortcut"):
            return self.conv(x) + self.shortcut(x)
        return self.conv(x) + x


class _ResEncoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, n_blocks=1, momentum=0.01):
        super().__init__()
        self.conv = nn.ModuleList([_ConvBlockRes(in_channels, out_channels, momentum)])
        for _ in range(n_blocks - 1):
            self.conv.append(_ConvBlockRes(out_channels, out_channels, momentum))
        self.kernel_size = kernel_size
        if kernel_size is not None:
            self.pool = nn.AvgPool2d(kernel_size=kernel_size)

    def forward(self, x):
        for conv in self.conv:
            x = conv(x)
        if self.kernel_size is not None:
            return x, self.pool(x)
        return x


class _Encoder(nn.Module):
    def __init__(self, in_channels, in_size, n_encoders, kernel_size, n_blocks, out_channels=16):
        super().__init__()
        self.bn = nn.BatchNorm2d(in_channels, momentum=0.01)
        self.layers = nn.ModuleList()
        for _ in range(n_encoders):
            self.layers.append(_ResEncoderBlock(in_channels, out_channels, kernel_size, n_blocks))
            in_channels = out_channels
            out_channels *= 2
            in_size //= 2
        self.out_channel = out_channels

    def forward(self, x):
        skips = []
        x = self.bn(x)
        for layer in self.layers:
            skip, x = layer(x)
            skips.append(skip)
        return x, skips


class _Intermediate(nn.Module):
    def __init__(self, in_channels, out_channels, n_inters, n_blocks):
        super().__init__()
        self.layers = nn.ModuleList(
            [_ResEncoderBlock(in_channels, out_channels, None, n_blocks)]
            + [_ResEncoderBlock(out_channels, out_channels, None, n_blocks) for _ in range(n_inters - 1)]
        )

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class _ResDecoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride, n_blocks=1, momentum=0.01):
        super().__init__()
        out_padding = (0, 1) if stride == (1, 2) else (1, 1)
        self.conv1 = nn.Sequential(
            nn.ConvTranspose2d(
                in_channels, out_channels, (3, 3), stride, (1, 1), out_padding, bias=False
            ),
            nn.BatchNorm2d(out_channels, momentum=momentum),
            nn.ReLU(),
        )
        self.conv2 = nn.ModuleList([_ConvBlockRes(out_channels * 2, out_channels, momentum)])
        for _ in range(n_blocks - 1):
            self.conv2.append(_ConvBlockRes(out_channels, out_channels, momentum))

    def forward(self, x, skip):
        x = torch.cat((self.conv1(x), skip), dim=1)
        for conv in self.conv2:
            x = conv(x)
        return x


class _Decoder(nn.Module):
    def __init__(self, in_channels, n_decoders, stride, n_blocks):
        super().__init__()
        self.layers = nn.ModuleList()
        for _ in range(n_decoders):
            out_channels = in_channels // 2
            self.layers.append(_ResDecoderBlock(in_channels, out_channels, stride, n_blocks))
            in_channels = out_channels

    def forward(self, x, skips):
        for index, layer in enumerate(self.layers):
            x = layer(x, skips[-1 - index])
        return x


class _DeepUnet(nn.Module):
    def __init__(self, kernel_size, n_blocks, en_de_layers=5, inter_layers=4, in_channels=1, en_out_channels=16):
        super().__init__()
        self.encoder = _Encoder(in_channels, N_MELS, en_de_layers, kernel_size, n_blocks, en_out_channels)
        self.intermediate = _Intermediate(
            self.encoder.out_channel // 2, self.encoder.out_channel, inter_layers, n_blocks
        )
        self.decoder = _Decoder(self.encoder.out_channel, en_de_layers, kernel_size, n_blocks)

    def forward(self, x):
        x, skips = self.encoder(x)
        return self.decoder(self.intermediate(x), skips)


class _BiGRU(nn.Module):
    def __init__(self, input_features, hidden_features, num_layers):
        super().__init__()
        self.gru = nn.GRU(
            input_features, hidden_features, num_layers=num_layers, batch_first=True, bidirectional=True
        )

    def forward(self, x):
        return self.gru(x)[0]


class _E2E(nn.Module):
    def __init__(self, n_blocks=4, n_gru=1, kernel_size=(2, 2), en_out_channels=16):
        super().__init__()
        self.unet = _DeepUnet(kernel_size, n_blocks, en_out_channels=en_out_channels)
        self.cnn = nn.Conv2d(en_out_channels, 3, (3, 3), padding=(1, 1))
        self.fc = nn.Sequential(
            _BiGRU(3 * N_MELS, 256, n_gru), nn.Linear(512, N_BINS), nn.Dropout(0.25), nn.Sigmoid()
        )

    def forward(self, mel):
        x = self.cnn(self.unet(mel.transpose(-1, -2).unsqueeze(1))).transpose(1, 2).flatten(-2)
        return self.fc(x)


class Rmvpe:
    def __init__(self, weights: Path, device: str = "cpu") -> None:
        self.device = device
        self.model = _E2E()
        # weights_only: the checkpoint is a third-party pickle; refuse anything but tensors.
        self.model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
        self.model.eval().to(device)
        basis = mel_filters(sr=SAMPLE_RATE, n_fft=1024, n_mels=N_MELS, fmin=30, fmax=8000, htk=True)
        self.mel_basis = torch.from_numpy(basis).float().to(device)
        self.window = torch.hann_window(1024).to(device)

    def _mel(self, audio: torch.Tensor) -> torch.Tensor:
        spectrum = torch.stft(
            audio, n_fft=1024, hop_length=HOP_LENGTH, win_length=1024, window=self.window,
            center=True, return_complex=True,
        )
        return torch.log(torch.clamp(self.mel_basis @ spectrum.abs(), min=1e-5))

    def salience(self, audio_16k: np.ndarray) -> np.ndarray:
        """Per-frame (10 ms) posterior over the 360 pitch bins."""
        with torch.no_grad():
            audio = torch.from_numpy(np.ascontiguousarray(audio_16k, dtype=np.float32)).to(self.device)
            mel = self._mel(audio.unsqueeze(0))
            frames = mel.shape[-1]
            pad = 32 * ((frames - 1) // 32 + 1) - frames
            if pad:
                mel = torch.nn.functional.pad(mel, (0, pad))
            return self.model(mel)[0, :frames].cpu().numpy()

    @staticmethod
    def decode(salience: np.ndarray, threshold: float = 0.03) -> tuple[np.ndarray, np.ndarray]:
        """Local weighted average around the peak bin -> (f0 Hz with 0 for unvoiced, peak)."""
        center = np.argmax(salience, axis=1) + 4
        padded = np.pad(salience, ((0, 0), (4, 4)))
        offsets = np.arange(-4, 5)
        index = center[:, None] + offsets[None, :]
        weights = np.take_along_axis(padded, index, axis=1)
        cents = (weights * CENTS_MAPPING[index]).sum(1) / np.maximum(weights.sum(1), 1e-9)
        peak = salience.max(axis=1)
        f0 = 10.0 * 2.0 ** (cents / 1200.0)
        f0[peak <= threshold] = 0.0
        return f0, peak
