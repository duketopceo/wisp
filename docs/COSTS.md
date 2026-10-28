# Costs

What Wisp costs, and where each number on the landing page comes from. The
only cost is the model bill: Wisp is free software (AGPL-3.0) and there is no
hosted service, subscription or telemetry.

## The cost card

The card on the landing page (`site/costs.json`, built by
`scripts/site/build.py`) states **one person's numbers**, with the source and
the date next to each:

| item | source |
|---|---|
| Default daily and monthly spend caps ($8.00 and $160.00) | `wisp/ledger.py` (`DEFAULT_DAILY_USD`, `DEFAULT_MONTHLY_USD`), `[budget]` in `docs/CONFIG.md` |
| Local models cost $0.00 and are never gated | README Spend section |
| Median cost of a paid model call; median and most expensive day of use; median paid calls per day | the owner's `usage.jsonl` over the last 30 days, written by `scripts/site/costcard.py` |

**Status: the measured rows are not published yet.** They exist only after the
owner runs `python3 scripts/site/costcard.py` against his own ledger and
commits the result, so the page currently shows the code's defaults and says
the per-day numbers are pending. Nothing here is estimated or taken from
another person's usage.

`costcard.py` counts only paid rows (`paid` true and `usd` above zero) in the
window, so local-model turns do not pull the median down.

## Reproduce

```sh
python3 scripts/site/costcard.py --days 30     # reads your ledger, rewrites site/costs.json
python3 scripts/site/build.py                  # builds build/site/
wispd spend                                    # today's and this month's totals
wispd eval                                     # first-time-correct rate per turn kind
```

## Comparison table

`site/compare.json`: every cell about another product names a source URL and
the date it was read. Prices change; re-read before quoting them.

## The page

Static HTML and CSS, no framework, no scripts, no analytics, no third-party
host (a test fails if the built page loads one) and under 300 KB with the
hero poster. It is deployed by `.github/workflows/pages.yml` to GitHub Pages
without a custom domain, only when the repo variable `PAGES_ENABLED` is
`true`.

## Lowering the key barrier (B34): proposed cap and terms

Built, tested, **not live**. Two ways for a first run without keys to work.
Neither is on in a shipped build (`[trial] enabled` and `[clibrain] enabled`
are `false`, and the trial has no URL). Going live needs the owner to read
this section and say yes.

### Option A: capped hosted trial (`trial:<model>`)

A proxy the owner runs (`scripts/trial_proxy/proxy.py`, standard library)
holds the only real key. The install sends a random token (`wt_` and 32 hex
digits), text only (the client and the proxy both drop screenshots). Every
cap is checked before anything is forwarded, and a refused call is never
sent upstream.

Proposed caps, all in `LIMITS` at the top of the proxy:

| cap | proposal | why |
|---|---|---|
| calls per install per day | 30 | enough to try every tour step and a day of use |
| calls per install in total | 100 | the trial ends by itself; worst case per install is about $0.20 |
| calls per address per day | 60 | two installs behind one router; stops a loop of fresh tokens |
| global dollars per day | **$5.00** (2,500 calls at $0.002) | the hard stop: the most the trial can cost in a day |
| per-call estimate | $0.002 | deliberately above the real figure: one text turn on the default model is a few thousand input tokens and about 300 out, well under a tenth of a cent at current OpenRouter list prices; confirm with `scripts/site/costcard.py` before launch |
| `max_tokens` | 600 | same as the key path |
| model | one, on an allowlist | `meta-llama/llama-4-maverick` |

Proposed ceiling: **$5 a day, about $150 a month**, and nothing if the owner
touches the kill switch (`TRIAL_OFF=1` or an `OFF` file beside the database).
Abuse: a token is free to mint, so the address and global caps are the real
defence; there is no account, so there is nothing to ban. The proxy keeps no
request log and stores only (day, token, address) rows. It still sees the
text of every trial turn, so the trial page and TRUST.md would have to say so
before launch. Speech to text is separate: it still needs a Groq key or a
local whisper.cpp model (`[stt] provider = "local"`).

### Option B: your own coding-agent CLI (`cli:claude`, `cli:codex`)

The user's installed CLI answers a turn: Wisp runs it once with the text on
stdin, with Wisp's own keys scrubbed from its environment, and never reads
its sign-in files. Text only. Terms read on 2026-10-28:

- **Claude Code** ([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)):
  subscription sign-in "is intended exclusively for" Claude Code and
  Claude.ai; third-party developers may not offer Claude.ai login, route
  requests through Free, Pro or Max credentials, or "collect, store, or
  intermediate" those credentials or session tokens. An end user signing in
  to the unmodified binary with their own plan is allowed, and usage limits
  "assume ordinary, individual usage". `claude -p` is the documented
  non-interactive mode. Wisp's design (run the user's own binary, touch no
  credentials, one call per turn) stays on the allowed side, but a tightening
  of the policy to cover non-interactive use would end it. It must not be
  used for high-volume or looping work.
- **Codex CLI** ([non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
  [Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)):
  `codex exec` is the documented way to run it in scripts and "reuses saved
  CLI authentication by default"; sign-in is `codex login`. The ChatGPT Terms
  of Use apply to data shared with it. API keys are the recommended default
  for automation, and ChatGPT-account auth is described for trusted private
  runners.
- **Gemini CLI** is not included: its terms were not read.

Not verified here: neither provider's terms were tested with a real
subscription, and nothing was run against a live CLI. Both live checks need
the owner's own accounts.
