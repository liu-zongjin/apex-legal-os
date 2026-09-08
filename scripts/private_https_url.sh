#!/bin/bash
set -euo pipefail

find_tailscale() {
  for candidate in \
    "${LEGAL_KB_TAILSCALE_BIN:-}" \
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale" \
    "/opt/homebrew/bin/tailscale" \
    "/usr/local/bin/tailscale" \
    "$(command -v tailscale 2>/dev/null || true)"
  do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! TAILSCALE_BIN="$(find_tailscale)"; then
  printf 'Tailscale CLI not found. Install and sign in to Tailscale first.\n' >&2
  exit 1
fi

DNS_NAME="$("$TAILSCALE_BIN" status --json | python3 -c '
import json, sys
name = str(json.load(sys.stdin).get("Self", {}).get("DNSName", "")).rstrip(".")
if not name.endswith(".ts.net"):
    raise SystemExit(1)
print(name)
')" || {
  printf "Could not determine this Mac's Tailscale HTTPS name. Enable MagicDNS and sign in to Tailscale.\n" >&2
  exit 1
}

printf 'https://%s\n' "$DNS_NAME"
