/**
 * Sorts every error the counted, case-insensitive score charges into one failure type.
 *
 * Walks the same json-diff output that official_json_accuracy.ts and counted_accuracy.ts
 * count, and labels each counted field instead of only adding it up. A document's labels
 * therefore sum to exactly the changes behind its published score; the script checks that
 * for every document and exits non-zero if one does not match evals/per_document.
 *
 * Usage (from the repository root):
 *   bun scripts/error_analysis.ts                write evals/error_analysis.json and print the table
 *   bun scripts/error_analysis.ts --check        compare with the stored file instead of writing it
 *   bun scripts/error_analysis.ts --examples M   print every labelled error of model M as JSON lines
 */
import { readFileSync, writeFileSync } from 'node:fs';
// The scorer's own pinned copy (scorer/bun.lock), so this walks exactly the diff the scorer counts.
import { diff } from '../scorer/node_modules/json-diff';

const MODELS = [
  'gemini-3.8-flash',
  'gpt-5.6-terra',
  'gpt-5.6-luna',
  'qwen3.5-4b-8bit_untrained',
  'nuextract3-4b',
];

/** Failure types, in the order the README table lists them. */
export const TYPES = [
  'not_json', // the answer was not valid JSON, so every field counts as missing
  'empty_left_out', // the correct answer has the key with null; the model left the key out
  'value_left_out', // a field with a real value is missing from the answer
  'value_added', // a field with a real value that the correct answer does not have
  'empty_added', // a key with null that the correct answer does not have
  'empty_as_zero_or_blank', // the correct answer is null; the model wrote 0, "" or "N/A" instead
  'filled_empty', // the correct answer is null; the model gave a real value
  'emptied_value', // the correct answer has a value; the model gave null
  'format_only', // same value written differently: "12" vs 12, "$1,200.00" vs 1200, date order kept
  'markdown_escape', // the value copied with the input's Markdown escaping: "APL\*APPLE" for "APL*APPLE"
  'wrong_value', // a different value
  'wrong_shape', // an object or list where the answer has a single value, or the reverse
] as const;
type Type = (typeof TYPES)[number];
type Counts = Record<Type, number>;

const zero = (): Counts => Object.fromEntries(TYPES.map((t) => [t, 0])) as Counts;

/** The scorer's convertStringsToUppercase: object values only, so strings directly inside a list keep their case. */
const upper = (x: any): any => {
  if (x === null || typeof x !== 'object') return x;
  if (Array.isArray(x)) return x.map(upper);
  return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, typeof v === 'string' ? v.toUpperCase() : upper(v)]));
};

const BLANK = new Set(['', '0', 'N/A', 'NA', 'NONE', 'NULL', '-', '—']);
/** 0, "", "N/A" and the like, or an object or list holding nothing else (`{}`, `{"ssn": ""}`, `[]`). */
const isBlank = (v: any): boolean =>
  v === null ||
  (typeof v === 'number' && v === 0) ||
  (typeof v === 'string' && BLANK.has(v.trim().toUpperCase())) ||
  (typeof v === 'object' && Object.values(v).every(isBlank));

