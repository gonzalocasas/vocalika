Pitch validation fixtures, 44.1 kHz / 16-bit PCM WAV.
Generated as clean sine tones so ground truth is known exactly.

Start with 01_* static-tone tests. They isolate cents math and F0 extraction.
Then use 02_* for melody/transposition, 03 for alignment, 04 for vibrato,
and 05 for a localized wrong-note test.

Exact reported values may differ slightly due to framing, fades, voiced/unvoiced
thresholds, alignment, and transition handling. Uniform static-tone tests should
nevertheless be very close to their stated expected values.
