// Fields Wisp reads but never fills: passwords, one-time codes, cards.
// The same rule lives in wisp/cua_safety.py; tests/fixtures/
// sensitive_fields.json is the shared authority, and a test in each
// language reads it. The page functions get these patterns as arguments,
// because a function injected into a page cannot import anything.

export interface Field {
  type?: string;
  autocomplete?: string;
  name?: string;
  id?: string;
  label?: string;
  placeholder?: string;
  ariaLabel?: string;
}

export interface Rule {
  types: string[];
  autocomplete: string;
  hint: string;
}

export const RULE: Rule = {
  types: ['password'],
  autocomplete:
    '(?:^|\\s)(?:one-time-code|current-password|new-password|cc-[a-z-]+)(?:\\s|$)',
  hint:
    '(?:pass(?:word|code|phrase)|\\bpin\\b|one[\\s_-]?time|\\botp\\b|\\b2fa\\b|' +
    '\\bmfa\\b|verification[\\s_-]?code|security[\\s_-]?code|auth(?:entication)?' +
    '[\\s_-]?code|\\bcvv\\b|\\bcvc\\b|card[\\s_-]?(?:number|no)|credit[\\s_-]?card|' +
    '\\bcc[\\s_-]?num)',
};

const str = (v: unknown): string =>
  v === undefined || v === null ? '' : String(v);

export function isSensitiveField(f: Field = {}, rule: Rule = RULE): boolean {
  if (rule.types.includes(str(f.type).trim().toLowerCase())) return true;
  if (new RegExp(rule.autocomplete, 'i').test(str(f.autocomplete))) return true;
  const hint = [f.name, f.id, f.label, f.placeholder, f.ariaLabel]
    .map(str)
    .join(' ');
  return new RegExp(rule.hint, 'i').test(hint);
}
