import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isSensitiveField } from '../src/fieldrule';
import type { Field } from '../src/fieldrule';

// the same file tests/test_browser_lane.py reads: one authority, two ports
const fixture = JSON.parse(
  readFileSync(new URL('../../tests/fixtures/sensitive_fields.json', import.meta.url), 'utf8'),
) as { cases: { field: Field; sensitive: boolean }[] };

describe('the sensitive-field rule', () => {
  it('has a meaningful fixture', () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(15);
    expect(fixture.cases.some((c) => c.sensitive)).toBe(true);
    expect(fixture.cases.some((c) => !c.sensitive)).toBe(true);
  });

  for (const c of fixture.cases) {
    it(`${c.sensitive ? 'refuses' : 'allows'} ${JSON.stringify(c.field)}`, () => {
      expect(isSensitiveField(c.field)).toBe(c.sensitive);
    });
  }

  it('treats a field with no attributes as fillable', () => {
    expect(isSensitiveField({})).toBe(false);
    expect(isSensitiveField()).toBe(false);
  });
});
