# Contributing to Wisp

Thanks for helping. Wisp is AGPL-3.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
By contributing you agree your work is licensed the same way.

## Set up

Linux (Omarchy/Hyprland) is the full-app target. You need Python 3.11+ and,
for the extension and site, Node 22+. Rust (stable) is only needed for `rs/wispd`.

```sh
git clone https://github.com/duketopceo/wisp && cd wisp
pip install sqlite-vec pillow     # test dependencies
python3 wispd doctor              # include its output in bug reports
```

Read `docs/ARCHITECTURE.md`, `docs/DEV_MODE.md` and `AGENTS.md` first.

## Run the tests

CI (`.github/workflows/test.yml`) runs these. The suite is hermetic: no
network, no API keys, no live model calls.

```sh
python -m py_compile wispd wisp/*.py wisp/tools/*.py tests/*.py
python -m unittest discover -s tests -v          # unit suite (Python 3.11 and 3.13)
(cd browser-extension && npm ci && npm run typecheck && npm test && npm run build)
(cd rs/wispd && cargo build --locked && cargo test)
python3 scripts/plugin_mirror.py --out build/mirror --version v0.0.0 --lint
```

The QML suites need Qt 6 and Quickshell and skip without them; CI runs them on Arch.

Rules for tests:

- Never call a paid or live model (OpenRouter, Groq, etc.) from a test. Use the
  fixtures and fakes in `tests/`.
- Docs are linted: `tests/test_docs_lint.py` fails when `README.md`, `ROADMAP.md`
  or `docs/*.md` name a command, flag or config key that does not exist.
- CLI help is checked against goldens. After an intended change, regenerate with
  `WISP_UPDATE_GOLDEN=1 COLUMNS=80 python -m unittest <test module>` and review the diff.
- Do not put real usernames, hostnames, emails or home paths in code, tests or docs.

## Branches and pull requests

- Branch from `master`: `feat/<short-name>`, `fix/<short-name>`, `docs/...`, `chore/...`.
- One logical change per PR. Fill in the PR template: what, why, how tested, risks.
- Commits use [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`), imperative mood.
- Add a line under `Unreleased` in `CHANGELOG.md` for user-visible changes.
- PRs are squash-merged after review and green CI.

## Sign-off (DCO)

Sign every commit with the [Developer Certificate of Origin](https://developercertificate.org/):

```sh
git commit -s -m "fix: describe the change"
```

This adds a `Signed-off-by:` line using your real name and email.

## Security and conduct

Report vulnerabilities privately, not in issues: see [SECURITY.md](SECURITY.md).
Everyone participating is bound by the [Code of Conduct](CODE_OF_CONDUCT.md).
