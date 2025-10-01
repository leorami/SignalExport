#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def load_json(s):
    try:
        return json.loads(s) if isinstance(s, str) else (s or {})
    except Exception:
        return {}


def scrub_conversation_json(obj: dict) -> dict:
    if not isinstance(obj, dict):
        return {}
    scrub_keys = {
        'name','profileFullName','profileName','e164','serviceId',
        'avatarPath','profileAvatarPath'
    }
    for k in list(obj.keys()):
        if k in scrub_keys:
            obj.pop(k, None)
    pa = obj.get('profileAvatar')
    if isinstance(pa, dict):
        for k in ['path','avatarPath','filePath','localKey','key','profileKey','keyMaterial']:
            pa.pop(k, None)
    return obj


def drop_triggers_and_fts(cur: sqlite3.Cursor) -> None:
    # Drop all triggers (names are stable in sqlite_master)
    cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    for (tname,) in cur.fetchall():
        try:
            cur.execute(f"DROP TRIGGER IF EXISTS \"{tname}\"")
        except Exception:
            pass
    # Drop VIRTUAL TABLES using FTS to avoid tokenizer deps
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE '%VIRTUAL TABLE %USING fts%'")
    for (tbl, _sql) in cur.fetchall():
        try:
            cur.execute(f"DROP TABLE IF EXISTS \"{tbl}\"")
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description='Sanitize a Signal export SQLite DB into an anonymized test DB.')
    ap.add_argument('--in', dest='src', required=True, help='Path to source (unencrypted) SQLite DB')
    ap.add_argument('--out', dest='dst', required=True, help='Path to output sanitized SQLite DB')
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    if not src.exists():
        print(f"ERROR: Source DB not found: {src}", file=sys.stderr)
        sys.exit(1)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())

    con = sqlite3.connect(str(dst))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute('PRAGMA foreign_keys=OFF')

    try:
        cur.execute('BEGIN')

        # Drop triggers and FTS virtual tables that may depend on custom tokenizers
        drop_triggers_and_fts(cur)

        # Map conversations to placeholder labels
        cur.execute("SELECT id, type FROM conversations")
        rows = cur.fetchall()
        user_i = 1
        group_i = 1
        label_by_cid = {}
        for r in rows:
            t = (r['type'] or '').lower()
            if 'group' in t:
                label = f"Group {group_i:03d}"
                group_i += 1
            else:
                label = f"User {user_i:03d}"
                user_i += 1
            label_by_cid[r['id']] = label

        # Sanitize conversations
        cur.execute("SELECT id, json FROM conversations")
        for r in cur.fetchall():
            cid = r['id']
            label = label_by_cid.get(cid, 'User')
            js = load_json(r['json'])
            js = scrub_conversation_json(js)
            cur.execute(
                "UPDATE conversations SET name=?, profileFullName=?, profileName=?, e164=NULL, serviceId=NULL, json=? WHERE id=?",
                (label, label, label, json.dumps(js), cid)
            )

        # Sanitize messages
        cur.execute("UPDATE messages SET body='Message', source=NULL, sourceServiceId=NULL")

        # Drop all attachments
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_attachments'")
        if cur.fetchone():
            cur.execute("DELETE FROM message_attachments")

        # Sanitize callsHistory if present
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='callsHistory'")
        if cur.fetchone():
            try:
                cur.execute("UPDATE callsHistory SET type='Call'")
            except Exception:
                pass

        con.commit()
        print(str(dst))
    except Exception as e:
        con.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        con.close()


if __name__ == '__main__':
    main()
