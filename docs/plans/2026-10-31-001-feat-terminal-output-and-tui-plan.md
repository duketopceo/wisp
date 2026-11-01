---
title: Wisp terminal output and TUI overhaul - Plan
type: feat
date: 2026-10-31
status: active
depth: deep
execution: code
---

# Wisp terminal output and TUI overhaul - Plan

## Summary

Make every Wisp terminal surface (`wispd` commands, the installer and helper scripts, and `wispd tui`) scannable, width-aware and consistent. One shared output module owns color, symbols, width and layout. Commands then adopt it one group at a time, and the curses TUI gets a new layout on top of its existing data models. Nine small PRs, each mergeable alone, each with a golden test at 60, 80 and 200 columns.

Wisp's CLI contract is already good and stays: `--json` everywhere, `E_*` errors with a `Try:` line, exit codes 0/1/2/3/4, `NO_COLOR`, plain output when piped. The work is presentation, not behavior.

## Problem Frame

Findings from running `wispd` in a scratch HOME and reading the code (all paths repo-relative):

- `wisp/cli/diagnose.py` (`doctor`, lines ~20-240): about 60 rows in 11 sections, printed flat. The six `MISS` rows sit in the middle (`integrations`), after 40 `ok` rows. Degraded rows (`not found`, `not installed`) show as `ok` because the mapping is `check["level"] != "block"`. Fix text is glued onto the row (`... (Try: ...)`), giving lines over 150 columns. No verdict line and no counts. The `E_UNHEALTHY` error says "Fix the MISS rows above" but arrives on stderr, separate from the table.
- `wisp/cli/settings.py` (`config show`) and `wisp/cli/core.py` (`status`): the human output is `json.dumps(..., indent=2)`. Every config value is a quoted string.
- `wisp/cli/learning.py` (`skills list`): prints nothing when empty. `wisp/cli/settings.py` (`inventory`): prints `mcp servers: 0 (...)` with a stray ellipsis and an em dash in the title line, which the repo's own copy rules ban.
- `wisp/cli/registry.py:_fmt` passes `width=None`, so help wraps at the terminal width with no cap. `tests/golden/cli_help/config_set.txt` is 8 KB because `config set --help` lists every setting.
- `wisp/cli/output.py`: pads with `len()`, has no truncation and no terminal-width read. It paints 24-bit color from theme tokens only, with no ANSI-16 path, while `wisp/tui.py` is ANSI-16 only. The two surfaces disagree.
- `scripts/bootstrap/install.py`, `scripts/replay_turn.py`, `scripts/ui/snap.py` and `scripts/demo/record.py`: raw `print` prose, no shared formatter, no `--no-color`.
- `wisp/tui.py` (730 lines): the status view is one flat text column; the other views are `view_lines` text lists. Bold, dim and underline only, no panels, no focus, a single static footer string, no resize handling beyond clipping, no log view with filter.

Constraints the plan must respect (found in the code, not assumed):

- Copy rules (`wisp/cli/strings.py`, `wisp/copy.py`): sentence case, plain verbs, no emoji, no em dashes, sentences end with a period.
- `tests/test_tui_render.py` currently forbids any non-ASCII in TUI lines (`test_no_unicode_icon_glyphs`), requires ANSI 0-15 only and no hex literals. The QML test bans the glyphs `✦✓✗⚠●○▸→✕⚙`.
- `wisp/tui.py` model builders mirror `shell-plugin/lib/health.js` and `lib/manage.js` field for field, with a parity test over one fixture. Only the draw layer may change.
- `tests/golden/cli_transcripts.json` pins legacy human stdout (`status`, `config_show`, `skills`, ...). `tests/golden/cli_help/*.txt` pin help at `COLUMNS=80`. Both run non-TTY with `NO_COLOR=1`.
- `scripts/bootstrap/install.py` runs before Wisp is installed and must stay standard-library-only and self-contained. Its security wording must not be weakened.
- Read-only on the daemon: the TUI and commands read state; nothing here changes daemon behavior.

