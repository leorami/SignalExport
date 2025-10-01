from __future__ import annotations
import argparse
import os
import platform
from pathlib import Path
from typing import Optional
from .exporter import run_export


def load_env_file(dotenv_path: Path) -> None:
    """Load simple KEY=VALUE lines from a .env file into os.environ.

    Parsing rules:
    - Ignore empty lines and lines starting with '#'.
    - Only the first '=' splits KEY and VALUE.
    - Leading/trailing whitespace is trimmed around KEY and VALUE.
    - If VALUE is wrapped in single or double quotes, remove the outermost quotes.
    - Expand environment variables ($VAR) and ~ (home) in VALUE.
    - Do not override already-existing environment variables in this process.
    """
    if not dotenv_path or not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key and key not in os.environ:
            expanded = os.path.expanduser(os.path.expandvars(val))
            os.environ[key] = expanded


def default_src_path() -> str:
    """Best-effort default for the Signal attachments directory (platform-aware)."""
    sysname = platform.system().lower()
    home = os.path.expanduser("~")
    if sysname == "darwin":
        return f"{home}/Library/Application Support/Signal/attachments.noindex"
    if sysname == "windows":
        appdata = os.environ.get("APPDATA", f"{home}\\AppData\\Roaming")
        return str(Path(appdata) / "Signal" / "attachments.noindex")
    return f"{home}/.config/Signal/attachments.noindex"


def resolve_paths(args) -> tuple[str, str, str]:
    """Resolve DB path, SRC path, and OUT path with precedence and HOME fallback.

    Precedence: CLI > .env > process env > defaults
    - HOME: if not set, defaults to project directory.
    - DB:   if not set, becomes f"{DB_OUT}/signal_plain.sqlite".
    - OUT:  prefers HTML_OUT, falls back to OUT.
    - DB_OUT default: f"{HOME}"
    - HTML_OUT default: f"{HOME}/signal_export_html"
    """
    project_root = Path(__file__).resolve().parents[2]
    home = os.environ.get("HOME") or str(project_root / ".artifacts")

    src = (args.src or os.environ.get("SRC") or default_src_path())

    db_out = os.environ.get("DB_OUT") or f"{home}"
    html_out = os.environ.get("HTML_OUT") or os.environ.get("OUT") or f"{home}/signal_export_html"

    db = (args.db or os.environ.get("DB") or str(Path(db_out) / "signal_plain.sqlite"))

    out = (args.out or html_out)

    # Ensure parent directories exist for DB file and OUT path
    db_parent = Path(db).expanduser().resolve().parent
    try:
        db_parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    Path(out).expanduser().mkdir(parents=True, exist_ok=True)

    return db, src, out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="signal-export",
        description=(
            "Build Signal export HTML from a plain SQLite DB.\n"
            "Env precedence: CLI flags > .env > process env > defaults\n"
            "Env vars: DB, SRC, OUT/HTML_OUT, DB_OUT, OPENSSL_BIN"
        ),
    )
    p.add_argument("--db", default=None, help="Path to decrypted SQLite (from signalbackup-tools).")
    p.add_argument("--src", default=None, help="Path to Signal attachments.noindex directory.")
    p.add_argument("--out", default=None, help="Output directory for HTML and assets.")
    p.add_argument("--template", default=None, help="Optional path to template.html. Defaults to packaged asset.")
    p.add_argument("--css", default=None, help="Optional path to styles.css. Defaults to packaged asset.")
    p.add_argument("--openssl", default=None, help="Path to OpenSSL binary (optional).")
    p.add_argument("--env-file", default=".env", help="Path to .env file to load (default: .env in CWD).")
    return p


def main(argv: list[str] | None = None) -> None:
    ap = build_parser()
    args = ap.parse_args(argv)

    load_env_file(Path(args.env_file))

    db, src, out = resolve_paths(args)
    openssl: Optional[str] = (args.openssl or os.environ.get("OPENSSL_BIN") or None)

    idx = run_export(
        db=db,
        src=src,
        out=out,
        template=args.template,
        css=args.css,
        openssl=openssl,
    )
    print(str(Path(idx)))


if __name__ == "__main__":
    main()
