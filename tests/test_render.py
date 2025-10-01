from pathlib import Path
from importlib import resources as importlib_resources
import json
import sqlite3
from src.signal_export.exporter import run_export


def test_packaged_assets_present():
    """Ensure that template.html and styles.css are correctly packaged and accessible."""
    tpl = importlib_resources.files("signal_export").joinpath("assets", "template.html")
    css = importlib_resources.files("signal_export").joinpath("assets", "styles.css")
    assert tpl.is_file()
    assert css.is_file()
    assert tpl.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert css.read_text(encoding="utf-8").startswith("/* ============================================================================")


def test_template_contains_call_rendering():
    """Test that template.html contains call event rendering logic."""
    tpl = importlib_resources.files("signal_export").joinpath("assets", "template.html")
    template_content = tpl.read_text(encoding="utf-8")
    
    # Check for call rendering JavaScript
    assert "if (m.kind === 'call')" in template_content
    assert "row.className = 'call'" in template_content
    assert "m.video ? '📹' : '📞'" in template_content
    assert "pill.appendChild(icon)" in template_content


def test_css_contains_call_styles():
    """Test that styles.css contains call chip styling."""
    css = importlib_resources.files("signal_export").joinpath("assets", "styles.css")
    css_content = css.read_text(encoding="utf-8")
    
    # Check for call-specific CSS
    assert ".call{" in css_content
    assert ".call .pill{" in css_content
    assert ".call.missed .pill{" in css_content
    assert ".call .icon{" in css_content


def test_template_linkify_function():
    """Test that template contains linkify function for URLs."""
    tpl = importlib_resources.files("signal_export").joinpath("assets", "template.html")
    template_content = tpl.read_text(encoding="utf-8")
    
    # Check for linkify function
    assert "function linkify(text)" in template_content
    assert "urlRe" in template_content
    assert "target=\"_blank\"" in template_content


def test_avatar_initials_fallback():
    """Test that template shows initials when avatars are disabled."""
    tpl = importlib_resources.files("signal_export").joinpath("assets", "template.html")
    template_content = tpl.read_text(encoding="utf-8")
    
    # Check for avatar initials handling
    assert "function liAvatar(t)" in template_content
    assert "initials(t.thread)" in template_content
    assert "disabled avatar images" in template_content


def test_html_output_structure(tmp_dirs, tmp_path):
    """Test that generated HTML has correct structure."""
    src, out = tmp_dirs
    
    # Create minimal test database
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT, duration INTEGER)")
    
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test User", "private"))
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                   (1, "1", 1678886400000, "incoming", "Hello world", 0))
    
    conn.commit()
    conn.close()
    
    # Run export
    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    
    # Check HTML structure
    assert "<!DOCTYPE html>" in html_content
    assert "<title>Signal Export</title>" in html_content
    assert 'class="app"' in html_content
    assert 'class="sidebar"' in html_content
    assert 'class="main"' in html_content
    
    # Check that data is embedded
    assert '<script id="data" type="application/json">' in html_content
    assert '<script id="meta" type="application/json">' in html_content
    
    # Check that CSS is inlined
    assert "/*__INLINE_CSS__*/" not in html_content  # Should be replaced
    assert ".sidebar{" in html_content  # CSS should be present
