# day-cost
title: What did today cost
length: 30
setup: A normal day's use on the real ledger. Do not show an API console.
proof: result=ANSWERED && transcript~cost
## steps
- show Ask for the day's spend; it comes from the local ledger.
- say 6 "What has Wisp cost me today?"
- wait 8
- run wispd spend
- wait 6
## captions
readme: Asking what the day cost. The answer is read from the local spend ledger, the same numbers `wispd spend` prints.
release: Spend is visible by voice and by `wispd spend`.
omarchy: One person's real ledger, shown as it is. Model bills are the only cost.
x: What the day cost, read from my own ledger. Model bills are the only cost.
short: What the day cost, out loud.
