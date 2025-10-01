# Signal Desktop → HTML Export

**Author:** Leo A. Ramirez Jr. — <leo.ramirez@alumni.stanford.edu>

## What it does

- Decrypts Signal Desktop data into a plain SQLite (via `signalbackup-tools`)
- Builds a responsive, light-themed HTML viewer of your conversations
- Copies attachments; best-effort decrypts certain unreadable blobs (if keys available)
- Includes call events (incoming/outgoing/missed)
- Shows a clean UI with searchable thread list and grouped messages

Current limitations (intentional, for safety and clarity):
- Sidebar avatars are disabled for now (initials-only).
- In-chat image thumbnails are disabled; image attachments are shown as archive icons with a tooltip.

## Screenshot

![Signal Export UI](src/signal_export/assets/Signal%20Export%20Screenshot.png)

## Project layout

```
.
├─ pyproject.toml
├─ README.md
├─ .gitignore
├─ env.template                # copy to .env and customize
├─ scripts/
│  └─ signal_export.sh         # macOS helper (decrypt + run Python CLI)
├─ src/
│  └─ signal_export/
│     ├─ __init__.py
│     ├─ cli.py                # cross-platform CLI (Python-only)
│     ├─ exporter.py           # export pipeline (DB→data→HTML, progress bars)
│     ├─ utils.py              # helpers
│     └─ assets/
│        ├─ template.html      # UI (avatars off, no clickable images)
│        └─ styles.css
├─ tests/
│  ├─ conftest.py
│  ├─ test_cli.py
│  ├─ test_render.py
│  └─ test_utils.py
└─ future/
   └─ README.md
```

## Requirements

- Python 3.12+ (latest stable Python 3)
- For macOS end-to-end flow: Homebrew + `signalbackup-tools` for DB decryption
- Optional: OpenSSL CLI on PATH (improves best-effort decryption)

## Configuration (.env and environment variables)

Precedence: CLI flags > `.env` > process env > defaults.

Copy `env.template` to `.env` and adjust:

```
# If not set, DB defaults to "$DB_OUT/signal_plain.sqlite"
DB=

# Where the decrypted SQLite file should live (default: $HOME)
DB_OUT="$HOME"

# Signal attachments directory
SRC="$HOME/Library/Application Support/Signal/attachments.noindex"

# Where the HTML export should be written (default: $HOME/signal_export_html)
HTML_OUT="$HOME/signal_export_html"

# Optional OpenSSL binary
OPENSSL_BIN=
```

- Values support `$VAR` and `~` expansion.
- For privacy, consider setting `HTML_OUT` to `~/nobackup/signal_export_html` or another backup-excluded path.

## Usage

### Python-only (cross-platform)

```bash
# Direct run without install
PYTHONPATH=src \
python -m signal_export.cli \
  --db /path/to/signal_plain.sqlite \
  --src "/path/to/attachments.noindex" \
  --out "$HOME/signal_export_html"

# Or install a console script
pip install -e .
signal-export \
  --db /path/to/signal_plain.sqlite \
  --src "/path/to/attachments.noindex" \
  --out "$HOME/signal_export_html"
```

### macOS helper script (end-to-end)

```bash
cp env.template .env   # edit to suit your environment
./scripts/signal_export.sh
```

- The script cd’s to the repo root, sources `.env`, computes sensible defaults using `$HOME`, and sets `PYTHONPATH` for local runs.
- It then runs `signalbackup-tools` to create/rotate `DB` and invokes the Python CLI to build the export.

### Progress display

- Terminal progress bars show:
  - Conversations and messages processed
  - Percent, counts, elapsed time, and ETA

## Testing

```
pip install -e .[dev]
pytest -q
```

- Tests include CLI smoke test, asset presence, env fallback behavior, and helper utilities.
- Grow coverage over time (goal: 1/2 to 2/3 lines of code in tests).

## Notes

- Avatars and image thumbnails are intentionally disabled at present due to decryption inconsistencies; message text and attachments (as links/icons) are fully exported.
- Decryption is best-effort; some files may remain unreadable.
- All processing is local. No network calls.

## Future

Planned: reliable avatar/image handling, message search, reply threading, live DB sync, schema compatibility, contact info, optional React UI. See `future/README.md`.