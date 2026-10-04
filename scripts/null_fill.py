"""Null-fill by code: how much of prompt v2's gain can a few lines of code get from v1's answers?

Prompt v2 adds one sentence: "Include every field the schema defines; when the document gives no
value for a field, write null." This applies the same rule to the stored v1 answers after the fact,
reading only the document's JSON schema (`evals/schemas.jsonl`) and the model's own answer, never
the correct answer:

- missing: every field the schema defines that the answer leaves out is added as null, at every
  depth (inside objects that are present, and inside each list item). A field the schema does not
  define is left alone, and so is an answer that is not valid JSON.
- missing + "": as above, and a field written as "" also becomes null. A 0 is left as it is: it
  can be a real value, and telling the two apart needs the document.

The v2 runs are filled too: whatever the fill still adds there is what v2 left out despite the
sentence. Each variant is re-scored with `scorer/score.ts`, then paired bootstraps (same draws and seed as
scripts/bootstrap.py) say whether the fill moves the score, and whether prompt v2 still beats it.

Usage: python3 scripts/null_fill.py   (run from the repository root; needs bun)
"""

import hashlib
import json
import pathlib
import random
import subprocess
import sys

RUNS = [
    "gpt-6.1-sol__extract-text-v1",
    "gpt-6.1-sol__extract-text-v2",
    "gemini-3.8-flash__extract-text-v1",
    "gemini-3.8-flash__extract-text-v2",
    "gpt-6-luna__extract-text-v1",
    "gpt-6-luna__extract-text-v2",
    "gemini-3.8-flash",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "qwen3.5-4b-8bit_untrained",
    "nuextract3-4b",
]
DRAWS, SEED = 10_000, 20261004


def jsonl(path):
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


split = json.loads(pathlib.Path("evals/eval_split_v1.json").read_text())
schema_hash = {str(d["id"]): d["schema_sha256"] for d in split["documents"]}
schemas = {}
for r in jsonl("evals/schemas.jsonl"):
    if hashlib.sha256(r["json_schema"].encode()).hexdigest() != schema_hash[r["id"]]:
        sys.exit(f"evals/schemas.jsonl: schema of document {r['id']} does not match the split's hash")
    schemas[r["id"]] = json.loads(r["json_schema"])
if set(schemas) != {str(i) for i in split["eval_ids"]}:
    sys.exit("evals/schemas.jsonl does not cover exactly the 300 test documents")


def fill(value, schema, blank_strings, counts):
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        for key, sub in schema["properties"].items():
            if key not in value:
                value[key] = None
                counts["missing"] += 1
            else:
                value[key] = fill(value[key], sub, blank_strings, counts)
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        value = [fill(v, schema["items"], blank_strings, counts) for v in value]
    elif blank_strings and value == "":
        counts["blank"] += 1
        return None
    return value


def score(rows):
    feed = "\n".join(json.dumps({"id": r["id"], "actual": r["actual"], "predicted": r["predicted"]}) for r in rows)
    p = subprocess.run(["bun", "scorer/score.ts", "-"], input=feed, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return {str(r["id"]): r for r in map(json.loads, p.stdout.splitlines())}


def variant(rows, blank_strings):
    counts = {"missing": 0, "blank": 0}
    out = []
    for r in rows:
        try:
            answer = json.loads(r["predicted"])
        except (json.JSONDecodeError, TypeError):
            out.append(r)
            continue
        filled = fill(answer, schemas[str(r["id"])], blank_strings, counts)
        out.append({**r, "predicted": json.dumps(filled)})
    return score(out), counts


rng = random.Random(SEED)


def gap(a, b, key):
    ids = sorted(a)
    diffs = [a[i][key] - b[i][key] for i in ids]
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(DRAWS))
    lo, hi = means[int(0.025 * DRAWS)], means[int(0.975 * DRAWS) - 1]
    return f"{sum(diffs) / n:+.4f} [{lo:+.4f}, {hi:+.4f}]"


def mean(s, key):
    return sum(r[key] for r in s.values()) / len(s)


results = {}
print("| Run | Official: as answered | missing -> null | missing + \"\" -> null | Counted: as answered | missing -> null | missing + \"\" -> null | Fields filled | \"\" nulled |")
print("|---|---|---|---|---|---|---|---|---|")
for m in RUNS:
    rows = jsonl(f"evals/predictions/{m}.jsonl")
    base = score(rows)
    stored = {str(r["id"]): r for r in jsonl(f"evals/per_document/{m}.jsonl")}
    if any(base[i]["score_loose"] != stored[i]["score_loose"] for i in stored):
        sys.exit(f"{m}: re-scored answers differ from evals/per_document")
    missing, _ = variant(rows, blank_strings=False)
    both, counts = variant(rows, blank_strings=True)
    results[m] = (base, missing, both)
    o = [mean(s, "score_loose") for s in (base, missing, both)]
    c = [mean(s, "score_counted_loose") for s in (base, missing, both)]
    print(f"| {m} | {o[0]:.4f} | {o[1]:.4f} | {o[2]:.4f} | {c[0]:.4f} | {c[1]:.4f} | {c[2]:.4f} | {counts['missing']} | {counts['blank']} |")

print("\nPaired bootstrap, official score, 95% interval:")
for m in RUNS:
    base, missing, both = results[m]
    print(f"  {m}: missing -> null minus as answered {gap(missing, base, 'score_loose')};"
          f" + \"\" -> null minus missing -> null {gap(both, missing, 'score_loose')}")
print("\nPrompt v2 against the best code fill of v1 (missing + \"\" -> null), official score:")
for m in RUNS:
    if not m.endswith("__extract-text-v1"):
        continue
    v2 = {str(r["id"]): r for r in jsonl(f"evals/per_document/{m.replace('-v1', '-v2')}.jsonl")}
    _, _, both = results[m]
    print(f"  {m.split('__')[0]}: v2 {mean(v2, 'score_loose'):.4f}, filled v1 {mean(both, 'score_loose'):.4f},"
          f" v2 minus filled v1 {gap(v2, both, 'score_loose')}")
