#!/usr/bin/env python3
"""
Best-effort decryption of exported Signal Desktop attachments.

- Reads message_attachments from the plain SQLite DB to collect keys.
- Scans OUT/assets/** and flags likely-encrypted blobs using:
  * no known magic header
  * high Shannon entropy (> 7.4 bits/byte)
  * "application/octet-stream" guess by extension
- Tries AES-256-GCM (nonce|ct|tag) then AES-256-CBC (iv|ct) using OpenSSL CLI.
- If successful, writes dec_<name> alongside the original and reports it.
- Produces an audit CSV (path, encrypted?, mode, preview_path, mime, error).

This is meant to be safe to run repeatedly.
"""

from __future__ import annotations
import base64, math, mimetypes, os, sqlite3, subprocess, sys
from pathlib import Path
from typing import Dict, Optional, Tuple

DB   = Path(os.environ["DB"])
OUT  = Path(os.environ["OUT"])
ASSETS = OUT / "assets"
OPENSSL = os.environ.get("OPENSSL_BIN", "openssl")
LIMIT = int(os.environ.get("LIMIT", "0"))

def entropy(b: bytes) -> float:
    if not b: return 0.0
    hist = [0]*256
    for x in b: hist[x]+=1
    total = len(b)
    return -sum((c/total)*math.log2(c/total) for c in hist if c)

def guess_mime(p: Path) -> str:
    m, _ = mimetypes.guess_type(p.name)
    if not m:
        head = p.read_bytes()[:16]
        if head.startswith(b"\x89PNG"): return "image/png"
        if head.startswith(b"\xFF\xD8\xFF"): return "image/jpeg"
        if head[:6] in (b"GIF87a", b"GIF89a"): return "image/gif"
        if head.startswith(b"RIFF") and b"WEBP" in head: return "image/webp"
        if head.startswith(b"%PDF"): return "application/pdf"
    return m or "application/octet-stream"

def looks_encrypted(p: Path) -> bool:
    try:
        b = p.read_bytes()[:4096]
        if not b: return False
        if b.startswith((b"\x89PNG", b"\xFF\xD8\xFF", b"%PDF")) or b[:6] in (b"GIF87a", b"GIF89a"):
            return False
        return (guess_mime(p) == "application/octet-stream") and (entropy(b) > 7.4)
    except Exception:
        return False

def b642bytes(s: Optional[str]) -> Optional[bytes]:
    if not s: return None
    s = s.strip()
    for pad in ("", "=", "=="):
        try:
            b = base64.b64decode(s + pad, validate=False)
            if b: return b
        except Exception:
            pass
    return None

def hex2bytes(s: Optional[str]) -> Optional[bytes]:
    if not s: return None
    try:
        return bytes.fromhex(s.strip())
    except Exception:
        return None

def openssl_ok() -> bool:
    try:
        subprocess.run([OPENSSL, "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def try_gcm(src: Path, dst: Path, key32: bytes) -> bool:
    data = src.read_bytes()
    if len(data) < 28: return False
    iv = data[:12].hex()
    tag = data[-16:].hex()
    ct = data[12:-16]
    p = subprocess.run([OPENSSL, "enc", "-aes-256-gcm", "-d",
                        "-K", key32.hex(), "-iv", iv, "-tag", tag, "-nosalt"],
                       input=ct, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0 and p.stdout:
        dst.write_bytes(p.stdout); return True
    return False

def try_cbc(src: Path, dst: Path, key32: bytes) -> bool:
    data = src.read_bytes()
    if len(data) < 32: return False
    iv = data[:16].hex()
    ct = data[16:]
    p = subprocess.run([OPENSSL, "enc", "-aes-256-cbc", "-d",
                        "-K", key32.hex(), "-iv", iv],
                       input=ct, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 0 and p.stdout:
        dst.write_bytes(p.stdout); return True
    return False

def best_key(row: sqlite3.Row) -> Optional[bytes]:
    # Prefer localKey (usually base64), then key (sometimes hex/base64)
    for field in ("localKey", "key"):
        v = row[field] if field in row.keys() else None
        if not v: continue
        b = b642bytes(v) or hex2bytes(v)
        if b and len(b) >= 32:
            return b[:32]
    return None

def main(audit_path: str):
    if not openssl_ok():
        print("OpenSSL not found/usable (OPENSSL_BIN). Exiting.", file=sys.stderr)
        sys.exit(1)

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Map rel path -> key material
    cur.execute("PRAGMA table_info(message_attachments)")
    cols = {r["name"] for r in cur.fetchall()}
    sel_local = "localKey" if "localKey" in cols else "NULL AS localKey"
    sel_key   = "key"      if "key"      in cols else "NULL AS key"

    cur.execute(f"""
      SELECT fileName, path, {sel_local}, {sel_key}, contentType
      FROM message_attachments
      WHERE path IS NOT NULL
    """)
    key_by_rel: Dict[str, sqlite3.Row] = {}
    for r in cur.fetchall():
        key_by_rel[r["path"]] = r

    assets = sorted([p for p in ASSETS.rglob("*") if p.is_file()])
    count = 0
    attempted = 0

    with open(audit_path, "a", encoding="utf-8") as audit:
        for f in assets:
            # Only consider likely encrypted (fast skip)
            if not looks_encrypted(f):
                audit.write(f"{f.relative_to(OUT)},{0},,," f"{guess_mime(f)},\n")
                continue

            # Map back to DB rel path (assets/<thread>/<hash>_<name>) → raw rel? We only
            # know the original on build; fall back to basename search in key map.
            db_row = None
            # Try exact rel from original (stored as suffix in the filename)
            # else, fallback: find any row with matching fileName
            name = f.name.split("_", 1)[-1] if "_" in f.name else f.name
            for r in key_by_rel.values():
                if r["fileName"] == name:
                    db_row = r; break

            if not db_row:
                audit.write(f"{f.relative_to(OUT)},{1},,," f"{guess_mime(f)},no-db-row\n")
                continue

            key = best_key(db_row)
            if not key:
                audit.write(f"{f.relative_to(OUT)},{1},,," f"{guess_mime(f)},no-key\n")
                continue

            # Respect LIMIT if set
            if LIMIT and attempted >= LIMIT:
                audit.write(f"{f.relative_to(OUT)},{1},,," f"{guess_mime(f)},limit-reached\n")
                continue

            attempted += 1
            dst = f.with_name("dec_" + name)

            mode = ""
            ok = try_gcm(f, dst, key)
            if ok:
                mode = "gcm"
            else:
                ok = try_cbc(f, dst, key)
                if ok: mode = "cbc"

            if ok:
                audit.write(f"{f.relative_to(OUT)},{1},{mode},{dst.relative_to(OUT)},{guess_mime(dst)},\n")
            else:
                audit.write(f"{f.relative_to(OUT)},{1},,," f"{guess_mime(f)},decrypt-failed\n")

            count += 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: decrypt_assets.py <audit_csv_out>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])