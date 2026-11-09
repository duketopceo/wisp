import { PROTOCOL, parseFromHost } from './protocol';
import type { Command, FromHost, ToHost } from './protocol';

/** The part of chrome.runtime.Port the link uses. */
export interface Port {
  postMessage(message: unknown): void;
  disconnect(): void;
  onMessage: { addListener(cb: (message: unknown) => void): void };
  onDisconnect: { addListener(cb: () => void): void };
}

export type LinkState =
  | { kind: 'off' }
  | { kind: 'connecting' }
  | { kind: 'connected' }
  | { kind: 'unavailable'; code: string; message: string };

export interface Timers {
  set(fn: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

export interface LinkHandlers {
  onCommand(cmd: Command): void;
  onState(state: LinkState): void;
}

export const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

/** Why a connection attempt failed, from Chrome's lastError text. */
export function explain(lastError: string | undefined): { code: string; message: string } {
  const m = lastError ?? '';
  if (/not found/i.test(m)) {
    return { code: 'host_missing', message: 'The Wisp native host is not installed.' };
  }
  if (/forbidden/i.test(m)) {
    return { code: 'host_forbidden', message: 'The native host does not list this extension.' };
  }
  return { code: 'host_exited', message: 'The Wisp native host stopped.' };
}

/**
 * One native messaging connection to wispd. It connects only when told to
 * (the user's consent), says hello, and reconnects a few times with
 * back-off when the link drops. After the last attempt it stops and says
 * why, so a Wisp that is not running costs nothing.
 */
export class NativeLink {
  private port: Port | null = null;
  private state: LinkState = { kind: 'off' };
  private attempts = 0;
  private timer: unknown = null;
  private wanted = false;
  private failure: { code: string; message: string } | null = null;

  constructor(
    private connect: () => Port,
    private handlers: LinkHandlers,
    private timers: Timers,
    private lastError: () => string | undefined,
    private version: string,
  ) {}

  get current(): LinkState {
    return this.state;
  }

  /** The user has agreed: connect, and keep reconnecting a few times. */
  start(): void {
    this.wanted = true;
    this.attempts = 0;
    this.failure = null;
    this.open();
  }

  /** The user withdrew consent, or pressed Disconnect. */
  stop(): void {
    this.wanted = false;
    this.cancelTimer();
    const p = this.port;
    this.port = null;
    if (p) {
      try {
        p.postMessage({ t: 'bye' } satisfies ToHost);
        p.disconnect();
      } catch {
        // the port was already gone
      }
    }
    this.set({ kind: 'off' });
  }

  send(msg: ToHost): boolean {
    if (!this.port || this.state.kind !== 'connected') return false;
    try {
      this.port.postMessage(msg);
      return true;
    } catch {
      return false;
    }
  }

  private set(s: LinkState): void {
    this.state = s;
    this.handlers.onState(s);
  }

  private cancelTimer(): void {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }

  private open(): void {
    if (!this.wanted || this.port) return;
    this.set({ kind: 'connecting' });
    let port: Port;
    try {
      port = this.connect();
    } catch (e) {
      this.failure = explain(e instanceof Error ? e.message : String(e));
      this.afterDrop();
      return;
    }
    this.port = port;
    port.onMessage.addListener((raw) => this.onMessage(port, raw));
    port.onDisconnect.addListener(() => this.onDisconnect(port));
    port.postMessage({ t: 'hello', v: PROTOCOL, ext: this.version } satisfies ToHost);
  }

  private onMessage(port: Port, raw: unknown): void {
    if (port !== this.port) return;
    const msg: FromHost | null = parseFromHost(raw);
    if (!msg) return;
    if (msg.t === 'hello_ok') {
      this.attempts = 0;
      this.failure = null;
      this.set({ kind: 'connected' });
    } else if (msg.t === 'error') {
      this.failure = { code: msg.code, message: msg.message };
    } else if (msg.t === 'cmd') {
      this.handlers.onCommand(msg.cmd);
    }
  }

  private onDisconnect(port: Port): void {
    if (port !== this.port) return;
    this.port = null;
    if (!this.failure) this.failure = explain(this.lastError());
    this.afterDrop();
  }

  private afterDrop(): void {
    if (!this.wanted) return;
    const delay = BACKOFF_MS[this.attempts];
    if (delay === undefined) {
      const f = this.failure ?? explain(undefined);
      this.set({ kind: 'unavailable', code: f.code, message: f.message });
      return;
    }
    this.attempts += 1;
    this.set({ kind: 'connecting' });
    this.cancelTimer();
    this.timer = this.timers.set(() => {
      this.timer = null;
      this.open();
    }, delay);
  }
}