/** The input text is Markdown, which escapes * _ # [ ] and similar with a backslash. */
const unescape = (v: any) => String(v).replace(/\\([\\`*_{}\[\]()#+\-.!|<>~])/g, '$1');

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
/** A month name in full or abbreviated, and nothing longer: "MARKET" is not March. */
const MONTH = '(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)';
const MONTH_DAY_YEAR = new RegExp(`^${MONTH}\\.?\\s+(\\d{1,2}),?\\s+(\\d{4})$`);
const DAY_MONTH_YEAR = new RegExp(`^(\\d{1,2})\\s+${MONTH}\\.?,?\\s+(\\d{4})$`);

/** "February 26, 2025" and "26 Feb 2025" as "2025-02-26"; anything else unchanged. */
const isoDate = (s: string): string => {
  let m = s.match(MONTH_DAY_YEAR);
  let month = '', day = '', year = '';
  if (m) [, month, day, year] = m;
  else if ((m = s.match(DAY_MONTH_YEAR))) [, day, month, year] = m;
  else return s;
  return `${year}-${String(MONTHS.indexOf(month.slice(0, 3)) + 1).padStart(2, '0')}-${day.padStart(2, '0')}`;
};

/** Same value written differently: case, spacing, punctuation, currency signs, number as text, date. */
const normal = (v: any): string => {
  let s = isoDate(String(v).toUpperCase().trim()).replace(/[\s,$€£%]/g, '').replace(/[.:;]+$/, '');
  if (/^-?\d+(\.\d+)?$/.test(s)) s = String(Number(s));
  return s;
};

interface Example {
  id: number;
  type: Type;
  path: string;
  correct: unknown;
  answer: unknown;
  fields: number;
}

/** Calls fn once per field countTotalFields would count, with that field's value and path. */
const leaves = (obj: any, path: string, fn: (v: any, p: string) => void) => {
  if (!obj || typeof obj !== 'object') return;
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => {
      if (typeof item === 'object' && item !== null) leaves(item, `${path}[${i}]`, fn);
      else fn(item, `${path}[${i}]`);
    });
    return;
  }
  for (const key in obj) {
    if (key.includes('__')) continue;
    const v = obj[key];
    if (v === null || ['string', 'number', 'boolean'].includes(typeof v)) fn(v, `${path}.${key}`);
    else if (typeof v === 'object') leaves(v, `${path}.${key}`, fn);
  }
};

const fieldCount = (obj: any) => {
  let n = 0;
  leaves(obj, '', () => n++);
  return n;
};

export const classify = (id: number, actual: any, predicted: any, parsed: boolean) => {
  const counts = zero();
  const examples: Example[] = [];
  const add = (type: Type, n: number, path: string, correct: unknown, answer: unknown) => {
    if (n <= 0) return;
    counts[type] += n;
    examples.push({ id, type, path, correct, answer, fields: n });
  };
  const gone = (v: any, p: string) => add(v === null ? 'empty_left_out' : 'value_left_out', 1, p, v, undefined);
  const extra = (v: any, p: string) => add(v === null ? 'empty_added' : 'value_added', 1, p, undefined, v);

  if (!parsed) {
    add('not_json', fieldCount(actual), '', null, null);
    return { counts, examples };
  }

  const walk = (obj: any, path: string) => {
    if (!obj || typeof obj !== 'object') return;
    for (const key in obj) {
      const value = obj[key];
      const name = key.replace(/__(deleted|added)$/, '');
      const p = `${path}.${name}`;
      if (Array.isArray(value) && !key.endsWith('__deleted') && !key.endsWith('__added')) {
        value.forEach((item: any, i: number) => {
          if (!Array.isArray(item) || item.length !== 2) return;
          const [op, el] = item;
          const ip = `${p}[${i}]`;
          if (op === '~' && el !== null && typeof el === 'object') walk(el, ip);
          else if (op === '-') el !== null && typeof el === 'object' ? leaves(el, ip, gone) : gone(el, ip);
          else if (op === '+') el !== null && typeof el === 'object' ? leaves(el, ip, extra) : extra(el, ip);
        });
      } else if (key.endsWith('__deleted')) {
        value !== null && typeof value === 'object' ? leaves(value, p, gone) : gone(value, p);
      } else if (key.endsWith('__added')) {
        value !== null && typeof value === 'object' ? leaves(value, p, extra) : extra(value, p);
      } else if (value !== null && typeof value === 'object') {
        if (value.__old !== undefined && value.__new !== undefined) {
          const { __old: o, __new: n } = value;
          const oObj = o !== null && typeof o === 'object';
          const nObj = n !== null && typeof n === 'object';
          if (o === null && isBlank(n)) add('empty_as_zero_or_blank', fieldCount(n) || 1, p, o, n);
          else if (o === null && n !== null) add('filled_empty', fieldCount(n) || 1, p, o, n);
          else if (oObj || nObj) add('wrong_shape', fieldCount(o) || 1, p, o, n);
          else if (n === null) add('emptied_value', 1, p, o, n);
          else if (normal(o) === normal(n)) add('format_only', 1, p, o, n);
          else if (typeof n === 'string' && n !== unescape(n) && normal(o) === normal(unescape(n)))
            add('markdown_escape', 1, p, o, n);
          else add('wrong_value', 1, p, o, n);
        } else {
          walk(value, p);
        }
      }
    }
  };

  walk(diff(upper(actual), upper(predicted), { sort: true }), '');
  return { counts, examples };
};

const jsonl = (path: string) =>
  readFileSync(path, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));

const analyse = (model: string) => {
  const stored = new Map(jsonl(`evals/per_document/${model}.jsonl`).map((r) => [r.id, r]));
  const fields = zero();
  const points = zero();
  const docs = zero();
  const byKind: Record<string, Counts> = {};
  const perDocument: Record<string, Partial<Counts>> = {};
  const examples: Example[] = [];
  const mismatched: number[] = [];
  let n = 0;

  for (const rec of jsonl(`evals/predictions/${model}.jsonl`)) {
    n++;
    const actual = JSON.parse(rec.actual);
    let predicted: any = {};
    let parsed = true;
    try {
      predicted = JSON.parse(rec.predicted);
    } catch {
      parsed = false;
    }
    if (predicted === null || predicted === undefined) {
      parsed = false;
      predicted = {};
    }
    const { counts, examples: ex } = classify(rec.id, actual, predicted, parsed);
    examples.push(...ex);

    const total = fieldCount(upper(actual));
    const changes = TYPES.reduce((s, t) => s + counts[t], 0);
    const score = Number(Math.max(0, 1 - changes / total).toFixed(4));
    if (score !== stored.get(rec.id)?.score_counted_loose) mismatched.push(rec.id);

    // A document's lost share (1 - score) is split across its types in proportion to their
    // counts; this also holds when more fields are wrong than exist and the score stops at 0.
    const lost = 1 - Math.max(0, 1 - changes / total);
    const kind = rec.doc_format;
    byKind[kind] ??= zero();
    const doc: Partial<Counts> = {};
    for (const t of TYPES) {
      if (!counts[t]) continue;
      fields[t] += counts[t];
      points[t] += (lost * counts[t]) / changes;
      docs[t] += 1;
      byKind[kind][t] += counts[t];
      doc[t] = counts[t];
    }
    perDocument[rec.id] = doc;
  }

  const round = (c: Counts) => Object.fromEntries(TYPES.map((t) => [t, Number((c[t] / n).toFixed(4))]));
  return {
    summary: {
      documents: n,
      points_lost: round(points),
      fields,
      documents_affected: docs,
      by_document_kind: byKind,
      per_document: perDocument,
    },
    examples,
    mismatched,
  };
};

const report = (check: boolean) => {
  const out: Record<string, unknown> = {};
  const failures: string[] = [];
  for (const m of MODELS) {
    const { summary, mismatched } = analyse(m);
    if (mismatched.length)
      failures.push(`${m}: labels do not add up to the stored score on ${mismatched.length} documents (${mismatched.slice(0, 5).join(', ')})`);
    out[m] = summary;
  }

  const text = JSON.stringify(out, null, 1) + '\n';
  if (!check) writeFileSync('evals/error_analysis.json', text);
  else if (readFileSync('evals/error_analysis.json', 'utf8') !== text)
    failures.push('evals/error_analysis.json differs from a fresh run');

  const pts = (m: string, t: Type) => ((out[m] as any).points_lost[t] * 100).toFixed(2);
  const lines = [['Points lost per type', ...MODELS].join(' | ')];
  for (const t of TYPES) lines.push([t, ...MODELS.map((m) => pts(m, t))].join(' | '));
  process.stdout.write(lines.join('\n') + '\n');

  if (failures.length) {
    console.error(failures.join('\n'));
    process.exitCode = 1;
  }
};

// Output goes out in one write and the process ends on its own: process.exit() can cut off
// output still queued for a pipe.
const args = process.argv.slice(2);
if (!import.meta.main) {
  // imported by the tests: run nothing
} else if (args[0] === '--examples') {
  process.stdout.write(analyse(args[1]).examples.map((e) => JSON.stringify(e) + '\n').join(''));
} else {
  report(args[0] === '--check');
}
