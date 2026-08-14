from pathlib import Path

from vocalika.pipeline import _resolve_output_paths


def test_output_directory_gets_default_artifact_name(tmp_path: Path) -> None:
    output_directory, artifact = _resolve_output_paths(tmp_path / "result")

    assert output_directory == (tmp_path / "result").resolve()
    assert artifact == (tmp_path / "result" / "analysis.json").resolve()


def test_explicit_json_output_is_preserved(tmp_path: Path) -> None:
    output_directory, artifact = _resolve_output_paths(tmp_path / "comparison.json")

    assert output_directory == tmp_path.resolve()
    assert artifact == (tmp_path / "comparison.json").resolve()
