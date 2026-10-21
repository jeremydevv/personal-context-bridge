"""Bounded read-only queries over the iPhone SQLCipher archives."""

from __future__ import annotations

from datetime import date, datetime, timezone
import time


def epoch_range(start: str, end: str, *, milliseconds: bool) -> tuple[int, int]:
    def parse(value: str) -> datetime:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("start and end need timezone offsets")
        return instant.astimezone(timezone.utc)

    start_dt, end_dt = parse(start), parse(end)
    if not start_dt < end_dt or (end_dt - start_dt).total_seconds() > 366 * 86400:
        raise ValueError("range must be positive and at most 366 days")
    factor = 1000 if milliseconds else 1
    return int(start_dt.timestamp() * factor), int(end_dt.timestamp() * factor)


def bounded_limit(limit: int, maximum: int = 200) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be 1..{maximum}")
    return limit


def bounded_offset(offset: int) -> int:
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100_000:
        raise ValueError("offset must be 0..100000")
    return offset


class HealthQueries:
    def __init__(self, db):
        self.db = db

    def status(self) -> dict:
        last, batches = self.db.execute("SELECT max(received_at), count(*) FROM batches").fetchone()
        samples = self.db.execute("SELECT count(*) FROM samples").fetchone()[0]
        return {"source": "apple_health", "last_received_at": last,
                "batch_count": batches, "sample_count": samples}

    def types(self, limit: int = 100) -> dict:
        limit = bounded_limit(limit, 100)
        rows = self.db.execute(
            "SELECT type, kind, count(*), min(start_ms), max(start_ms) FROM samples "
            "GROUP BY type, kind ORDER BY count(*) DESC LIMIT ?", (limit,)).fetchall()
        return {"last_received_at": self.status()["last_received_at"],
                "types": [{"type": r[0], "kind": r[1], "count": r[2],
                           "first_ms": r[3], "last_ms": r[4]} for r in rows]}

    def samples(self, health_type: str, start: str, end: str, limit: int = 100) -> dict:
        if not health_type or len(health_type) > 200:
            raise ValueError("health_type must be 1..200 characters")
        lo, hi = epoch_range(start, end, milliseconds=True)
        limit = bounded_limit(limit)
        rows = self.db.execute(
            "SELECT uuid, kind, start_ms, end_ms, value, unit, category, source_name, device "
            "FROM samples WHERE type=? AND start_ms>=? AND start_ms<? "
            "ORDER BY start_ms DESC LIMIT ?", (health_type, lo, hi, limit)).fetchall()
        return {"type": health_type, "last_received_at": self.status()["last_received_at"],
                "samples": [{"id": r[0], "kind": r[1], "start_ms": r[2], "end_ms": r[3],
                             "value": r[4], "unit": r[5], "category": r[6],
                             "source": r[7], "device": r[8]} for r in rows]}

    def aggregates(self, health_type: str, start: str, end: str, limit: int = 200) -> dict:
        if not health_type or len(health_type) > 200:
            raise ValueError("health_type must be 1..200 characters")
        lo, hi = epoch_range(start, end, milliseconds=True)
        limit = bounded_limit(limit)
        rows = self.db.execute(
            "SELECT func, interval_value, interval_unit, device_filter, bucket_start_ms, "
            "bucket_end_ms, value, unit FROM aggregates WHERE type=? AND bucket_start_ms>=? "
            "AND bucket_start_ms<? ORDER BY bucket_start_ms DESC LIMIT ?",
            (health_type, lo, hi, limit)).fetchall()
        return {"type": health_type, "last_received_at": self.status()["last_received_at"],
                "aggregates": [{"function": r[0], "interval_value": r[1], "interval_unit": r[2],
                                "device_filter": r[3], "start_ms": r[4], "end_ms": r[5],
                                "value": r[6], "unit": r[7]} for r in rows]}

    def workouts(self, start: str, end: str, limit: int = 50) -> dict:
        lo, hi = epoch_range(start, end, milliseconds=True)
        limit = bounded_limit(limit, 100)
        rows = self.db.execute(
            "SELECT uuid, type, start_ms, end_ms, source_name, device, line FROM samples "
            "WHERE kind='workout' AND start_ms>=? AND start_ms<? "
            "ORDER BY start_ms DESC LIMIT ?", (lo, hi, limit)).fetchall()
        import json
        return {"last_received_at": self.status()["last_received_at"],
                "workouts": [{"id": r[0], "type": r[1], "start_ms": r[2], "end_ms": r[3],
                              "source": r[4], "device": r[5],
                              "details": json.loads(r[6]).get("workout")} for r in rows]}

    def activity_days(self, start_day: str, end_day: str, limit: int = 100) -> dict:
        try:
            start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
        except (TypeError, ValueError) as exc:
            raise ValueError("days must be YYYY-MM-DD") from exc
        if start.isoformat() != start_day or end.isoformat() != end_day or not start < end or (end - start).days > 366:
            raise ValueError("day range must be positive and at most 366 days")
        limit = bounded_limit(limit)
        rows = self.db.execute(
            "SELECT date,move_kcal,move_goal_kcal,exercise_min,exercise_goal_min,"
            "stand_hours,stand_goal_hours,move_mode,move_time_min,move_time_goal_min,updated_at "
            "FROM activity_summaries WHERE date>=? AND date<? ORDER BY date DESC LIMIT ?",
            (start_day, end_day, limit)).fetchall()
        keys = ("date", "move_kcal", "move_goal_kcal", "exercise_min", "exercise_goal_min",
                "stand_hours", "stand_goal_hours", "move_mode", "move_time_min", "move_time_goal_min", "updated_at")
        return {"last_received_at": self.status()["last_received_at"],
                "days": [dict(zip(keys, row)) for row in rows]}

    def workout_route(self, workout_id: str, limit: int = 200, offset: int = 0) -> dict:
        if not isinstance(workout_id, str) or not 1 <= len(workout_id) <= 128:
            raise ValueError("workout_id must be a nonempty archived workout ID")
        limit, offset = bounded_limit(limit), bounded_offset(offset)
        total = self.db.execute("SELECT count(*) FROM route_points WHERE workout_uuid=?", (workout_id,)).fetchone()[0]
        rows = self.db.execute(
            "SELECT t_ms,lat,lon,alt,h_acc,v_acc,speed,course FROM route_points "
            "WHERE workout_uuid=? ORDER BY t_ms LIMIT ? OFFSET ?", (workout_id, limit, offset)).fetchall()
        keys = ("timestamp_ms", "latitude", "longitude", "altitude_m", "horizontal_accuracy_m",
                "vertical_accuracy_m", "speed_mps", "course_degrees")
        return {"workout_id": workout_id, "total": total, "offset": offset,
                "last_received_at": self.status()["last_received_at"],
                "points": [dict(zip(keys, row)) for row in rows]}

    def workout_series(self, workout_id: str, limit: int = 200, offset: int = 0) -> dict:
        if not isinstance(workout_id, str) or not 1 <= len(workout_id) <= 128:
            raise ValueError("workout_id must be a nonempty archived workout ID")
        limit, offset = bounded_limit(limit), bounded_offset(offset)
        total = self.db.execute("SELECT count(*) FROM series_points WHERE workout_uuid=?", (workout_id,)).fetchone()[0]
        rows = self.db.execute(
            "SELECT type,t_ms,value,unit FROM series_points WHERE workout_uuid=? "
            "ORDER BY t_ms,type LIMIT ? OFFSET ?", (workout_id, limit, offset)).fetchall()
        return {"workout_id": workout_id, "total": total, "offset": offset,
                "last_received_at": self.status()["last_received_at"],
                "points": [{"type": r[0], "timestamp_ms": r[1], "value": r[2], "unit": r[3]}
                           for r in rows]}


