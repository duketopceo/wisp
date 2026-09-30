#!/bin/sh
# dayflow-bridge tool — read-only dayflow queries, allowlisted.
set -eu
cmd="${1:-today}"; shift 2>/dev/null || true
case "$cmd" in
  today)     exec dayflow today --json ;;
  timeline)  exec dayflow timeline --json "${1:-}" ;;
  day)       exec dayflow day "${1:?needs YYYY-MM-DD}" --json ;;
  status)    exec dayflow status --json ;;
  insights)  exec dayflow insights --json 2>/dev/null || dayflow today --json ;;
  agents)    exec dayflow agents "${1:-}" --json ;;
  search)    exec dayflow timeline --json | grep -i "${*:-}" || true ;;
  *) echo "REFUSED (allowed: today|timeline|day|status|insights|agents|search)"; exit 2 ;;
esac
