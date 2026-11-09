import React from 'react';
import { ALL_SITES } from '../steps';
import type { UiState } from '../state';
import { describe, truncate } from './model';
import type { ActionId } from './model';

export interface Actions {
  connect(): void;
  retry(): void;
  disconnect(): void;
  stop(): void;
  allowSite(): void;
  allowAll(): void;
}

const runAction = (id: ActionId, a: Actions): (() => void) => {
  switch (id) {
    case 'connect':
      return a.connect;
    case 'retry':
      return a.retry;
    case 'grant-site':
      return a.allowSite;
    case 'grant-all':
      return a.allowAll;
  }
};

export function App({ ui, actions }: { ui: UiState; actions: Actions }): React.JSX.Element {
  const head = describe(ui);
  const connected = ui.consent && ui.link.kind === 'connected';
  const urgent = head.tone === 'red';
  return (
    <main className="panel">
      <header className={`status status-${head.tone}`} aria-live="polite">
        <h1>{head.title}</h1>
        <p role={urgent ? 'alert' : undefined}>{head.why}</p>
        {head.command ? (
          <p>
            Run <code>{head.command}</code>
          </p>
        ) : null}
        <div className="actions">
          {head.action ? (
            <button type="button" className="primary" onClick={runAction(head.action.id, actions)}>
              {head.action.label}
            </button>
          ) : null}
          {ui.pendingGrant && ui.pendingGrant.pattern !== ALL_SITES ? (
            <button type="button" onClick={actions.allowAll}>
              Allow all sites
            </button>
          ) : null}
        </div>
      </header>

      <section aria-label="Stop">
        <button
          type="button"
          className="stop"
          disabled={!connected}
          onClick={actions.stop}
          title="Alt+Shift+S"
        >
          Stop Wisp
        </button>
      </section>

      <section aria-labelledby="log-title" className="log">
        <h2 id="log-title">Steps</h2>
        {ui.log.length === 0 ? (
          <div className="empty">
            <p>Wisp's steps appear here as it works.</p>
            <p>Nothing has run yet.</p>
            <p>Ask Wisp to do something in your browser.</p>
          </div>
        ) : (
          <ol reversed>
            {[...ui.log].reverse().map((r) => (
              <li key={r.n} className={r.ok ? 'ok' : 'bad'}>
                <span className="op">{r.op}</span>
                <span className="host">{r.host}</span>
                <span className="mark" aria-label={r.ok ? 'done' : 'failed'}>
                  {r.ok ? 'done' : 'failed'}
                </span>
                {r.error ? <p className="err">{truncate(r.error)}</p> : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {ui.consent ? (
        <footer>
          <button type="button" onClick={actions.disconnect}>
            Disconnect Wisp
          </button>
        </footer>
      ) : null}
    </main>
  );
}