## Requirements

- R1. One output module decides color, symbols, width and layout for every CLI command and script that lives in the repo.
- R2. Color is ANSI-16 by default so the user's terminal theme applies; the five Wisp tones (`ember`, `needsYou`, `fail`, `ok`, `muted`) are the whole vocabulary. No new tones.
- R3. Status is never color alone: a word always accompanies the color, and an optional glyph is allowed only from a small allow-list with an ASCII fallback.
- R4. Output is correct at 60, 80 and 200 columns: no wrapped table cells, flexible column truncated with an ellipsis, padding by display width.
- R5. Color, glyphs and animation are off when the stream is not a TTY, `NO_COLOR` is set, `TERM=dumb`, or `--no-color`; `FORCE_COLOR` forces color on.
- R6. Piped output of existing commands is byte-compatible where scripts depend on it (`status`, `config show` stay JSON when piped); `--json` envelopes are unchanged except for additive fields.
- R7. `doctor` leads with a verdict, lists problems first with their fix on a second line, and collapses passing rows.
- R8. Empty results print a message that says what to do.
- R9. `wispd tui` has panels, a focus marker, context key hints, a header with state and clock, a log view with level coloring and filter, adaptive layout from 60 to 200 columns, and a clear non-TTY fallback.
- R10. Golden tests cover plain output at 60, 80 and 200 columns for every changed command and TUI view.
- R11. VHS captures of the main flows are reproducible from tape files in the repo.
- R12. A guard test stops new raw `print` calls from creeping into `wisp/cli/`.

## Scope Boundaries

Non-goals: changing daemon behavior, IPC messages, exit codes, config keys, or `--json` field names; the QML management app and desktop overlay; adding a Python dependency (the repo has none, `pyproject.toml` lists `dependencies = []`); a plugin or marketplace change.

### Deferred to Follow-Up Work

- A mouse-driven TUI, command palette and theme picker inside the TUI.
- Truecolor gradients and sparkline graphs in the spend and latency views, if Luke wants btop-style graphs after the restyle ships.
- Windows and macOS terminal checks beyond the existing platform tests.
- Moving CLI error strings into `wisp/copy.py` (existing TODO W17).

## Key Technical Decisions

- **KTD1. Standard library only; one module.** Extend `wisp/cli/output.py` rather than adding rich or textual. It stays the only place that emits escape codes; commands call `ctx.table`, `ctx.kv`, `ctx.summary`, `ctx.section`. The TUI imports the same width and truncation helpers, and its curses color pairs keep using `_TONE_ANSI`.
- **KTD2. Reuse Wisp's five tones, ANSI-16 default.** Map as `wisp/tui.py:_TONE_ANSI` already does (`ember` yellow, `needsYou` bright yellow, `fail` red, `ok` green, `muted` dim). Headings are bold, not a new color. Theme-token truecolor stays available, but only when `COLORTERM` is `truecolor` or `24bit`; otherwise ANSI-16. This removes the CLI/TUI disagreement without losing the Omarchy theme look on capable terminals.
- **KTD3. Words first, glyphs optional (decision for Luke).** Existing tests ban non-ASCII icons and the copy rules ban emoji. Default in this plan: status words (`ok`, `warn`, `fail`, `skip`) are always printed, and a tiny allow-list of non-emoji glyphs (`●`, `○`, `›`, box-drawing `─ │`) is used only when `LANG` is UTF-8 and the stream is a TTY, with ASCII fallbacks (`*`, `o`, `>`, `-`, `|`). No `✓ ✗ ⚠`, which keeps the QML ban consistent. `tests/test_tui_render.py` is amended to an explicit allow-list (U6). If Luke prefers ASCII only, drop the glyph path and skip that test change; nothing else depends on it.
- **KTD4. Human view differs from piped only where today's output is raw JSON.** `status` and `config show` print JSON when stdout is not a TTY (keeps `cli_transcripts.json` goldens and any scripts intact) and a key/value view on a TTY. Add `--json` already exists for the envelope. Other commands keep the same plain text structure when piped and only change layout.
- **KTD5. Empty-state hints go to stderr, only on a TTY.** stdout stays empty so goldens and pipes are unchanged.
- **KTD6. Doctor keeps its data, changes its view.** `doctor_sections` rows gain an additive `level` (`ok`, `warn`, `fail`); `ok` stays a boolean for the exit code. Preflight `degraded` becomes `warn`. Exit codes do not change (4 when any row has `ok == false`), so behavior is the same and only the label is honest.
- **KTD7. TUI: new draw layer, same models.** `sections()`, `spend_view()`, `cua_view()`, `health_lines()` and the parity-tested builders are untouched. A small layout engine (header, titled panel, focus, footer, resize) draws them. State arrives on the existing subscription; no polling is added.
- **KTD8. Installer stays dependency-free.** `scripts/bootstrap/install.py` gets its own 40-line formatter (same rules, no imports from `wisp`). Repo-local scripts import `wisp.cli.output`.
- **KTD9. Golden strategy.** Text goldens under `tests/golden/output/<surface>_<cols>.txt` and `tests/golden/tui/<view>_<cols>.txt`, run with `NO_COLOR=1`, fixed `COLUMNS`, fixed fixtures, regenerated with the existing `WISP_UPDATE_GOLDEN=1` convention. A separate color test asserts escape sequences appear only with a TTY.

