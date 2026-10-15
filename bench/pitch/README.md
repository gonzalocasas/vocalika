# Pitch tracker benchmark

How Vocalika chose RMVPE over pyin, and the numbers any future pitch change
has to beat. Results are in `results/`; `summary.csv` holds the table below.

## Conditions

| Condition | What it tests | Ground truth |
|---|---|---|
| `vocadito` | 40 solo a cappella tracks, 29 singers, 9 languages | Vocadito F0 annotations |
| `vocadito-band-demucs` | each Vocadito vocal mixed at 0 dB into a real band instrumental from the project library, then separated with htdemucs -- the path every song takes | same |
| `csd-lead6` | soprano melody 6 dB over an alto harmony below it | Choral Singing Dataset, hand-corrected per-singer F0 |
| `csd-lowlead6` | alto melody 6 dB over a soprano harmony above it | same |
| `csd-duet0` | soprano and alto at equal level, scored against the soprano | same |
| `csd-satb6` | soprano 6 dB over alto, tenor and bass | same |

Choir sections were recorded separately, so mixing them builds harmony with a
known answer.

## Results

Share of voiced frames within 50 cents of the truth (RPA):

| Condition | **vocalika** | pyin (before) | rmvpe | fcpe | torchcrepe | basic-pitch |
|---|---|---|---|---|---|---|
| vocadito | **0.982** | 0.860 | 0.984 | 0.988 | 0.983 | 0.572 |
| vocadito-band-demucs | **0.957** | 0.850 | 0.963 | 0.962 | 0.951 | 0.541 |
| csd-lead6 | **0.840** | 0.294 | 0.553 | 0.360 | 0.652 | 0.339 |
| csd-lowlead6 | **0.956** | 0.489 | 0.961 | 0.954 | 0.950 | 0.440 |
| csd-duet0 | 0.111* | 0.094 | 0.178 | 0.147 | 0.199 | 0.238 |
| csd-satb6 | 0.324 | 0.042 | 0.349 | 0.088 | 0.239 | 0.227 |

Median error on solo / separated-from-band: vocalika 3.1 / 3.9 cents, pyin
11.1 / 11.6. Speed on CPU, as multiples of real time: vocalika 26x (two RMVPE
passes), rmvpe 56x, fcpe 123x, pyin 9x, basic-pitch 7x, torchcrepe 0.7x.

`vocalika` is the shipped path: RMVPE, second-voice recovery, the louder
voice, and cleaning. `rmvpe` alone follows the lower of two voices, which is
why it fails `csd-lead6`.

\* In an equal-level duet there is no acoustic answer to which voice is the
melody; "louder" lands on the alto here. With the project's voice set to
"upper", the same audio scores 0.85 against the soprano.

On the project library, where there is no ground truth, `audit.py` measures
coverage of sung lyric lines and checks that every reported pitch sits on a
harmonic series in the spectrum. RMVPE covered 90-97% of audible sung frames
on every song, where pyin dropped as low as 27% (Queen) and 31% ("Rasguña las
piedras", whose harmonised choruses pyin missed entirely).

## Running it

The benchmark has its own environment, because basic-pitch brings TensorFlow
and PENN needs a newer torch:

```bash
uv venv bench-env && VIRTUAL_ENV=bench-env uv pip install -e ".[real-input]" torchcrepe torchfcpe mir_eval matplotlib
uv venv -p 3.11 bp-env && VIRTUAL_ENV=bp-env uv pip install basic-pitch "setuptools<81"
uv run python scripts/fetch_open_datasets.py vocadito
# Choral Singing Dataset (Zenodo 2649950, CC BY 4.0) unpacked into
# tests/external-data/csd/; RMVPE weights in tests/external-data/models/.
BASIC_PITCH_PYTHON=bp-env/bin/python bench-env/bin/python bench/pitch/run.py
bench-env/bin/python bench/pitch/audit.py --plot <project_id>:30-48
```

Estimates are cached per tracker and clip in
`tests/external-data/pitch-bench-cache/`, so a rerun only rescores. pyin's
estimates survive only there: the extractor itself is gone from Vocalika.
