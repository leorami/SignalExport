#!/usr/bin/env python3
import argparse
import hashlib
import json
import random
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Tuple


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


FIRST_NAMES = [
    "Alex","Jordan","Taylor","Sam","Casey","Riley","Morgan","Avery","Jamie","Quinn",
    "Chris","Pat","Drew","Cameron","Lee","Adrian","Cory","Elliot","Reese","Skyler",
    "Maya","Priya","Noah","Liam","Emma","Olivia","Ava","Sophia","Isabella","Mia",
]
LAST_NAMES = [
    "Rivera","Kim","Patel","Nguyen","Garcia","Lee","Martinez","Brown","Davis","Chen",
    "Khan","Taylor","Morgan","Singh","Wang","Lopez","Anderson","Thomas","Moore","Jackson",
]
ADJECTIVES = [
    "Bright","Midnight","Rustic","Silver","Crimson","Emerald","Quiet","Golden","Rapid","Urban",
]
NOUNS = [
    "Owls","Harbor","Rangers","Circuit","Valley","Summit","Studio","Garden","Collective","Lab",
]
PHRASES = [
    "Got it.","On my way.","Let’s catch up later.","I’ll send it soon.","Sounds good to me.",
    "Can we move this to tomorrow?","Here’s the update:","Thanks again!","Works on my end.",
    "Ping me when you’re free.","Check this out: https://example.com","Yep","Nope","Maybe",
]


def seeded_rand(cid: str, base_seed: int) -> random.Random:
    h = int(hashlib.sha256((cid + str(base_seed)).encode()).hexdigest(), 16) & ((1<<63)-1)
    return random.Random(h)


def make_person_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def make_group_name(rng: random.Random) -> str:
    style = rng.randint(0, 2)
    if style == 0:
        return f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
    if style == 1:
        return f"Project {rng.choice(ADJECTIVES)}"
    return f"The {rng.choice(NOUNS)}"


def classify_conversations(cur: sqlite3.Cursor) -> Dict[str, bool]:
    """Return cid -> is_group by inspecting distinct non-me senders in messages."""
    # Build sender sets per conversation
    cur.execute("SELECT id, conversationId, source, sourceServiceId, isChangeCreatedByUs FROM messages")
    by_cid: Dict[str, set] = {}
    for r in cur.fetchall():
        cid = str(r[1])
        is_me = int(r[4] or 0) == 1
        sid = (r[3] or r[2] or "")
        if is_me:
            continue
        by_cid.setdefault(cid, set()).add(sid or "other")
    # Heuristic: >1 distinct non-me senders => group, else user
    out: Dict[str, bool] = {}
    cur.execute("SELECT id, type FROM conversations")
    for r in cur.fetchall():
        cid = str(r[0])
        senders = by_cid.get(cid, set())
        is_group = len([s for s in senders if s]) > 1
        out[cid] = is_group
    return out


def synthetic_body(rng: random.Random) -> str:
    # Build a short message with some variation
    parts = []
    for _ in range(rng.randint(1, 3)):
        parts.append(rng.choice(PHRASES))
    # add emoji occasionally
    if rng.random() < 0.3:
        parts.append(rng.choice(["🙂","👍","🎉","🔥","✅"]))
    return " ".join(parts)


def drop_triggers_and_fts(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    for (tname,) in cur.fetchall():
        try:
            cur.execute(f"DROP TRIGGER IF EXISTS \"{tname}\"")
        except Exception:
            pass
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE '%VIRTUAL TABLE %USING fts%'")
    for (tbl, _sql) in cur.fetchall():
        try:
            cur.execute(f"DROP TABLE IF EXISTS \"{tbl}\"")
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description='Sanitize a Signal export SQLite DB into an anonymized test DB with human-like data.')
    ap.add_argument('--in', dest='src', required=True, help='Path to source (unencrypted) SQLite DB')
    ap.add_argument('--out', dest='dst', required=True, help='Path to output sanitized SQLite DB')
    ap.add_argument('--seed', type=int, default=1337, help='Base RNG seed for deterministic output')
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

        # Avoid tokenizer dependency issues
        drop_triggers_and_fts(cur)

        # Classify conversations by message participants
        is_group_by = classify_conversations(cur)

        # Assign human-like labels
        cur.execute("SELECT id FROM conversations")
        for row in cur.fetchall():
            cid = str(row['id'])
            rng = seeded_rand(cid, args.seed)
            label = make_group_name(rng) if is_group_by.get(cid, False) else make_person_name(rng)
            js = scrub_conversation_json(load_json(None))
            cur.execute(
                "UPDATE conversations SET name=?, profileFullName=?, profileName=?, e164=NULL, serviceId=NULL, json=? WHERE id=?",
                (label, label, label, json.dumps(js), cid)
            )

        # Replace message bodies with synthetic content; clear sender identifiers
        cur.execute("SELECT id, conversationId FROM messages")
        msgs = cur.fetchall()
        for r in msgs:
            cid = str(r['conversationId'])
            rng = seeded_rand(cid + ":msg:" + str(r['id']), args.seed)
            body = synthetic_body(rng)
            cur.execute("UPDATE messages SET body=?, source=NULL, sourceServiceId=NULL WHERE id=?", (body, r['id']))

        # Remove attachments content entirely
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_attachments'")
        if cur.fetchone():
            cur.execute("DELETE FROM message_attachments")

        # Normalize callsHistory if present
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