class TravelQueries:
    def __init__(self, db):
        self.db = db

    def status(self) -> dict:
        last, events = self.db.execute("SELECT max(received_ts), count(*) FROM events").fetchone()
        locations = self.db.execute("SELECT count(*) FROM events WHERE event_type='location'").fetchone()[0]
        fix, receipt = self.db.execute("SELECT max(event_ts),max(received_ts) FROM events WHERE event_type='location'").fetchone()
        now = time.time()
        age = max(0, now-fix) if fix else None
        recent = self.db.execute("SELECT sum(received_ts>=?),sum(received_ts>=?) FROM events WHERE event_type='location'", (now-86400,now-7*86400)).fetchone()
        historical = self.db.execute("SELECT count(*) FROM timeline_segments").fetchone()[0]
        last_import = self.db.execute("SELECT max(imported_ts) FROM timeline_imports").fetchone()[0]
        return {"source": "iphone_location", "last_received_unix": last,
                "event_count": events, "location_count": locations,
                "last_location_received_unix":receipt,"last_location_fix_unix":fix,
                "location_age_seconds":round(age) if age is not None else None,
                "location_freshness":"unknown" if age is None else ("recent" if age<=3600 else "stale_or_stationary"),
                "location_receipts_24h":recent[0] or 0,"location_receipts_7d":recent[1] or 0,
                "historical_segment_count": historical, "last_historical_import_unix": last_import}

    def locations(self, start: str, end: str, limit: int = 200) -> dict:
        lo, hi = epoch_range(start, end, milliseconds=False)
        limit = bounded_limit(limit)
        rows = self.db.execute(
            "SELECT digest, event_ts, lat, lon, accuracy, topic FROM events "
            "WHERE event_type='location' AND event_ts>=? AND event_ts<? "
            "ORDER BY event_ts DESC LIMIT ?", (lo, hi, limit)).fetchall()
        return {"last_received_unix": self.status()["last_received_unix"],
                "locations": [{"id": r[0], "timestamp": r[1], "latitude": r[2],
                               "longitude": r[3], "accuracy_m": r[4], "topic": r[5]} for r in rows]}

    def event(self, event_id: str) -> dict:
        if len(event_id) != 64 or any(c not in "0123456789abcdef" for c in event_id):
            raise ValueError("event_id must be a SHA-256 hex digest from travel_locations")
        row = self.db.execute("SELECT payload, received_ts FROM events WHERE digest=?", (event_id,)).fetchone()
        if row is None:
            return {"found": False}
        import json
        return {"found": True, "event": json.loads(row[0]), "received_unix": row[1]}

    def historical_segments(self, start: str, end: str, kind: str = "all", limit: int = 100) -> dict:
        lo, hi = epoch_range(start, end, milliseconds=False)
        limit = bounded_limit(limit)
        if kind not in ("all", "visit", "activity", "path", "other"):
            raise ValueError("kind must be all, visit, activity, path, or other")
        sql = ("SELECT digest,kind,start_ts,end_ts,lat,lon,place_id,source, "
               "json_extract(payload,'$.visit.topCandidate.semanticType'), "
               "json_extract(payload,'$.visit.probability'), "
               "json_extract(payload,'$.activity.topCandidate.type'), "
               "json_extract(payload,'$.activity.distanceMeters'), "
               "json_array_length(payload,'$.timelinePath') "
               "FROM timeline_segments WHERE end_ts>=? AND start_ts<?")
        args: list = [lo, hi]
        if kind != "all":
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY start_ts DESC LIMIT ?"
        args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        return {"last_historical_import_unix": self.status()["last_historical_import_unix"],
                "segments": [{"id": r[0], "kind": r[1], "start_unix": r[2],
                              "end_unix": r[3], "latitude": r[4], "longitude": r[5],
                              "place_id": r[6], "source": r[7],
                              "semantic_type": r[8], "visit_probability": r[9],
                              "activity_type": r[10], "distance_m": r[11],
                              "path_points": r[12]} for r in rows]}

    def historical_segment(self, segment_id: str) -> dict:
        if len(segment_id) != 64 or any(c not in "0123456789abcdef" for c in segment_id):
            raise ValueError("segment_id must be a SHA-256 hex digest from read_historical_travel_segments")
        row = self.db.execute(
            "SELECT payload,source,first_import_run FROM timeline_segments WHERE digest=?",
            (segment_id,),
        ).fetchone()
        if row is None:
            return {"found": False}
        import json
        return {"found": True, "segment": json.loads(row[0]), "source": row[1],
                "first_import_run": row[2]}
