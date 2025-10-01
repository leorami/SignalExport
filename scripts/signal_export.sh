#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Signal Desktop → Plain SQLite → HTML Conversation Export (macOS)
# Uses Python cross-platform CLI for the HTML build step.
# - Reads .env if present (KEY=VALUE) to set DB, SRC, OUT/HTML_OUT, DB_OUT, OPENSSL_BIN
# - Computes defaults using $HOME (falls back to project directory)
# ------------------------------------------------------------------------------
set -euo pipefail

# Move to repo root if invoked from scripts/ directory
cd "$(dirname "$0")/.."

# ---------- Load .env (if present) ----------
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env || true
  set +a
fi

# ---------- HOME fallback ----------
if [ -z "${HOME:-}" ]; then
  export HOME="$(pwd)"
fi

# ---------- Defaults (overridable via environment) ----------
DB_OUT="${DB_OUT:-"$HOME/.artifacts"}"
HTML_OUT="${HTML_OUT:-"$HOME/.artifacts/signal_export_html"}"
DB="${DB:-"$DB_OUT/signal_plain.sqlite"}"
SRC_DEFAULT="$HOME/Library/Application Support/Signal/attachments.noindex"
SRC="${SRC:-$SRC_DEFAULT}"
OPENSSL_BIN="${OPENSSL_BIN:-}"

# Ensure output roots exist
mkdir -p "$DB_OUT" "$HTML_OUT"

# ---------- Close Signal to avoid file locks ----------
pkill -x Signal >/dev/null 2>&1 || true
sleep 1

# ---------- Ensure Homebrew + signalbackup-tools ----------
if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: Homebrew not found. Install from https://brew.sh" >&2
  exit 1
fi

if ! command -v signalbackup-tools >/dev/null 2>&1; then
  brew tap bepaald/signalbackup-tools https://github.com/bepaald/signalbackup-tools
  brew install --HEAD signalbackup-tools
fi

# ---------- Decrypt (rotate existing DB, then overwrite) ----------
mkdir -p "$(dirname "$DB")"

if [ -f "$DB" ]; then
  ts="$(date +%Y%m%d-%H%M%S)"
  mv "$DB" "${DB%.sqlite}_$ts.sqlite"
  echo "→ Rotated previous DB to ${DB%.sqlite}_$ts.sqlite"
fi

echo "→ Decrypting Signal Desktop DB"
signalbackup-tools --dumpdesktopdb "$DB" --overwrite

# Verify minimal schema exists
if ! sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE name='conversations' LIMIT 1" >/dev/null; then
  echo "ERROR: Decrypted DB missing 'conversations' table. Aborting." >&2
  exit 1
fi

# ---------- Prepare HTML output directory ----------
rm -rf "$HTML_OUT"
mkdir -p "$HTML_OUT"

# ---------- Export HTML (Python CLI) ----------
echo "→ Building HTML export (avatars, attachments, calls)"
if command -v signal-export >/dev/null 2>&1; then
  signal-export --db "$DB" --src "$SRC" --out "$HTML_OUT" ${OPENSSL_BIN:+--openssl "$OPENSSL_BIN"}
else
  PYTHONPATH="$(pwd)/src${PYTHONPATH:+":$PYTHONPATH"}" \
  python3 -m signal_export.cli --db "$DB" --src "$SRC" --out "$HTML_OUT" ${OPENSSL_BIN:+--openssl "$OPENSSL_BIN"}
fi

echo "→ Done. Open: $HTML_OUT/index.html"
open "$HTML_OUT/index.html" 2>/dev/null || true
