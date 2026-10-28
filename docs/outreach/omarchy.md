# Omarchy outreach drafts

Drafts only. **Nothing here has been sent, posted or submitted**, and the repo
holds no webhook, token or send script for any of these channels
(`tests/test_outreach_docs.py` enforces that). Each draft is for the owner to
read, change and send by hand.

Every claim in a draft carries a fact tag like `[F3]`. The table below says
where that fact is proven (a repo file, a test, or a dated external page).
Features that are not on `master` yet are not named anywhere in this file; the
test keeps a list of them and fails if a draft mentions one. Superlatives
("best", "fastest", "first", "only") are banned unless a source line is added
here.

## Facts

| tag | fact | proof |
|---|---|---|
| F1 | Hold `Super+D`, speak, release to send | [README](../../README.md#using-it) |
| F2 | Speech is transcribed locally by default | [README privacy](../../README.md#privacy) |
| F3 | Wisp answers with the screenshot taken at the key press, and a `[POINT]` reply flies a cursor buddy to the thing it means | [README](../../README.md#using-it), [`wisp/points.py`](../../wisp/points.py) |
| F4 | You can draw on the screen while you hold the key and the strokes ride into the question | [`wisp/scribble.py`](../../wisp/scribble.py), [`tests/test_scribble.py`](../../tests/test_scribble.py) |
| F5 | On an Omarchy machine, questions about Omarchy are answered from that machine's own install: version, theme, the key bindings as rebound, and the `omarchy` command list; it never runs a package command | [`wisp/omarchy_tutor.py`](../../wisp/omarchy_tutor.py), [`tests/test_omarchy_skills.py`](../../tests/test_omarchy_skills.py) |
| F6 | Risky actions ask first; `Esc` stops a turn | [README](../../README.md#using-it), [`wisp/confirm.py`](../../wisp/confirm.py) |
| F7 | Model spend goes in one ledger with daily and monthly caps (`wispd spend`) | [README](../../README.md#spend), [`wisp/ledger.py`](../../wisp/ledger.py) |
| F8 | It can run on local OpenAI-compatible servers (llama.cpp, Ollama, LM Studio) | [README](../../README.md#local-models) |
| F9 | A background helper can take a long job and report back by voice | [README](../../README.md#using-it) |
| F10 | `wispd install` writes files, the shell plugin, a unit, a desktop entry and a bind; the Omarchy plugin form installs through a plan the user confirms | [README](../../README.md#install), [`docs/INSTALL.md`](../INSTALL.md), [`tests/test_plugin_mirror.py`](../../tests/test_plugin_mirror.py) |
| F11 | Removal: `omarchy plugin remove io.github.duketopceo.wisp` and `wispd uninstall` | [`scripts/plugin_mirror.py`](../../scripts/plugin_mirror.py) |
| F12 | Linux (Omarchy / Hyprland) is the only supported platform; v0.9 is shipped and v1.0 is a verification milestone | [README status](../../README.md) |
| F13 | It needs whisper.cpp with a model, `hyprctl` and `notify-send`; a cloud brain needs a provider key | [README install](../../README.md#install) |
| F14 | Screenshots go to the model only for the turn that needs them, and stay local with `screenshots = "false"` or a local brain | [README privacy](../../README.md#privacy) |
| F15 | The license is AGPL-3.0 (releases up to v0.9.0 were MIT) | [README license](../../README.md#license), [`LICENSE`](../../LICENSE) |
| F16 | Omarchy voice plugins already in the marketplace: omarchy-voice (213 stars), Jarvis, omavoice, O.M.A., omarchy-hermes-companion (read 2026-10-28) | [plan, second scrub](../plans/2026-10-27-feat-wisp-beat-competitors-plan.md) |
| F17 | The first plugin competition closed 2026-08-24 and was decided 2026-08-28; more were announced with no date | [Omarchy news, 2026-08-19](https://omarchy.org/news/2026/08/the-first-plugin-competition/), [winners, 2026-08-28](https://omarchy.org/news/2026/08/the-first-plugin-competition-winners/) (read 2026-10-28) |
| F18 | Omarchy Rangers is an official help team; applications go to rangers@omarchy.org | [Omarchy news, 2026-08-27](https://omarchy.org/news/2026/08/introducing-the-omarchy-rangers/) (read 2026-10-28) |
| F19 | Meetups are community-run, listed on the Omarchy Luma calendar, and may not become a sales pitch; Omarchy Northern Utah is listed for Nov 10 | [Meetups](https://omarchy.org/meetups/), [rules](https://omarchy.org/news/2026/08/omarchy-meetups-around-the-world/) (read 2026-10-28) |
| F20 | The marketplace asks for a public repo with a root `manifest.json`, a README with install and removal, a license, a unique id outside `omarchy.*`; approval is not a security review | [SUBMISSION.md](https://github.com/omacom/omarchy-plugin-marketplace/blob/master/SUBMISSION.md) (read 2026-10-28) |

## 1. Marketplace submission issue

**Do not open this until** (a) the mirror repo `duketopceo/wisp-plugin` is
public and built from a release tag with `scripts/plugin_mirror.py` (the
release workflow attaches the tree), (b) the marketplace has been searched for
the id `io.github.duketopceo.wisp`, and (c) the owner has read and confirmed
every checklist line, including that he owns the plugin and its preview
assets. The marketplace guide asks that the completed title and body are shown
to the owner and only then created. [F20]

Open with (title `[Plugin]: Wisp`):

```sh
gh issue create --repo omacom/omarchy-plugin-marketplace \
  --title "[Plugin]: Wisp" --body-file /tmp/omarchy-plugin-submission.md
```

Body, headings and checklist text exactly as the guide gives them:

```markdown
### Repository URL

https://github.com/duketopceo/wisp-plugin

### Category

Productivity

### Tags

ai, hyprland, education

### Suggest a missing tag

_No response_

### Maintainer notes

Wisp is a voice assistant for Omarchy: hold Super+D, speak, and it answers with your screen as context and can point at the thing it means. This repo is a release-built, plugin-only mirror of https://github.com/duketopceo/wisp (the source of truth). The bar widget and overlay are QML only; the daemon (wispd, Python) is installed by `wispd install` after it prints every file it will touch and asks, and the Install flow adds one push-to-talk bind to bindings.lua only after consent. License: AGPL-3.0 (see LICENSE). External dependencies: whisper.cpp with a model, hyprctl, notify-send; a cloud model key is optional (local models work). Linux/Omarchy only.

### Submission checklist

- [x] The repository is public and contains installation and removal instructions.
- [x] I have documented the plugin license and any external dependencies.
- [x] I confirm that I own or have permission to submit this plugin and its preview assets.
- [x] The plugin does not overwrite user configuration without explicit consent.
- [x] I understand that approval is for listing and is not a security review.
```

Facts behind it: category and tags are from the guide's allowed lists [F20];
consent-first install [F10]; removal [F11]; license [F15]; dependencies [F13];
platform [F12]. The preview image is `preview.png` made from the README
renders. The `[x]` boxes are the owner's statements to make, not mine.

## 2. Post for the Omarchy community

> **Wisp: hold Super+D, ask your Omarchy a question out loud, and it answers with your screen in view.** [F1][F3]
>
> It can point at the thing it means, take a drawn circle as part of the question, and answer Omarchy questions from your own install (your version, your theme, your key bindings as you rebound them) instead of from a manual. [F3][F4][F5] Risky actions ask first. [F6]
>
> Install: `omarchy plugin add https://github.com/duketopceo/wisp-plugin --enable`, then follow the plan it prints before it touches anything. [F10] Remove it with `omarchy plugin remove io.github.duketopceo.wisp` and `wispd uninstall`. [F11]
>
> Honest limits: Omarchy/Hyprland only, v0.9 so expect rough edges, it needs whisper.cpp and a model, and a cloud brain needs a key (local models work). [F12][F13][F8] With a cloud brain your screenshot goes to that provider for the turn that needs it; `screenshots = "false"` or a local brain keeps it on the machine. [F14] AGPL-3.0. [F15]
>
> There are already voice plugins in the marketplace (omarchy-voice, Jarvis, omavoice and others). [F16] Wisp's angle is the screen: it sees what you see and teaches by pointing. Feedback and bug reports welcome.

Attach the README hero clip once one has been recorded (`docs/MEDIA.md`).

## 3. Plugin competition and Rangers

**Competition.** The one that ran in August is over [F17]; there is nothing to enter. Draft
for when a new one is announced (replace the bracket with the real rules and
date): *Wisp enters [competition name]. It is a voice teacher for Omarchy that
points at your screen, installable with one line. [F1][F3][F10] Source and
tests are public. [F15]*

**Rangers.** Applications go to rangers@omarchy.org. [F18] Draft, to be sent
only if the owner wants to help new users himself (the Rangers help people,
they do not promote tools):

> Subject: Rangers application
>
> Hi, I use Omarchy daily and build a voice helper for it called Wisp. I would like to help new people find their way: [one sentence of your own on why]. I will not use the role to promote my plugin. [Your timezone and hours.]

## 4. Meetup lightning talk (5 minutes)

Meetups may not become a sales pitch, so this shows a setup, not a product. [F19]

1. 0:00 Show the thing you use daily: hold the key, ask "where do I change X on my setup", it points. [F1][F3]
2. 1:00 Show it reading your own rebinds: ask for the key that opens the Omarchy menu after you changed it. [F5]
3. 2:00 Draw a circle on something you do not understand and ask. [F4]
4. 3:00 What it costs: run `wispd spend`, show a real day. [F7]
5. 4:00 Limits and what is rough, then how to install and remove it. [F10][F11][F12]
6. 4:45 Ask the room what they would want it to teach.

Omarchy Northern Utah is listed for Nov 10 (Syracuse, UT). [F19]

## 5. Reply template for existing voice-plugin threads

Generous, not a pitch. Use only where someone is asking for help with voice on
Omarchy and only after reading the thread.

> I have been using [their plugin] too and liked [one specific thing you actually checked]. I work on a different take, Wisp, which is more about looking at your screen and pointing at things; if that is useful for what you are doing it is at https://github.com/duketopceo/wisp-plugin. Happy to compare notes on latency and hold-to-talk, and to link yours from the README if you want that.

Do not name a feature the other plugin lacks unless you have tried it. [F16]
