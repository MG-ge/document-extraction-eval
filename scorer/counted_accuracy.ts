/**
 * The official score with one flaw corrected: a whole list that is missing from the
 * prediction, or present only in the prediction, is counted field by field.
 *
 * The official countChanges sends every array in the diff to its array branch before it
 * checks for the `__deleted` / `__added` key suffix. json-diff reports a one-sided list as
 * `key__deleted: [...]` or `key__added: [...]`, whose items are not `[operation, element]`
 * pairs, so the official code counts nothing for them. An empty answer therefore averages
 * 0.627 on the frozen 300 and an answer with every list removed scores 1.0
 * (docs/SCORER_AUDIT.md).
 *
 * official_json_accuracy.ts stays unchanged so the official number still matches the
 * published leaderboard. This file adds the uncounted list fields on top of its result.
 */
import { calculateJsonAccuracy, countTotalFields } from './official_json_accuracy';

export interface WholeListChanges {
  additions: number;
  deletions: number;
}

/** Fields inside lists that exist on only one side, which the official count skips. */
export const countWholeLists = (diffResult: any): WholeListChanges => {
  const out: WholeListChanges = { additions: 0, deletions: 0 };

  const walk = (obj: any) => {
    if (!obj || typeof obj !== 'object') return;
    for (const key in obj) {
      const value = obj[key];
      if (Array.isArray(value)) {
        if (key.endsWith('__deleted')) {
          out.deletions += countTotalFields(value);
        } else if (key.endsWith('__added')) {
          out.additions += countTotalFields(value);
        } else {
          // Same shape the official code reads: modified elements are ['~', element].
          for (const item of value) {
            if (Array.isArray(item) && item.length === 2 && item[0] === '~') walk(item[1]);
          }
        }
      } else if (
        value !== null &&
        typeof value === 'object' &&
        !key.endsWith('__deleted') &&
        !key.endsWith('__added') &&
        !(value.__old !== undefined && value.__new !== undefined)
      ) {
        walk(value);
      }
    }
  };

  walk(diffResult);
  return out;
};

export interface CountedAccuracyResult {
  score: number;
  officialScore: number;
  totalFields: number;
  wholeListAdditions: number;
  wholeListDeletions: number;
}

export const calculateCountedAccuracy = (
  actual: Record<string, any>,
  predicted: Record<string, any>,
  ignoreCases: boolean = false,
): CountedAccuracyResult => {
  const official = calculateJsonAccuracy(actual, predicted, ignoreCases);
  const d = official.jsonDiff && Object.keys(official.jsonDiff).length ? official.jsonDiff : null;
  const extra = d ? countWholeLists(d) : { additions: 0, deletions: 0 };
  const errors = (official.jsonDiffStats?.total ?? 0) + extra.additions + extra.deletions;
  const score = official.totalFields
    ? Math.max(0, 1 - errors / official.totalFields)
    : official.score;
  return {
    score: Number(score.toFixed(4)),
    officialScore: official.score,
    totalFields: official.totalFields,
    wholeListAdditions: extra.additions,
    wholeListDeletions: extra.deletions,
  };
};
