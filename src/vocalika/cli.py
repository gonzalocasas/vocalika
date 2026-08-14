from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from vocalika.api.app import create_app
from vocalika.pipeline import run_analysis
from vocalika.plotting import plot_artifact

app = typer.Typer(no_args_is_help=True, help="Analyze and compare vocal performances.")


@app.command()
def analyze(
    reference: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
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
) -> None:
    """Run the Milestone 0 local-file feasibility analysis."""
    artifact = run_analysis(
        reference,
        performance,
        output,
        reference_is_vocal=reference_is_vocal,
        reference_mix_path=reference_mix,
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
    analysis: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
) -> None:
    """Serve an analysis and the local practice UI."""
    repository_root = Path(__file__).resolve().parents[2]
    frontend_directory = repository_root / "frontend" / "dist"
    uvicorn.run(create_app(analysis, frontend_directory), host=host, port=port)
