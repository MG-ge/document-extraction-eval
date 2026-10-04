"""Calibration: does a run through another route score like the stored API run of the same model?

The last pass ran partly through sign-ins (ChatGPT Plus via the Codex route, Gemini via
Antigravity) instead of the paid API. Each pair below re-runs a stored model at the same
reasoning effort through another route; a paired bootstrap (10,000 resamples of the 300
documents, same seed as scripts/bootstrap.py) of re-run minus stored API run says whether the
route changes the score. An interval containing 0 means no measurable difference on this test set.

gpt-5.6-luna__api-rerun is the API again (pi's openai/ provider billed API credits), so its
interval is the run-to-run noise that the two sign-in routes are measured against.

Usage: python3 scripts/calibrate.py   (run from the repository root, after scripts/verify.py)
"""

import json
import pathlib
import random

PAIRS = [
    ("gpt-5.6-luna__api-rerun", "gpt-5.6-luna"),
    ("gpt-5.6-luna__codex", "gpt-5.6-luna"),
    ("gemini-3.8-flash__extract-text-v1", "gemini-3.8-flash"),
]
DRAWS, SEED = 10_000, 20261004


def scores(model):
    rows = (json.loads(l) for l in pathlib.Path(f"evals/per_document/{model}.jsonl").open() if l.strip())
    return {str(r["id"]): r for r in rows}


rng = random.Random(SEED)
outside = []
for rerun, stored in PAIRS:
    a, b = scores(rerun), scores(stored)
    assert set(a) == set(b), f"{rerun} and {stored} do not cover the same documents"
    ids = sorted(a)
    print(f"{rerun} against {stored}:")
    for key, name in (("score_loose", "official"), ("score_counted_loose", "counted")):
        diffs = [a[i][key] - b[i][key] for i in ids]
        n = len(diffs)
        means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(DRAWS))
        lo, hi = means[int(0.025 * DRAWS)], means[int(0.975 * DRAWS) - 1]
        same = sum(1 for d in diffs if d == 0)
        verdict = "within error" if lo <= 0 <= hi else "OUTSIDE error"
        if verdict != "within error":
            outside.append(f"{rerun} {name}")
        print(f"  {name:8} {sum(a[i][key] for i in ids) / n:.4f} against {sum(b[i][key] for i in ids) / n:.4f}:"
              f" {sum(diffs) / n:+.4f}, 95% interval [{lo:+.4f}, {hi:+.4f}], {verdict}"
              f" ({same}/{n} documents scored the same)")
if outside:
    print("Outside error: " + ", ".join(outside))
