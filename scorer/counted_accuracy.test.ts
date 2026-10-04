import { describe, it, expect } from 'bun:test';
import { calculateCountedAccuracy } from './counted_accuracy';
import { calculateJsonAccuracy } from './official_json_accuracy';

const doc = { a: 'x', b: 'y', items: [{ d: 1, e: 'p' }, { d: 2, e: 'q' }], tags: ['t1', 't2'] };

describe('calculateCountedAccuracy', () => {
  it('scores an identical answer 1', () => {
    expect(calculateCountedAccuracy(doc, structuredClone(doc)).score).toBe(1);
  });

  it('scores an empty answer 0, where the official score gives credit', () => {
    expect(calculateJsonAccuracy(doc, {}).score).toBeGreaterThan(0);
    expect(calculateCountedAccuracy(doc, {}).score).toBe(0);
  });

  it('counts every field of a missing list of objects and of primitives', () => {
    const r = calculateCountedAccuracy(doc, { a: 'x', b: 'y' });
    expect(r.officialScore).toBe(1);
    expect(r.wholeListDeletions).toBe(6);
    expect(r.score).toBe(0.25);
  });

  it('counts an invented list', () => {
    const r = calculateCountedAccuracy(doc, { ...structuredClone(doc), junk: [{ z: 1 }, { z: 2 }] });
    expect(r.officialScore).toBe(1);
    expect(r.wholeListAdditions).toBe(2);
    expect(r.score).toBe(0.75);
  });

  it('counts a list missing inside a modified list element', () => {
    const actual = { rows: [{ id: 1, sub: [{ v: 1 }, { v: 2 }] }] };
    const r = calculateCountedAccuracy(actual, { rows: [{ id: 1 }] });
    expect(r.wholeListDeletions).toBe(2);
    expect(r.score).toBe(Number((1 - 2 / 3).toFixed(4)));
  });

  it('counts a list missing inside a nested object', () => {
    const actual = { head: { name: 'n', lines: [{ v: 1 }] } };
    const r = calculateCountedAccuracy(actual, { head: { name: 'n' } });
    expect(r.wholeListDeletions).toBe(1);
    expect(r.score).toBe(0.5);
  });

  it('matches the official score when no whole list differs', () => {
    const pred = { ...structuredClone(doc), a: 'wrong', items: [{ d: 1, e: 'p' }, { d: 3, e: 'q' }] };
    const r = calculateCountedAccuracy(doc, pred);
    expect(r.wholeListAdditions + r.wholeListDeletions).toBe(0);
    expect(r.score).toBe(calculateJsonAccuracy(doc, pred).score);
  });

  it('does not double count a list inside a deleted object', () => {
    const actual = { head: { name: 'n', lines: [{ v: 1 }] }, a: 'x' };
    const r = calculateCountedAccuracy(actual, { a: 'x' });
    expect(r.wholeListDeletions).toBe(0);
    expect(r.score).toBe(Number((1 - 2 / 3).toFixed(4)));
  });
});
