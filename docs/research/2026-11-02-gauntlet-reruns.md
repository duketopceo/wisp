# Wisp gauntlet rerun, live desktop (eDP-1), master 55016cb

Run `gauntlet-20261102-034310` (`~/.local/share/wisp-gauntlet/runs/gauntlet-20261102-034310/`, report.md and rows.jsonl there).
Worktree `~/.local/share/worktrees/wisp-rerun`, branch `test/live-rerun` (not committed). Command:
`orch python scripts/gauntlet.py --session live --profiles hybrid,openrouter --cap 10`. 19 of 19 cases ran. Click probe not rerun.
Wall time 33m39s.

## Scores (first attempt per case, n=1)

| arm | tuning before (full / folded) | tuning now | held-out before | held-out now |
|---|---|---|---|---|
| hybrid | 2/13 / ~4/13 | 2/12 | 3/7 | 5/7 |
| openrouter | 0/13 / ~3/13 | 3/12 | 2/7 | 5/7 |

Case set changed (#301): windows-move-workspace is now skipped (tuning is 12, not 13), and the two menu cases are live-only
(menu-open-close is tuning, menu-launcher-close is held-out). Held-out 60% gate: both arms now clear it (71%).
Tuning is flat against the folded baseline. Skill wins: hybrid 2 of 10, openrouter 3 of 11.

## Per-case flips

Versus the full third run (folded = after the three-browser-case rerun):

| case | arm | before | now |
|---|---|---|---|
| browser-address-bar (held-out) | openrouter | fail | pass |
| browser-new-tab-site (held-out) | openrouter | fail | pass |
| files-new-folder (held-out) | hybrid | fail | pass |
| files-new-folder (held-out) | openrouter | fail | pass |
| terminal-count-lines (held-out) | hybrid | fail | pass |
| terminal-where-am-i | openrouter | fail | pass |
| browser-open-page | hybrid, openrouter | fail (full), pass (folded) | pass |
| browser-search-site | openrouter | fail (full), pass (folded) | pass |
| windows-focus-files | hybrid | pass | fail (pass->fail) |
| browser-settings-page | openrouter | fail (full), pass (folded) | fail (pass->fail vs folded) |
| browser-search-site | hybrid | fail | fail (still click grounding) |

Only clean pass->fail against the full run: windows-focus-files [hybrid] (outcome "success" from the agent but check failed:
`evidence/windows-focus-files-hybrid-1.json`; model/check issue, not a policy block). Everything else not listed is unchanged.
windows-move-workspace was fail/fail, now skipped on both arms (not a flip in score terms).
Menu cases: menu-open-close and menu-launcher-close are not scoreable (see class 3).

## Spend

This run $0.2910 (hybrid $0.1406, openrouter $0.1504; includes $0.0204 orcheval judge). Cumulative spend file $1.3277 of the $10 cap
(was ~$1.04). All through `orch`.

## Failure classes (tuning + held-out failures; evidence under `.../gauntlet-20261102-034310/evidence/`)

1. **Expected policy block: "no element at model-chosen coordinates"** (click refused). Main blocker; most frequent.
   browser-search-site-hybrid-1, browser-follow-link-hybrid-1/openrouter-1, browser-settings-page-openrouter-1,
   files-open-folder-{hybrid,openrouter}-1, files-open-nested-openrouter-1, files-rename-*-1. The string also appears in many
   passing runs, so not every refusal is fatal.
2. **Expected policy block: shell denied / "shell disabled"** ("dev run denies shell"). files-open-nested-hybrid-1 (stopped, shell disabled),
   files-rename-openrouter-1, terminal-list-files-hybrid-1 (also hit class 4), terminal-read-file-openrouter-1/-2,
   terminal-count-lines-openrouter-1.
3. **Expected policy block: "click needs user confirmation"**. menu-open-close-hybrid-1, menu-launcher-close-{hybrid,openrouter}-1.
4. **Possible new bug / harness gap (not on the expected list):** `REFUSED (gauntlet: no sandbox window is registered)` in all four
   menu runs (menu-open-close-{hybrid,openrouter}-1, menu-launcher-close-{hybrid,openrouter}-1), and
   `REFUSED (gauntlet sandbox: the focused window is not a sandbox window)` in terminal-list-files-hybrid-1. The sandbox guard fires
   on the live session, where the menu cases (live-only) have no sandbox window by design. Likely a #301 interaction; worth a
   look before treating menu cases as model results. Also `REFUSED (gauntlet: super and alt chords reach the compositor, not the window)`
   in browser-settings-page-openrouter-1 (chord guard on a live-run case, same suspicion), and `dev run denies mcp_call` in
   browser-follow-link-openrouter-1 (dev-policy refusal; model picked an MCP tool).
5. **Model failures (acted or gave up, check failed):** terminal-list-files-openrouter-1, terminal-read-file-hybrid-1,
   terminal-where-am-i-hybrid-1 ("stated it could not perform the action"), windows-focus-files-{hybrid,openrouter}-1,
   files-rename-hybrid-1 (max steps), terminal-read-file-openrouter-1 (ask_user), browser-address-bar-hybrid-1,
   terminal-count-lines-openrouter-1.

## Blocked only by the pending policy PR

Classes 1, 2 and 3: files-open-folder (both), files-open-nested (both), files-rename (both), browser-follow-link (hybrid; openrouter
also hits class 4 mcp_call), browser-search-site-hybrid, menu-open-close-hybrid. Menu cases additionally need the class-4
sandbox-guard question resolved, since the live session has no sandbox window.

## Final state

wispd.service active; workspace 1 on eDP-1; submap default; the run ended with the owner back on workspace 1 (observed on 91
mid-run, restored by the driver). Nothing committed or pushed.

## Run on PR #302

Branch fix/gauntlet-run-policy at 86dc049 (clean, equals origin). Command: `orch python scripts/gauntlet.py --session live --profiles hybrid,openrouter --cap 10`. Run dir: `~/.local/share/wisp-gauntlet/runs/gauntlet-20261102-042144` (report.md, rows.jsonl, evidence/). No code changes, no commits. Spend: $0.2717 this run, $1.5994 of $10 cumulative. Wall time about 25 min. Single attempt per case, so differences are within noise for many cases.

| arm | master tuning | PR #302 tuning | master held-out | PR #302 held-out |
|---|---|---|---|---|
| hybrid | 2/12 | 7/12 | 5/7 | 5/7 |
| openrouter | 3/12 | 7/12 | 5/7 | 3/7 |

### Flips (master -> PR #302)

Tuning, hybrid: gained browser-follow-link, terminal-list-files, terminal-read-file, windows-focus-files, menu-open-close (judge). No losses.
Tuning, openrouter: gained browser-settings-page, files-open-nested, terminal-list-files, terminal-read-file, menu-open-close (judge). Lost browser-search-site (stopped after 2 steps, never typed the query).
Held-out, hybrid: gained browser-address-bar, menu-launcher-close; lost files-new-folder, terminal-count-lines.
Held-out, openrouter: gained terminal-count-lines; lost browser-new-tab-site, browser-address-bar, files-new-folder.

### Blocks

- "no element at model-chosen coordinates": gone (0 matches in the run dir).
- "click needs user confirmation": gone (0 matches).
- Shell denied: real `shell` calls now run through rsh (`SHELL rc=0 ...` in terminal-list-files, terminal-read-file, terminal-count-lines). The string "SKIPPED (shell disabled)" still appears 3 times in the evidence, but only on invented tool names (`default_type_text`, `default_focus`, `default_click`), which `risk_of` treats as unknown and therefore as the shell tier. That is a model error (nonexistent tool names) plus a minor wisp bug (misleading message). It is not the allow_shell policy block.

### Known open issues

- Menu cases: no `REFUSED (no sandbox window)` any more. Clicks execute as plain `CLICKED(x,y)` at model-guessed coordinates on the live desktop (menu-open-close: 1049,992 / 36,1067, then a click-away; menu-launcher-close: 33,968 / 10,1060). Judge verdicts: menu-open-close success on both arms; menu-launcher-close hybrid success, openrouter "launcher not visible". These are judge-only (no deterministic check), so treat them as unverified. Nothing gates clicks on non-sandbox windows now, which is the risk side of the pre-approval.
- terminal-list-files: "focused window is not a sandbox window" did not recur. Both arms passed (hybrid via type_text+key, openrouter via rsh shell).
- Super/alt chord refusal: recurred in files-rename hybrid and windows-resize hybrid (`REFUSED (gauntlet: super and alt chords reach the compositor...)`). Not in browser-settings-page (there the model's `ctrl+comma` chords hit `SKIP (unknown chord)` and it fell back to typing; passed).
- "dev run denies mcp_call": did not recur in browser-follow-link.
- Also seen: `rsh: refused (mv is not allowed)` / cp / hyprctl in files-rename, files-new-folder (hybrid), windows-resize (hybrid). This is a new wisp/sandbox allowlist gap that blocks legitimate task commands. `CANCELLED (user)` appeared in 6 rows (files-rename hybrid, files-go-up/windows-resize/menu-launcher-close openrouter etc.); its cause was not investigated.

### Remaining failures

Wisp bug / policy gap:
- rsh allowlist refuses mv/cp/hyprctl: files-rename (both arms), files-new-folder hybrid, windows-resize hybrid. Evidence: evidence/files-rename-openrouter-1.json, files-new-folder-hybrid-1.json, windows-resize-hybrid-1.json.
- Unknown tool names reported as "shell disabled": files-open-folder openrouter, files-open-nested hybrid, browser-search-site hybrid (the model error is the trigger).
- Super/alt chord refusal in files-rename hybrid (gauntlet policy).

Model failure:
- Stops after claiming success without verifying: browser-search-site openrouter, browser-new-tab-site openrouter, browser-address-bar openrouter, terminal-count-lines hybrid and terminal-where-am-i hybrid (typed the command, never pressed Enter), files-open-folder hybrid (one click, folder not opened), browser-follow-link openrouter, windows-focus-files openrouter (focused foot instead of Nautilus), files-new-folder openrouter.
- Hybrid files-new-folder ran mv and then reported it as done.

Not established: whether a few of the one-click "acted but check failed" cases come from wrong coordinates or from a click that did not take effect. A screenshot review would tell.

### Final state

wispd.service: active. Desktop: workspace 1 on eDP-1, submap default; no restore was needed. Nothing committed or pushed.

## Run on PR #302 + click guard

Run: `gauntlet-20261102-051957` (~/.local/share/wisp-gauntlet/runs/). Code: PR #302 head 7dda49f (fix/gauntlet-run-policy), tree clean and equal to origin. Command: `orch python scripts/gauntlet.py --session live --profiles hybrid,openrouter --cap 10`. Spend this run $0.2387; cumulative $1.8381 of $10.

### Scores (report.md scoring)

| arm | tuning before -> after | held-out before -> after |
|---|---|---|
| hybrid | 7/12 -> 5/12 | 5/7 -> 5/7 |
| openrouter | 7/12 -> 6/12 | 3/7 -> 2/7 |

Attempt-1-only pass counts from rows.jsonl differ slightly (previous run hybrid 6/12 tuning, 4/7 held; openrouter 6/12, 3/7; this run matches the report). The report appears to count a later attempt as well, so the flips below are attempt 1.

### Per-case flips (attempt 1, old -> new)

Regressions:
- browser-follow-link hybrid P->F (click refused by guard)
- browser-settings-page hybrid P->F (0 steps, "done" without acting; model)
- files-go-up openrouter P->F (every click refused; held-out)
- terminal-read-file hybrid and openrouter P->F (typed `cat a.txt`, or pressed enter, never completed both; model)
- terminal-count-lines openrouter P->F (held-out; typed/ran `wc`, check saw no executed line)
Improvements:
- browser-address-bar openrouter F->P (held-out), browser-search-site both arms F->P, files-new-folder hybrid F->P (held-out), terminal-where-am-i hybrid F->P
Unchanged failing: browser-follow-link openrouter, browser-new-tab-site openrouter, files-open-folder both, files-open-nested hybrid, files-rename both, files-new-folder openrouter, terminal-count-lines hybrid, windows-focus-files openrouter, menu cases.

### Click safety

No click executed. Zero CLICKED rows in rows.jsonl and zero in evidence/*.json. Every click step is REFUSED or SKIPPED. No unguarded click on the live desktop (no P0). Menu cases: menu-open-close both arms SKIPPED (click needs user confirmation) (openrouter in the report also shows REFUSED no sandbox window); menu-launcher-close never got a super key. These were refused, as expected.

Problem: the guard also refuses every click in the legitimate sandbox windows (files and browser cases) with "a layer surface (menu, launcher or bar) is over the click point". `hyprctl layers` on the idle desktop shows `omarchy-notifications` as a fullscreen overlay layer (0,0 1728x1080) and `omarchy-bar`. The guard looks like it counts any layer surface covering the point, so the always-present fullscreen notifications overlay blocks all clicks. windows-resize was refused for "a window that is not a sandbox window is under the point", which is correct.

### Provider errors

None: no HTTP 503/429 in daemon.log, rows.jsonl or evidence for either arm or any model (previous runs had one each). No cases were lost to provider errors.

### Remaining failures

Wisp (guard): browser-follow-link hybrid, files-open-folder both, files-open-nested hybrid, files-rename openrouter, files-go-up both (hybrid still passed), browser-search-site openrouter extra refusals. Evidence: evidence/files-open-folder-hybrid-1.json, files-go-up-openrouter-1.json, browser-follow-link-hybrid-1.json. Root cause: fullscreen notifications layer counted as covering.
Wisp (policy, unchanged): files-rename hybrid "shell disabled"; files-new-folder openrouter "cannot create folder because shell is disabled".
Gauntlet/menu design: menu cases refused as intended; super key not simulable.
Model: browser-settings-page hybrid (0 steps), terminal-read-file both and terminal-count-lines both (stop after typing/claiming success without verifying), browser-new-tab-site openrouter (claimed success), windows-focus-files openrouter (claimed already focused; check disagrees), browser-follow-link openrouter (gave up after refusal).

### Final state

wispd.service active; Hyprland on workspace 1 (eDP-1); no restore needed. Nothing committed.

## Run on PR #303 (overlay fix)

Run `gauntlet-20261102-055333`, worktree wisp-overlay at bb33bee (clean, equals origin/fix/gauntlet-click-overlay), `orch python scripts/gauntlet.py --session live --profiles hybrid,openrouter --cap 10`. 19 of 19 cases, plus 1 skipped (windows-move-workspace, no tool). Spend $0.2727 this run, $2.1109 cumulative of $10.

### Scores (first attempt, `success` field of rows.jsonl n=1; matches each report.md)

| arm | #302 no guard | guard + overlay bug | #303 |
|---|---|---|---|
| hybrid tuning | 7/12 | 5/12 | 7/12 |
| hybrid held-out | 5/7 | 5/7 | 4/7 |
| openrouter tuning | 7/12 | 6/12 | 7/12 |
| openrouter held-out | 3/7 | 2/7 | 2/7 |

Flips vs #302 (P pass, F fail; order 302/guard/303):
- hybrid: browser-address-bar PPF (held-out, lost), browser-settings-page PFF (lost), browser-follow-link PFP, browser-search-site FPP (gained), files-new-folder FPP (gained, held-out), terminal-where-am-i FPP (gained), terminal-read-file PFP.
- openrouter: browser-follow-link FFP (gained), windows-focus-files FFP (gained), files-open-nested PPF (lost), terminal-count-lines PFF (held-out, lost), browser-address-bar FPF, browser-search-site FPF, files-go-up PFP, terminal-read-file PFP.
- Net vs #302: hybrid tuning and openrouter tuning equal; hybrid held-out -1; openrouter held-out -1. Many flips are single-sample noise (same model, gemini-2.5-flash, on both arms).

### Click safety (P0)
- 52 CLICKED, all on sandbox-window cases (browser-follow-link, browser-search-site, files-*). Zero CLICKED on menu-open-close, menu-launcher-close, terminal-* or windows-* cases.
- Menu cases: only REFUSED (no sandbox window is registered), 4 clicks each in menu-open-close; menu-launcher-close made no clicks.
- Refusal tally: 52 CLICKED; 10 REFUSED "a window that is not a sandbox window is under the click point" (files-go-up-openrouter-1 x6, files-new-folder-openrouter-1 x2, terminal-list-files-openrouter-2 x2); 8 REFUSED "no sandbox window is registered" (menu-open-close); 2 SKIPPED "shell disabled" (files-open-nested). Layer refusals: 0 (was 96 in the overlay-bug run). No layer is refusing any more.
- Note: the 10 non-sandbox-window refusals mean clicks aimed at Luke's own windows were correctly stopped.

### Provider errors
None found: no 429/503 or endpoint errors in daemon.log, evidence JSON or journalctl for hybrid or openrouter (0 and 0). A screenshot toast "Wisp can't reach the answering model" was visible in evidence/files-open-folder-hybrid-1.png, but no matching log line exists; origin unverified (possibly stale toast). Same screenshot shows stale "Process crashed: Hyprland / xdg-desktop-portal-hyprland" toasts; coredumpctl shows those crashes at 12:54 and 13:51, before this run, none during it.

### Remaining failures (first attempt)
Wisp or harness:
- menu-open-close (both arms), menu-launcher-close (hybrid): by design no sandbox window for menu cases, so the guard refuses clicks; model then gives up. Case can't pass with guard unless menu clicks are allowed. evidence/menu-open-close-*-1.json
- files-open-nested hybrid: SKIPPED shell disabled, model told user to click manually (model misreading a tool refusal; shell was not needed). evidence/files-open-nested-hybrid-1.json
- files-open-folder (both arms, all three runs): judge says the folder opened (hybrid) or is only selected (openrouter); check expects title matching "Projects" but the window title stays "workspace". Likely check issue or double-click not landing. Screenshot evidence/files-open-folder-hybrid-1.png shows folder only selected. Suspect harness/wisp click (single vs double). Do not tune.
- files-rename openrouter: key f2 unknown to wisp key tool (SKIP unknown key 'f2'); wisp gap. evidence/files-rename-openrouter-1.json
- files-new-folder openrouter: ended CANCELLED (user), unclear cause. evidence/files-new-folder-openrouter-1.json
- terminal-count-lines (both): trust prompt blocked execution in openrouter; hybrid typed without Enter. Mixed.
Model:
- browser-address-bar (both), browser-search-site openrouter, browser-new-tab-site openrouter, terminal-count-lines hybrid: typed text but never pressed Enter / claimed success without verification. browser-settings-page hybrid: 0 steps, claimed "done". files-rename hybrid: wrong flow, error dialog.

### Desktop state
wispd.service active after run; workspace 1, submap default. No config changes, no commits.
