"""Shared fixtures for feature query tests.

Re-exports the migrated_pool fixture from tests/db/conftest.py so that
feature tests have the full schema available via the same pattern.
"""

from tests.db.conftest import migrated_pool

__all__ = ["migrated_pool"]
