import os
import sys
import sqlite3
from pathlib import Path
import tempfile
import shutil
import pytest

# Ensure local package is importable without installation
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture()
def tmp_dirs(tmp_path: Path):
    out = tmp_path / "out"
    src = tmp_path / "attachments"
    out.mkdir()
    src.mkdir()
    return src, out


@pytest.fixture()
def tiny_db(tmp_path: Path) -> Path:
    db = tmp_path / "tiny.sqlite"
    con = sqlite3.connect(str(db))
    cur = con.cursor()

    cur.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cur.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER)")

    cur.execute("INSERT INTO conversations (id, name, type) VALUES ('c1', 'Alice', 'private')")
    cur.execute("INSERT INTO messages (id, conversationId, sent_at, type, source, isChangeCreatedByUs, body) VALUES (1, 'c1', 1700000000000, 'incoming', 'alice', 0, 'Hello')")

    con.commit(); con.close()
    return db
