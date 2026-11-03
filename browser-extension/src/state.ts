import type { LogEntry, SiteGrant } from './lane';
import type { LinkState } from './native';

export const UI_KEY = 'ui';
export const LANE_KEY = 'lane';
export const CONSENT_KEY = 'consent';
export const LOG_MAX = 100;

export interface LogRow extends LogEntry {
  n: number;
}

/** Everything the side panel draws. Kept in storage.session so the panel
 *  and the service worker agree after either one restarts. */
export interface UiState {
  link: LinkState;
  consent: boolean;
  running: boolean;
  stopped: boolean;
  pendingGrant: SiteGrant | null;
  log: LogRow[];
}

export const initialUi = (): UiState => ({
  link: { kind: 'off' },
  consent: false,
  running: false,
  stopped: false,
  pendingGrant: null,
  log: [],
});

export type PanelMessage =
  | { type: 'connect' }
  | { type: 'disconnect' }
  | { type: 'retry' }
  | { type: 'stop' };

export function isPanelMessage(v: unknown): v is PanelMessage {
  if (typeof v !== 'object' || v === null) return false;
  const t = (v as { type?: unknown }).type;
  return t === 'connect' || t === 'disconnect' || t === 'retry' || t === 'stop';
}
