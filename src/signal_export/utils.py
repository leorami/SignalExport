from __future__ import annotations
import re


def safe(name: str) -> str:
    """Sanitize a string for filesystem/HTML-friendly names."""
    name = (name or "unknown").strip()
    name = re.sub(r'[/\\:*?"<>|]+', "_", name)
    return name[:120] or "unknown"


def first_name(full: str) -> str:
    if not full:
        return ""
    parts = re.split(r"[\s·•|,]+", full.strip())
    return parts[0] if parts else full


def looks_unknown(label: str) -> bool:
    if not label or label.startswith("conv:"):
        return True
    if re.fullmatch(r"\+?\d[\d\s\-\(\)]{3,}", label or ""):
        return True
    if re.fullmatch(r"[0-9a-fA-F-]{8,}", label or ""):
        return True
    return False
