#!/usr/bin/env bash
# Stand-alone best-effort decryptor for a finished export
# Scans OUT/assets/**, consults DB message_attachments for keys,
# and tries AES-256-GCM (nonce|ct|tag) then AES-256-CBC (iv|ct).
#
# Usage:
#   DB="signal_plain.sqlite" OUT="signal_export_html" ./scripts/decrypt_assets.sh
#
# Optional:
#   OPENSSL_BIN="/opt/homebrew/opt/openssl@3/bin/openssl"  # custom OpenSSL
#   LIMIT=1000  # only attempt first N suspicious files (speed)

set -euo pipefail

DB="${DB:-signal_plain.sqlite}"
OUT="${OUT:-signal_export_html}"
OPENSSL_BIN="${OPENSSL_BIN:-openssl}"
LIMIT="${LIMIT:-0}"

if [[ ! -f "$DB" ]]; then
  echo "DB not found: $DB" >&2; exit 1
fi
if [[ ! -d "$OUT/assets" ]]; then
  echo "No assets folder under OUT: $OUT/assets" >&2; exit 1
fi

# Create an audit output
AUDIT="${OUT%/}/signal_attachment_audit.csv"
echo "path,was_encrypted,mode,preview_path,mime_guess,error" > "$AUDIT"

DB="$DB" OUT="$OUT" OPENSSL_BIN="$OPENSSL_BIN" LIMIT="$LIMIT" \
python3 tools/decrypt_assets.py "$AUDIT"

echo "✅ Decrypt audit written: $AUDIT"