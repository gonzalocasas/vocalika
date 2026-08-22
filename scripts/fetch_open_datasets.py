#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Dataset:
    key: str
    record_id: int
    title: str
    archive_name: str
    size_bytes: int
    md5: str
    nested_archives: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"https://zenodo.org/api/records/{self.record_id}/files/{self.archive_name}/content"


DATASETS = {
    dataset.key: dataset
    for dataset in (
        Dataset(
            key="vocadito",
            record_id=5578807,
            title="vocadito: A dataset of solo vocals with f0, note, and lyric Annotations",
            archive_name="vocadito.zip",
            size_bytes=58_492_257,
            md5="dea40fd18f14d899643c4ba221b33a46",
        ),
        Dataset(
            key="mast-melody",
            record_id=8007358,
            title="MAST melody dataset",
            archive_name="MASTmelody_dataset.zip",
            size_bytes=331_169_725,
            md5="4f51a6ddff9e92a5d02853a14b618eee",
            nested_archives=(
                "audioFiles/MAST_melody_audio.zip",
                "f0data_crepe/MAST_melody_f0.zip",
                "chroma/MAST_melody_chroma.zip",
            ),
        ),
    )
}


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(dataset: Dataset, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(f"{archive.suffix}.part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        dataset.url, headers={"User-Agent": "Vocalika dataset fetcher"}
    )
    downloaded = 0
    with urllib.request.urlopen(request) as response, partial.open("wb") as destination:
        while chunk := response.read(1024 * 1024):
            destination.write(chunk)
            downloaded += len(chunk)
            print(
                f"\r{dataset.key}: {downloaded / 1_000_000:.1f} / "
                f"{dataset.size_bytes / 1_000_000:.1f} MB",
                end="",
                flush=True,
            )
    print()
    if downloaded != dataset.size_bytes:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Unexpected size for {dataset.archive_name}: {downloaded} bytes "
            f"(expected {dataset.size_bytes})."
        )
    actual_md5 = _md5(partial)
    if actual_md5 != dataset.md5:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"Checksum mismatch for {dataset.archive_name}: {actual_md5} (expected {dataset.md5})."
        )
    os.replace(partial, archive)


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as package:
        root = destination.resolve()
        for member in package.infolist():
            member_destination = (destination / member.filename).resolve()
            try:
                member_destination.relative_to(root)
            except ValueError as error:
                raise RuntimeError(
                    f"Unsafe archive member in {archive.name}: {member.filename}"
                ) from error
        package.extractall(destination)


def _extract(
    dataset: Dataset,
    archive: Path,
    target: Path,
    *,
    keep_archives: bool,
) -> None:
    temporary = target.parent / f".{dataset.key}.extracting"
    if target.exists() or temporary.exists():
        raise RuntimeError(
            f"Refusing to replace existing data at {target}. Remove it explicitly and retry."
        )
    temporary.mkdir(parents=True)
    try:
        _safe_extract(archive, temporary)
        for relative_archive in dataset.nested_archives:
            nested_archive = temporary / relative_archive
            if not nested_archive.is_file():
                raise RuntimeError(
                    f"Expected nested archive is missing from {dataset.archive_name}: "
                    f"{relative_archive}"
                )
            _safe_extract(nested_archive, nested_archive.parent)
            if not keep_archives:
                nested_archive.unlink()
        marker = {
            **asdict(dataset),
            "source_url": dataset.url,
            "record_url": f"https://zenodo.org/records/{dataset.record_id}",
            "license": "CC-BY-4.0",
        }
        (temporary / ".vocalika-dataset.json").write_text(
            json.dumps(marker, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def fetch(dataset: Dataset, root: Path, *, keep_archives: bool) -> None:
    target = root / dataset.key
    marker = target / ".vocalika-dataset.json"
    if marker.is_file():
        installed = json.loads(marker.read_text(encoding="utf-8"))
        if installed.get("record_id") == dataset.record_id and installed.get("md5") == dataset.md5:
            print(f"{dataset.key}: already present and pinned to Zenodo record {dataset.record_id}")
            return
        raise RuntimeError(f"Dataset marker at {marker} does not match the pinned record.")

    archive = root / ".downloads" / dataset.archive_name
    if archive.is_file():
        if archive.stat().st_size != dataset.size_bytes or _md5(archive) != dataset.md5:
            raise RuntimeError(f"Existing archive failed verification: {archive}")
        print(f"{dataset.key}: using verified archive {archive}")
    else:
        _download(dataset, archive)
    _extract(dataset, archive, target, keep_archives=keep_archives)
    if not keep_archives:
        archive.unlink()
    print(f"{dataset.key}: ready at {target}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch pinned open datasets used by Vocalika's opt-in integration tests."
    )
    parser.add_argument(
        "datasets",
        nargs="*",
        choices=sorted(DATASETS),
        help="Dataset keys; omit to fetch all datasets.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests" / "external-data",
        help="Ignored destination root.",
    )
    parser.add_argument("--keep-archives", action="store_true")
    args = parser.parse_args()
    root = args.target.expanduser().resolve()
    try:
        for key in args.datasets or sorted(DATASETS):
            fetch(DATASETS[key], root, keep_archives=args.keep_archives)
    except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
