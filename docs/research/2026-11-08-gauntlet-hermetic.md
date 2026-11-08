# Wisp gauntlet, hermetic run record, branch lfg/v2-region-403 (base b71759e)

Hermetic pieces only (no model, no network, no display, no audio). Run id: none (the offline scorer writes no run directory).
Commands: `python scripts/gauntlet.py --teach-offline` and `python -m unittest discover -s tests -p 'test_gauntlet*' -v`.
Wall time: teach-offline 0.069s; test_gauntlet* 4.5s (132 tests, OK).

KTD11 (owner-directed): every test, gauntlet and bake-off run sets `[voice] enabled = "false"` in its throwaway config.
`seed_config()` in `scripts/gauntlet.py` now writes it, and `TestSeedSilent` in `tests/test_gauntlet_driver.py` asserts the seeded
config parses to `"false"`, that `speech.voice_enabled` is off for it, and that `speech.speak` launches no process
(`subprocess.Popen` and `subprocess.run` patched, neither called).

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
`orch python scripts/gauntlet.py --session isolated --profiles hybrid,openrouter --cap 1.00`
It must never stop the owner's wispd.
