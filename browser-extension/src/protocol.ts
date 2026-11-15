// The messages between the extension and wispd (through the native
// messaging relay). Documented in wisp/tools/browser_nm.py; both ends
// validate every message and drop what does not fit.

export const PROTOCOL = 1;
export const HOST_NAME = 'com.wisp.browser';

/**
 * Why a `keep` step leaves a tab open. A kept tab is a real cost to the
 * user's window, so the reason has a closed set and the end-of-task
 * summary counts them by it: a retained tab is accounted for, not silently
 * kept. Optional on the wire so an older caller does not fail.
 */
export const KEEP_REASONS = ['comparison', 'reference', 'later', 'distraction'] as const;
export type KeepReason = (typeof KEEP_REASONS)[number];

export interface Step {
  do: string;
  /** Only meaningful on `do: 'keep'`; one of KEEP_REASONS. */
  why?: KeepReason;
  [key: string]: unknown;
}

export interface Command {
  id: string;
  op: 'batch' | 'end_task';
  task?: string;
  steps?: Step[];
  resume?: boolean;
}

export interface StepResult {
  ok: boolean;
  error?: string;
  [key: string]: unknown;
}

export interface BatchResult {
  ok: boolean;
  error?: string;
  results: StepResult[];
}

export type ToHost =
  | { t: 'hello'; v: number; ext: string }
  | ({ t: 'result'; id: string } & BatchResult)
  | { t: 'stop' }
  | { t: 'ping' }
  | { t: 'bye' };

export type FromHost =
  | { t: 'hello_ok'; v: number }
  | { t: 'cmd'; cmd: Command }
  | { t: 'pong' }
  | { t: 'error'; code: string; message: string };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function parseCommand(v: unknown): Command | null {
  if (!isRecord(v) || typeof v.id !== 'string' || v.id === '') return null;
  if (v.op === 'end_task') {
    return { id: v.id, op: 'end_task', task: String(v.task ?? '') };
  }
  if (v.op !== 'batch') return null;
  if (!Array.isArray(v.steps) || !v.steps.every(isRecord)) return null;
  const steps = v.steps.map((s) => ({ ...s, do: String(s.do ?? '') }));
  return {
    id: v.id,
    op: 'batch',
    task: String(v.task ?? 'task'),
    steps,
    resume: v.resume === true,
  };
}

/** A message from the host, or null when it is not one we understand. */
export function parseFromHost(raw: unknown): FromHost | null {
  if (!isRecord(raw)) return null;
  switch (raw.t) {
    case 'hello_ok':
      return typeof raw.v === 'number' ? { t: 'hello_ok', v: raw.v } : null;
    case 'pong':
      return { t: 'pong' };
    case 'error':
      return {
        t: 'error',
        code: String(raw.code ?? 'unknown'),
        message: String(raw.message ?? ''),
      };
    case 'cmd': {
      const cmd = parseCommand(raw.cmd);
      return cmd ? { t: 'cmd', cmd } : null;
    }
    default:
      return null;
  }
}
