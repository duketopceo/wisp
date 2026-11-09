import { defineConfig } from 'wxt';

// The public half of the development key. It pins the unpacked extension's
// id (cbbeeaamnkogifjkglfcklifijjnjpma) so the native host manifest can
// name it; wisp/tools/browser_nm.py checks the two agree. The private half
// was never stored.
const DEV_KEY =
  'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4hVJ0twQfywWQ9cPDAkvfFiuXmrgPOGZeV3FbiEvo2+4xjZPtLILU7Dd1qUnu/6KNf3vJ1bsKAnzn9b7YwSw7Rc6+lwWCLuQkDm+R2q3lveXpGMDzGDXbQTZRWfPoPesI+UDrv6T47nMsrJQ/8Jq3KhKs6OwOk7WgtHHDy0HbaJtj9x7QokRena6DLOjMBEH3AvkQD3D6rDaXe7LZnW7h444m+DaOaZ5StJZj730eMGZjB5nONkNYAR5VH6OGqpHTMtb05kAf+T5sdKB7t4dIwYNo7hzu1UW9k0BkxeZzxba9NSyWmg/ULZ0aXQldQLFVXSRSlITPrDMEBKtr7X8LQIDAQAB';

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  manifest: ({ mode }) => ({
    name: 'Wisp browser lane',
    description:
      'Lets Wisp work in a tab group beside yours, in plain sight, and stops the moment you press Stop. Off until you press Connect.',
    key: DEV_KEY,
    minimum_chrome_version: '116',
    incognito: 'not_allowed',
    permissions: [
      'tabs',
      'tabGroups',
      'scripting',
      'nativeMessaging',
      'storage',
      'sidePanel',
    ],
    optional_host_permissions: ['<all_urls>'],
    action: { default_title: 'Wisp browser lane' },
    commands: {
      stop: {
        suggested_key: { default: 'Alt+Shift+S' },
        description: 'Stop Wisp in this browser',
      },
    },
    // A browser cannot click Chrome's own permission prompt, so the e2e
    // builds (and only they) are given host access up front: `e2e` the
    // fixture server's origin, `e2e-all` every site (screenshots need it).
    ...(mode === 'e2e' ? { host_permissions: ['http://127.0.0.1/*'] } : {}),
    ...(mode === 'e2e-all' ? { host_permissions: ['<all_urls>'] } : {}),
  }),
});
