"""Which database errors are reported as 503 (no PostgreSQL or Elasticsearch needed)."""

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from app.main import is_database_unavailable


class DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("exc", "unavailable"),
    [
        (ConnectionRefusedError(111, "Connection refused"), True),
        (TimeoutError(), True),
        (OperationalError("SELECT 1", None, DriverError("XX000")), True),
        (DBAPIError("SELECT 1", None, DriverError("57P01")), True),  # admin shutdown
        (DBAPIError("SELECT 1", None, DriverError("08006")), True),  # connection failure
        (DBAPIError("SELECT 1", None, DriverError("XX000"), connection_invalidated=True), True),
        (ProgrammingError("SELEC 1", None, DriverError("42601")), False),  # a bug, not an outage
        (DBAPIError("SELECT 1", None, DriverError("23505")), False),
    ],
)
def test_is_database_unavailable(exc, unavailable):
    assert is_database_unavailable(exc) is unavailable
