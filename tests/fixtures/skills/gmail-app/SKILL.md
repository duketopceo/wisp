---
name: gmail-app
description: Gmail web UI — inbox, compose, search, settings. Use for "in Gmail" asks; not for Calendar, Drive or Docs.
url_hosts: mail.google.com
asks: How do I reply to this thread; Where are my filters; How do I search my mail
tier: safe
provenance: authored from wisp screen captures 2026-10-28 (7 screens)
draft: first-run (unverified)
---
# gmail-app

## Overview

Gmail's web app. Most asks are: read/find mail, reply or compose, and
tweak settings (filters, labels, forwarding).

## Screens

- Inbox — left rail (Compose, labels, categories), conversation list
  center, search bar top-center.
- Search results — same chrome; result list replaces the inbox; search
  operators in the box.
- Label view — a label selected in the left rail scopes the list.
- Sent — sent label view.
- Settings / General — full-page settings, tab bar across the top
  (General, Labels, Accounts, Filters and Blocked Addresses, …).
- Filters and Blocked Addresses — list of filters + "Create a new
  filter" link.
- Compose — bottom-right overlay window: To/Cc/Bcc, Subject, body,
  formatting toolbar, Send button top-left of the window.

## Controls

- Compose — top of left rail — opens the compose overlay.
- Search box — top center — query + Enter; supports operators
  (`from:`, `has:attachment`, `is:unread`, `after:YYYY/MM/DD`).
- Gear icon — top right — quick settings panel; "See all settings"
  opens the full settings page.
- Left rail labels — each scopes the conversation list.
- Reply arrows — bottom of an open thread — reply vs reply-all.
- Send — top-left of compose window — sends immediately, no confirm.

## Workflows

1. Reply in a thread: open the thread → scroll to the last message →
   click the reply area → type → Send.
2. Compose new: Compose (left rail) → fill To / Subject / body → Send.
3. Search: click the search box → type query or operators → Enter.
4. Create a filter: Gear → See all settings → "Filters and Blocked
   Addresses" tab → "Create a new filter" → criteria → "Create filter".

## Tools

- none known in wisp's toolbelt — Google Workspace APIs (gmail.readonly
  etc.) are the natural API lane if one gets wired.

## Verify before done

- After creating a draft or reply, reopen the thread and confirm the
  draft banner/body is actually there. Say "drafted", not "sent".
- After changing a setting, reload the settings tab and confirm the
  value stuck.
- Send is irreversible — treat anything about to Send as needing the
  user's explicit go-ahead.

## Gotchas

- `before:` in search is exclusive and dates count in UTC — local-day
  searches can look off by one.
- Filters page hides behind the settings tab bar — easy to miss the
  "Create a new filter" link at the list's bottom.
- unverified — needs a deeper capture: quick-settings panel contents,
  label creation flow, keyboard-shortcuts overlay (`?`).
