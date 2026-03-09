from __future__ import annotations

from datetime import datetime, timezone

from agent.db.database import Database


class TokenUsageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        model: str,
        call_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            INSERT INTO token_usage
                (session_id, model, call_type, prompt_tokens, completion_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, model, call_type, prompt_tokens, completion_tokens, now),
        )
        await self._db.conn.commit()

    async def get_total(self) -> dict:
        cursor = await self._db.conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0) FROM token_usage"
        )
        row = await cursor.fetchone()
        prompt = int(row[0])
        completion = int(row[1])
        return {"prompt": prompt, "completion": completion, "total": prompt + completion}

    async def get_by_session(self, session_id: str) -> dict:
        cursor = await self._db.conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0) FROM token_usage WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        prompt = int(row[0])
        completion = int(row[1])
        return {"prompt": prompt, "completion": completion, "total": prompt + completion}

    async def get_by_call_type(self) -> list[dict]:
        cursor = await self._db.conn.execute(
            """
            SELECT call_type,
                   SUM(prompt_tokens)     AS prompt,
                   SUM(completion_tokens) AS completion,
                   COUNT(*)              AS calls
            FROM token_usage
            GROUP BY call_type
            ORDER BY call_type
            """
        )
        rows = await cursor.fetchall()
        return [
            {
                "call_type": r[0],
                "prompt_tokens": int(r[1]),
                "completion_tokens": int(r[2]),
                "total_tokens": int(r[1]) + int(r[2]),
                "calls": int(r[3]),
            }
            for r in rows
        ]
