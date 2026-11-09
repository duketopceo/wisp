import type { Rule } from '../fieldrule';

interface Wisp {
  epoch: number;
  els: Element[];
}
type WithWisp = typeof globalThis & { __wisp?: Wisp };

export interface ActResult {
  ok: boolean;
  error?: string;
}

// Runs inside the page. Refuses a stale epoch and any password,
// one-time-code or card field, whatever the caller asked.
export function pageAct(
  epoch: number,
  index: number,
  action: 'click' | 'fill',
  value: string,
  rule: Rule,
): ActResult {
  const w = (globalThis as WithWisp).__wisp;
  if (!w || w.epoch !== epoch) return { ok: false, error: 'stale ref (snapshot again)' };
  const el = w.els[index] as
    | (HTMLElement & { value?: string; labels?: NodeListOf<HTMLLabelElement> })
    | undefined;
  if (!el || !el.isConnected) {
    return { ok: false, error: 'that element is gone (snapshot again)' };
  }
  el.scrollIntoView({ block: 'center' });
  if (action === 'click') {
    el.click();
    return { ok: true };
  }
  const f = {
    type: el.getAttribute('type') || '',
    autocomplete: el.getAttribute('autocomplete') || '',
    name: el.getAttribute('name') || '',
    id: el.id || '',
    label: (el.labels && el.labels[0] && el.labels[0].innerText) || '',
    placeholder: el.getAttribute('placeholder') || '',
    ariaLabel: el.getAttribute('aria-label') || '',
  };
  const bad =
    rule.types.includes(f.type.toLowerCase()) ||
    new RegExp(rule.autocomplete, 'i').test(f.autocomplete) ||
    new RegExp(rule.hint, 'i').test([f.name, f.id, f.label, f.placeholder, f.ariaLabel].join(' '));
  if (bad) {
    return {
      ok: false,
      error: 'refused: password, one-time code and card fields are never filled',
    };
  }
  el.focus();
  if (el.isContentEditable) {
    el.textContent = value;
  } else {
    const proto =
      el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype
        : el.tagName === 'SELECT'
          ? HTMLSelectElement.prototype
          : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true };
}
