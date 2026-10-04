# Document extraction: five models, one benchmark, and a scorer that rewards leaving things out

[![reproduce](https://github.com/MG-ge/document-extraction-eval/actions/workflows/reproduce.yml/badge.svg)](https://github.com/MG-ge/document-extraction-eval/actions/workflows/reproduce.yml)

**Every model here was given each document's correct text, not the document image.** So this
measures one thing: how well a model turns a document's text into the structured fields a
schema asks for. Reading a scan or a photo is a separate step, and it is not tested here.

Two questions:

1. How accurate and how expensive are current models at pulling fields out of business
   documents such as invoices, bank statements, leases and tax forms?
2. Can the published benchmark's score be trusted? Partly. Its scorer ignores whole lists that
   are missing or invented, so an empty answer scores 0.627 and an answer with every line item
   removed scores a perfect 1.000.

Everything below can be re-checked from this repository in a few minutes, with no API keys.

## Setup

- **Data:** the [OmniAI OCR benchmark](https://huggingface.co/datasets/getomni-ai/ocr-benchmark)
  (MIT licence, version of 21 Feb 2025). Each document comes with its correct text, a JSON
  schema and the correct JSON answer.
- **Test set:** 300 of its 1,000 documents, frozen before any model was run: stratified by
  document type, seeded shuffle, 31 document types, 22,176 fields to fill. The test and
  training IDs, and a SHA-256 hash of each test document's image, text, schema and answer, are in
  [`evals/eval_split_v1.json`](evals/eval_split_v1.json) (fingerprint `2ed8fd9b1e0348df`).
- **Runs:** one run per model, temperature 0, thinking off, up to 16,384 output tokens, on
  18 Sep 2026. Every model except NuExtract got the same prompt:

  > **System:** You extract structured data from documents. You are given the text of one
  > document and a JSON schema. Reply with one JSON object that matches the schema and contains
  > what the document says. Reply with the JSON object and nothing else: no explanation, no
  > code fence.
  >
  > **User:** JSON schema: `{schema}` Document: `{text}` Return only the JSON object described
  > by the schema.

  A code fence or a thinking block around the answer was stripped; anything else that is not
  valid JSON scores as an empty answer.
- **Score:** the share of fields right, upper and lower case ignored; 1.0 is every field right.
  The **official** score is the benchmark's own code, copied in unchanged
  ([`scorer/official_json_accuracy.ts`](scorer/official_json_accuracy.ts)). The **counted**
  score is the same arithmetic with the flaw below fixed
  ([`scorer/counted_accuracy.ts`](scorer/counted_accuracy.ts)).

## Results

Source: `evals/<model>.json`, re-computed from the raw answers by `scripts/verify.py`.
Prices are each supplier's list price on 18 Sep 2026, converted at the ECB rate of
1.1481 dollars per euro. The two open models ran on an Apple M4 Pro laptop, at no per-token cost.

| Model | Official score | Counted score | Answers not valid JSON | € for all 300 documents | Median seconds per document |
|---|---|---|---|---|---|
| Gemini 3.8 Flash (Google) | 0.9446 | 0.9380 | 1 | 0.89 | 3.25 |
| `gpt-5.6-terra` (OpenAI, mid-priced) | 0.9380 | 0.9347 | 0 | 2.45 | 3.44 |
| `gpt-5.6-luna` (OpenAI, cheapest) | 0.9372 | 0.9338 | 0 | 0.27 | 3.24 |
| Qwen 3.5 4B, 8-bit, untrained | 0.8179 | 0.7351 | 25 | 0.00 | 9.86 |
| NuExtract3 4B, Q8, a specialised extraction model | 0.7728 | 0.7695 | 0 | 0.00 | 16.79 |

**The cheapest large model is level with the best, within measurement error, at 70% less
cost.** Paired bootstrap over the 300 documents (10,000 draws, `scripts/bootstrap.py`):

| Comparison | Official score gap, 95% interval | Counted score gap, 95% interval |
|---|---|---|
| Gemini 3.8 Flash minus `gpt-5.6-luna` | +0.0074 [−0.0007, +0.0175] | +0.0041 [−0.0058, +0.0148] |
| Gemini 3.8 Flash minus `gpt-5.6-terra` | +0.0066 [+0.0022, +0.0120] | +0.0033 [−0.0043, +0.0101] |
| `gpt-5.6-terra` minus `gpt-5.6-luna` | +0.0009 [−0.0060, +0.0096] | +0.0009 [−0.0061, +0.0098] |

Every interval contains zero except one: on the official score Gemini beats `gpt-5.6-terra`,
but that lead disappears once missing lists are counted. `gpt-5.6-luna` costs €0.27 for the
300 documents against Gemini's €0.89 and `gpt-5.6-terra`'s €2.45.

Long documents are where every model drops. Over 150 fields per answer, `gpt-5.6-terra` scores
0.80, the untrained Qwen 0.76 and NuExtract 0.65 (`by_answer_size` in each `evals/<model>.json`).

## The scorer finding

The official scorer does not count a list that exists on only one side. Scored against all 300
correct answers (`scripts/scorer_audit.ts`):

| Answer given for every document | Official score | Counted score |
|---|---|---|
| `{}`, an empty answer | 0.627 | 0 |
| The correct answer with every list of items removed | 1.000 | 0.333 |
| The correct answer plus 50 invented list items | 1.000 | 0.079 |

With the official scorer, the empty answer scores 0.5 or more on 199 of the 300 documents and
0.9 or more on 144.

**Cause.** The scorer compares answers with [json-diff](https://www.npmjs.com/package/json-diff),
which reports a list missing from the answer as `key__deleted: [...]` and an invented one as
`key__added: [...]`. In `countChanges`, every array goes to the array branch first. That branch
expects `[operation, element]` pairs; the items of a one-sided list are plain objects, so it
skips every one. The `__deleted` / `__added` handling further down never sees them.

**Fix.** One line:

```diff
-      if (Array.isArray(value)) {
+      if (Array.isArray(value) && !key.endsWith('__deleted') && !key.endsWith('__added')) {
```

The benchmark's own 20 tests still pass with it. This repository keeps the official file
unchanged and adds the missing count on top, in `scorer/counted_accuracy.ts`, so both numbers
can be reported. Applied to all five models' answers in both case modes (3,000 scorings), the
one-line fix and the counted score give identical results.

**Effect on real models.** The three large models move by under one point and keep their order.
The untrained Qwen drops from 0.818 to 0.735, more than eight points. It often fails to write
valid JSON, and an unparseable answer is scored as an empty one, so under the official scorer
each of its 25 broken answers still earned partial credit.

## Why it matters

A leaderboard built on this scorer overstates models that drop or garble whole lists. And used
as a training reward, the official scorer would teach a model to leave out line items:
removing every list earns a perfect score. Line items are the hardest part of most business
documents, so this rewards skipping exactly the work that matters.

## Limits

- **Text input only.** These scores say nothing about reading images; a real pipeline adds
  that error on top.
- **One run per model.** At temperature 0 the runs should vary little, but this was not measured.
- **A sixth model was not scored.** `gpt-6-astra` ran out of API credit at 194 of 300 documents.
- **Mostly tidy documents.** By the dataset's own labels, 97 of the 300 are clean digital files,
  95 good scans, 79 poor scans and 29 photographs. With text input this split does not affect
  the scores above.
- **NuExtract was run its maker's way, which may understate it.** It was prompted in its own
  template format, not the shared prompt above. Its schema converter rejected a non-standard
  `"type": "enum"` in 16 of the 300 schemas, so those were rewritten to the standard form with
  the same allowed values. The converter also drops field descriptions (247 of the 300 schemas
  have them). Passing them in through its instructions section raised its scores on a 60-document
  trial; that change was not run on all 300.
- **Prices change.** The euro figures use 18 Sep 2026 list prices.
- **No model was trained here.** This is a measurement, not a fine-tuning result.

## Reproduce

Needs [Bun](https://bun.sh) 1.x and Python 3.9 or later. No API keys.

```bash
git clone https://github.com/MG-ge/document-extraction-eval
cd document-extraction-eval
./scripts/reproduce.sh
```

That installs the scorer's one dependency, runs its tests, re-scores every stored answer and
checks each one against the published files, then prints the results table, the scorer audit
and the bootstrap intervals. GitHub runs the same script on every change and weekly (the badge above).

## Files

| Path | What it holds |
|---|---|
| `evals/eval_split_v1.json` | The frozen split: 300 test and 700 training IDs, hashes for the 300 |
| `evals/predictions/<model>.jsonl` | Every raw answer, with the correct answer, tokens and seconds; published only so the scores can be checked |
| `evals/per_document/<model>.jsonl` | Every document's scores |
| `evals/<model>.json` | Each model's summary, cost and breakdowns |
| `scorer/` | The official scorer (unchanged), the counted score, both test suites |
| `src/summarize_eval.py` | Turned raw answers into the per-document and summary files |
| `scripts/` | `verify.py`, `scorer_audit.ts`, `bootstrap.py`, `reproduce.sh` |

## Licence

MIT ([LICENSE](LICENSE)). `scorer/official_json_accuracy.ts` is byte-identical to `src/evaluation/json.ts`
in [getomni-ai/benchmark](https://github.com/getomni-ai/benchmark) at commit `cf84a584`, and its
tests are that repository's, with only the import path changed. Both are under the MIT licence in
[`scorer/OMNI_LICENSE`](scorer/OMNI_LICENSE). The correct answers in `evals/predictions/` come
from the [getomni-ai/ocr-benchmark](https://huggingface.co/datasets/getomni-ai/ocr-benchmark)
dataset, also MIT.
