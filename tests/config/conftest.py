"""
Fixtures for configuration tests.

These need pydantic (the ``api`` extra) but no database, so they live outside
``tests/integration``, whose autouse ``clean_tables`` fixture would otherwise
spin up a PostgreSQL for every test in the directory.
"""

import pytest

pytest.importorskip("pydantic")
