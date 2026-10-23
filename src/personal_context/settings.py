"""Portable settings shared by generation and query entrypoints."""

import os
from zoneinfo import ZoneInfo


def configured_timezone(value=None):
    """Use an explicit IANA zone, the operator's private setting, or UTC."""
    name = value if value is not None else os.environ.get("PERSONAL_CONTEXT_TIMEZONE", "UTC")
    ZoneInfo(name)  # Fail explicitly on invalid configuration.
    return name
