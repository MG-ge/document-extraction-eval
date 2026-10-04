# Document extraction: eight models, a scorer that rewards leaving things out, and one sentence worth five points

[![reproduce](https://github.com/MG-ge/document-extraction-eval/actions/workflows/reproduce.yml/badge.svg)](https://github.com/MG-ge/document-extraction-eval/actions/workflows/reproduce.yml)

**Every model here was given each document's correct text, not the document image.** So this
measures one thing: how well a model turns a document's text into the structured fields a
schema asks for. Reading a scan or a photo is a separate step, and it is not tested here.

Four questions:

1. How accurate and how expensive are current models at pulling fields out of business
   documents such as invoices, bank statements, leases and tax forms?
2. Can the published benchmark's score be trusted? Partly. Its scorer ignores whole lists that
   are missing or invented, so an empty answer scores 0.627 and an answer with every line item
   removed scores a perfect 1.000.
3. Where do the models lose their points? For the large models, mostly not on reading: about 80%
   of their lost score is how an empty field is written, and apart from one Gemini answer that
   is not valid JSON, each gets only about 40 of the 22,176 fields really wrong.
4. Does saying how to write an empty field fix that? Mostly. One added sentence in the prompt
   lifts `gpt-6.1-sol` from 0.941 to 0.991 and Gemini 3.8 Flash from 0.944 to 0.989. Filling the
   gaps by code, from the schema alone, works as well, and better for `gpt-6-luna`, which ignored
   the sentence on 2,156 fields.

Everything below can be re-checked from this repository in a few minutes, with no API keys.

## Setup

- **Data:** the [OmniAI OCR benchmark](https://huggingface.co/datasets/getomni-ai/ocr-benchmark)
  (MIT licence, version of 21 Feb 2025). Each document comes with its correct text, a JSON
  schema and the correct JSON answer.
- **Test set:** 300 of its 1,000 documents, frozen before any model was run: stratified by
  document type, seeded shuffle, 31 document types, 22,176 fields to fill. The test and
  training IDs, and a SHA-256 hash of each test document's image, text, schema and answer, are in
  [`evals/eval_split_v1.json`](evals/eval_split_v1.json) (fingerprint `2ed8fd9b1e0348df`).
- **Runs:** one run per model on 18 Sep 2026, up to 16,384 output tokens. Gemini ran at
  temperature 0; the OpenAI requests set no temperature. Neither set a reasoning level, so each
  ran at its API's default, medium; the last pass (below) sets medium explicitly. The two laptop
  models ran greedy (temperature 0) with thinking off. Every model except NuExtract got the same
  prompt:

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

## Where the points go

Every error the counted score charges was sorted into a type by rule
([`scripts/error_analysis.ts`](scripts/error_analysis.ts), walking the scorer's own diff, so the
types add up exactly to each document's score). Points lost out of 100:

| Model | Points lost | An empty field written differently | A real value missing, extra or different | Answer not valid JSON | Same value, written differently |
|---|---|---|---|---|---|
| Gemini 3.8 Flash | 6.20 | 4.78 | 1.04 | 0.33 | 0.04 |
| `gpt-5.6-terra` | 6.53 | 5.31 | 1.20 | 0 | 0.02 |
| `gpt-5.6-luna` | 6.62 | 5.20 | 1.35 | 0 | 0.07 |
| Qwen 3.5 4B, untrained | 26.49 | 4.78 | 13.37 | 8.33 | 0 |
| NuExtract3 4B | 23.05 | 2.91 | 20.10 | 0 | 0.05 |

Each type, with field and document counts, is in [`evals/error_analysis.json`](evals/error_analysis.json).

**About 80% of the large models' lost score is how an empty field is written.** The correct
answers write a field the document leaves blank as `null`. The large models mostly leave such a
field out (2,619 to 2,713 fields each) or write `0`, `""` or `{}` instead (365 to 447). Every
field they left out is optional in its schema, and the prompt never said how to write an empty
field, so these answers are valid; the score counts them wrong only because the key is missing.
Asking for every schema field, with `null` when the document has no value, should recover most
of these points. The last pass below tests that.

**The rest was read by hand.** Every real-value error of the three large models, 50 documents
and 97 document-model pairs, was checked against the document's text. Each judgement is a rule
in [`scripts/error_reading.py`](scripts/error_reading.py), which checks that every error is
covered by exactly one. Fields, of 22,176:

| Whose error | Gemini 3.8 Flash | `gpt-5.6-terra` | `gpt-5.6-luna` |
|---|---|---|---|
| The model's: the document clearly supports the correct answer | 301 (263 from one answer that is not valid JSON) | 41 | 39 |
| The correct answer's: the document contradicts it | 12 | 12 | 12 |
| Neither: the document supports both | 58 | 72 | 80 |

- **Model mistakes are few and specific.** Apart from Gemini's one broken answer, each large model
  gets about 40 of 22,176 fields wrong (38, 41 and 39). They are concentrated in a few documents: a
  chart's ten business units left out of its revenue list, keeping only the three segments above
  them (Gemini and `gpt-5.6-terra`, 20 fields each); the wrong
  row of a shipping table taken as the most recent shipment (`gpt-5.6-luna`, 19 fields); a row
  label the schema has no field for, added anyway (11 each). The rest are one to four fields each:
  a care-of company named as the transfer agent, a cheque's routing and check numbers swapped, a
  tick box misread, an ID with its last character dropped.
- **Some correct answers are wrong.** One schema asks for `migration_option` while its correct
  answer uses `migration_options`; all three models follow the schema and lose 10 fields. One
  receipt reads `INDUNA` and its correct answer says `INDINIA`.
- **Many "errors" are a reading the document allows.** A glossary that repeats a letter heading
  after a page break is merged into one section in the correct answer and kept as two by the
  models (43 to 49 fields). A heading "Pay-In Sheet - 2025-09" is copied whole where the correct
  answer drops the date. A city is given with its state where the schema has no state field.
- **Input formatting leaks into answers.** The input text is Markdown, which writes `*` as `\*`.
  `gpt-5.6-luna` copied the backslash into 48 fields, `gpt-5.6-terra` into 16, Gemini into none.

So the three large models are level on real mistakes as well as on score, and their score gaps
are smaller than the effect of the empty-field convention.

**The small models fail differently.** Their losses are mostly real values. Of Qwen's 25 answers
that are not valid JSON, 17 break only in their last one or two characters, with a closing bracket
missing, extra or out of order; with that fixed, each one parses. A sample of their other errors (eight per type and
model, not a full reading) shows long tables drifting out of line, with rows dropped and others
added, routing and check numbers swapped, and NuExtract scaling numbers (28,609 written as
28,609,000,000 and 0.08 as 8).

## The last pass: one sentence, or a few lines of code

Three current models were run on 4 and 5 Oct 2026 with the prompt above (v1) and with v2, which
adds one sentence to the system prompt:

> Include every field the schema defines; when the document gives no value for a field, write null.

Same 300 documents, same scorer, reasoning level medium throughout
(`evals/<model>__extract-text-v1.json` and `-v2.json`; intervals from `scripts/bootstrap.py`):

| Model | Official, v1 | Official, v2 | v2 minus v1, 95% interval | Counted, v1 | Counted, v2 |
|---|---|---|---|---|---|
| `gpt-6.1-sol` | 0.9407 | 0.9910 | +0.0503 [+0.0374, +0.0642] | 0.9374 | 0.9877 |
| Gemini 3.8 Flash | 0.9441 | 0.9886 | +0.0445 [+0.0310, +0.0584] | 0.9408 | 0.9853 |
| `gpt-6-luna` | 0.9364 | 0.9580 | +0.0217 [+0.0094, +0.0336] | 0.9330 | 0.9547 |

**One sentence is worth about five points**, as the error analysis predicted. With it,
`gpt-6.1-sol` gets 99.1% of the fields right on the official score.

**The same fix by code.** [`scripts/null_fill.py`](scripts/null_fill.py) takes each stored answer
and adds, as `null`, every field its schema defines that the answer leaves out; a second variant
also turns `""` into `null`. It reads only the schema ([`evals/schemas.jsonl`](evals/schemas.jsonl),
hash-checked against the split) and the model's answer, never the correct answer. Official score:

| Answers | As answered | Missing fields → `null` | And `""` → `null` |
|---|---|---|---|
| `gpt-6.1-sol`, v1 | 0.9407 | 0.9863 | 0.9886 |
| Gemini 3.8 Flash, v1 | 0.9441 | 0.9886 | 0.9907 |
| `gpt-6-luna`, v1 | 0.9364 | 0.9813 | 0.9834 |
| `gpt-6-luna`, v2 | 0.9580 | 0.9805 | 0.9805 |
| Gemini 3.8 Flash, 18 Sep | 0.9446 | 0.9852 | 0.9874 |
| `gpt-5.6-terra`, 18 Sep | 0.9380 | 0.9820 | 0.9854 |
| `gpt-5.6-luna`, 18 Sep | 0.9372 | 0.9788 | 0.9829 |

- **For Sol and Gemini, the code and the sentence do the same job.** v2 minus filled v1 is
  +0.0025 [−0.0015, +0.0070] for Sol and −0.0021 [−0.0072, +0.0028] for Gemini, and their v2
  answers leave out no schema field.
- **`gpt-6-luna` did not follow the sentence.** Its v2 answers still leave out 2,156 schema
  fields, and filled v1 beats v2 by 0.0254 [0.0135, 0.0384]. Where a model does not reliably
  follow a formatting instruction, the code is the dependable fix: it costs nothing and needs no
  new run.
- **The 18 Sep order holds.** Filled, the three API models score 0.987, 0.985 and 0.983.
- **The small models gain little.** Qwen moves from 0.818 to 0.825 (its 25 answers that are not
  valid JSON cannot be filled); NuExtract does not move, since its template already writes every
  field.

**How these runs were made.** They did not all go through the paid API, and each answer records
its route (`answers_by_route` in a run's JSON where a run mixes them):

- **OpenAI** ran through the `pi` command-line client with its tools, context files and system
  prompt switched off and ours in their place. Its `openai/` provider bills the API, so most
  OpenAI answers are API answers. Its `openai-codex/` provider uses a ChatGPT Plus plan, which
  takes no temperature and may add a fixed preamble of its own; 136 of Sol's 300 v1 answers and
  1 of Luna's came that way.
- **Gemini** ran through Google's Antigravity command-line client on a free sign-in, with a custom
  agent that drops the client's own prompt and tools. A tool call would have made that answer an
  error; none occurred.

Before a route was trusted, a stored model was re-run through it and compared with its 18 Sep API
run, document by document ([`scripts/calibrate.py`](scripts/calibrate.py), paired bootstrap of
re-run minus stored run):

| Re-run | Official gap, 95% interval | Counted gap, 95% interval | Documents scored the same |
|---|---|---|---|
| `gpt-5.6-luna`, API again | +0.0013 [−0.0061, +0.0103] | −0.0000 [−0.0099, +0.0097] | 276 of 300 |
| `gpt-5.6-luna`, ChatGPT Plus | +0.0027 [−0.0017, +0.0102] | +0.0027 [−0.0017, +0.0103] | 276 of 300 |
| Gemini 3.8 Flash, Antigravity | −0.0005 [−0.0066, +0.0051] | +0.0028 [−0.0046, +0.0109] | 264 of 300 |

Every interval contains zero, so the route makes no measurable difference here. Gemini's
Antigravity re-run is also its v1 run above. The API re-run measures the run-to-run noise: about
one document in twelve changes score between two identical runs.

There is no euro column for the last pass, since it mixed API billing with plan allowances, and
seconds per document are not comparable either: the command-line clients add start-up time.

## What next

- **Read the images.** Every score here starts from the document's correct text. The same 300
  documents read from their images would add the reading error a real pipeline has.
- **Enforce the schema instead of asking for it.** A structured-output mode with every field
  required could stop omissions like Luna's at the source; it has not been tested against the
  code fill.
- **A second reader** for the hand judgements in `scripts/error_reading.py`.

## Limits

- **Text input only.** These scores say nothing about reading images; a real pipeline adds
  that error on top.
- **One run per model.** A second API run of `gpt-5.6-luna` changed the score of 24 of the 300
  documents and the mean by +0.0013, well inside its interval (last pass, calibration table).
  Gaps under about one point are not a ranking.
- **A ninth model was not scored.** `gpt-6-astra` stopped at 236 of 300 documents when the API
  credit ran out, and its ChatGPT Plus allowance was too small to finish it.
- **The last pass is one prompt change on three models.** v2 was not run on the 18 Sep models or
  the laptop models; the code fill was.
- **Mostly tidy documents.** By the dataset's own labels, 97 of the 300 are clean digital files,
  95 good scans, 79 poor scans and 29 photographs. With text input this split does not affect
  the scores above.
- **NuExtract was run its maker's way, which may understate it.** It was prompted in its own
  template format, not the shared prompt above. Its schema converter rejected a non-standard
  `"type": "enum"` in 16 of the 300 schemas, so those were rewritten to the standard form with
  the same allowed values. The converter also drops field descriptions (247 of the 300 schemas
  have them). Passing them in through its instructions section raised its scores on a 60-document
  trial; that change was not run on all 300.
- **Prices change.** The euro figures use 18 Sep 2026 list prices; the last pass has none.
- **No model was trained here.** This is a measurement, not a fine-tuning result.
- **One person read the errors.** The hand judgements had no second reader. Each one is written
  out in `scripts/error_reading.py`, so any of them can be checked and disputed.

## Reproduce

Needs [Bun](https://bun.sh) 1.x and Python 3.9 or later. No API keys.

```bash
git clone https://github.com/MG-ge/document-extraction-eval
cd document-extraction-eval
./scripts/reproduce.sh
```

That installs the scorer's one dependency, runs its tests, re-scores every stored answer and
checks each one against the published files, then prints the results and last-pass tables, the
scorer audit, the bootstrap intervals, the route calibration, the null-fill re-scoring and the
error analysis, checking that every error has a type and every large-model real-value error a
hand judgement. GitHub runs the same script on every change and weekly (the badge above).

## Files

| Path | What it holds |
|---|---|
| `evals/eval_split_v1.json` | The frozen split: 300 test and 700 training IDs, hashes for the 300 |
| `evals/predictions/<run>.jsonl` | Every raw answer, with the correct answer, tokens and seconds; published only so the scores can be checked. `<run>` is the model for the 18 Sep runs, `<model>__extract-text-v1` or `-v2` for the last pass, `gpt-5.6-luna__api-rerun` and `__codex` for the calibration |
| `evals/per_document/<run>.jsonl` | Every document's scores |
| `evals/<run>.json` | Each run's summary, cost and breakdowns |
| `evals/schemas.jsonl` | The 300 test documents' JSON schemas, read only by the null-fill |
| `scorer/` | The official scorer (unchanged), the counted score, both test suites |
| `src/summarize_eval.py` | Turned raw answers into the per-document and summary files |
| `evals/error_analysis.json` | Every model's errors by type: points lost, fields, documents, by document kind and per document |
| `scripts/` | `verify.py`, `scorer_audit.ts`, `bootstrap.py`, `calibrate.py`, `null_fill.py`, `error_analysis.ts` and its tests, `error_reading.py`, `reproduce.sh` |

## Licence

MIT ([LICENSE](LICENSE)). `scorer/official_json_accuracy.ts` is byte-identical to `src/evaluation/json.ts`
in [getomni-ai/benchmark](https://github.com/getomni-ai/benchmark) at commit `cf84a584`, and its
tests are that repository's, with only the import path changed. Both are under the MIT licence in
[`scorer/OMNI_LICENSE`](scorer/OMNI_LICENSE). The correct answers in `evals/predictions/` and the
schemas in `evals/schemas.jsonl` come from the [getomni-ai/ocr-benchmark](https://huggingface.co/datasets/getomni-ai/ocr-benchmark)
dataset, also MIT.
