import json
import sqlite3
from pathlib import Path
import pytest
from src.signal_export.exporter import run_export


def test_call_history_detection_and_rendering(tmp_dirs, tmp_path):
    """Test that call-history type messages are detected and rendered as chips."""
    src, out = tmp_dirs
    
    # Create a test database with call-history messages
    db_path = tmp_path / "test_calls.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create schema
    cursor.execute("""
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            json TEXT,
            name TEXT,
            profileFullName TEXT,
            profileName TEXT,
            e164 TEXT,
            serviceId TEXT,
            type TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            conversationId TEXT,
            sent_at INTEGER,
            type TEXT,
            source TEXT,
            sourceServiceId TEXT,
            isChangeCreatedByUs INTEGER,
            body TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE message_attachments (
            messageId INTEGER,
            fileName TEXT,
            path TEXT,
            orderInMessage INTEGER,
            localKey TEXT,
            key TEXT,
            contentType TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE callsHistory (
            conversationId TEXT,
            timestamp INTEGER,
            type TEXT,
            duration INTEGER
        )
    """)
    
    # Insert test data
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test User", "private"))
    
    # Insert call-history type messages
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                   (1, "1", 1678886400000, "call-history", "Incoming voice call", 0))
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                   (2, "1", 1678886460000, "call-history", "Outgoing voice call", 1))
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                   (3, "1", 1678886520000, "call-history", "Missed video call", 0))
    
    conn.commit()
    conn.close()
    
    # Run export
    output_html = run_export(db_path, src, out, openssl="")
    
    # Read the generated HTML and extract JSON data
    html_content = output_html.read_text(encoding="utf-8")
    
    # Extract JSON data from the HTML
    start_marker = '<script id="data" type="application/json">'
    end_marker = '</script>'
    start_idx = html_content.find(start_marker) + len(start_marker)
    end_idx = html_content.find(end_marker, start_idx)
    json_data = html_content[start_idx:end_idx].strip()
    
    data = json.loads(json_data)
    
    # Find the test conversation (name gets processed by safe() function)
    test_conv = next((conv for conv in data if "Test" in conv["thread"]), None)
    assert test_conv is not None, f"Test conversation not found. Available: {[c['thread'] for c in data]}"
    
    # Check that call messages have the correct properties
    call_messages = [msg for msg in test_conv["messages"] if msg.get("kind") == "call"]
    assert len(call_messages) == 3, f"Expected 3 call messages, got {len(call_messages)}"
    
    # Check incoming call
    incoming = next((msg for msg in call_messages if "Incoming" in msg["body"]), None)
    assert incoming is not None
    assert incoming["kind"] == "call"
    assert incoming["out"] is False
    assert incoming["video"] is False
    assert incoming["missed"] is False
    
    # Check outgoing call
    outgoing = next((msg for msg in call_messages if "Outgoing" in msg["body"]), None)
    assert outgoing is not None
    assert outgoing["kind"] == "call"
    assert outgoing["out"] is True
    assert outgoing["video"] is False
    assert outgoing["missed"] is False
    
    # Check missed video call
    missed = next((msg for msg in call_messages if "Missed" in msg["body"]), None)
    assert missed is not None
    assert missed["kind"] == "call"
    assert missed["out"] is False
    assert missed["video"] is True
    assert missed["missed"] is True


def test_call_chip_css_classes(tmp_dirs, tmp_path):
    """Test that call events generate proper CSS classes for styling."""
    src, out = tmp_dirs
    
    # Create a minimal test database with call events
    db_path = tmp_path / "test_css.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT, duration INTEGER)")
    
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test", "private"))
    cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                   (1, "1", 1678886400000, "call-history", "Missed voice call", 0))
    
    conn.commit()
    conn.close()
    
    # Run export
    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    
    # Check that CSS classes for call chips are present
    assert ".call{" in html_content, "Call CSS class not found"
    assert ".call .pill{" in html_content, "Call pill CSS class not found"
    assert ".call.missed .pill{" in html_content, "Missed call CSS class not found"
    
    # Check that JavaScript template handles call rendering
    assert 'if (m.kind === \'call\'){' in html_content, "Call rendering JavaScript not found"
    assert 'row.className = \'call\' + (m.missed ? \' missed\' : \'\');' in html_content, "Call CSS class assignment not found"


