/**
 * Three answers no model would be proud of, scored against the correct answer of every
 * test document, by the official scorer and by the counted one.
 *
 *   empty      `{}` for every document
 *   no-lists   the correct answer with every list of items (a list holding objects, such as
 *              invoice lines) removed, at any depth; lists of plain values are kept
 *   invented   the correct answer plus one invented list of 50 two-field items
 *
 * Usage: bun scripts/scorer_audit.ts   (run from the repository root)
 */
import { readFileSync } from 'node:fs';
import { calculateJsonAccuracy } from '../scorer/official_json_accuracy';
import { calculateCountedAccuracy } from '../scorer/counted_accuracy';

// Every predictions file carries the same correct answers; any one will do.
const truths = readFileSync('evals/predictions/gpt-5.6-luna.jsonl', 'utf8')
  .split('\n')
  .filter((l) => l.trim())
  .map((l) => JSON.parse(JSON.parse(l).actual));

const isItemList = (x: any) => Array.isArray(x) && x.some((e) => e !== null && typeof e === 'object');

const withoutLists = (v: any): any => {
  if (Array.isArray(v)) return v.map(withoutLists);
  if (v === null || typeof v !== 'object') return v;
  const out: Record<string, any> = {};
  for (const [k, x] of Object.entries(v)) if (!isItemList(x)) out[k] = withoutLists(x);
  return out;
};

const answers: Record<string, (t: any) => any> = {
  empty: () => ({}),
  'no-lists': withoutLists,
  invented: (t) => ({
    ...t,
    invented_items: Array.from({ length: 50 }, (_, i) => ({ name: `item ${i + 1}`, amount: i + 1 })),
  }),
};

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

for (const [name, make] of Object.entries(answers)) {
  const official = truths.map((t) => calculateJsonAccuracy(t, make(t), true).score);
  const counted = truths.map((t) => calculateCountedAccuracy(t, make(t), true).score);
  console.log(
    JSON.stringify({
      answer: name,
      documents: truths.length,
      official: Number(mean(official).toFixed(4)),
      counted: Number(mean(counted).toFixed(4)),
      official_at_least_0_5: official.filter((s) => s >= 0.5).length,
      official_at_least_0_9: official.filter((s) => s >= 0.9).length,
    }),
  );
}
