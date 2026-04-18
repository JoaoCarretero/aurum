"""core.data — data layer subpackage.

Legacy ``from core.data import fetch_all`` continues to work via
re-export from core.data.base.
"""
from core.data.base import fetch, fetch_all, fetch_mt5, validate  # noqa: F401