def test_call_body_content_detection(tmp_dirs, tmp_path):
    """Test that various call-related body content is properly detected."""
    src, out = tmp_dirs
    
    db_path = tmp_path / "test_body.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT, duration INTEGER)")
    
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test", "private"))
    
    # Test various body content that should be detected as calls
    test_cases = [
        ("Call", "incoming"),
        ("Audio", "incoming"), 
        ("Video", "incoming"),
        ("Missed call", "incoming"),
        ("voice call", "incoming"),
        ("video call", "outgoing")
    ]
    
    for i, (body, msg_type) in enumerate(test_cases):
        is_out = 1 if msg_type == "outgoing" else 0
        cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                       (i+1, "1", 1678886400000 + i*1000, "incoming", body, is_out))
    
    conn.commit()
    conn.close()
    
    # Run export
    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    
    # Extract and parse JSON data
    start_marker = '<script id="data" type="application/json">'
    end_marker = '</script>'
    start_idx = html_content.find(start_marker) + len(start_marker)
    end_idx = html_content.find(end_marker, start_idx)
    json_data = html_content[start_idx:end_idx].strip()
    
    data = json.loads(json_data)
    test_conv = data[0]
    
    # All messages should be detected as calls
    call_messages = [msg for msg in test_conv["messages"] if msg.get("kind") == "call"]
    assert len(call_messages) == len(test_cases), f"Expected {len(test_cases)} call messages, got {len(call_messages)}"


def test_no_false_positive_call_detection(tmp_dirs, tmp_path):
    """Test that regular messages are not incorrectly detected as calls."""
    src, out = tmp_dirs
    
    db_path = tmp_path / "test_false_positive.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, json TEXT, name TEXT, profileFullName TEXT, profileName TEXT, e164 TEXT, serviceId TEXT, type TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, sent_at INTEGER, type TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER, localKey TEXT, key TEXT, contentType TEXT)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT, duration INTEGER)")
    
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("1", "Test", "private"))
    
    # Regular messages that should NOT be detected as calls
    regular_messages = [
        "Hello there",
        "How are you?",
        "Let's meet tomorrow",
        "I'll send you the file",
        "Thanks for calling earlier"  # Contains "call" but not a call event
    ]
    
    for i, body in enumerate(regular_messages):
        cursor.execute("INSERT INTO messages (id, conversationId, sent_at, type, body, isChangeCreatedByUs) VALUES (?, ?, ?, ?, ?, ?)", 
                       (i+1, "1", 1678886400000 + i*1000, "incoming", body, 0))
    
    conn.commit()
    conn.close()
    
    # Run export
    output_html = run_export(db_path, src, out, openssl="")
    html_content = output_html.read_text(encoding="utf-8")
    
    # Extract and parse JSON data
    start_marker = '<script id="data" type="application/json">'
    end_marker = '</script>'
    start_idx = html_content.find(start_marker) + len(start_marker)
    end_idx = html_content.find(end_marker, start_idx)
    json_data = html_content[start_idx:end_idx].strip()
    
    data = json.loads(json_data)
    test_conv = data[0]
    
    # No messages should be detected as calls
    call_messages = [msg for msg in test_conv["messages"] if msg.get("kind") == "call"]
    assert len(call_messages) == 0, f"Expected 0 call messages, got {len(call_messages)}"
    
    # All messages should be regular messages
    regular_msgs = [msg for msg in test_conv["messages"] if msg.get("kind") != "call"]
    assert len(regular_msgs) == len(regular_messages), f"Expected {len(regular_messages)} regular messages, got {len(regular_msgs)}"
