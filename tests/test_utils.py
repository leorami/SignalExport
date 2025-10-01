from signal_export.utils import safe, first_name, looks_unknown


def test_safe_truncates_and_sanitizes():
    assert safe("a/b:c") == "a_b_c"
    assert safe("") == "unknown"


def test_first_name():
    assert first_name("Alice Bob") == "Alice"
    assert first_name("") == ""


def test_looks_unknown():
    assert looks_unknown("conv:123")
    assert looks_unknown("+1 555 1212")
    assert not looks_unknown("Alice")
