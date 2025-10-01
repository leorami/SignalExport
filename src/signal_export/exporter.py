from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import mimetypes
import shutil
import sqlite3
import subprocess
import sys
import time
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from importlib import resources as importlib_resources

from .utils import safe, first_name, looks_unknown


ICON_MAP = {
    "image":   "🖼️",
    "video":   "🎞️",
    "audio":   "🎵",
    "pdf":     "📄",
    "zip":     "🗜️",
    "text":    "📄",
    "word":    "📝",
    "excel":   "📊",
    "ppt":     "📽️",
    "binary":  "📦",
    "unknown": "📁",
}


def icon_for_mime(mtype: str) -> str:
    if not mtype: return ICON_MAP["unknown"]
    if mtype.startswith("image/"): return ICON_MAP["image"]
    if mtype.startswith("video/"): return ICON_MAP["video"]
    if mtype.startswith("audio/"): return ICON_MAP["audio"]
    if mtype == "application/pdf": return ICON_MAP["pdf"]
    if mtype in {"application/zip","application/x-7z-compressed","application/x-rar-compressed"}: return ICON_MAP["zip"]
    if mtype.startswith("text/"): return ICON_MAP["text"]
    if mtype in {"application/msword","application/vnd.openxmlformats-officedocument.wordprocessingml.document"}: return ICON_MAP["word"]
    if mtype in {"application/vnd.ms-excel","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}: return ICON_MAP["excel"]
    if mtype in {"application/vnd.ms-powerpoint","application/vnd.openxmlformats-officedocument.presentationml.presentation"}: return ICON_MAP["ppt"]
    return ICON_MAP["binary"]


def guess_mime(path: Path, fallback_name: str = "") -> str:
    name = path.name if path else fallback_name
    mtype, _ = mimetypes.guess_type(name)
    if not mtype and path and path.exists():
        try:
            head = path.read_bytes()[:16]
            if head.startswith(b"\x89PNG"): return "image/png"
            if head.startswith(b"\xFF\xD8\xFF"): return "image/jpeg"
            if head[:6] in (b"GIF87a", b"GIF89a"): return "image/gif"
            if head.startswith(b"RIFF") and b"WEBP" in head: return "image/webp"
            if head.startswith(b"%PDF"): return "application/pdf"
        except Exception:
            pass
    return mtype or "application/octet-stream"


def byte_entropy(b: bytes) -> float:
    if not b: return 0.0
    hist = [0]*256
    for x in b: hist[x]+=1
    total = len(b)
    return -sum((c/total)*math.log2(c/total) for c in hist if c)


def likely_encrypted_file(path: Path) -> bool:
    if not path or not path.exists(): return False
    try:
        b = path.read_bytes()[:4096]
        if not b: return False
        if b.startswith((b"\x89PNG", b"\xFF\xD8\xFF", b"%PDF")) or b[:6] in (b"GIF87a", b"GIF89a"):
            return False
        m = guess_mime(path)
        return (m == "application/octet-stream") and (byte_entropy(b) > 7.4)
    except Exception:
        return False


def b64_or_hex_to_bytes(s: Optional[str]) -> Optional[bytes]:
    if not s: return None
    s = s.strip()
    try:
        import base64
        for pad in ("", "=", "=="):
            try:
                out = base64.b64decode(s + pad, validate=False)
                if out:
                    return out
            except Exception:
                pass
    except Exception:
        pass
    try:
        return bytes.fromhex(s)
    except Exception:
        return None


def openssl_available(openssl_bin: str) -> bool:
    try:
        subprocess.run([openssl_bin, "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def try_decrypt_gcm(src: Path, dst: Path, key32: bytes, openssl_bin: str) -> bool:
    try:
        data = src.read_bytes()
        if len(data) < 28: return False
        nonce = data[:12].hex()
        tag   = data[-16:].hex()
        with open(dst, "wb") as w:
            p = subprocess.run(
                [openssl_bin, "enc", "-aes-256-gcm", "-d",
                 "-K", key32.hex(), "-iv", nonce, "-nosalt", "-nopad",
                 "-aad", "", "-tag", tag],
                input=data[12:-16],
                stdout=w, stderr=subprocess.DEVNULL
            )
        ok = (p.returncode == 0) and dst.exists() and dst.stat().st_size > 0
        if not ok and dst.exists(): dst.unlink(missing_ok=True)
        return ok
    except Exception:
        if dst.exists(): dst.unlink(missing_ok=True)
        return False


def try_decrypt_cbc(src: Path, dst: Path, key32: bytes, openssl_bin: str) -> bool:
    try:
        data = src.read_bytes()
        if len(data) < 32: return False
        iv_hex = data[:16].hex()
        with open(dst, "wb") as w:
            p = subprocess.run(
                [openssl_bin, "enc", "-aes-256-cbc", "-d",
                 "-K", key32.hex(), "-iv", iv_hex],
                input=data[16:],
                stdout=w, stderr=subprocess.DEVNULL
            )
        ok = (p.returncode == 0) and dst.exists() and dst.stat().st_size > 0
        if not ok and dst.exists(): dst.unlink(missing_ok=True)
        return ok
    except Exception:
        if dst.exists(): dst.unlink(missing_ok=True)
        return False


def best_effort_decrypt(src: Path, dest_dir: Path, name_hint: str,
                        local_key: Optional[str], key_alt: Optional[str],
                        openssl_bin: str) -> Optional[Path]:
    if not openssl_available(openssl_bin) or not src.exists():
        return None
    key_bytes = None
    for s in (local_key, key_alt):
        b = b64_or_hex_to_bytes(s) if s else None
        if b and len(b) >= 32:
            key_bytes = b[:32]; break
    if not key_bytes:
        return None
    dst = dest_dir / f"dec_{name_hint}"
    if try_decrypt_gcm(src, dst, key_bytes, openssl_bin) or try_decrypt_cbc(src, dst, key_bytes, openssl_bin):
        return dst
    return None


def _parse_avatar_info_from_json(js: str | None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    path = None
    key1 = None
    key2 = None
    if not js:
        return path, key1, key2
    try:
        obj = json.loads(js) if isinstance(js, str) else js
        for key in ("profileAvatarPath", "avatarPath", "profileAvatar"):
            v = obj.get(key)
            if isinstance(v, dict):
                for k2 in ("path", "avatarPath", "filePath"):
                    if isinstance(v.get(k2), str) and not path:
                        path = v[k2]
                for kk in ("localKey", "key", "profileKey", "attachmentKey", "keyMaterial"):
                    if isinstance(v.get(kk), str) and not key1:
                        key1 = v[kk]
            elif isinstance(v, str) and not path:
                path = v
        pa = obj.get("profileAvatar") or {}
        if isinstance(pa, dict):
            for k2 in ("path", "avatarPath", "filePath"):
                if isinstance(pa.get(k2), str) and not path:
                    path = pa[k2]
            for kk in ("localKey", "key", "profileKey", "attachmentKey", "keyMaterial"):
                if isinstance(pa.get(kk), str):
                    if not key1:
                        key1 = pa[kk]
                    elif not key2:
                        key2 = pa[kk]
    except Exception:
        pass
    return path, key1, key2


# ---------------- Progress helpers -----------------

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _fmt_time(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _progress(label: str, done: int, total: int, start_ts: float) -> None:
    width = shutil.get_terminal_size(fallback=(80, 20)).columns
    barw = max(10, min(40, width - 50))
    pct = int(100 * done / max(1, total))
    fill = int(barw * done / max(1, total))
    filled = "█" * fill
    unfilled = "░" * (barw - fill)

    # Signal blue (#3B45FD) as 24-bit ANSI if supported
    if _supports_color():
        BLUE = "\x1b[38;2;59;69;253m"
        RESET = "\x1b[0m"
        bar = f"{BLUE}{filled}{RESET}{unfilled}"
    else:
        bar = filled + unfilled

    elapsed = time.time() - start_ts
    rate = (done / elapsed) if elapsed > 0 else 0
    eta = ((total - done) / rate) if rate > 0 and total > 0 else 0
    msg = f"{label} [{bar}] {done}/{total} ({pct}%) | elapsed {_fmt_time(elapsed)} | eta {_fmt_time(eta)}"

    # Avoid slicing when colored to prevent breaking escape sequences
    out = "\r" + (msg if _supports_color() else msg[: width - 1])
    sys.stdout.write(out)
    sys.stdout.flush()


# ---------------------------------------------------

def run_export(db: str | Path, src: str | Path, out: str | Path,
               *, template: Optional[str | Path] = None,
               css: Optional[str | Path] = None,
               openssl: Optional[str] = None) -> Path:
    DB = Path(db)
    SRC = Path(src)
    OUT = Path(out)
    OPENSSL = openssl or "openssl"

    ASSETS = OUT / "assets"
    AVADIR = ASSETS / "avatars"
    ASSETS.mkdir(parents=True, exist_ok=True)
    AVADIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Conversations
    cur.execute("SELECT COUNT(1) FROM conversations")
    total_convs = cur.fetchone()[0] or 0
    start_av = time.time()
    _progress("Conversations", 0, total_convs, start_av)

    cur.execute("""
      SELECT id, json, name, profileFullName, profileName, e164, serviceId, type
      FROM conversations
    """)

    conv_name: Dict[str, str] = {}
    is_group:  Dict[str, bool] = {}
    by_e164:   Dict[str, str] = {}
    by_sid:    Dict[str, str] = {}
    conv_avatar_rel: Dict[str, str] = {}
    conv_avatar_enc: Dict[str, bool] = {}

    processed_conv = 0
    for row in cur.fetchall():
        processed_conv += 1
        if processed_conv == total_convs or processed_conv % 25 == 0:
            _progress("Conversations", processed_conv, total_convs, start_av)

        raw = (row["name"] or row["profileFullName"] or row["profileName"] or
               row["e164"] or row["serviceId"] or f"conv:{row['id']}")
        group_flag = (row["type"] or "").lower().startswith("group")
        display = raw if group_flag else (first_name(raw) or raw)
        conv_name[row["id"]] = display
        is_group[row["id"]] = group_flag
        if row["e164"]:     by_e164[row["e164"]] = first_name(raw) or display
        if row["serviceId"]: by_sid[row["serviceId"]] = first_name(raw) or display

        avatar_rel = None
        avatar_enc_fail = False
        avatar_path, ava_k1, ava_k2 = _parse_avatar_info_from_json(row["json"])
        if avatar_path:
            srcp = SRC / avatar_path
            if srcp.exists():
                base = safe(display)
                ext_guess = (srcp.suffix or ".jpg")[:8]
                dest = AVADIR / f"{base}{ext_guess}"
                try:
                    if not dest.exists():
                        shutil.copy2(srcp, dest)
                    m_before = guess_mime(dest, dest.name)
                    looks_enc = (m_before == "application/octet-stream") and likely_encrypted_file(dest)
                    if looks_enc:
                        dec = best_effort_decrypt(dest, AVADIR, f"{base}{ext_guess}", ava_k1, ava_k2, OPENSSL)
                        if dec and dec.exists():
                            avatar_rel = str(dec.relative_to(OUT))
                        else:
                            avatar_rel = str(dest.relative_to(OUT))
                            avatar_enc_fail = True
                    else:
                        avatar_rel = str(dest.relative_to(OUT))
                except Exception:
                    avatar_rel = None
                    avatar_enc_fail = True
        if avatar_rel:
            conv_avatar_rel[row["id"]] = avatar_rel
            if avatar_enc_fail:
                conv_avatar_enc[row["id"]] = True

    # newline after avatars progress
    sys.stdout.write("\n")

    def resolve_sender(identifier: str | None) -> str:
        if not identifier: return "other"
        if identifier in by_sid:  return by_sid[identifier]
        if identifier in by_e164: return by_e164[identifier]
        return first_name(identifier) or identifier

    # Messages + attachments
    cur.execute("SELECT COUNT(DISTINCT id) FROM messages")
    total_msgs = cur.fetchone()[0] or 0
    start_msg = time.time()
    _progress("Messages", 0, total_msgs, start_msg)

    cur.execute("PRAGMA table_info(message_attachments)")
    ma_cols = {r["name"] for r in cur.fetchall()}
    has_localKey    = "localKey"    in ma_cols
    has_key         = "key"         in ma_cols
    has_contentType = "contentType" in ma_cols

    select_local = "ma.localKey AS localKey"        if has_localKey    else "NULL AS localKey"
    select_key   = "ma.key AS key_alt"              if has_key         else "NULL AS key_alt"
    select_ct    = "ma.contentType AS contentType"  if has_contentType else "NULL AS contentType"

    cur.execute(f"""
    SELECT
      m.id                   AS mid,
      m.conversationId       AS cid,
      m.sent_at              AS sent_at,
      m.type                 AS mtype,
      m.source               AS msource,
      m.sourceServiceId      AS msource_service,
      m.isChangeCreatedByUs  AS is_me_change,
      m.body                 AS body,
      ma.fileName            AS fileName,
      ma.path                AS relPath,
      ma.orderInMessage      AS ord,
      {select_local},
      {select_key},
      {select_ct}
    FROM messages m
    LEFT JOIN message_attachments ma ON ma.messageId = m.id
    ORDER BY m.conversationId, m.sent_at, ma.orderInMessage
    """)

    threads: Dict[str, List[Dict[str, Any]]] = {}
    msg_index: Dict[str, Dict[str, Any]] = {}
    thread_avatar: Dict[str, str] = {}
    thread_avatar_enc: Dict[str, bool] = {}

    seen_msgs = 0
    for r in cur:
        label = safe(conv_name.get(r["cid"]) or f"conv:{r['cid']}")
        threads.setdefault(label, [])
        if label not in thread_avatar and r["cid"] in conv_avatar_rel:
            thread_avatar[label] = conv_avatar_rel[r["cid"]]
            if r["cid"] in conv_avatar_enc:
                thread_avatar_enc[label] = True

        mid = r["mid"]
        if mid not in msg_index:
            t = (r["mtype"] or "").lower()
            is_out = bool("out" in t or r["is_me_change"] == 1)
            sender = "me" if is_out else resolve_sender(r["msource_service"] or r["msource"] or "")

            body_raw = (r["body"] or "").strip()
            lb = body_raw.lower()
            
            # Primary detection: message type is call-history
            is_call_type = ("call" in t) or (t == "call-history")
            # Secondary detection: body content suggests call (more specific patterns)
            call_patterns = [
                "incoming call", "outgoing call", "missed call",
                "incoming voice call", "outgoing voice call", "missed voice call",
                "incoming video call", "outgoing video call", "missed video call",
                "voice call", "video call"
            ]
            exact_matches = {"call", "audio", "video"}
            body_suggests_call = any(pattern in lb for pattern in call_patterns) or lb in exact_matches
            
            looks_call = is_call_type or body_suggests_call
            is_video = ("video" in t) or ("video" in lb) or (lb == "video")
            missed = ("miss" in t) or ("miss" in lb) or ("missed" in lb)

            base = None
            if looks_call:
                if missed:
                    base = "Missed video call" if is_video else "Missed voice call"
                    is_out = False
                elif is_out:
                    base = "Outgoing video call" if is_video else "Outgoing voice call"
                else:
                    base = "Incoming video call" if is_video else "Incoming voice call"

            msg = {
                "id": mid,
                "ts": int(r["sent_at"] or 0),
                "sender": sender,
                "out": is_out,
                "body": (base if base else body_raw),
                "atts": [],
                "group": bool(is_group.get(r["cid"], False)),
            }
            if base:
                msg["kind"] = "call"
                msg["video"] = bool(is_video)
                msg["missed"] = bool(missed)
            msg_index[mid] = msg
            threads[label].append(msg)

        if r["relPath"]:
            srcp = SRC / r["relPath"]
            rel = None
            mtype = None
            enc   = False
            icon  = ICON_MAP["unknown"]
            dec_rel = None

            if srcp.exists():
                base = safe(r["fileName"] or srcp.name)
                h = hashlib.sha1(str(srcp).encode()).hexdigest()[:8]
                d = ASSETS / label
                d.mkdir(parents=True, exist_ok=True)
                dest = d / f"{h}_{base}"
                try:
                    if not dest.exists():
                        shutil.copy2(srcp, dest)
                    rel = str(dest.relative_to(OUT))
                    mtype = guess_mime(dest, base)
                    icon  = icon_for_mime(mtype)
                    enc   = likely_encrypted_file(dest)

                    if enc and (r["localKey"] or r["key_alt"]):
                        dec = best_effort_decrypt(dest, d, base, r["localKey"], r["key_alt"], OPENSSL)
                        if dec and dec.exists():
                            dec_rel = str(dec.relative_to(OUT))
                            mtype   = guess_mime(dec, base)
                            icon    = icon_for_mime(mtype)
                            enc     = False
                except Exception:
                    rel = None

            msg_index[mid]["atts"].append({
                "name": r["fileName"] or "",
                "path": dec_rel or rel,
                "mime": mtype or "",
                "icon": icon,
                "likelyEncrypted": bool(enc),
                "originalPath": rel if dec_rel else None,
                "localKey": r["localKey"],
                "contentType": r["contentType"],
            })

    # newline after messages progress
    sys.stdout.write("\n")

    # callsHistory (optional)
    def table_exists(name: str) -> bool:
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,))
        return cur.fetchone() is not None

    if table_exists("callsHistory"):
        cur.execute("PRAGMA table_info(callsHistory)")
        cols = {c["name"] for c in cur.fetchall()}
        col_cid = next((x for x in ("conversationId", "cid", "threadId") if x in cols), None)
        col_ts  = next((x for x in ("timestamp", "startedAt", "startTimestamp", "sent_at", "time") if x in cols), None)
        col_ty  = next((x for x in ("type", "callType", "direction", "status") if x in cols), None)
        col_du  = next((x for x in ("duration", "callDurationSeconds", "endedTimestamp") if x in cols), None)
        col_peer = next((x for x in ("peerId", "ringerId", "startedById") if x in cols), None)

        if col_cid and col_ts and col_ty:
            cur.execute(f"SELECT {col_cid} AS cid, {col_ts} AS ts, {col_ty} AS ctype, {col_du} AS dur FROM callsHistory ORDER BY {col_cid}, {col_ts}")
            for row in cur.fetchall():
                label = safe(conv_name.get(row["cid"]) or f"conv:{row['cid']}")
                t = (row["ctype"] or "").lower()
                is_video = ("video" in t)
                missed = ("miss" in t)
                outb = ("out" in t or "placed" in t)
                if missed:
                    base = "Missed video call" if is_video else "Missed voice call"
                    outb = False
                elif outb:
                    base = "Outgoing video call" if is_video else "Outgoing voice call"
                elif ("in" in t or "received" in t):
                    base = "Incoming video call" if is_video else "Incoming voice call"
                else:
                    base = "Call"
                ts = int(row["ts"] or 0)
                ts = ts if ts > 10_000 else ts * 1000
                threads.setdefault(label, []).append({
                    "id": f"call-{ts}",
                    "ts": ts,
                    "sender": "me" if outb else "",
                    "out": outb,
                    "body": base,
                    "kind": "call",
                    "missed": missed,
                    "video": is_video,
                    "atts": [],
                    "group": bool(is_group.get(row["cid"], False)),
                })
        elif col_peer and col_ts and col_ty:
            # Fallback: map by a peer identifier to a person label via resolve_sender
            cur.execute(f"SELECT {col_peer} AS pid, {col_ts} AS ts, {col_ty} AS ctype, {col_du} AS dur FROM callsHistory ORDER BY {col_ts}")
            for row in cur.fetchall():
                name = resolve_sender(row["pid"])
                label = safe(name or "Call")
                t = (row["ctype"] or "").lower()
                is_video = ("video" in t)
                missed = ("miss" in t)
                outb = ("out" in t or "placed" in t)
                if missed:
                    base = "Missed video call" if is_video else "Missed voice call"
                    outb = False
                elif outb:
                    base = "Outgoing video call" if is_video else "Outgoing voice call"
                elif ("in" in t or "received" in t):
                    base = "Incoming video call" if is_video else "Incoming voice call"
                else:
                    base = "Call"
                ts = int(row["ts"] or 0)
                ts = ts if ts > 10_000 else ts * 1000
                threads.setdefault(label, []).append({
                    "id": f"call-{ts}",
                    "ts": ts,
                    "sender": "me" if outb else "",
                    "out": outb,
                    "body": base,
                    "kind": "call",
                    "missed": missed,
                    "video": is_video,
                    "atts": [],
                    "group": False,
                })

    for k in list(threads.keys()):
        threads[k] = [m for m in threads[k] if (m["body"].strip() or any(a.get("path") for a in m["atts"]))]

    for arr in threads.values():
        arr.sort(key=lambda m: (m["ts"], m["id"]))

    data: List[Dict[str, Any]] = []
    for label, msgs in sorted(threads.items(), key=lambda kv: kv[0].lower()):
        if not msgs: continue
        data.append({
            "thread": label,
            "unknown": looks_unknown(label),
            "avatar": (thread_avatar.get(label) or ""),
            "avatarEncrypted": bool(thread_avatar_enc.get(label, False)),
            "messages": [
                {
                    "ts": m["ts"], "sender": m["sender"], "out": m["out"], "body": m["body"], 
                    "atts": m["atts"], "group": m["group"],
                    "kind": m.get("kind"), "video": m.get("video", False), "missed": m.get("missed", False)
                }
                for m in msgs
            ],
        })

    exported_on = dt.datetime.now().strftime("%a, %b %d, %Y • %I:%M %p")

    if template:
        tpl_text = Path(template).read_text(encoding="utf-8")
    else:
        tpl_text = importlib_resources.files("signal_export").joinpath("assets", "template.html").read_text(encoding="utf-8")

    if css:
        css_text = Path(css).read_text(encoding="utf-8")
    else:
        css_text = importlib_resources.files("signal_export").joinpath("assets", "styles.css").read_text(encoding="utf-8")

    html = (tpl_text
            .replace("__DATA__", json.dumps(data))
            .replace("__STAMP__", exported_on)
            .replace("/*__INLINE_CSS__*/", css_text))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    return OUT / "index.html"
