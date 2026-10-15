from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from vocalika.api.app import create_app
from vocalika.cache.manager import CacheManager
from vocalika.config import AnalysisConfig
from vocalika.pipeline import run_analysis
from vocalika.plotting import plot_artifact

app = typer.Typer(no_args_is_help=True, help="Analyze and compare vocal performances.")


@app.command()
def analyze(
    reference: Annotated[
        str,
        typer.Option(help="Public YouTube URL or local reference audio path."),
    ],
    performance: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    output: Annotated[
        Path,
        typer.Option(help="Output directory, or an explicit .json artifact path."),
    ] = Path("analysis-output"),
    reference_is_vocal: Annotated[
        bool,
        typer.Option(
            "--reference-is-vocal",
            help="Skip the full-mix warning for isolated vocals.",
        ),
    ] = False,
    reference_mix: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional original mix retained for listening when reference is an isolated stem.",
        ),
    ] = None,
    isolate_performance: Annotated[
        bool,
        typer.Option(
            "--isolate-performance",
            help="Separate the vocal from instruments in the performance before analysis.",
        ),
    ] = False,
    concert_pitch: Annotated[
        float,
        typer.Option(min=400.0, max=480.0, help="Concert A tuning in Hz."),
    ] = 440.0,
    minimum_midi: Annotated[
        float,
        typer.Option(min=0.0, max=126.0, help="Lowest expected vocal pitch as MIDI."),
    ] = 36.0,
    maximum_midi: Annotated[
        float,
        typer.Option(min=1.0, max=127.0, help="Highest expected vocal pitch as MIDI."),
    ] = 84.0,
    cache_directory: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Override the local artifact cache directory."),
    ] = None,
    refresh_cache: Annotated[
        bool,
        typer.Option(help="Recompute downloaded and derived cache entries."),
    ] = False,
) -> None:
    """Acquire, prepare, and compare a reference with a local vocal performance."""
    if minimum_midi >= maximum_midi:
        raise typer.BadParameter("--minimum-midi must be lower than --maximum-midi")
    config = AnalysisConfig(
        concert_pitch_hz=concert_pitch,
        pitch_min_midi=minimum_midi,
        pitch_max_midi=maximum_midi,
    )
    artifact = run_analysis(
        reference,
        performance,
        output,
        reference_is_vocal=reference_is_vocal,
        reference_mix_path=reference_mix,
        isolate_performance=isolate_performance,
        config=config,
        cache_directory=cache_directory,
        refresh_cache=refresh_cache,
        progress=typer.echo,
    )
    typer.echo(f"Next: vocalika plot {artifact}")


@app.command("plot")
def plot_command(
    analysis: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option()] = Path("analysis-output/plot.html"),
) -> None:
    """Generate a standalone interactive diagnostic graph."""
    result = plot_artifact(analysis, output)
    typer.echo(f"Plot written to {result}")


@app.command()
def serve(
    analysis: Annotated[
        Path | None,
        typer.Argument(exists=True, dir_okay=False, readable=True),
    ] = None,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    analyses_directory: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root folder browsed for saved analyses."),
    ] = Path("analysis-output"),
    cache_directory: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Cache used by analyses started in the web UI."),
    ] = None,
) -> None:
    """Serve the analysis workspace, optionally opening an analysis."""
    repository_root = Path(__file__).resolve().parents[2]
    frontend_directory = repository_root / "frontend" / "dist"
    analyses_directory = analyses_directory.expanduser().resolve()
    web_analysis_runner = partial(run_analysis, cache_directory=cache_directory)
    uvicorn.run(
        create_app(
            analysis,
            frontend_directory,
            analyses_directory=analyses_directory / "web",
            library_directory=analyses_directory,
            analysis_runner=web_analysis_runner,
            projects_directory=analyses_directory / "projects",
            cache_directory=cache_directory,
        ),
        host=host,
        port=port,
    )


