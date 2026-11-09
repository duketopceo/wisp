# App skill targets

Wisp teaches apps from short skill files in `wisp/skills_seed/apps/<name>/SKILL.md`
(companion core plan U9, KTD7). Desktop apps match by `app_classes`, web apps
by `url_hosts`; one skill may carry both when the app ships on both. HeyClicky
claims teaching coverage for about 89 apps; this list sets Wisp's own target at
**89 skills**, ordered Linux desktop first, then the web apps people use most,
then the rest of HeyClicky's kind of coverage where it fits Linux or is cheap.

Rules for every entry:

- One skill per app. No two skills claim the same window class or host.
  Google's editors share `docs.google.com`, so they are one skill.
- Each skill ships one synthetic teach case in `tests/fixtures/teach/`, drawn
  by `scripts/gen_teach_fixtures.py`, whose recorded reply the teach-case
  scorer marks correct.
- Teaching notes stay within the guide cap in `tests/test_teaching_guides.py`.
- Shortcuts are the app's documented defaults, never a personal setup.

## Shipped (17)

1password, blender, chromium, firefox, gimp, github, hyprland, kitty,
libreoffice, nautilus, nvim, obsidian, omarchy-settings, spotify, steam,
thunderbird, vscode

## Batch 1: Linux desktop essentials (10)

| Skill | Matches |
|---|---|
| alacritty | class `alacritty` |
| ghostty | class `com.mitchellh.ghostty` |
| gnome-terminal | class `org.gnome.terminal` |
| konsole | class `org.kde.konsole` |
| dolphin | class `org.kde.dolphin` |
| thunar | class `thunar` |
| vlc | class `vlc` |
| mpv | class `mpv` |
| evince | class `org.gnome.evince`, `org.gnome.papers` |
| gnome-text-editor | class `org.gnome.texteditor`, `gedit` |

## Batch 2: Linux creative and media (10)

| Skill | Matches |
|---|---|
| inkscape | class `org.inkscape.inkscape` |
| krita | class `krita` |
| kdenlive | class `org.kde.kdenlive` |
| obs-studio | class `com.obsproject.studio` |
| audacity | class `audacity` |
| darktable | class `darktable` |
| shotcut | class `org.shotcut.shotcut` |
| okular | class `org.kde.okular` |
| calibre | class `calibre-gui` |
| flameshot | class `flameshot` |

## Batch 3: developer tools (10)

| Skill | Matches |
|---|---|
| zed | class `dev.zed.zed` |
| sublime-text | class `sublime_text` |
| intellij-idea | class `jetbrains-idea`, `jetbrains-idea-ce` |
| emacs | class `emacs` |
| kate | class `org.kde.kate` |
| postman | class `postman` |
| dbeaver | class `dbeaver` |
| virt-manager | class `virt-manager` |
| gitlab | host `gitlab.com` |
| stack-overflow | host `stackoverflow.com` |

## Batch 4: chat and calls (10)

| Skill | Matches |
|---|---|
| slack | class `slack`, host `app.slack.com` |
| discord | class `discord`, host `discord.com` |
| signal | class `signal` |
| telegram | class `org.telegram.desktop`, host `web.telegram.org` |
| element | class `element`, host `app.element.io` |
| zoom | class `zoom`, host `zoom.us` |
| google-meet | host `meet.google.com` |
| microsoft-teams | host `teams.microsoft.com` |
| whatsapp-web | host `web.whatsapp.com` |
| gmail | host `mail.google.com` |

## Batch 5: documents and storage on the web (10)

| Skill | Matches |
|---|---|
| google-docs-editors | host `docs.google.com` |
| google-drive | host `drive.google.com` |
| google-calendar | host `calendar.google.com` |
| outlook-web | host `outlook.office.com`, `outlook.live.com` |
| office-web | host `www.office.com`, `onedrive.live.com` |
| dropbox | host `dropbox.com` |
| notion | host `notion.so` |
| overleaf | host `overleaf.com` |
| zotero | class `zotero` |
| joplin | class `joplin` |

## Batch 6: work trackers and design (10)

| Skill | Matches |
|---|---|
| linear | host `linear.app` |
| jira | host `atlassian.net` |
| trello | host `trello.com` |
| asana | host `app.asana.com` |
| airtable | host `airtable.com` |
| figma | host `figma.com` |
| canva | host `canva.com` |
| miro | host `miro.com` |
| excalidraw | host `excalidraw.com` |
| clickup | host `app.clickup.com` |

## Batch 7: everyday web (12)

| Skill | Matches |
|---|---|
| youtube | host `youtube.com` |
| google-search | host `google.com` |
| google-maps | host `maps.google.com` |
| wikipedia | host `wikipedia.org` |
| reddit | host `reddit.com` |
| x | host `x.com` |
| linkedin | host `linkedin.com` |
| amazon | host `amazon.com` |
| chatgpt | host `chatgpt.com` |
| claude | host `claude.ai` |
| bitwarden | class `bitwarden`, host `vault.bitwarden.com` |
| keepassxc | class `org.keepassxc.keepassxc` |

Batches 1 to 7 add 72 skills; with the 17 shipped that is **89**.

## Not planned now

Apps HeyClicky covers that are macOS-only (Finder, Xcode, Final Cut Pro,
Logic Pro, Pages, Keynote, Numbers, Safari, Apple Notes) wait for the macOS
port. Paid niche suites without a Linux build are left out unless they are
cheap to add later.
