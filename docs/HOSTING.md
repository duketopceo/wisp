# Wisp website hosting

The production website uses Cloudflare Workers Static Assets, not GitHub Pages
or Cloudflare Pages. The desktop application still runs on the owner's machine;
the website's Three.js examples are deterministic illustrations, not remote
desktop sessions.

## Source and build

- **Homepage:** `site-app/`, built with Vite (`site-app/build.mjs`). Section
  layouts and primitives are adapted from launch-ui (React, shadcn/ui,
  Tailwind); React renders the page to static HTML at build time, so the
  browser gets plain HTML, one stylesheet and a small first-paint module
  (theme toggle, copy button). The hero background is ThreeUI's Ribbon Field
  shader (`site-app/src/client/hero.ts`), fetched as a separate chunk only
  after first paint, and skipped for reduced motion, data saver, low-power
  devices and missing WebGL; a designed static frame (flame and gradient) is
  always painted underneath. The build prints the bundle sizes. Credits ship
  at `/credits.txt`.
- **Wisp flame:** the idle loop and stills are published from
  `assets/brand/wisp-flame/export/` by `scripts/site/build_3d.py`; nothing is
  copied into `site-3d/` or `site-app/`.
- **Guiding-light preview:** `site-3d/light/`, served at `/light/` by the same
  build. A small real-time WebGL light (plain WebGL1, drawn only while it
  moves) with a CSS-orb fallback, self-hosted font, no inline script; design in
  `site-3d/light/DESIGN.md`, credits in `THIRD_PARTY_NOTICES.md`.
- **Independent fallback:** `site/`, assembled at `/plain/` without JavaScript.
- **Bootstrap:** the reviewed `scripts/bootstrap/install.py`, copied exactly to
  `/install.py`. Publication does not authenticate that initial script.
- **Assembly:** `python3 scripts/site/build_workers.py` writes only the public
  asset bundle to `build/published/`.
- **Worker:** `wrangler.json` declares `wisp-observer`, static assets, both custom
  domains and genuine not-found responses, not an SPA fallback.

Website tooling needs Node.js 22 or newer and Python 3, and `npm ci` at the
repository root before `build_workers.py` (it runs the homepage build). Node.js
is not a new desktop installation prerequisite.

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run build:site
npx --no-install wrangler deploy --dry-run --outdir build/worker-dry-run
npm run preview:site
```

Wrangler is pinned in `package-lock.json`. The dry run validates and bundles
without publishing; the preview is local.

## Publication and domains

The approved production Worker serves [wisp.observer](https://wisp.observer/)
and [www.wisp.observer](https://www.wisp.observer/). Its alternate address is
[wisp-observer.duketopceo.workers.dev](https://wisp-observer.duketopceo.workers.dev/).

The owner approved replacing the four GitHub Pages apex A records with
Worker-managed domain routing. Both hostnames are connected to the production
Worker, and the obsolete GitHub Pages custom-domain association is cleared.
Do not restore the old GitHub A records or GitHub `www` CNAME.

**Merging to `master` publishes the website.** The `website` workflow
(`.github/workflows/pages.yml`) validates the baseline and the homepage, runs
Chromium and WebKit against the local Worker, and assembles
`wisp-workers-assets`. Only when every lane passes does its `deploy` job run:

- It runs only for pushes to `master` (path-filtered to website inputs) and
  for manual `master` dispatches. Pull requests never deploy.
- It uses the `production` environment. The owner can require reviewer
  approval there before a deploy starts.
- It uploads the exact `wisp-workers-assets` artifact that passed the tests
  with the Wrangler version pinned in `package-lock.json`
  (`npx --no-install wrangler deploy`).
- It then checks that `https://wisp.observer/` returns 200 and that
  `https://wisp.observer/install.py` is byte-identical to
  `scripts/bootstrap/install.py`. A failed check fails the run but does not
  roll back the Worker automatically.
- Repository secrets: `CLOUDFLARE_API_TOKEN` (an API token with Workers Scripts:
  Edit, account-scoped) and `CLOUDFLARE_ACCOUNT_ID`.

Runs on `master` queue rather than cancel each other, so a publish is never
killed mid-upload.

**Rollback:** run the `website` workflow manually from `master` with the `ref`
input set to a reviewed commit SHA. The workflow rebuilds and retests that
commit, then deploys it. Leave `ref` empty to deploy the current `master` HEAD.

A manual local publish with `npm run deploy:site` is an emergency fallback
only. Authenticate first, and do not use it when the workflow can run.

Alternatively, upload the assembled assets through this Worker's **New
deployment** dashboard flow. The archive must have `index.html` at its root,
preserve asset subdirectories and include `_headers`; never upload repository
roots, credentials or development dependencies.

The `pages.yml` filename is historical; the workflow is named `website`. It has
no GitHub Pages deployment job or Pages write permission. Its Worker deploy job
is the only publication path, and an uploaded QA artifact is not evidence of
public deployment by itself.

## Headers and privacy

`site-3d/_headers` restricts script and font loading to the website's own origin,
disables microphone/camera/geolocation access in the illustration, and makes
`/install.py` noncacheable. These website restrictions do not configure desktop
application permissions.

The live browser gate rejects external asset requests as well as page errors.
Cloudflare's automatic RUM injection must be disabled for this zone to preserve
that contract; do not allowlist its injected beacon merely to pass the gate.
Server-side Worker metrics are separate from a browser-injected script.

## Installation and rollback boundaries

Keep repository installation visible until actual native candidate assets have
been published and verified. `/install.py` requires the independently trusted
`gh` verifier and exact release identity; it cannot authenticate itself, so follow
the separate source-trust step in [INSTALL.md](INSTALL.md).

To roll back a website deployment, dispatch the `website` workflow with a reviewed
commit in `ref` (see above), or use a previously verified asset bundle. Website publication is not a stable-v1 release,
hardware validation or evidence that the owner-labelled success gate passed.
