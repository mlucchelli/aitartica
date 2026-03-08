from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class ActivityLogsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        session_id: str,
        action_type: str,
        payload: str,
        result: str,
    ) -> dict:
        created_at = datetime.now(timezone.utc).isoformat()
        async with self._db.conn.execute(
            """INSERT INTO activity_logs (session_id, action_type, payload, result, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, action_type, payload[:500], result[:500], created_at),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return {
            "id": row_id,
            "session_id": session_id,
            "action_type": action_type,
            "created_at": created_at,
        }

    async def get_by_range(self, from_dt: str | None, to_dt: str | None) -> list[dict]:
        if from_dt and to_dt:
            async with self._db.conn.execute(
                """SELECT * FROM activity_logs
                   WHERE created_at >= ? AND created_at <= ?
                   ORDER BY created_at ASC""",
                (from_dt, to_dt),
            ) as cur:
                rows = await cur.fetchall()
        elif from_dt:
            async with self._db.conn.execute(
                "SELECT * FROM activity_logs WHERE created_at >= ? ORDER BY created_at ASC",
                (from_dt,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.conn.execute(
                "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 100"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_today(self, session_id: str | None = None) -> list[dict]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id:
            async with self._db.conn.execute(
                """SELECT * FROM activity_logs
                   WHERE created_at >= ? AND session_id = ?
                   ORDER BY created_at ASC""",
                (today, session_id),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.conn.execute(
                "SELECT * FROM activity_logs WHERE created_at >= ? ORDER BY created_at ASC",
                (today,),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
