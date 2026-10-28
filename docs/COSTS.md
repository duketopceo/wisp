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
