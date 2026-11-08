# Open test datasets

Vocalika uses three optional open datasets, all with human-verified
annotations, for regression coverage. Their large
archives and extracted files are not redistributed in this repository. They
are pinned to immutable Zenodo records, checksum-verified when downloaded, and
stored under the Git-ignored `tests/external-data/` directory.

## Fetching the data

Fetch and extract every pinned record:

```bash
uv run python scripts/fetch_open_datasets.py
```

Fetch only one dataset:

```bash
uv run python scripts/fetch_open_datasets.py vocadito
uv run python scripts/fetch_open_datasets.py mast-melody
uv run python scripts/fetch_open_datasets.py csd
```

The Choral Singing Dataset is about 1.1 GB; the other two are 58 and 331 MB.

The fetcher is idempotent, validates the exact byte size and MD5 checksum
published by Zenodo, rejects unsafe ZIP paths, and expands MAST's nested audio,
F0, and chroma archives. Use `--keep-archives` to retain downloaded ZIP files.
Use `--target PATH` with `VOCALIKA_OPEN_DATA_DIR=PATH` if the datasets should
live outside the default directory.

A plain `uv run pytest` includes these tests, and one whose dataset is not
installed **fails**, naming the fetch command: a forgotten download must not
pass as a green run. Run only the open-data tests, or everything else, with:

```bash
uv run pytest -m open_data
uv run pytest -m "not open_data"
```

In CI, the Tests workflow runs everything else on every commit. The Open
datasets workflow (up to 45 minutes) runs when a change touches the analysis
or scoring code, the dependencies or these tests, on every release pull
request (release-please bumps `src/vocalika/__init__.py`), weekly, and by
hand. The datasets are fetched once and cached.

The Vocadito tests send all 40 tracks, covering 29 singers and 9 languages,
through Vocalika's production pitch path -- RMVPE with second-voice search,
then cleaning -- and compare the result with the published frame-level F0
annotations. Each track is scored against a recorded per-track baseline in
`tests/integration/vocadito_pitch_baseline.csv`, with tolerances wide enough to
absorb numerical drift between torch builds but narrow enough to fail on a real
accuracy regression; after an intended change, re-record it with
`uv run python tests/integration/test_open_datasets.py`. Per-track bars key off
the median cents error rather than the mean, because RMVPE errs by an octave
on under 1% of frames in tracks 5, 6, 33, 34 and 40 -- pinned by its own test
so it cannot spread silently. Further Vocadito tests check
the practice layer against the two independent note transcriptions: the notes
`segment_notes` offers for practice must be real notes at the transcribed
pitch, about as often as the second annotator's are, and held notes both
annotators agree on must get the score their annotated F0 implies.

The MAST tests send published CREPE tracks through Vocalika's
alignment and comparison layers. They include a targeted temporal-alignment
regression and a dataset-wide benchmark covering all exactly paired
performances unanimously rated either perfect or completely off. The same
benchmark runs again with every sung take measured by Vocalika's own take
path; the piano references stay on the published track, because RMVPE is
trained on singing and a Vocalika reference is always a voice.

The Choral Singing Dataset tests (`tests/integration/test_choral_singing.py`)
use its hand-corrected per-singer F0. They check, in turn:

- the take path on all 16 singers, soprano to bass, track by track;
- that the reference path's second-voice search costs little on a solo voice;
- voice choice in harmony, built by mixing separately recorded sections: a
  melody over or under a harmony, and equal-level duets with the voice set to
  upper or lower;
- the full pipeline on real reference/take pairs -- singers 2-4 of each
  section against singer 1 -- whose reported bias, per-frame error and
  per-note error must match the intonation difference the annotations show;
- `score_held_note` and `score_interval` on real held notes and leaps.

One published F0 file, `CSD_ND_tenor_3.f0`, is a near-copy of singer 2's and is
left out; a guard test fails if a corrected release appears.

All the open-data tests together take about ten minutes on a laptop CPU.

## Acknowledgements and licenses

Vocadito and MAST are licensed under the [Creative Commons Attribution 4.0
International license](https://creativecommons.org/licenses/by/4.0/); the
Choral Singing Dataset under [Creative Commons Attribution-NonCommercial
4.0](https://creativecommons.org/licenses/by-nc/4.0/), which permits this use
but rules out shipping it in anything sold. Vocalika
does not redistribute the downloaded records, and the fetched source files are
left unchanged. During the Vocadito tests each track is resampled in full to
16 kHz to match Vocalika's analysis format; the MAST CREPE F0 arrays are read as
published. Scoring all 40 tracks -- about 13.6 minutes of audio -- takes well under a
minute with RMVPE, and is shared by every Vocadito test via a session fixture.

The broader comparison that chose RMVPE (pyin, RMVPE, FCPE, torchcrepe and
basic-pitch, solo, separated from a band mix, and in harmony using the Choral
Singing Dataset) lives in `bench/pitch/`; see its README.

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

### Choral Singing Dataset

Helena Cuesta, Emilia Gómez, Agustín Martorell, and Felipe Loáiciga (2018),
*Analysis of Intonation in Unison Choir Singing*. 15th International
Conference on Music Perception and Cognition (ICMPC). Zenodo. DOI:
[10.5281/zenodo.2649950](https://doi.org/10.5281/zenodo.2649950).

Vocalika gratefully acknowledges the singers of the Anton Bruckner Choir of
Barcelona and the dataset's creators. The pinned record contains three SATB
pieces sung by four singers per section, each on an individual microphone,
with hand-corrected F0 for every singer and note annotations for every
section.
