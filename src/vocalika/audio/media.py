"""Reading and writing compressed audio through PyAV.

PyAV's wheels carry their own FFmpeg libraries (LGPL builds), so decoding,
filtering and encoding need no `ffmpeg` executable on the user's machine and
no per-platform binaries in the desktop app: uv installs PyAV like any other
package.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import av
import av.error
import numpy as np
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
from av.audio.stream import AudioStream
from av.container import InputContainer
from av.filter import Graph
from numpy.typing import NDArray

# Sample formats that carry no more than 16 bits; a lossless re-encode of these
# keeps 16 bits rather than inflating the file to 32.
_SIXTEEN_BIT_FORMATS = {"u8", "u8p", "s16", "s16p"}


class AudioDecodeError(RuntimeError):
    """Raised when an input cannot be read, filtered or encoded."""


@dataclass(frozen=True)
class MediaInfo:
    format_name: str
    duration_seconds: float
    sample_rate: int
    channels: int


def _open(path: Path) -> InputContainer:
    try:
        return av.open(str(path))
    except (av.error.FFmpegError, OSError) as error:
        raise AudioDecodeError(f"Unable to read {path.name}: {error}") from error


def _audio_stream(container: InputContainer, path: Path) -> AudioStream:
    if not container.streams.audio:
        raise AudioDecodeError(f"No audio stream found in {path.name}")
    return container.streams.audio[0]


def _frames(container: InputContainer, stream: AudioStream) -> Iterator[AudioFrame]:
    """Decoded frames of `stream`, skipping packets the decoder rejects.

    A damaged packet in the middle of a download loses a few milliseconds,
    the same as the ffmpeg command line, instead of the whole file.
    """
    for packet in container.demux(stream):
        try:
            decoded: list[Any] = list(packet.decode())
        except av.error.InvalidDataError:
            continue
        yield from (frame for frame in decoded if isinstance(frame, AudioFrame))


def probe(path: Path) -> MediaInfo:
    with _open(path) as container:
        stream = _audio_stream(container, path)
        if container.duration is not None:
            duration = container.duration / av.time_base
        elif stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = 0.0
        return MediaInfo(
            format_name=container.format.name,
            duration_seconds=float(duration),
            sample_rate=int(stream.codec_context.sample_rate),
            channels=int(stream.codec_context.channels),
        )


def duration_seconds(path: Path) -> float | None:
    try:
        return probe(path).duration_seconds
    except AudioDecodeError:
        return None


def decode(
    path: Path,
    *,
    sample_rate: int | None = None,
    mono: bool = False,
) -> tuple[NDArray[np.float32], int]:
    """The first audio stream as float32 `(frames, channels)` samples.

    Resampling and down-mixing go through libswresample with its defaults,
    which is exactly what `ffmpeg -ar <rate> -ac 1` did before.
    """
    with _open(path) as container:
        stream = _audio_stream(container, path)
        rate = sample_rate or int(stream.codec_context.sample_rate)
        resampler = AudioResampler(
            format="fltp",
            layout="mono" if mono else stream.codec_context.layout,
            rate=rate,
        )
        chunks: list[NDArray[Any]] = []
        try:
            for frame in _frames(container, stream):
                chunks.extend(out.to_ndarray() for out in resampler.resample(frame))
            chunks.extend(out.to_ndarray() for out in resampler.resample(None))
        except av.error.FFmpegError as error:
            raise AudioDecodeError(f"Unable to decode {path.name}: {error}") from error
    if not chunks:
        raise AudioDecodeError(f"No audio could be decoded from {path.name}")
    planar = np.concatenate(chunks, axis=1)
    return np.ascontiguousarray(planar.T, dtype=np.float32), rate


def _standard_layout(layout: av.AudioLayout) -> str:
    """A layout an encoder accepts for the same channels.

    A WAV without a channel mask decodes as "2 channels" in no defined order,
    which encoders such as libmp3lame reject.
    """
    return {1: "mono", 2: "stereo"}.get(layout.nb_channels, layout.name)


def _drain(graph: Graph) -> Iterator[AudioFrame]:
    while True:
        try:
            frame = graph.pull()
        except (BlockingIOError, EOFError):
            return
        if isinstance(frame, AudioFrame):
            yield frame


def transcode(
    source: Path,
    destination: Path,
    *,
    codec: str,
    filters: Sequence[tuple[str, str]] = (),
    options: dict[str, str] | None = None,
    sample_rate: int | None = None,
) -> None:
    """Re-encode the first audio stream of `source`, optionally through filters.

    `filters` are `(name, arguments)` pairs chained in order, as in
    `ffmpeg -af name=arguments,...`. The output keeps the source's sample rate
    unless `sample_rate` asks for another (Opus, for one, only takes 48 kHz
    and a few divisors of it).
    """
    with _open(source) as container:
        stream = _audio_stream(container, source)
        try:
            graph: Graph | None = None
            if filters:
                graph = Graph()
                nodes = [graph.add_abuffer(template=stream)]
                nodes += [graph.add(name, arguments) for name, arguments in filters]
                nodes.append(graph.add("abuffersink"))
                graph.link_nodes(*nodes).configure()
            sixteen_bit = stream.codec_context.format.name in _SIXTEEN_BIT_FORMATS

            def frames() -> Iterator[AudioFrame]:
                for frame in _frames(container, stream):
                    if graph is None:
                        yield frame
                        continue
                    graph.push(frame)
                    yield from _drain(graph)
                if graph is not None:
                    graph.push(None)
                    yield from _drain(graph)

            _encode(
                frames(),
                destination,
                codec=codec,
                sample_rate=sample_rate or int(stream.codec_context.sample_rate),
                layout=_standard_layout(stream.codec_context.layout),
                sixteen_bit=sixteen_bit,
                options=options,
            )
        except av.error.FFmpegError as error:
            raise AudioDecodeError(f"Unable to process {source.name}: {error}") from error


def encode(
    audio: NDArray[np.floating[Any]],
    sample_rate: int,
    destination: Path,
    *,
    codec: str,
    options: dict[str, str] | None = None,
) -> None:
    """Encode float `(frames, channels)` samples into `destination`."""
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, None]
    layout = {1: "mono", 2: "stereo"}.get(samples.shape[1])
    if layout is None:
        raise ValueError(f"Cannot encode {samples.shape[1]} channels")
    block = 65_536

    def frames() -> Iterator[AudioFrame]:
        for start in range(0, samples.shape[0], block):
            planar = np.ascontiguousarray(samples[start : start + block].T)
            frame = AudioFrame.from_ndarray(planar, format="fltp", layout=layout)
            frame.sample_rate = sample_rate
            yield frame

    try:
        _encode(
            frames(),
            destination,
            codec=codec,
            sample_rate=sample_rate,
            layout=layout,
            sixteen_bit=False,
            options=options,
        )
    except av.error.FFmpegError as error:
        raise AudioDecodeError(f"Unable to encode {destination.name}: {error}") from error


def _encode(
    frames: Iterator[AudioFrame],
    destination: Path,
    *,
    codec: str,
    sample_rate: int,
    layout: str,
    sixteen_bit: bool,
    options: dict[str, str] | None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(destination), "w") as output:
        out = output.add_stream(codec, rate=sample_rate, layout=layout, options=options or {})
        assert isinstance(out, AudioStream)
        supported = [f.name for f in out.codec_context.codec.audio_formats or ()]
        if sixteen_bit and "s16" in supported:
            out.codec_context.format = "s16"
        # Frames are timed by sample count; carried-over timestamps from the
        # source or filter graph would only confuse the muxer.
        for frame in frames:
            frame.pts = None
            for packet in out.encode(frame):
                output.mux(packet)
        for packet in out.encode(None):
            output.mux(packet)
