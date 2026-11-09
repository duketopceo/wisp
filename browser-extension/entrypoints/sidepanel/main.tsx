import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '../../src/ui/App';
import type { Actions } from '../../src/ui/App';
import { UI_KEY, initialUi } from '../../src/state';
import type { UiState } from '../../src/state';
import './style.css';

function usePanelState(): UiState {
  const [ui, setUi] = React.useState<UiState>(initialUi());
  React.useEffect(() => {
    void chrome.storage.session.get(UI_KEY).then((r) => {
      const v = r[UI_KEY] as UiState | undefined;
      if (v) setUi(v);
    });
    const on = (changes: Record<string, chrome.storage.StorageChange>, area: string): void => {
      const change = changes[UI_KEY];
      if (area === 'session' && change) setUi(change.newValue as UiState);
    };
    chrome.storage.onChanged.addListener(on);
    return () => chrome.storage.onChanged.removeListener(on);
  }, []);
  return ui;
}

const send = (type: 'connect' | 'disconnect' | 'retry' | 'stop'): void => {
  void chrome.runtime.sendMessage({ type });
};

function Panel(): React.JSX.Element {
  const ui = usePanelState();
  const actions: Actions = {
    connect: () => send('connect'),
    retry: () => send('retry'),
    disconnect: () => send('disconnect'),
    stop: () => send('stop'),
    // permissions.request needs this click as its user gesture
    allowSite: () => {
      if (ui.pendingGrant) void chrome.permissions.request({ origins: [ui.pendingGrant.pattern] });
    },
    allowAll: () => void chrome.permissions.request({ origins: ['<all_urls>'] }),
  };
  return <App ui={ui} actions={actions} />;
}

createRoot(document.getElementById('root') as HTMLElement).render(<Panel />);
