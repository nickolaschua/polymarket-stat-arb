"""Shared fixtures for analysis tests.

Re-exports the migrated_pool fixture from tests/db/conftest.py.
"""

from tests.db.conftest import migrated_pool

__all__ = ["migrated_pool"]
