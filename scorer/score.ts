/**
 * Scores predicted JSON against the correct JSON using the OmniAI benchmark's
 * own arithmetic, copied unchanged into official_json_accuracy.ts.
 *
 * Reads one JSON object per line from a file or standard input. Each line needs
 * an id, the correct answer, and the prediction:
 *
 *   {"id": 0, "actual": {...}, "predicted": {...}}
 *
 * The prediction may also be a raw string, in which case it is parsed here and
 * scores zero if it is not valid JSON. Writes one result object per line.
 *
 * Both scores are reported for every row: "strict" compares text exactly,
 * "loose" ignores upper and lower case. The published leaderboard this is
 * compared against used the case-insensitive one.
 *
 * Each also comes "counted": the same arithmetic with whole lists that are missing or
 * invented counted field by field (counted_accuracy.ts). The official number is kept for
 * comparison with the published leaderboard; the counted one is what our audit and any
 * training reward use.
 */
import { readFileSync } from 'node:fs';
import { calculateJsonAccuracy } from './official_json_accuracy';
import { calculateCountedAccuracy } from './counted_accuracy';

const path = process.argv[2];
const text = path && path !== '-' ? readFileSync(path, 'utf8') : readFileSync(0, 'utf8');

let rows = 0;
let sumStrict = 0;
let sumLoose = 0;
let sumCountedStrict = 0;
let sumCountedLoose = 0;
let unparseable = 0;
const out: string[] = [];

for (const line of text.split('\n')) {
  const t = line.trim();
  if (!t) continue;
  const rec = JSON.parse(t);
  const actual = typeof rec.actual === 'string' ? JSON.parse(rec.actual) : rec.actual;

  let predicted: unknown = rec.predicted;
  let parsed = true;
  if (typeof predicted === 'string') {
    try {
      predicted = JSON.parse(predicted);
    } catch {
      parsed = false;
      predicted = {};
    }
  }
  if (predicted === null || predicted === undefined) {
    parsed = false;
    predicted = {};
  }
  if (!parsed) unparseable++;

  const strict = calculateJsonAccuracy(actual as any, predicted as any, false);
  const loose = calculateJsonAccuracy(actual as any, predicted as any, true);
  const countedStrict = calculateCountedAccuracy(actual as any, predicted as any, false);
  const countedLoose = calculateCountedAccuracy(actual as any, predicted as any, true);

  rows++;
  sumStrict += strict.score;
  sumLoose += loose.score;
  sumCountedStrict += countedStrict.score;
  sumCountedLoose += countedLoose.score;

  out.push(
    JSON.stringify({
      id: rec.id,
      score_strict: strict.score,
      score_loose: loose.score,
      score_counted_strict: countedStrict.score,
      score_counted_loose: countedLoose.score,
      total_fields: strict.totalFields,
      additions: strict.jsonDiffStats?.additions ?? 0,
      deletions: strict.jsonDiffStats?.deletions ?? 0,
      modifications: strict.jsonDiffStats?.modifications ?? 0,
      whole_list_additions: countedStrict.wholeListAdditions,
      whole_list_deletions: countedStrict.wholeListDeletions,
      json_parsed: parsed,
    }),
  );
}

// One write: many console.log calls into a pipe can lose lines when the process exits (seen with
// bun 1.4.2 on macOS).
process.stdout.write(out.join('\n') + '\n');
console.error(
  JSON.stringify({
    rows,
    mean_score_strict: rows ? Number((sumStrict / rows).toFixed(4)) : 0,
    mean_score_loose: rows ? Number((sumLoose / rows).toFixed(4)) : 0,
    mean_score_counted_strict: rows ? Number((sumCountedStrict / rows).toFixed(4)) : 0,
    mean_score_counted_loose: rows ? Number((sumCountedLoose / rows).toFixed(4)) : 0,
    predictions_that_were_not_valid_json: unparseable,
  }),
);
