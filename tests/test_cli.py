from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import os


def test_cli_smoke(tmp_dirs, tiny_db):
    src, out = tmp_dirs
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[1]
    pythonpath = str(repo_root / "src")
    env["PYTHONPATH"] = (pythonpath + os.pathsep + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else pythonpath

    cmd = [sys.executable, "-m", "signal_export.cli", "--db", str(tiny_db), "--src", str(src), "--out", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    idx = out / "index.html"
    assert idx.exists()
    txt = idx.read_text(encoding="utf-8")
    assert "Exported on" in txt


def test_env_dbout_htmlout_home_fallback(tmp_path):
    """If HOME is unset, CLI should use project root as HOME fallback, and
    DB/OUT should be computed from DB_OUT/HTML_OUT envs when DB/OUT not given."""
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("HOME", None)
    env["PYTHONPATH"] = str(project_root / "src")

    # Create temp roots for DB_OUT and HTML_OUT under tmp_path to avoid writing to repo
    db_out = tmp_path / "dbroot"
    html_out = tmp_path / "htmlroot"
    db_out.mkdir()
    html_out.mkdir()

    env["DB_OUT"] = str(db_out)
    env["HTML_OUT"] = str(html_out)
    src = tmp_path / "attachments"
    src.mkdir()

    # Need a minimal DB to satisfy exporter
    import sqlite3
    db_path = db_out / "signal_plain.sqlite"
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cur.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER)")
    con.commit(); con.close()

    # Explicitly set DB to avoid any platform-specific path quirks
    env["DB"] = str(db_path)

    cmd = [sys.executable, "-m", "signal_export.cli", "--src", str(src)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(project_root))
    assert p.returncode == 0, p.stderr
    idx = html_out / "index.html"
    assert idx.exists()
