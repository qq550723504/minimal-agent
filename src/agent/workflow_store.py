"""SQLite persistence for restartable Agent workflows."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


class WorkflowStore:
    """Persist workflow metadata, ordered steps, and lifecycle events."""

    def __init__(self, path: str):
        self.path = path
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(database_path),
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 0,
                retry_delay REAL NOT NULL DEFAULT 0.0,
                results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                failed_step INTEGER,
                created_at REAL NOT NULL,
                completed_at REAL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workflow_steps (
                workflow_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                definition_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT NOT NULL DEFAULT '',
                started_at REAL,
                completed_at REAL,
                PRIMARY KEY (workflow_id, step_index),
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                step_index INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                    ON DELETE CASCADE
            );
            """
        )
        self._connection.commit()

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _decode(value: Optional[str], default: Any = None) -> Any:
        if value is None:
            return default
        return json.loads(value)

    def _append_event(
        self,
        workflow_id: str,
        event_type: str,
        step_index: Optional[int] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO workflow_events
                (workflow_id, event_type, step_index, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (workflow_id, event_type, step_index, self._encode(payload or {}), time.time()),
        )

    def create_workflow(
        self,
        workflow_id: str,
        owner_id: str,
        steps: list[Any],
        max_retries: int,
        retry_delay: float,
    ) -> None:
        now = time.time()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO workflows
                    (workflow_id, owner_id, status, max_retries, retry_delay,
                     created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?, ?, ?)
                """,
                (workflow_id, owner_id, max_retries, retry_delay, now, now),
            )
            for step_index, definition in enumerate(steps):
                self._connection.execute(
                    """
                    INSERT INTO workflow_steps
                        (workflow_id, step_index, definition_json, status)
                    VALUES (?, ?, ?, 'pending')
                    """,
                    (workflow_id, step_index, self._encode(definition)),
                )
            self._append_event(workflow_id, "enqueued")

    def _fetch_workflow_row(
        self, workflow_id: str, owner_id: Optional[str] = None
    ) -> Optional[sqlite3.Row]:
        if owner_id is None:
            return self._connection.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        return self._connection.execute(
            "SELECT * FROM workflows WHERE workflow_id = ? AND owner_id = ?",
            (workflow_id, owner_id),
        ).fetchone()

    def _record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        workflow_id = row["workflow_id"]
        steps = self._connection.execute(
            """
            SELECT * FROM workflow_steps
            WHERE workflow_id = ?
            ORDER BY step_index
            """,
            (workflow_id,),
        ).fetchall()
        events = self._connection.execute(
            """
            SELECT event_id, event_type, step_index, payload_json, created_at
            FROM workflow_events
            WHERE workflow_id = ?
            ORDER BY event_id
            """,
            (workflow_id,),
        ).fetchall()
        return {
            "workflow_id": workflow_id,
            "owner_id": row["owner_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_retries": row["max_retries"],
            "retry_delay": row["retry_delay"],
            "results": self._decode(row["results_json"], []),
            "error": row["error"],
            "failed_step": row["failed_step"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
            "steps": [
                {
                    "step_index": step["step_index"],
                    "definition": self._decode(step["definition_json"]),
                    "status": step["status"],
                    "attempts": step["attempts"],
                    "result": self._decode(step["result_json"]),
                    "error": step["error"],
                    "started_at": step["started_at"],
                    "completed_at": step["completed_at"],
                }
                for step in steps
            ],
            "events": [
                {
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "step_index": event["step_index"],
                    "payload": self._decode(event["payload_json"], {}),
                    "created_at": event["created_at"],
                }
                for event in events
            ],
        }

    @staticmethod
    def _metadata_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workflow_id": row["workflow_id"],
            "owner_id": row["owner_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_retries": row["max_retries"],
            "retry_delay": row["retry_delay"],
            "results": json.loads(row["results_json"]),
            "error": row["error"],
            "failed_step": row["failed_step"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }

    def get_workflow(
        self, workflow_id: str, owner_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._fetch_workflow_row(workflow_id, owner_id)
            return self._record_from_row(row) if row is not None else None

    def list_workflows(
        self,
        status: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            values.append(status)
        if owner_id is not None:
            clauses.append("owner_id = ?")
            values.append(owner_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM workflows{where} ORDER BY created_at, workflow_id"
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
            return [self._metadata_from_row(row) for row in rows]

    def mark_interrupted_workflows_pending(self) -> int:
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT workflow_id FROM workflows WHERE status = 'running'"
            ).fetchall()
            now = time.time()
            for row in rows:
                workflow_id = row["workflow_id"]
                self._connection.execute(
                    """
                    UPDATE workflows
                    SET status = 'pending', updated_at = ?
                    WHERE workflow_id = ?
                    """,
                    (now, workflow_id),
                )
                self._append_event(workflow_id, "recovered")
            return len(rows)

    def list_recoverable_workflows(self) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT workflow_id FROM workflows
                WHERE status IN ('pending', 'retrying')
                ORDER BY created_at, workflow_id
                """
            ).fetchall()
            return [row["workflow_id"] for row in rows]

    def _require_workflow(self, workflow_id: str) -> sqlite3.Row:
        row = self._fetch_workflow_row(workflow_id)
        if row is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        return row

    def start_workflow(self, workflow_id: str) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            self._connection.execute(
                """
                UPDATE workflows
                SET status = 'running', attempts = attempts + 1,
                    error = '', failed_step = NULL, updated_at = ?
                WHERE workflow_id = ?
                """,
                (now, workflow_id),
            )
            self._append_event(workflow_id, "started")

    def start_step(self, workflow_id: str, step_index: int) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            cursor = self._connection.execute(
                """
                UPDATE workflow_steps
                SET status = 'running', attempts = attempts + 1, started_at = ?, error = ''
                WHERE workflow_id = ? AND step_index = ?
                """,
                (now, workflow_id, step_index),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"workflow step not found: {workflow_id}/{step_index}")
            self._append_event(workflow_id, "step_started", step_index)

    def complete_step(
        self,
        workflow_id: str,
        step_index: int,
        result: str,
        results: list[str],
    ) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            cursor = self._connection.execute(
                """
                UPDATE workflow_steps
                SET status = 'completed', result_json = ?, error = '', completed_at = ?
                WHERE workflow_id = ? AND step_index = ?
                """,
                (self._encode(result), now, workflow_id, step_index),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"workflow step not found: {workflow_id}/{step_index}")
            self._connection.execute(
                """
                UPDATE workflows
                SET results_json = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (self._encode(results), now, workflow_id),
            )
            self._append_event(
                workflow_id,
                "step_completed",
                step_index,
                {"result": result},
            )

    def retry_workflow(
        self,
        workflow_id: str,
        error: str,
        failed_step: Optional[int],
    ) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            self._connection.execute(
                """
                UPDATE workflows
                SET status = 'retrying', error = ?, failed_step = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (error, failed_step, now, workflow_id),
            )
            if failed_step is not None:
                cursor = self._connection.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'pending', error = ?, result_json = NULL,
                        started_at = NULL, completed_at = NULL
                    WHERE workflow_id = ? AND step_index = ?
                    """,
                    (error, workflow_id, failed_step),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"workflow step not found: {workflow_id}/{failed_step}")
            self._append_event(workflow_id, "retry", failed_step, {"error": error})

    def fail_workflow(
        self,
        workflow_id: str,
        error: str,
        failed_step: Optional[int],
        results: list[str],
    ) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            self._connection.execute(
                """
                UPDATE workflows
                SET status = 'failed', error = ?, failed_step = ?, results_json = ?,
                    completed_at = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (error, failed_step, self._encode(results), now, now, workflow_id),
            )
            if failed_step is not None:
                cursor = self._connection.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'failed', error = ?, completed_at = ?
                    WHERE workflow_id = ? AND step_index = ?
                    """,
                    (error, now, workflow_id, failed_step),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"workflow step not found: {workflow_id}/{failed_step}")
            self._append_event(workflow_id, "failed", failed_step, {"error": error})

    def complete_workflow(self, workflow_id: str, results: list[str]) -> None:
        with self._lock, self._connection:
            self._require_workflow(workflow_id)
            now = time.time()
            self._connection.execute(
                """
                UPDATE workflows
                SET status = 'completed', results_json = ?, error = '', failed_step = NULL,
                    completed_at = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (self._encode(results), now, now, workflow_id),
            )
            self._append_event(workflow_id, "completed")

    def close(self) -> None:
        with self._lock:
            self._connection.close()
