/**
 * classify() must charge exactly what the counted, case-insensitive score charges, and label
 * each field with the right type. Run from the repository root: bun test ./scripts
 */
import { describe, it, expect } from 'bun:test';
import { classify, TYPES } from './error_analysis';
import { calculateJsonAccuracy, countChanges, countTotalFields } from '../scorer/official_json_accuracy';
import { countWholeLists } from '../scorer/counted_accuracy';

/** Changes behind the counted loose score: the official count plus the whole lists it skips. */
const scorerChanges = (actual: any, predicted: any) => {
  const d = calculateJsonAccuracy(actual, predicted, true).jsonDiff;
  if (!d || !Object.keys(d).length) return 0;
  const w = countWholeLists(d);
  return countChanges(d).total + w.additions + w.deletions;
};
const total = (c: Record<string, number>) => TYPES.reduce((s, t) => s + c[t], 0);
const types = (actual: any, predicted: any) =>
  Object.fromEntries(Object.entries(classify(0, actual, predicted, true).counts).filter(([, n]) => n));

const cases: [string, any, any][] = [
  ['one-sided list missing', { a: 'x', items: [{ d: 1, e: 'p' }, { d: 2, e: null }] }, { a: 'x' }],
  ['one-sided list invented', { a: 'x' }, { a: 'x', items: [{ d: 1 }, { d: 2, e: [3, 4] }] }],
  ['primitive list elements', { tags: ['t1', 't2', null] }, { tags: ['t2', 't3'] }],
  ['case-only change inside a primitive list', { tags: ['abc', 'def'] }, { tags: ['ABC', 'def'] }],
  ['null replaced by an object', { addr: null }, { addr: { street: 's', city: 'c' } }],
  ['object replaced by a primitive', { addr: { street: 's', city: 'c' } }, { addr: 'S, C' }],
  ['empty object, empty list, blank object for null', { a: null, b: null, c: null }, { a: {}, b: [], c: { ssn: '' } }],
  ['modified list rows', { rows: [{ x: 1, y: 'a' }, { x: 2, y: 'b' }] }, { rows: [{ x: 1, y: 'A' }, { x: 3, y: 'b' }, { x: 4 }] }],
  ['more changes than fields', { a: 'x' }, { a: 'y', b: 1, c: 2, d: [5, 6] }],
];

describe('classify', () => {
  for (const [name, actual, predicted] of cases) {
    it(`charges what the scorer charges: ${name}`, () => {
      expect(total(classify(0, actual, predicted, true).counts)).toBe(scorerChanges(actual, predicted));
    });
  }

  it('counts every field of an answer that is not JSON', () => {
    const actual = { a: 1, b: null, items: [{ c: 'x' }, 'y'] };
    expect(classify(0, actual, {}, false).counts.not_json).toBe(countTotalFields(actual));
    expect(scorerChanges(actual, {})).toBe(countTotalFields(actual));
  });

  it('labels {}, [] and all-blank objects for null as empty_as_zero_or_blank', () => {
    expect(types({ a: null, b: null, c: null }, { a: {}, b: [], c: { ssn: '' } })).toEqual({ empty_as_zero_or_blank: 3 });
  });

  it('labels a Markdown backslash copied into the value as markdown_escape', () => {
    expect(types({ m: 'APL*APPLE' }, { m: 'APL\\*APPLE' })).toEqual({ markdown_escape: 1 });
  });

  it('treats a written-out date and an ISO date as the same value', () => {
    expect(types({ d: '2025-02-26', e: '2025-02-26' }, { d: 'February 26, 2025', e: '26 Feb 2025' })).toEqual({ format_only: 2 });
  });

  it('does not read a word that only starts like a month as a date', () => {
    expect(types({ d: '2025-03-12' }, { d: 'Market 12, 2025' })).toEqual({ wrong_value: 1 });
    expect(types({ d: '2020-06-05' }, { d: 'Junk 5 2020' })).toEqual({ wrong_value: 1 });
  });
});
