"""Re-score every stored answer from scratch and check it against the published files.

Three checks, any failure exits non-zero:

1. Every predictions file answers exactly the 300 test documents of the frozen split, and
   each document's correct answer hashes to the `answer_sha256` recorded in the split, so
   the correct answers here are the dataset's, unedited.
2. `scorer/score.ts` re-scores every answer, and each document's four scores equal the ones
   in `evals/per_document/<model>.jsonl`.
3. The means equal the ones in `evals/<model>.json` to 4 decimals.

Then prints the results table, the last-pass table (prompt v1 against v2) and checks the two
calibration re-runs the same way.

Usage: python3 scripts/verify.py   (run from the repository root; needs bun)
"""

import hashlib
import json
import pathlib
import subprocess
import sys

MODELS = [
    "gemini-3.8-flash",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "qwen3.5-4b-8bit_untrained",
    "nuextract3-4b",
]
LAST_PASS = [
    f"{m}__extract-text-{v}"
    for m in ("gpt-6.1-sol", "gemini-3.8-flash", "gpt-6-luna")
    for v in ("v1", "v2")
]
CALIBRATION = ["gpt-5.6-luna__api-rerun", "gpt-5.6-luna__codex"]
SCORES = ["score_strict", "score_loose", "score_counted_strict", "score_counted_loose"]
MEANS = {
    "mean_score_strict": "mean_score_case_sensitive",
    "mean_score_loose": "mean_score_case_insensitive",
    "mean_score_counted_strict": "mean_score_counted_case_sensitive",
    "mean_score_counted_loose": "mean_score_counted_case_insensitive",
}

split = json.loads(pathlib.Path("evals/eval_split_v1.json").read_text())
expected_hash = {str(d["id"]): d["answer_sha256"] for d in split["documents"]}
eval_ids = {str(i) for i in split["eval_ids"]}
failures = []


def jsonl(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


rows_out = []
last_pass_out = []
for m in MODELS + LAST_PASS + CALIBRATION:
    preds = jsonl(f"evals/predictions/{m}.jsonl")
    ids = [str(p["id"]) for p in preds]
    if len(ids) != len(set(ids)) or set(ids) != eval_ids:
        failures.append(f"{m}: answers do not cover exactly the 300 test documents")
    bad = [i for p, i in zip(preds, ids) if hashlib.sha256(p["actual"].encode()).hexdigest() != expected_hash.get(i)]
    if bad:
        failures.append(f"{m}: {len(bad)} correct answers do not match the split's hashes")

    proc = subprocess.run(
        ["bun", "scorer/score.ts", f"evals/predictions/{m}.jsonl"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(proc.stderr)
    fresh = {str(r["id"]): r for r in map(json.loads, proc.stdout.splitlines())}
    totals = json.loads(proc.stderr.strip().splitlines()[-1])

    stored = {str(r["id"]): r for r in jsonl(f"evals/per_document/{m}.jsonl")}
    differ = [i for i in stored if any(stored[i][k] != fresh[i][k] for k in SCORES)]
    if differ or set(stored) != set(fresh):
        failures.append(f"{m}: {len(differ)} per-document scores differ from evals/per_document")

    report = json.loads(pathlib.Path(f"evals/{m}.json").read_text())
    for k, rk in MEANS.items():
        if round(totals[k], 4) != round(report["score"][rk], 4):
            failures.append(f"{m}: {k} {totals[k]} != {report['score'][rk]} in evals/{m}.json")

    if m in LAST_PASS:
        last_pass_out.append(
            (
                report["run"]["label"],
                totals["mean_score_loose"],
                totals["mean_score_counted_loose"],
                totals["predictions_that_were_not_valid_json"],
                report["work"]["seconds_per_document_median"],
            )
        )
    if m not in MODELS:
        continue
    rows_out.append(
        (
            report["run"]["label"],
            totals["mean_score_loose"],
            totals["mean_score_counted_loose"],
            totals["predictions_that_were_not_valid_json"],
            report["cost"]["eur_for_all_300_documents"],
            report["work"]["seconds_per_document_median"],
        )
    )

print("| Model | Official score | Counted score | Answers not valid JSON | € for 300 documents | Median seconds per document |")
print("|---|---|---|---|---|---|")
for label, off, cnt, bad_json, eur, sec in rows_out:
    print(f"| {label} | {off:.4f} | {cnt:.4f} | {bad_json} | {eur:.2f} | {sec:.2f} |")

print("\nLast pass, prompt v1 against v2 (no cost column: the runs mixed the paid API with sign-in routes, so no one price applies):\n")
print("| Model and prompt | Official score | Counted score | Answers not valid JSON | Median seconds per document |")
print("|---|---|---|---|---|")
for label, off, cnt, bad_json, sec in last_pass_out:
    print(f"| {label} | {off:.4f} | {cnt:.4f} | {bad_json} | {sec:.2f} |")

if failures:
    print("\nFAILED:\n" + "\n".join(failures), file=sys.stderr)
    sys.exit(1)
n = len(MODELS + LAST_PASS + CALIBRATION)
print(f"\nverify: all {n} runs re-scored; hashes, per-document scores and means match", file=sys.stderr)
