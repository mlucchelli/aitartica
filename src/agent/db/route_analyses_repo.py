from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.db.database import Database


class RouteAnalysesRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, analysis: "RouteAnalysis") -> int:  # type: ignore[name-defined]
        now = datetime.now(timezone.utc).isoformat()
        sites_json = json.dumps([
            {
                "name": s.name,
                "distance_km": s.distance_km,
                "bearing_deg": s.bearing_deg,
                "bearing_compass": s.bearing_compass,
                "eta_hours": s.eta_hours,
            }
            for s in analysis.nearest_sites
        ])
        async with self._db.conn.execute(
            """
            INSERT INTO route_analyses
                (analyzed_at, date, window_hours, latitude, longitude, point_count,
                 bearing_deg, bearing_compass, speed_kmh, avg_speed_kmh,
                 distance_km, stopped, wind_speed_kmh, wind_direction_deg,
                 wind_angle_label, nearest_sites_json, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.analyzed_at,
                analysis.date,
                analysis.window_hours,
                analysis.latitude,
                analysis.longitude,
                analysis.point_count,
                analysis.bearing_deg,
                analysis.bearing_compass,
                analysis.speed_kmh,
                analysis.avg_speed_kmh,
                analysis.distance_km,
                1 if analysis.stopped else 0,
                analysis.wind_speed_kmh,
                analysis.wind_direction_deg,
                analysis.wind_angle_label,
                sites_json,
                analysis.to_text(),
                now,
            ),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.conn.commit()
        return row_id  # type: ignore[return-value]

    async def get_recent(self, limit: int = 5) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM route_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_date(self, date: str) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT * FROM route_analyses WHERE date = ? ORDER BY id DESC",
            (date,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_by_id(self, analysis_id: int) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM route_analyses WHERE id = ?", (analysis_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_latest_by_date(self, date: str) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM route_analyses WHERE date = ? ORDER BY id DESC LIMIT 1",
            (date,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_latest(self) -> dict | None:
        async with self._db.conn.execute(
            "SELECT * FROM route_analyses ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None
