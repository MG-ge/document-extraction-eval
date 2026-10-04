"""Turn one model's raw answers into the published score for that model.

The arithmetic is not done here. This hands every answer to `scorer/score.ts`,
which is the benchmark publisher's own scoring code copied in unchanged, and
then groups the numbers they return.

One average over 300 documents can hide a total failure on the hard tenth, so
the score is also reported split by how the document was captured (clean file,
good scan, poor scan, photograph), by how much JSON the answer needed, and by
kind of document.

Usage:
  python src/summarize_eval.py --predictions evals/predictions/<name>.jsonl \
      --out evals/<name>.json --label "..." [--usd-per-million-input 1.25 ...]
"""

import argparse
import json
import pathlib
import statistics
import subprocess
import sys
from collections import Counter, defaultdict

SPLIT = pathlib.Path("evals/eval_split_v1.json")


def mean(xs):
    return round(statistics.fmean(xs), 4) if xs else None


def group(rows, key):
    out = {}
    buckets = defaultdict(list)
    for r in rows:
        buckets[key(r)].append(r)
    for name in sorted(buckets):
        g = buckets[name]
        out[name] = {
            "documents": len(g),
            "mean_score_case_insensitive": mean([r["score_loose"] for r in g]),
            "mean_score_case_sensitive": mean([r["score_strict"] for r in g]),
            "mean_score_counted_case_insensitive": mean([r["score_counted_loose"] for r in g]),
            "answers_that_were_not_valid_json": sum(1 for r in g if not r["json_parsed"]),
        }
    return out


def field_bucket(r):
    n = r["total_fields"]
    if n <= 20:
        return "1: up to 20 fields"
    if n <= 60:
        return "2: 21 to 60 fields"
    if n <= 150:
        return "3: 61 to 150 fields"
    return "4: more than 150 fields"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True, help="how this model is named in the report")
    ap.add_argument("--run-kind", default="baseline, no training")
    ap.add_argument("--usd-per-million-input", type=float, default=0.0)
    ap.add_argument("--usd-per-million-output", type=float, default=0.0)
    ap.add_argument("--price-source", default="")
    ap.add_argument("--price-checked-on", default="")
    ap.add_argument("--eur-per-usd", type=float, default=0.0)
    ap.add_argument("--eur-rate-source", default="")
    ap.add_argument("--temperature", default=0, type=lambda v: None if v == "unset" else float(v),
                    help='"unset" for routes that send no temperature')
    ap.add_argument("--max-output-tokens", default=16384, type=lambda v: None if v == "unset" else int(v),
                    help='"unset" for routes that send no output cap')
    args = ap.parse_args()

    preds = [json.loads(l) for l in pathlib.Path(args.predictions).open() if l.strip()]
    by_id = {p["id"]: p for p in preds}
    split = json.loads(SPLIT.read_text())
    expected = split["eval_ids"]
    missing = [i for i in expected if i not in by_id]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(expected)} documents have no answer; run is incomplete")

    feed = "\n".join(
        json.dumps({"id": p["id"], "actual": p["actual"], "predicted": p["predicted"]})
        for p in preds
    )
    proc = subprocess.run(
        ["bun", "scorer/score.ts", "-"],
        input=feed,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("the scorer failed")
    scored = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    totals = json.loads(proc.stderr.strip().splitlines()[-1])

    rows = []
    for s in scored:
        p = by_id[s["id"]]
        rows.append({**s, **{k: p[k] for k in ("document_quality", "doc_format", "tokens_in", "tokens_out", "seconds")}, "failed_request": bool(p.get("error"))})

    per_doc = pathlib.Path("evals/per_document") / (pathlib.Path(args.out).stem + ".jsonl")
    per_doc.parent.mkdir(parents=True, exist_ok=True)
    per_doc.write_text("\n".join(json.dumps(r) for r in sorted(rows, key=lambda r: r["score_loose"])) + "\n")

    tin = sum(r["tokens_in"] for r in rows)
    tout = sum(r["tokens_out"] for r in rows)
    usd = tin / 1e6 * args.usd_per_million_input + tout / 1e6 * args.usd_per_million_output
    eur = usd * args.eur_per_usd if args.eur_per_usd else None

    routes = Counter(p["model"] for p in preds)
    report = {
        "run": {
            "label": args.label,
            "kind": args.run_kind,
            "model": preds[0]["model"],
            "served_by": preds[0]["backend"],
            "prompt_version": preds[0]["prompt_version"],
            **({"answers_by_route": dict(routes)} if len(routes) > 1 else {}),
            "input": "the document's correct text plus the JSON schema; no image is read",
            "temperature": args.temperature,
            "max_output_tokens": args.max_output_tokens,
            "documents": len(rows),
            "split_file": str(SPLIT),
            "split_fingerprint": split["manifest_sha256"][:16],
            "scored_by": "scorer/score.ts: the benchmark publisher's own code, unchanged, plus a counted score that also counts whole lists missing or invented (docs/SCORER_AUDIT.md)",
        },
        "score": {
            "mean_score_case_insensitive": totals["mean_score_loose"],
            "mean_score_case_sensitive": totals["mean_score_strict"],
            "mean_score_counted_case_insensitive": totals["mean_score_counted_loose"],
            "mean_score_counted_case_sensitive": totals["mean_score_counted_strict"],
            "note": "higher is better, 1.0 is every field right; the published leaderboard used the official case-insensitive number; the counted number also counts whole lists missing or invented and is the one our audit uses",
            "documents_scoring_zero_counted": sum(1 for r in rows if r["score_counted_loose"] == 0),
            "answers_that_were_not_valid_json": totals["predictions_that_were_not_valid_json"],
            "requests_that_failed_outright": sum(1 for r in rows if r["failed_request"]),
            "median_document_score_case_insensitive": round(statistics.median([r["score_loose"] for r in rows]), 4),
            "documents_scoring_zero": sum(1 for r in rows if r["score_loose"] == 0),
            "documents_scoring_one": sum(1 for r in rows if r["score_loose"] == 1),
        },
        "by_image_quality": group(rows, lambda r: r["document_quality"]),
        "by_answer_size": group(rows, field_bucket),
        "by_document_kind": group(rows, lambda r: r["doc_format"]),
        "work": {
            "tokens_in_total": tin,
            "tokens_out_total": tout,
            "seconds_per_document_median": round(statistics.median([r["seconds"] for r in rows]), 2),
            "seconds_total_if_run_one_at_a_time": round(sum(r["seconds"] for r in rows), 1),
        },
        "cost": {
            "usd_per_million_input_tokens": args.usd_per_million_input,
            "usd_per_million_output_tokens": args.usd_per_million_output,
            "price_source": args.price_source,
            "price_checked_on": args.price_checked_on,
            "eur_per_usd": args.eur_per_usd or None,
            "eur_rate_source": args.eur_rate_source,
            "usd_for_all_300_documents": round(usd, 4),
            "eur_for_all_300_documents": round(eur, 4) if eur is not None else None,
            "eur_per_document": round(eur / len(rows), 6) if eur is not None else None,
        },
        "per_document_scores": str(per_doc),
    }
    pathlib.Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps({
        "model": report["run"]["label"],
        "mean_case_insensitive": report["score"]["mean_score_case_insensitive"],
        "mean_counted_case_insensitive": report["score"]["mean_score_counted_case_insensitive"],
        "not_valid_json": report["score"]["answers_that_were_not_valid_json"],
        "eur_per_document": report["cost"]["eur_per_document"],
        "written": args.out,
    }))


if __name__ == "__main__":
    main()
