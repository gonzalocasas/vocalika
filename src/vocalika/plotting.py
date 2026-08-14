from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray
from plotly.subplots import make_subplots

from vocalika.models.artifact import load_artifact


def _valid_values(values: list[float], valid: list[bool]) -> NDArray[np.float64]:
    result = np.asarray(values, dtype=np.float64)
    result[~np.asarray(valid, dtype=np.bool_)] = np.nan
    return result


def plot_artifact(artifact_path: Path, output_path: Path) -> Path:
    artifact = load_artifact(artifact_path)
    frames: dict[str, Any] = artifact["comparison"]["frames"]
    valid = frames["valid"]
    reference_time = frames["reference_time"]
    reference_midi = _valid_values(frames["reference_midi"], valid)
    performance_midi = _valid_values(frames["performance_midi"], valid)
    error = _valid_values(frames["absolute_error_cents"], valid)
    performance_time = np.asarray(frames["performance_time"], dtype=np.float64)
    alignment_offset = performance_time - np.asarray(reference_time, dtype=np.float64)

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.52, 0.28, 0.20],
        subplot_titles=(
            "Aligned continuous pitch",
            "Absolute pitch error",
            "Alignment warp",
        ),
    )
    figure.add_trace(
        go.Scatter(x=reference_time, y=reference_midi, name="Reference", mode="lines"), row=1, col=1
    )
    figure.add_trace(
        go.Scatter(x=reference_time, y=performance_midi, name="Mine", mode="lines"), row=1, col=1
    )
    figure.add_trace(
        go.Scatter(x=reference_time, y=error, name="Error", mode="lines"), row=2, col=1
    )
    figure.add_trace(
        go.Scatter(
            x=reference_time,
            y=alignment_offset,
            name="Performance − reference time",
            mode="lines",
        ),
        row=3,
        col=1,
    )
    figure.add_hline(y=0, line_dash="dot", line_color="#888", row=2, col=1)
    figure.add_hrect(y0=-25, y1=25, fillcolor="#4caf50", opacity=0.12, line_width=0, row=2, col=1)
    figure.update_yaxes(title_text="Continuous MIDI", row=1, col=1)
    figure.update_yaxes(title_text="Cents", row=2, col=1)
    figure.update_yaxes(title_text="Seconds", row=3, col=1)
    figure.update_xaxes(title_text="Reference time (seconds)", row=3, col=1)
    figure.update_layout(title="Vocalika feasibility analysis", hovermode="x unified", height=1050)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs=True)
    return output_path
