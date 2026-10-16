"""Driving estimates use fresh phone observations, never the server's location."""
from datetime import datetime, timezone
import math
import time


def fresh_location(db, *, now=None):
    now = time.time() if now is None else now
    row = db.execute("SELECT event_ts,lat,lon,accuracy FROM events WHERE event_type='location' ORDER BY event_ts DESC LIMIT 1").fetchone()
    if not row or any(type(n) not in (float, int) or not math.isfinite(n) for n in row):
        raise ValueError('a fresh phone location is required for automatic driving time')
    observed, latitude, longitude, accuracy = row
    if not -30 <= now - observed <= 300 or not 0 <= accuracy <= 250 or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('phone location is stale, inaccurate, or invalid; refresh phone location first')
    return dict(latitude=latitude, longitude=longitude, age_seconds=max(0, now - observed),
                observed_at=datetime.fromtimestamp(observed, timezone.utc).isoformat())


def estimate(destination, arrival_at):
    from iphone_context.read_mcp import open_archive
    from .apple_write_worker import read_native
    try:
        db = open_archive('travel')
        try: origin = fresh_location(db)
        finally: db.close()
    except Exception as exc:
        raise ValueError('automatic driving requires a configured encrypted travel archive and a phone location within five minutes') from exc
    result = read_native('calendar', dict(operation='driving_eta', destination=destination,
                        arrival_at=arrival_at, origin=origin))
    if result.get('success') is not True:
        raise ValueError('Apple Maps driving estimate unavailable: ' + result.get('error_code', 'route_unavailable'))
    return result['driving']