## Output structure

    wisp/cli/output.py            # extended: width, symbols, summary, section, kv, banner
    wisp/tui_layout.py            # new: header, panel, focus, footer, resize (draw layer only)
    tests/test_cli_output.py      # new
    tests/test_tui_layout.py      # new
    tests/golden/output/          # new: doctor, config_show, status, inventory at 60/80/200
    tests/golden/tui/             # new: each view at 60/80/200
    docs/design/TERMINAL.md       # new: house style, links to the upstream skills
    docs/media/tui/*.tape         # new: VHS tapes
    scripts/ui/tui_capture.sh     # new: runs the tapes against a fixture daemon

## Implementation Units

PR order: PR1 first. PR2 to PR5 are independent of each other and can land in any order after PR1. PR6 depends on PR1. PR7 and PR8 depend on PR6. PR9 last.

### U1. Shared output core (PR1)

- **Goal:** Replace the thin table helper with the module every later PR uses. No command changes yet.
- **Requirements:** R1, R2, R3, R4, R5.
- **Dependencies:** none.
- **Files:** `wisp/cli/output.py`, `wisp/cli/registry.py` (expose helpers on `Ctx`), `tests/test_cli_output.py`.
- **Approach:**
  - `term_width(stream)` reads `COLUMNS`, then the ioctl, then 80; clamps to 40..200 for layout, 100 for prose.
  - `display_width(s)` strips ANSI and uses `unicodedata.east_asian_width` (wide = 2, combining = 0); `pad`, `truncate(s, n)` (ellipsis `...` in ASCII mode, `…` otherwise) use it.
  - `use_color(stream, no_color_flag, env)` implements R5 per stream; `use_glyphs(...)` is UTF-8 plus TTY plus not `TERM=dumb`.
  - `paint(text, tone)` emits ANSI-16 SGR (`\x1b[33m` etc.); truecolor from `theme.load` tokens only when `COLORTERM` allows (KTD2).
  - `symbol(tone)` returns word-plus-glyph or ASCII marker; `status_cell(tone, word)`.
  - `table(headers, rows, tones, flex=<col index>)`: header dim, columns padded by display width, flex column truncated to fit `term_width`, numbers right-aligned when the cell is numeric.
  - `kv(pairs)`: two-column list for single records, keys dim, aligned.
  - `summary(title, counts)`: title left, counts right-aligned on one line, then one blank line.
  - `section(name, count=None)`: bold heading line.
  - `banner(version)`: the 3-line mark (KTD3 glyph rules; plain `wisp  voice agent for Omarchy  vX` in ASCII mode). Rule: only on bare `wispd`, `onboard` and `--version`, only on a TTY, never with `--json`, `--quiet` or a pipe.
- **Test scenarios:**
  - Happy: table with 3 columns at 80 columns; no line exceeds 80 display columns.
  - Edge: a cell containing a wide character and one with ANSI escapes pad to the same display width; width 60 and 200; empty rows list; a single column; a cell longer than the whole width.
  - Color gate: `NO_COLOR=1`, empty `NO_COLOR=`, `TERM=dumb`, not a TTY, `--no-color`, `FORCE_COLOR=1` each produce the expected on/off result, per stream.
  - Glyphs: `LANG=C` gives ASCII markers; UTF-8 TTY gives allow-list glyphs only; no emoji or em dash in any output.
  - Tones: only the five Wisp tones are accepted; unknown tone returns plain text.
- **Verification:** the full existing suite passes unchanged, `tests/test_cli_output.py` passes at the three widths, and nothing in `wisp/cli/` outputs differently yet.

### U2. Doctor view (PR2)

- **Goal:** `wispd doctor` reads like a report: verdict, problems with fixes, collapsed passes.
- **Requirements:** R4, R7, R6.
- **Dependencies:** U1.
- **Files:** `wisp/cli/diagnose.py`, `wisp/preflight.py` (additive `level` passthrough only), `tests/test_cli.py`, `tests/golden/output/doctor_{60,80,200}.txt`.
- **Approach:**
  - Rows carry `level` (`ok`, `warn`, `fail`); the boolean `ok` and the exit code logic stay as they are (KTD6). `degraded` preflight rows become `warn`; the `E_UNHEALTHY` count stays the number of rows with `ok == false`.
  - Human view: `summary("wisp doctor", ...)` with counts, one verdict sentence, then `Needs attention (n)` listing `fail` rows first, then `warn`, each as `word  name  short value` and an indented `fix:` line (the fix text split out of the value). Then `Passing (n)` collapsed to one dim wrapped line; `--all` expands to the full table; `--section <name>` prints one section.
  - The `E_UNHEALTHY` text stops saying "above"; it says `wispd doctor --all` for the full list.
  - Em dashes in row values (`turn recording`, `cua-driver not installed ...`) are replaced to satisfy the copy rule.
  - `--json` adds `level` per row and a `counts` object; existing keys untouched.
- **Test scenarios:**
  - Happy: fixture with 2 fail, 3 warn, 20 ok shows fails first, fix lines present, passes collapsed, counts correct.
  - Edge: all ok (verdict only, no problem section); only warn (exit code 0 path unchanged); a fix line longer than the width wraps with a hanging indent at 60 columns.
  - Error path: any `fail` row still exits 4 with the same JSON `healthy: false`.
  - Compatibility: `--json` output validates against the old key set plus the new keys; `--all` output contains every row name from the old output.
- **Verification:** a person can read the verdict and the first fix in the first five lines at 80 columns; exit codes and `--json` keys are unchanged.

### U3. Config, status, empty states, inventory (PR3)

- **Goal:** Replace the raw JSON dumps on a TTY and fix silent or malformed outputs.
- **Requirements:** R6, R8.
- **Dependencies:** U1.
- **Files:** `wisp/cli/settings.py`, `wisp/cli/core.py`, `wisp/cli/learning.py`, `wisp/cli/agents.py`, `wisp/cli/share.py` (empty states only), `tests/golden/output/{config_show,status,inventory}_{60,80,200}.txt`, `tests/test_cli.py`.
- **Approach:**
  - `config show` on a TTY: sections as headings, `key  value  (default x)` rows via `kv`, changed-from-default values marked with the `ember` tone; piped output remains the current JSON (KTD4). Booleans and numbers print unquoted in the human view.
  - `status` on a TTY: state word with tone, then `kv` for heard, ghost, tasks; piped stays JSON.
  - Empty states (KTD5): `skills list` hints `no skills installed (wispd skills import <dir>)`; audit the other list commands (`task list`, `captures`, `suggest list`, `routine list`, `learn fails`) for the same.
  - `inventory`: use `kv`, drop the stray ellipsis, show the first eight MCP server names only when there are any, no em dash.
- **Test scenarios:**
  - Happy: config with two changed keys shows the marker and the default beside them at 80 columns.
  - Edge: a 150-character value truncates in the human view at 60 columns and is complete in `--json`; zero skills prints nothing on stdout and the hint on stderr on a TTY only.
  - Compatibility: piped `status` and `config show` match `tests/golden/cli_transcripts.json` byte for byte.
  - Error path: daemon down still exits 3 with the same error text.
- **Verification:** existing transcript goldens pass untouched.

### U4. Help text and banner (PR4)

- **Goal:** Help stays one screen per command; bare `wispd` gets the banner.
- **Requirements:** R4, R8.
- **Dependencies:** U1.
- **Files:** `wisp/cli/registry.py` (`_fmt`, `top_help`), `wisp/cli/settings.py` (`config set` help), `tests/golden/cli_help/*.txt` (regenerated), `tests/test_cli.py`.
- **Approach:**
  - `_fmt` uses `width=min(term_width, 100)`; option descriptions wrap with a hanging indent.
  - `config set --help` points to `wispd config keys` instead of printing every setting; the setting list moves to `config keys` output, which gets the table view.
  - Top help: banner on a TTY only, then the existing grouped command list unchanged, so the non-TTY golden `tests/golden/cli_help/wispd.txt` does not change.
  - Examples stay before the global options in each leaf help.
- **Test scenarios:**
  - Golden help at 60, 80 and 200 columns for `wispd`, `doctor`, `config set`, `daemon install`.
  - Banner absent in a pipe, with `--json`, with `--quiet`, with `NO_COLOR`; present on a TTY.
  - Every command still has a summary and examples (existing test).
- **Verification:** `config set --help` is under 40 lines; help goldens regenerated by `WISP_UPDATE_GOLDEN=1` and reviewed.

### U5. Installer and scripts (PR5)

- **Goal:** First-run and developer script output follows the same rules.
- **Requirements:** R1, R5, R12.
- **Dependencies:** U1 (repo-local scripts only; the installer is independent).
- **Files:** `scripts/bootstrap/install.py`, `scripts/replay_turn.py`, `scripts/ui/snap.py`, `scripts/demo/record.py`, `tests/test_bootstrap.py`, `tests/test_install_release_edges.py`.
- **Approach:**
  - Installer: a small self-contained block (color gate, `step(n, total, text)`, `warn`, `fail`) with the same NO_COLOR/TTY rules. Output becomes numbered steps (`1/6 Check platform`, ...), one fact per line, the long security sentence split into a short checklist. `--inspect-source` output stays exactly the file contents. `--dry-run` prints a plan list. Wording of every security claim is preserved.
  - Other scripts: import `wisp.cli.output`; add `--no-color` and a final one-line result.
- **Test scenarios:**
  - Installer `--dry-run` golden at 60 and 80 columns, plain.
  - `--inspect-source` byte-identical to the file.
  - Installer refuses root with the same exit code (4) and a `fix:` line.
  - Non-TTY: no escape codes, no carriage returns.
- **Verification:** the installer still has no imports outside the standard library (checked by an AST import test) and its exit codes are unchanged.

### U6. TUI layout engine (PR6)

- **Goal:** Give `wisp/tui.py` a reusable draw layer without touching its data models.
- **Requirements:** R2, R3, R9.
- **Dependencies:** U1.
- **Files:** `wisp/tui_layout.py` (new), `wisp/tui.py` (call sites only), `tests/test_tui_layout.py`, `tests/test_tui_render.py` (glyph allow-list, per KTD3).
- **Approach:**
  - Primitives that take a window-like object: `header(win, state)` (name, state word with tone, daemon up or down, clock), `panel(win, rect, title, lines, focused)` (titled rule, focused panel title in bold), `footer(win, hints)` (hints for the current view and focus, truncated by priority so `q quit` always shows), `layout(h, w)` returning rects: under 60 columns a single column with views tabbed; 60-99 one column of stacked panels; 100 and wider two columns.
  - Handle `KEY_RESIZE`, recompute, and clip safely at tiny sizes (a "terminal too small, need 40x10" line instead of a crash).
  - Styles stay `_TONE_ANSI` pairs; box characters follow `use_glyphs` with `+ - |` fallback.
  - Non-TTY: `wispd tui` exits 2 with `E_USAGE`-style text and the commands to use instead (`wispd status`, `wispd doctor`).
- **Test scenarios:**
  - `FakeWin` (already in `tests/test_tui_render.py`) at 40x10, 60x24, 100x30, 200x50: no `addnstr` call exceeds the width, no row past the height.
  - Focus: the focused panel title carries the bold attribute; unfocused do not.
  - Footer: at 60 columns the lowest-priority hints drop first and `q` stays.
  - Fallback: ASCII mode contains no non-ASCII character; `TERM=dumb` and no TTY give the refusal message.
  - Resize: draw after a size change does not raise.
- **Verification:** `tests/test_tui_render.py` passes with the explicit glyph allow-list; model parity tests are untouched and green.

### U7. TUI views restyle (PR7)

- **Goal:** Status, health, spend and binds views on the new layer.
- **Requirements:** R3, R9, R10.
- **Dependencies:** U6.
- **Files:** `wisp/tui.py` (`_draw`, `_draw_view`, `view_lines` call sites), `tests/golden/tui/{status,health,spend,binds}_{60,80,200}.txt`, `tests/test_tui_render.py`.
- **Approach (what to borrow):**
  - Header strip with state and hints, in the manner of `derailed/k9s`.
  - Conversation-style block in the status view in the manner of `charmbracelet/crush`: `heard`, then steps as dim sub-lines, then `result`, with the role words as dim labels and the `ember` tone for work in progress, `needsYou` for a pending choice.
  - Focus and contextual hints in the manner of `jesseduffield/lazygit`: the pending suggestion or choice panel is focusable (`c`, `y`, `n`, `v` shown only when something is pending).
  - Spend and health as aligned tables with the cap shown as a plain ratio (`$1.20 of $8.00 today (15%)`), no graphs in this PR.
  - Copy rules hold: text still flows through `wisp/copy.py`.
- **Test scenarios:**
  - Golden render per view at 60, 80 and 200 columns from the existing fixtures.
  - Offline state: header says offline and the panel shows the existing copy string plus the command to start the daemon.
  - Pending choice: hints include `c`; none pending: hints omit it.
  - Parity: shared-fixture parity test still passes.
- **Verification:** every view is legible at 60 columns with no clipped words in a heading or key hint.

### U8. TUI log and audit view (PR8)

- **Goal:** A log view with level coloring, filter and follow.
- **Requirements:** R3, R9, R10.
- **Dependencies:** U6.
- **Files:** `wisp/tui.py` (audit view and a new decisions-log view), `wisp/tui_layout.py` (filter bar), `tests/golden/tui/{audit,log}_{60,80,200}.txt`, `tests/test_tui_layout.py`.
- **Approach:** In the manner of `tstack/lnav`: dim timestamp, tone-colored level word, plain message, one row per entry, no wrapping (truncate with an ellipsis; `Enter` opens the full row in a detail panel). `/` opens a filter bar (substring on the visible text), `f` toggles follow, `Esc` clears. Reads the same audit text the view reads today (`audit_text`, `audit_rows`); no new file watching or polling beyond the existing one-shot read and `r` reload (follow uses the push stream only where it already exists).
- **Test scenarios:**
  - Happy: 50 entries with mixed levels render with the right tone per row.
  - Edge: a 300-character message truncates at 60 columns and shows in full in the detail panel; filter with zero matches shows `no matches (Esc to clear)`.
  - Error path: unreadable log file shows the existing copy string, not a traceback.
- **Verification:** filter and detail work in the `FakeWin` harness; goldens at three widths.

### U9. Style doc, VHS captures, guard (PR9)

- **Goal:** Make the result reproducible and keep it from regressing.
- **Requirements:** R11, R12.
- **Dependencies:** U2 to U8.
- **Files:** `docs/design/TERMINAL.md`, `docs/media/tui/doctor.tape`, `docs/media/tui/tui-status.tape`, `docs/media/tui/tui-audit.tape`, `scripts/ui/tui_capture.sh`, `docs/MEDIA.md` (one paragraph), `tests/test_cli_output_guard.py`.
- **Approach:**
  - `docs/design/TERMINAL.md`: the tones, the glyph allow-list, the width rules, the `fix:` line shape, banner rules, and a pointer to the upstream `terminal-output-design` and `tui-design` skills.
  - Tapes run against a fixture daemon and scratch HOME (reuse `tests/cli_env.py` setup), fixed window size 100x30 and a dark theme; the script writes GIFs to a gitignored output directory; capture is manual and not part of CI.
  - Guard: an AST test fails when `wisp/cli/*.py` calls `print(` outside `output.py`, `Ctx.emit` and an explicit allow-list (the existing places that stream NDJSON), and when any human-view string contains `—`.
- **Test scenarios:**
  - Guard fails on a synthetic file with a raw `print`; passes on the repo.
  - Tape files reference only commands that exist in `wispd --help`.
- **Verification:** `scripts/ui/tui_capture.sh` produces three captures from a clean checkout on a machine with VHS installed; the guard is green.

## Risks and Mitigations

- **Glyph policy collides with existing tests and copy rules.** Mitigated by KTD3: words always, glyphs optional and allow-listed, one explicit test amendment in U6, and an easy opt-out.
- **Golden churn hides regressions.** Goldens are plain text, fixed width, reviewed in each PR; piped compatibility is protected by the existing transcript goldens (KTD4).
- **TUI parity with the QML app drifts.** Only the draw layer changes; parity tests stay in the gate for PR6 to PR8.
- **Installer wording is security-relevant.** U5 reformats only; a diff review checks that every security claim survives, and `--inspect-source` stays byte-identical.
- **Terminal differences.** Width and color decisions are per stream and tested against environment variables; real terminals are checked through the VHS captures and a manual pass in the Omarchy terminal.
- **Scope creep into behavior.** Any change to exit codes, JSON keys or daemon behavior is out of scope; additive JSON keys only.

## Open Questions

- Resolve before U1 merges: glyphs on (allow-list, default) or ASCII only (KTD3).
- Resolve before U7: whether the status view should show the little wordmark in a TUI corner or keep the plain `wisp  <state>` header.
- Deferred to implementation: exact priority order of footer hints per view; exact text of the `fix:` line splitting for rows whose fix is embedded in free text.

## Sources and References

- Upstream guidance this plan applies: `clig.dev` (cli-guidelines), the Heroku CLI style guide, `no-color.org`; the `terminal-output-design` and `tui-design` skills proposed for `luke-agents`.
- Visual references: `derailed/k9s`, `charmbracelet/crush`, `jesseduffield/lazygit`, `tstack/lnav`, `aristocratos/btop`, `darrenburns/posting`.
- Repo evidence: `wisp/cli/output.py`, `wisp/cli/diagnose.py`, `wisp/cli/registry.py`, `wisp/cli/settings.py`, `wisp/cli/strings.py`, `wisp/tui.py`, `wisp/copy.py`, `tests/test_tui_render.py`, `tests/test_cli.py`, `tests/cli_env.py`, `tests/golden/`.
