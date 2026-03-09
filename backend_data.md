# Backend Data Contract — Antartia Agent → Server

Describes every payload the agent sends to the Railway server.

---

## Auth

All requests include:

```
Authorization: Bearer <REMOTE_SYNC_API_KEY>
Content-Type: application/json   (multipart/form-data for photo uploads)
```

---

## POST `/api/track`

Full GPS route as GeoJSON. Sent by `publish_route_snapshot`.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [-68.3, -54.8],
          [-67.85, -55.42],
          [-56.85, -63.38]
        ]
      },
      "properties": {
        "recorded_at": ["2026-03-17T18:00:00Z", "2026-03-18T00:00:00Z"],
        "total_points": 73,
        "distance_km": 1240.42,
        "last_updated": "2026-03-20T18:00:00Z"
      }
    }
  ]
}
```

---

## POST `/api/weather`

Latest weather snapshot. Sent by `publish_weather_snapshot`.

```json
{
  "latitude": -63.38,
  "longitude": -56.85,
  "temperature": 3.7,
  "apparent_temperature": 0.7,
  "wind_speed": 23.4,
  "wind_gusts": 31.2,
  "wind_direction": 220,
  "precipitation": 0.0,
  "snowfall": 0.0,
  "condition": "Partly cloudy",
  "recorded_at": "2026-03-20T18:00:00Z"
}
```

---

## POST `/api/photos`

Photo upload with metadata. Sent by `upload_image`. Multipart form-data.

**Form fields:**

| Field | Type | Description |
|-------|------|-------------|
| `file` | binary | JPEG (preprocessed, max 2048px) |
| `metadata` | JSON string | see below |

**`metadata` JSON:**

```json
{
  "file_name": "IMG_0423.jpg",
  "recorded_at": "2026-03-20T10:32:00Z",
  "latitude": -63.35,
  "longitude": -57.20,
  "significance_score": 0.91,
  "vision_description": "A colony of Adélie penguins on volcanic rock, approximately 200 individuals visible. Brown Bluff's distinctive red-brown cliffs rise in the background.",
  "vision_summary": "Adélie colony at Brown Bluff",
  "agent_quote": "Standing at Brown Bluff as the colony erupted into motion — this is what we came for.",
  "width": 1920,
  "height": 1440
}
```

`agent_quote` is `null` on most photos. Only set on 1–2 images per day that the agent considers truly remarkable.

---

## POST `/api/reflections`

Daily reflection. Sent by `publish_reflection`.

```json
{
  "date": "2026-03-20",
  "content": "The ship moved through the Antarctic Sound today, threading between tabular icebergs that dwarfed the vessel...",
  "created_at": "2026-03-20T21:03:00Z"
}
```

---

## POST `/api/route-analysis`

Navigation snapshot. Sent by `publish_route_analysis`.

```json
{
  "analyzed_at": "2026-03-20T18:44:00Z",
  "date": "2026-03-20",
  "window_hours": 12,
  "position": {
    "latitude": -63.3733,
    "longitude": -56.8551
  },
  "bearing_deg": 75.8,
  "bearing_compass": "ENE",
  "speed_kmh": 9.1,
  "avg_speed_kmh": 8.4,
  "distance_km": 98.3,
  "stopped": false,
  "wind": {
    "speed_kmh": 23.4,
    "direction_deg": 220,
    "angle_label": "beam reach"
  },
  "nearest_sites": [
    {
      "name": "Hope Bay",
      "distance_km": 6.5,
      "bearing_compass": "W",
      "eta_hours": 0.8
    },
    {
      "name": "Antarctic Sound",
      "distance_km": 12.2,
      "bearing_compass": "ESE",
      "eta_hours": 1.5
    }
  ],
  "summary": "Route analysis — 2026-03-20 18:44 UTC  (last 12h window)\n..."
}
```

---

## POST `/api/messages`

Short agent dispatch. Sent by `publish_agent_message`.

```json
{
  "content": "Zodiac landing confirmed at Brown Bluff. 68 passengers ashore. Adélie colony active, juveniles in crèche phase. Air temp -2°C, wind 15 km/h SW.",
  "published_at": "2026-03-20T11:52:00Z"
}
```

---

## POST `/api/progress`

Expedition-wide running totals. Sent by `publish_daily_progress`. Always reflects the **full expedition so far** — the server overwrites the previous snapshot.

```json
{
  "expedition_day": 4,
  "distance_km_total": 1240.42,
  "photos_captured_total": 3421,
  "wildlife_spotted_total": 12,
  "temperature_min_all_time": -45.0,
  "temperature_max_all_time": -12.0,
  "current_position": {
    "latitude": -63.3733,
    "longitude": -56.8551
  },
  "published_at": "2026-03-20T21:00:00Z"
}
```
