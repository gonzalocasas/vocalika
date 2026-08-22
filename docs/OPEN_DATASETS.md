# Open test datasets

Vocalika uses two optional open datasets for regression coverage. Their large
archives and extracted files are not redistributed in this repository. They
are pinned to immutable Zenodo records, checksum-verified when downloaded, and
stored under the Git-ignored `tests/external-data/` directory.

## Fetching the data

Fetch and extract both pinned records:

```bash
uv run python scripts/fetch_open_datasets.py
```

Fetch only one dataset:

```bash
uv run python scripts/fetch_open_datasets.py vocadito
uv run python scripts/fetch_open_datasets.py mast-melody
```

The fetcher is idempotent, validates the exact byte size and MD5 checksum
published by Zenodo, rejects unsafe ZIP paths, and expands MAST's nested audio,
F0, and chroma archives. Use `--keep-archives` to retain downloaded ZIP files.
Use `--target PATH` with `VOCALIKA_OPEN_DATA_DIR=PATH` if the datasets should
live outside the default directory.

When the data is absent, its tests are reported as skipped. Once fetched, run
the open-data tests with:

```bash
uv run pytest -m open_data
```

The Vocadito tests compare Vocalika's pYIN estimates with published frame-level
F0 annotations. The MAST tests send published CREPE tracks through Vocalika's
alignment and comparison layers. They include a targeted temporal-alignment
regression and a dataset-wide benchmark covering all exactly paired
performances unanimously rated either perfect or completely off.

## Acknowledgements and licenses

Both datasets are licensed under the [Creative Commons Attribution 4.0
International license](https://creativecommons.org/licenses/by/4.0/). Vocalika
does not redistribute the downloaded records, and the fetched source files are
left unchanged. During the Vocadito test, a temporary eight-second excerpt is
resampled to 16 kHz to match Vocalika's analysis format; the MAST CREPE F0
arrays are read as published.

### Vocadito

Rachel Bittner, Katherine Pasalo, Juan José Bosch, Gabriel Meseguer Brocal,
and David Rubinstein (2021), *vocadito: A dataset of solo vocals with f0, note,
and lyric Annotations*. Zenodo. DOI:
[10.5281/zenodo.5578807](https://doi.org/10.5281/zenodo.5578807).

Vocalika gratefully acknowledges the dataset's singers, annotators, and
creators. The pinned record contains 40 short solo-vocal excerpts with F0,
two independent note transcriptions, lyrics, and language metadata.

### MAST melody dataset

Baris Bozkurt and Ozan Baysal (2023), *MAST melody dataset*. Zenodo. DOI:
[10.5281/zenodo.8007358](https://doi.org/10.5281/zenodo.8007358).

Vocalika gratefully acknowledges the creators, the students whose singing was
recorded during the 2015 and 2016 Istanbul Technical University entrance
examinations, data collectors Cihan Yaygın and Aslı Kılınç, and the expert
annotators. The 2022 annotation work was supported by TÜBİTAK grant 121E198
under the Scientific and Technological Research Projects Funding Program
(1001).

The Zenodo record asks users to also cite the paper announcing the original
dataset:

> Bozkurt, B., Baysal, O., and Yuret, D. (2017). A Dataset and Baseline System
> for Singing Voice Assessment. *13th International Symposium on Computer
> Music Multidisciplinary Research (CMMR 2017)*, Porto, September 25–28, 2017.
