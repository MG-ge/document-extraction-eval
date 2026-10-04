"""Paired bootstrap: is the gap between two models larger than measurement error?

Resamples the 300 test documents with replacement 10,000 times, with the same documents
for both models in each draw, and reports the mean score difference with its 95% interval.
An interval that contains 0 means the gap is within measurement error on this test set.

Usage: python3 scripts/bootstrap.py   (run from the repository root)
"""

import json
import pathlib
import random

PAIRS = [
    ("gemini-3.8-flash", "gpt-5.6-luna"),
    ("gemini-3.8-flash", "gpt-5.6-terra"),
    ("gpt-5.6-terra", "gpt-5.6-luna"),
]
DRAWS = 10_000
SEED = 20261004


def scores(model, key):
    rows = (json.loads(l) for l in pathlib.Path(f"evals/per_document/{model}.jsonl").open() if l.strip())
    return {str(r["id"]): r[key] for r in rows}


rng = random.Random(SEED)
for key, name in (("score_loose", "official"), ("score_counted_loose", "counted")):
    for a, b in PAIRS:
        sa, sb = scores(a, key), scores(b, key)
        diffs = [sa[i] - sb[i] for i in sorted(sa)]
        n = len(diffs)
        means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(DRAWS))
        lo, hi = means[int(0.025 * DRAWS)], means[int(0.975 * DRAWS) - 1]
        print(f"{name:8} {a} minus {b}: {sum(diffs) / n:+.4f}, 95% interval [{lo:+.4f}, {hi:+.4f}]")