@app.command()
def reanalyze(
    project: Annotated[
        list[str] | None,
        typer.Option(
            "--project",
            "-p",
            help="Project id, or part of its title. Repeat for several; omit for all.",
        ),
    ] = None,
    analyses_directory: Annotated[
        Path,
        typer.Option(file_okay=False, help="Root folder holding the projects."),
    ] = Path("analysis-output"),
    cache_directory: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Cache shared with the web UI."),
    ] = None,
) -> None:
    """Recompute projects with the current pipeline: reference pitch and every take.

    Each take is compared against the project's current melody voice and the
    key it was recorded in. A take that fails is reported and skipped.
    """
    from vocalika.api.reference_pitch import build_reference_pitch
    from vocalika.projects.repository import ProjectRepository
    from vocalika.projects.service import ProjectService

    repository = ProjectRepository((analyses_directory / "projects").expanduser().resolve())
    cache = (
        CacheManager(cache_directory.expanduser().resolve())
        if cache_directory
        else CacheManager.default()
    )
    service = ProjectService(repository, cache=cache)
    projects = sorted(repository.list(), key=lambda candidate: candidate.title.lower())
    if project:
        chosen = []
        for wanted in project:
            matches = [
                candidate
                for candidate in projects
                if candidate.id == wanted or wanted.lower() in candidate.title.lower()
            ]
            if not matches:
                raise typer.BadParameter(f"No project matches {wanted!r}.")
            if len(matches) > 1:
                titles = ", ".join(candidate.title for candidate in matches)
                raise typer.BadParameter(f"{wanted!r} matches several projects: {titles}.")
            chosen.extend(matches)
        projects = list({candidate.id: candidate for candidate in chosen}.values())

    failures = 0
    for current in projects:
        typer.echo(f"{current.title} (melody: {current.reference_voice} voice)")
        build_reference_pitch(current, service.reference_audio, cache, current.transpose_semitones)
        typer.echo("  reference pitch: ready")
        for take in current.takes:
            try:
                _, analyzed, _ = service.analyze_take(current.id, take.id)
            except Exception as error:  # report it and carry on with the next take
                failures += 1
                typer.echo(f"  {take.name}: FAILED ({error})")
                continue
            summary = analyzed.analysis_summary or {}
            typer.echo(
                f"  {take.name}: offset {summary.get('global_bias_cents', 0.0):+.0f} c, "
                f"error {summary.get('relative_mean_absolute_error_cents', 0.0):.0f} c "
                f"over {summary.get('matched_seconds', 0.0):.0f} s"
            )
    if failures:
        raise typer.Exit(code=1)


@app.command("setup-models")
def setup_models() -> None:
    """Download and cache the separation, pitch and lyric-alignment models."""
    try:
        from demucs.pretrained import get_model
    except ImportError as error:
        raise typer.BadParameter(
            "Real-input dependencies are missing. Run `uv sync --extra real-input`."
        ) from error
    typer.echo("Downloading the htdemucs source-separation model if needed…")
    get_model("htdemucs")
    typer.echo("Model ready: htdemucs")
    from torchaudio.pipelines import MMS_FA

    typer.echo("Downloading the MMS lyric-alignment model if needed…")
    MMS_FA.get_model(with_star=True)
    typer.echo("Model ready: MMS forced aligner")
    from vocalika.analysis.rmvpe import ensure_weights

    typer.echo("Downloading the RMVPE pitch model if needed…")
    ensure_weights()
    typer.echo("Model ready: RMVPE")


@app.command("cache-path")
def cache_path() -> None:
    """Print the default local artifact cache path."""
    typer.echo(CacheManager.default().root)


@app.command("cache-clear")
def cache_clear(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm deletion without an interactive prompt."),
    ] = False,
) -> None:
    """Delete Vocalika's default downloaded and derived artifact cache."""
    cache_root = CacheManager.default().root.resolve()
    if not cache_root.is_dir():
        typer.echo(f"Cache is already empty: {cache_root}")
        return
    if not yes and not typer.confirm(f"Delete Vocalika's cache at {cache_root}?"):
        raise typer.Abort()
    shutil.rmtree(cache_root)
    typer.echo(f"Deleted cache: {cache_root}")
