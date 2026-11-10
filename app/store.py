"""SQLite persistence for analysis reports.

Analyses are ephemeral by default: each report carries an expiry timestamp and
expired rows are removed on startup and on demand. SQLite keeps the prototype
dependency-light while the store interface stays small enough to replace with
PostgreSQL without touching the service layer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain import AnalysisReport

DEFAULT_RETENTION_HOURS = 24


class AnalysisStore:
    def __init__(self, db_path: Path, retention_hours: int = DEFAULT_RETENTION_HOURS) -> None:
        if retention_hours < 1:
            raise ValueError("retention_hours must be at least 1")
        self.db_path = db_path
        self.retention_hours = retention_hours
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    report_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS analyses_expiry_idx ON analyses (expires_at)"
            )

    def expiry_for(self, created_at: datetime) -> str:
        return (created_at + timedelta(hours=self.retention_hours)).isoformat()

    def save(self, report: AnalysisReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO analyses (analysis_id, created_at, expires_at, report_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    report.analysis_id,
                    report.created_at,
                    report.expires_at,
                    report.model_dump_json(),
                ),
            )

    def get(self, analysis_id: str, now: datetime | None = None) -> AnalysisReport | None:
        current = (now or datetime.now(UTC)).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM analyses WHERE analysis_id = ? AND expires_at > ?",
                (analysis_id, current),
            ).fetchone()
        if row is None:
            return None
        return AnalysisReport.model_validate_json(row["report_json"])

    def delete(self, analysis_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM analyses WHERE analysis_id = ?", (analysis_id,)
            )
            return cursor.rowcount > 0

    def purge_expired(self, now: datetime | None = None) -> int:
        current = (now or datetime.now(UTC)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM analyses WHERE expires_at <= ?", (current,))
            return cursor.rowcount
