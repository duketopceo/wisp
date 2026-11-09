import type { Step } from './protocol';

export const MAX_STEPS = 20;
export const WAIT_MAX_MS = 15000;
/** The match pattern for every site. */
export const ALL_SITES = '<all_urls>';
export const STEP_OPS = [
  'open',
  'snapshot',
  'click',
  'fill',
  'scroll',
  'wait_for',
  'screenshot',
  'keep',
  'done',
] as const;

/** Only plain web pages: never file:, chrome:, javascript:, data:, blob:. */
export function safeUrl(u: unknown): boolean {
  try {
    const p = new URL(String(u ?? ''));
    return p.protocol === 'http:' || p.protocol === 'https:';
  } catch {
    return false;
  }
}

/** The match pattern that covers one page's whole origin. */
export function originPattern(u: string): string {
  const p = new URL(u);
  return `${p.protocol}//${p.host}/*`;
}

export function hostOf(u: string): string {
  try {
    return new URL(u).host;
  } catch {
    return '';
  }
}

/** Why the batch cannot run, or '' when it can. */
export function checkSteps(steps: unknown): string {
  if (!Array.isArray(steps) || steps.length === 0) return 'no steps';
  if (steps.length > MAX_STEPS) {
    return `too many steps (${steps.length}, most is ${MAX_STEPS})`;
  }
  return '';
}

export function isStepOp(op: string): op is (typeof STEP_OPS)[number] {
  return (STEP_OPS as readonly string[]).includes(op);
}

export function stepsOf(v: Step[] | undefined): Step[] {
  return v ?? [];
}
