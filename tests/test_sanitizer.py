import json
import sqlite3
import tempfile
from pathlib import Path
import pytest
import subprocess
import sys


def test_sanitizer_script_exists():
    """Test that the sanitizer script exists and is executable."""
    sanitizer_path = Path(__file__).resolve().parents[1] / "tools" / "sanitize_db.py"
    assert sanitizer_path.exists(), "Sanitizer script not found"
    assert sanitizer_path.stat().st_mode & 0o111, "Sanitizer script not executable"


def test_sanitizer_group_classification(tmp_path):
    """Test that sanitizer correctly classifies groups vs individual conversations."""
    # Create a test database
    input_db = tmp_path / "input.sqlite"
    output_db = tmp_path / "output.sqlite"
    
    conn = sqlite3.connect(input_db)
    cursor = conn.cursor()
    
    # Create schema
    cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, name TEXT, type TEXT, json TEXT, e164 TEXT, serviceId TEXT, profileFullName TEXT, profileName TEXT)")
    cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
    cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER)")
    cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT)")
    
    # Insert test conversations
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("conv1", "John Doe", "private"))
    cursor.execute("INSERT INTO conversations (id, name, type) VALUES (?, ?, ?)", ("conv2", "Team Chat", "group"))
    
    # Insert messages - conv1 has 1 sender (individual), conv2 has multiple senders (group)
    cursor.execute("INSERT INTO messages (id, conversationId, source, isChangeCreatedByUs, body) VALUES (?, ?, ?, ?, ?)", 
                   (1, "conv1", "john@example.com", 0, "Hello"))
    cursor.execute("INSERT INTO messages (id, conversationId, source, isChangeCreatedByUs, body) VALUES (?, ?, ?, ?, ?)", 
                   (2, "conv1", "john@example.com", 0, "How are you?"))
    
    # Group conversation with multiple senders
    cursor.execute("INSERT INTO messages (id, conversationId, source, isChangeCreatedByUs, body) VALUES (?, ?, ?, ?, ?)", 
                   (3, "conv2", "alice@example.com", 0, "Hi team"))
    cursor.execute("INSERT INTO messages (id, conversationId, source, isChangeCreatedByUs, body) VALUES (?, ?, ?, ?, ?)", 
                   (4, "conv2", "bob@example.com", 0, "Hello everyone"))
    cursor.execute("INSERT INTO messages (id, conversationId, source, isChangeCreatedByUs, body) VALUES (?, ?, ?, ?, ?)", 
                   (5, "conv2", "charlie@example.com", 0, "Good morning"))
    
    conn.commit()
    conn.close()
    
    # Run sanitizer
    sanitizer_path = Path(__file__).resolve().parents[1] / "tools" / "sanitize_db.py"
    result = subprocess.run([
        sys.executable, str(sanitizer_path),
        "--in", str(input_db),
        "--out", str(output_db),
        "--seed", "42"
    ], capture_output=True, text=True)
    
    assert result.returncode == 0, f"Sanitizer failed: {result.stderr}"
    
    # Check output
    conn = sqlite3.connect(output_db)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name FROM conversations ORDER BY id")
    conversations = cursor.fetchall()
    
    # Should have realistic names
    assert len(conversations) == 2
    conv1_name = conversations[0][1]
    conv2_name = conversations[1][1]
    
    # Individual conversation should have person name format
    assert " " in conv1_name, f"Individual conversation name '{conv1_name}' should be 'First Last' format"
    
    # Group conversation should have group name format
    group_indicators = ["Project", "The", "Team", "Lab", "Studio", "Collective"]
    is_group_name = any(indicator in conv2_name for indicator in group_indicators) or not " " in conv2_name
    assert is_group_name, f"Group conversation name '{conv2_name}' should be group-style name"
    
    conn.close()


