import type { Rule } from '../fieldrule';

interface Wisp {
  epoch: number;
  els: Element[];
}
type WithWisp = typeof globalThis & { __wisp?: Wisp };

export interface SnapshotElement {
  ref: string;
  tag: string;
  type: string;
  name: string;
  sensitive: boolean;
  value: string;
}

export interface Snapshot {
  epoch: number;
  url: string;
  title: string;
  elements: SnapshotElement[];
  text: string;
}

// Runs inside the page (chrome.scripting.executeScript serializes it), so
// it uses nothing from this module's scope.
export function pageSnapshot(epoch: number, rule: Rule): Snapshot {
  const sensitive = (f: Record<string, string>): boolean => {
    if (rule.types.includes(String(f.type || '').toLowerCase())) return true;
    if (new RegExp(rule.autocomplete, 'i').test(String(f.autocomplete || '')))
      return true;
    return new RegExp(rule.hint, 'i').test(
      [f.name, f.id, f.label, f.placeholder, f.ariaLabel].join(' '),
    );
  };
  const sel =
    'a[href],button,input,select,textarea,summary,[role=button],[role=link],' +
    "[role=checkbox],[role=tab],[role=menuitem],[contenteditable=''],[contenteditable='true']";
  const els: Element[] = [];
  const out: SnapshotElement[] = [];
  const nodes = document.querySelectorAll(sel);
  for (let i = 0; i < nodes.length && els.length < 150; i++) {
    const el = nodes[i] as HTMLElement & { value?: string; labels?: NodeListOf<HTMLLabelElement> };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || s.visibility === 'hidden' || s.display === 'none')
      continue;
    const first = el.labels && el.labels[0];
    const raw =
      el.getAttribute('aria-label') ||
      (first && first.innerText) ||
      el.getAttribute('placeholder') ||
      el.innerText ||
      el.value ||
      el.getAttribute('title') ||
      '';
    const lab = String(raw).replace(/\s+/g, ' ').trim().slice(0, 80);
    const editable = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable;
    const f = {
      type: el.getAttribute('type') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      name: el.getAttribute('name') || '',
      id: el.id || '',
      label: lab,
      placeholder: el.getAttribute('placeholder') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
    };
    const sens = editable && sensitive(f);
    els.push(el);
    out.push({
      ref: `${epoch}:${els.length - 1}`,
      tag: el.tagName.toLowerCase(),
      type: f.type,
      name: lab,
      sensitive: sens,
      value: editable && !sens && el.value ? String(el.value).slice(0, 80) : '',
    });
  }
  (globalThis as WithWisp).__wisp = { epoch, els };
  return {
    epoch,
    url: location.href,
    title: document.title,
    elements: out,
    text: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 3000),
  };
}
