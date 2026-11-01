# Wisp website hosting

The production website uses Cloudflare Workers Static Assets, not GitHub Pages
or Cloudflare Pages. The desktop application still runs on the owner's machine;
the website's Three.js examples are deterministic illustrations, not remote
desktop sessions.

## Source and build

- **Enhanced homepage:** `site-3d/`, with vendored Three.js, companion artwork,
  fonts and license notices.
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

Website tooling needs Node.js 22 or newer and Python 3. Node.js is not a new
desktop installation prerequisite.

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

After publication is explicitly authorized, an authenticated maintainer can use:

```sh
npm run deploy:site
```

Alternatively, upload the assembled assets through this Worker's **New
deployment** dashboard flow. The archive must have `index.html` at its root,
preserve asset subdirectories and include `_headers`; never upload repository
roots, credentials or development dependencies.

The historical workflow filename `.github/workflows/pages.yml` now names the
`website` workflow. It validates baseline and enhanced sites, runs Chromium and
WebKit against the local Worker, then produces `wisp-workers-assets` only after
both lanes pass. It has no GitHub Pages deployment job or Pages write permission;
an uploaded QA artifact is not evidence of public deployment.

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

To roll back a website deployment, use a previously verified asset bundle or
rebuild a reviewed commit. Website publication is not a stable-v1 release,
hardware validation or evidence that the owner-labelled success gate passed.
