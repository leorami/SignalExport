import io
import sys
import shutil
from unittest.mock import patch, MagicMock
import pytest
from src.signal_export.exporter import _progress, _supports_color


def test_supports_color():
    """Test color support detection."""
    # Test with NO_COLOR environment variable
    with patch.dict('os.environ', {'NO_COLOR': '1'}):
        with patch('sys.stdout.isatty', return_value=True):
            assert not _supports_color()
    
    # Test without NO_COLOR but not a TTY
    with patch.dict('os.environ', {}, clear=True):
        with patch('sys.stdout.isatty', return_value=False):
            assert not _supports_color()
    
    # Test with TTY and no NO_COLOR
    with patch.dict('os.environ', {}, clear=True):
        with patch('sys.stdout.isatty', return_value=True):
            assert _supports_color()


def test_progress_basic():
    """Test basic progress bar functionality."""
    # Capture stdout
    captured_output = io.StringIO()
    
    with patch('sys.stdout', captured_output):
        with patch('shutil.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(columns=80)
            with patch('time.time', return_value=1000.0):
                _progress("Test", 50, 100, 999.0)
    
    output = captured_output.getvalue()
    
    # Should contain progress elements
    assert "Test" in output
    assert "50/100" in output
    assert "(50%)" in output


def test_progress_with_color():
    """Test progress bar with color support."""
    captured_output = io.StringIO()
    
    with patch('sys.stdout', captured_output):
        with patch('shutil.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(columns=80)
            with patch('time.time', return_value=1000.0):
                with patch('src.signal_export.exporter._supports_color', return_value=True):
                    _progress("Colored", 25, 100, 998.0)
    
    output = captured_output.getvalue()
    
    # Should contain progress elements
    assert "Colored" in output
    assert "25/100" in output


def test_progress_completion():
    """Test progress bar at completion."""
    captured_output = io.StringIO()
    
    with patch('sys.stdout', captured_output):
        with patch('shutil.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(columns=80)
            with patch('time.time', return_value=1005.0):
                _progress("Complete", 100, 100, 1000.0)
    
    output = captured_output.getvalue()
    
    # Should contain completion elements
    assert "Complete" in output
    assert "100/100" in output
    assert "(100%)" in output


def test_progress_zero_iteration():
    """Test progress bar at start (iteration 0)."""
    captured_output = io.StringIO()
    
    with patch('sys.stdout', captured_output):
        with patch('shutil.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(columns=80)
            with patch('time.time', return_value=1000.0):
                _progress("Starting", 0, 100, 1000.0)
    
    output = captured_output.getvalue()
    
    # Should handle zero iteration gracefully
    assert "Starting" in output
    assert "0/100" in output
    assert "(0%)" in output


def test_progress_bar_characters():
    """Test progress bar contains expected characters."""
    captured_output = io.StringIO()
    
    with patch('sys.stdout', captured_output):
        with patch('shutil.get_terminal_size') as mock_size:
            mock_size.return_value = MagicMock(columns=80)
            with patch('time.time', return_value=1000.0):
                _progress("Custom", 50, 100, 999.0)
    
    output = captured_output.getvalue()
    
    # Should contain progress bar characters
    assert "█" in output or "░" in output  # Progress bar characters
    assert "Custom" in output