def test_sanitizer_removes_pii():
    """Test that sanitizer removes personally identifiable information."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_db = tmp_path / "input.sqlite"
        output_db = tmp_path / "output.sqlite"
        
        conn = sqlite3.connect(input_db)
        cursor = conn.cursor()
        
        # Create schema
        cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, name TEXT, type TEXT, json TEXT, e164 TEXT, serviceId TEXT, profileFullName TEXT, profileName TEXT)")
        cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
        cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER)")
        cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT)")
        
        # Insert conversation with PII
        pii_json = json.dumps({
            "profileAvatarPath": "/path/to/avatar.jpg",
            "profileKey": "sensitive_key_data",
            "localKey": "another_sensitive_key"
        })
        cursor.execute("INSERT INTO conversations (id, name, e164, serviceId, json) VALUES (?, ?, ?, ?, ?)", 
                       ("conv1", "Real Person Name", "+1234567890", "real.service.id", pii_json))
        
        # Insert message with PII
        cursor.execute("INSERT INTO messages (id, conversationId, source, sourceServiceId, body) VALUES (?, ?, ?, ?, ?)", 
                       (1, "conv1", "real.email@example.com", "real.service.id", "Sensitive personal information"))
        
        conn.commit()
        conn.close()
        
        # Run sanitizer
        sanitizer_path = Path(__file__).resolve().parents[1] / "tools" / "sanitize_db.py"
        result = subprocess.run([
            sys.executable, str(sanitizer_path),
            "--in", str(input_db),
            "--out", str(output_db),
            "--seed", "42"
        ], capture_output=True, text=True)
        
        assert result.returncode == 0, f"Sanitizer failed: {result.stderr}"
        
        # Check that PII is removed
        conn = sqlite3.connect(output_db)
        cursor = conn.cursor()
        
        # Check conversations
        cursor.execute("SELECT name, e164, serviceId, json FROM conversations")
        conv_data = cursor.fetchone()
        
        # Name should be anonymized
        assert conv_data[0] != "Real Person Name"
        # e164 and serviceId should be NULL
        assert conv_data[1] is None
        assert conv_data[2] is None
        # JSON should not contain sensitive keys
        json_data = json.loads(conv_data[3]) if conv_data[3] else {}
        assert "profileAvatarPath" not in json_data
        assert "profileKey" not in json_data
        assert "localKey" not in json_data
        
        # Check messages
        cursor.execute("SELECT source, sourceServiceId, body FROM messages")
        msg_data = cursor.fetchone()
        
        # Source identifiers should be NULL
        assert msg_data[0] is None
        assert msg_data[1] is None
        # Body should be synthetic
        assert msg_data[2] != "Sensitive personal information"
        
        conn.close()


def test_sanitizer_deterministic_output():
    """Test that sanitizer produces deterministic output with same seed."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_db = tmp_path / "input.sqlite"
        output_db1 = tmp_path / "output1.sqlite"
        output_db2 = tmp_path / "output2.sqlite"
        
        # Create identical input databases
        for db_path in [input_db]:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, name TEXT, type TEXT, json TEXT, e164 TEXT, serviceId TEXT, profileFullName TEXT, profileName TEXT)")
            cursor.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversationId TEXT, source TEXT, sourceServiceId TEXT, isChangeCreatedByUs INTEGER, body TEXT)")
            cursor.execute("CREATE TABLE message_attachments (messageId INTEGER, fileName TEXT, path TEXT, orderInMessage INTEGER)")
            cursor.execute("CREATE TABLE callsHistory (conversationId TEXT, timestamp INTEGER, type TEXT)")
            
            cursor.execute("INSERT INTO conversations (id, name) VALUES (?, ?)", ("conv1", "Test User"))
            cursor.execute("INSERT INTO messages (id, conversationId, body) VALUES (?, ?, ?)", (1, "conv1", "Test message"))
            
            conn.commit()
            conn.close()
        
        sanitizer_path = Path(__file__).resolve().parents[1] / "tools" / "sanitize_db.py"
        
        # Run sanitizer twice with same seed
        for output_db in [output_db1, output_db2]:
            result = subprocess.run([
                sys.executable, str(sanitizer_path),
                "--in", str(input_db),
                "--out", str(output_db),
                "--seed", "12345"
            ], capture_output=True, text=True)
            assert result.returncode == 0, f"Sanitizer failed: {result.stderr}"
        
        # Compare outputs
        conn1 = sqlite3.connect(output_db1)
        conn2 = sqlite3.connect(output_db2)
        
        cursor1 = conn1.cursor()
        cursor2 = conn2.cursor()
        
        cursor1.execute("SELECT name FROM conversations")
        cursor2.execute("SELECT name FROM conversations")
        
        name1 = cursor1.fetchone()[0]
        name2 = cursor2.fetchone()[0]
        
        assert name1 == name2, "Sanitizer should produce deterministic output with same seed"
        
        conn1.close()
        conn2.close()
