# Wisp gauntlet, hermetic run record, branch lfg/v2-region-403 (base b71759e)

Hermetic pieces only (no model, no network, no display, no audio). Run id: none (the offline scorer writes no run directory).
Commands: `python scripts/gauntlet.py --teach-offline` and `python -m unittest discover -s tests -p 'test_gauntlet*' -v`.
Wall time: teach-offline 0.069s; test_gauntlet* 3.8s (136 tests, OK, after the PR #347 review fixes).

KTD11 (owner-directed): every test, gauntlet and bake-off run sets `[voice] enabled = "false"` in its throwaway config.
`seed_config()` in `scripts/gauntlet.py` writes it, `--dir` is resolved to an absolute path (a relative XDG dir is ignored by
the daemon, which would fall back to `voice = auto`), and each arm's profile is rewritten into `<dir>/profiles/` with
`[voice] enabled = "false"` forced, so a profile that sets voice on cannot undo the seed. `TestSeedSilent` and
`TestTurnConfigSilent` in `tests/test_gauntlet_driver.py` check the effective turn configuration (seed plus profile through
`devrun.run_config`, relative `--dir`, voice-on profile): voice is off and `speech.speak` launches no process
(`subprocess.Popen` and `subprocess.run` patched, neither called). `PrivateTextTests` in `tests/test_speech.py` selects the
silent command provider (`provider = "cmd"`) and shuts off the Groq availability check, so a Groq key or audio player on the
machine cannot reach audio or the network; `test_a_groq_key_and_player_never_reach_audio_or_network` proves it with both present.

## Scores (teach-offline, recorded planner replies from tests/fixtures/teach, n=15)

| case | app | expect | verdict |
|---|---|---|---|
| browser-address-bar | browser | click | wrong-kind |
| browser-new-tab | browser | click | wrong-target |
| browser-open-settings | browser | click | no-element |
| calc-select-range | libreoffice | area | wrong-kind |
| files-drag-to-folder | files | motion | wrong-kind |
| files-new-folder | files | click | wrong-kind |
| gimp-crop-handle | gimp | handle | wrong-target |
| gimp-layer-eye | gimp | hover | wrong-kind |
| gimp-paintbrush | gimp | click | wrong-kind |
| omarchy-display-settings | omarchy | click | no-element |
| omarchy-no-activities | omarchy | voice-confirm | wrong-kind |
| terminal-list-files | terminal | voice-confirm | wrong-kind |
| terminal-new-tab | terminal | click | wrong-kind |
| writer-bold | libreoffice | click | wrong-kind |
| writer-file-menu | libreoffice | click | wrong-kind |

| class | cases |
|---|---|
| first-time-correct | 0/15 |
| wrong-target | 2 |
| wrong-kind | 11 |
| no-element | 2 |
| (target right, any kind) | 11/15 |

Verified rate: not measured (needs U4 verify ladder).

## Spend

$0 (no model calls).

## Live battery: not run

The live battery is an owner-run, capped step. Command:
`orch python scripts/gauntlet.py --session isolated --profiles openrouter --cap 1.00`
One arm only, on purpose: a case is only started when its reserve fits the remaining cap. The reserve per arm is the
profile's `act_max_usd` ($0.25) plus the judge reserve ($0.02), times 3 attempts for a learnable case. Both profiles
(`hybrid,openrouter`) need $1.62 for the first (learnable) case, above the $1.00 cap, so the run would stop before case one.
One arm needs $0.81 and starts; a non-learnable case needs $0.27. `TestOwnerBatteryFitsCap` pins these numbers.
The cap is not raised. A two-arm comparison needs a larger owner-approved cap.
It must never stop the owner's wispd.
