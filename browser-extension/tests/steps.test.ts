import { describe, expect, it } from 'vitest';
import { MAX_STEPS, checkSteps, hostOf, isStepOp, originPattern, safeUrl } from '../src/steps';

describe('safeUrl', () => {
  it.each(['http://a.test/', 'https://a.test/x?y=1', 'HTTP://A.TEST'])('allows %s', (u) => {
    expect(safeUrl(u)).toBe(true);
  });

  it.each([
    'file:///etc/passwd',
    'chrome://settings',
    'chrome-extension://abc/x.html',
    'javascript:alert(1)',
    'data:text/html,hi',
    'blob:https://a.test/1',
    'ftp://a.test',
    'about:blank',
    '',
    'not a url',
    '//a.test',
    undefined,
    null,
    42,
  ])('refuses %j', (u) => {
    expect(safeUrl(u)).toBe(false);
  });
});

describe('originPattern and hostOf', () => {
  it('covers the origin and nothing above it', () => {
    expect(originPattern('https://a.test/deep/path?q=1#h')).toBe('https://a.test/*');
    expect(originPattern('http://127.0.0.1:8123/x')).toBe('http://127.0.0.1:8123/*');
  });

  it('does not widen http to https', () => {
    expect(originPattern('http://a.test/')).toBe('http://a.test/*');
  });

  it('names the host with its port, and is empty for junk', () => {
    expect(hostOf('http://a.test:81/x')).toBe('a.test:81');
    expect(hostOf('junk')).toBe('');
  });
});

describe('checkSteps', () => {
  it('accepts one step up to the cap', () => {
    expect(checkSteps([{ do: 'open' }])).toBe('');
    expect(checkSteps(Array.from({ length: MAX_STEPS }, () => ({ do: 'snapshot' })))).toBe('');
  });

  it('refuses none, too many and non-lists', () => {
    expect(checkSteps([])).toBe('no steps');
    expect(checkSteps(undefined)).toBe('no steps');
    expect(checkSteps('x')).toBe('no steps');
    expect(checkSteps(Array.from({ length: MAX_STEPS + 1 }, () => ({})))).toBe(
      `too many steps (${MAX_STEPS + 1}, most is ${MAX_STEPS})`,
    );
  });

  it('knows the step vocabulary and no other', () => {
    expect(isStepOp('click')).toBe(true);
    expect(isStepOp('eval')).toBe(false);
    expect(isStepOp('cookies')).toBe(false);
  });
});
