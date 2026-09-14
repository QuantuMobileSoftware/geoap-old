"""Per-unit telemetry aggregation for GET /api/units/telemetry.
"""
import statistics
from collections import namedtuple

from django.db import connection
from django.db.models import Q

from user.alert_config import TRACK_POINT_CAP
from user.alerts import evaluate_unit_alerts
from user.models import EdgeCoverage, EdgePrediction

SIMPLIFY_TOLERANCE_M = 5
BUCKET_MINUTES = 15

StreamRow = namedtuple('StreamRow', ['ts', 'source', 'image_path', 'det', 'location'])


def _window_q(start, end):
    return (
        Q(captured_at__gte=start, captured_at__lt=end)
        | Q(captured_at__isnull=True, created_at__gte=start, created_at__lt=end)
    )


def fetch_stream(serial, user, start, end):
    """Merged, time-ordered coverage + prediction rows for one camera.
    Filters on both serial and chunk.user to check ownership."""
    coverage_rows = EdgeCoverage.objects.filter(
        serial=serial, chunk__user=user,
    ).filter(_window_q(start, end)).values('captured_at', 'created_at', 'image_path', 'location')

    prediction_rows = EdgePrediction.objects.filter(
        serial=serial, chunk__user=user,
    ).filter(_window_q(start, end)).values('captured_at', 'created_at', 'image_path', 'predictions', 'location')

    stream = []
    for row in coverage_rows:
        ts = row['captured_at'] or row['created_at']
        stream.append(StreamRow(
            ts=ts, source='coverage', image_path=row['image_path'], det=0, location=row['location'],
        ))
    for row in prediction_rows:
        ts = row['captured_at'] or row['created_at']
        det = len(row['predictions']) if row['predictions'] else 0
        stream.append(StreamRow(
            ts=ts, source='prediction', image_path=row['image_path'], det=det, location=row['location'],
        ))

    stream.sort(key=lambda r: (r.ts, r.source))
    return stream


def _compute_totals(stream):
    messages = len(stream)
    images = sum(1 for r in stream if r.image_path)
    detections = sum(r.det for r in stream)
    first_at = stream[0].ts if stream else None
    last_at = stream[-1].ts if stream else None
    return {
        'messages': messages,
        'images': images,
        'detections': detections,
        'first_at': first_at,
        'last_at': last_at,
    }


def _bucket_count(start, end):
    total_minutes = (end - start).total_seconds() / 60
    return int(total_minutes // BUCKET_MINUTES)


def _compute_buckets_and_gap(coverage_stream, start, end):
    """Coverage-only: predictions must not count as a liveness signal."""
    n_buckets = _bucket_count(start, end)
    buckets = [0] * n_buckets

    if not coverage_stream:
        return buckets, 0

    timestamps = [r.ts for r in coverage_stream]

    if len(timestamps) < 2:
        expected = 1
    else:
        deltas = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
        median_gap_seconds = statistics.median(deltas)
        expected = max(1, round(900 / median_gap_seconds)) if median_gap_seconds > 0 else 1

    counts = [0] * n_buckets
    for ts in timestamps:
        idx = int((ts - start).total_seconds() // (BUCKET_MINUTES * 60))
        if 0 <= idx < n_buckets:
            counts[idx] += 1

    for i, count in enumerate(counts):
        if count == 0:
            buckets[i] = 0
        elif count >= expected:
            buckets[i] = 2
        else:
            buckets[i] = 1

    first_idx = min(max(int((timestamps[0] - start).total_seconds() // (BUCKET_MINUTES * 60)), 0), n_buckets - 1)
    last_idx = min(max(int((timestamps[-1] - start).total_seconds() // (BUCKET_MINUTES * 60)), 0), n_buckets - 1)
    empty_buckets = sum(1 for c in counts[first_idx:last_idx + 1] if c == 0)
    gap_minutes = empty_buckets * BUCKET_MINUTES

    return buckets, gap_minutes


_WINDOW_SQL = (
    "(captured_at >= %(start)s AND captured_at < %(end)s) "
    "OR (captured_at IS NULL AND created_at >= %(start)s AND created_at < %(end)s)"
)

_TRACK_SQL = f"""
WITH stream AS (
    SELECT location, COALESCE(captured_at, created_at) AS ts
    FROM user_edgecoverage
    WHERE serial = %(serial)s
      AND chunk_id IN (SELECT id FROM user_stonesdetectionchunk WHERE user_id = %(user_id)s)
      AND ({_WINDOW_SQL})
    UNION ALL
    SELECT location, COALESCE(captured_at, created_at) AS ts
    FROM user_edgeprediction
    WHERE serial = %(serial)s
      AND chunk_id IN (SELECT id FROM user_stonesdetectionchunk WHERE user_id = %(user_id)s)
      AND ({_WINDOW_SQL})
),
line AS (
    -- location is geography; ST_MakeLine only accepts geometry, so cast explicitly.
    -- ST_Length below casts back to geography to get metres, not degrees.
    SELECT ST_MakeLine(location::geometry ORDER BY ts) FILTER (WHERE location IS NOT NULL) AS geom
    FROM stream
),
simplified AS (
    SELECT ST_Transform(
        ST_SimplifyPreserveTopology(ST_Transform(line.geom, 3857), %(tolerance)s),
        4326
    ) AS geom
    FROM line
),
dumped AS (
    SELECT (ST_DumpPoints(simplified.geom)).path[1] AS seq,
           (ST_DumpPoints(simplified.geom)).geom AS pt
    FROM simplified
)
SELECT
    (SELECT ST_Length(geom::geography) FROM line) AS distance_m,
    ST_X(dumped.pt) AS lng,
    ST_Y(dumped.pt) AS lat
FROM dumped
ORDER BY dumped.seq
"""


def _fetch_distance_and_simplified_track(serial, user, start, end):
    params = {
        'serial': serial,
        'user_id': user.id,
        'tolerance': SIMPLIFY_TOLERANCE_M,
        'start': start,
        'end': end,
    }
    with connection.cursor() as cursor:
        cursor.execute(_TRACK_SQL, params)
        rows = cursor.fetchall()

    if not rows:
        return 0.0, []

    distance_m = rows[0][0] or 0.0
    points = [(row[1], row[2]) for row in rows]
    return distance_m, points


def _row_matches_point(row, lng, lat, epsilon):
    return abs(row.location.x - lng) < epsilon and abs(row.location.y - lat) < epsilon


def _reattach_track_metadata(stream, simplified_points, epsilon=1e-5):
    """Matches simplified points back to source rows by coordinate -
    simplification only removes points, never adds new ones. Several rows
    can share one coordinate (stationary unit, stuck GPS clock); every
    matching row is aggregated into the point instead of only the first,
    and enough rows are always held back for the remaining points so none
    are silently dropped."""
    located = [r for r in stream if r.location is not None]
    n_points = len(simplified_points)
    track = []
    j = 0
    for point_index, (lng, lat) in enumerate(simplified_points):
        remaining_after = n_points - point_index - 1

        while j < len(located) - 1 and not _row_matches_point(located[j], lng, lat, epsilon):
            j += 1

        matched = []
        while j < len(located) and _row_matches_point(located[j], lng, lat, epsilon) \
                and len(located) - j > remaining_after:
            matched.append(located[j])
            j += 1
        if not matched and j < len(located):
            matched.append(located[j])
            j += 1

        if matched:
            track.append({
                't': matched[-1].ts,
                'lat': lat,
                'lng': lng,
                'img': any(bool(row.image_path) for row in matched),
                'det': sum(row.det for row in matched),
            })
        else:
            track.append({'t': None, 'lat': lat, 'lng': lng, 'img': False, 'det': 0})
    return track


def _stride_sample(track, cap):
    if len(track) <= cap:
        return track
    stride = len(track) / cap
    return [track[int(i * stride)] for i in range(cap)]


def _compute_distance_and_track(serial, user, start, end, stream):
    located = [r for r in stream if r.location is not None]

    # ST_MakeLine needs at least 2 points; handle 0/1 directly.
    if len(located) == 0:
        return 0.0, []
    if len(located) == 1:
        row = located[0]
        return 0.0, [{
            't': row.ts, 'lat': row.location.y, 'lng': row.location.x,
            'img': bool(row.image_path), 'det': row.det,
        }]

    distance_m, simplified_points = _fetch_distance_and_simplified_track(serial, user, start, end)
    distance_km = round(distance_m / 1000, 1)

    track = _reattach_track_metadata(stream, simplified_points)
    track = _stride_sample(track, TRACK_POINT_CAP)

    return distance_km, track


def build_unit_telemetry(camera, user, start, end, last_received_at, now):
    serial = camera.cam_serial_num
    stream = fetch_stream(serial, user, start, end)
    coverage_stream = [r for r in stream if r.source == 'coverage']

    totals = _compute_totals(stream)
    buckets, gap_minutes = _compute_buckets_and_gap(coverage_stream, start, end)
    distance_km, track = _compute_distance_and_track(serial, user, start, end, stream)

    totals['distance_km'] = distance_km
    totals['gap_minutes'] = gap_minutes

    return {
        'unit_id': serial,
        'track': track,
        'buckets': buckets,
        'totals': totals,
        'alerts': evaluate_unit_alerts(stream, last_received_at, now),
    }


def build_unit_range_totals(camera, user, start, end):
    """Totals for an arbitrary sub-range of a unit's already-fetched window."""
    serial = camera.cam_serial_num
    stream = fetch_stream(serial, user, start, end)
    coverage_stream = [r for r in stream if r.source == 'coverage']

    totals = _compute_totals(stream)
    _, gap_minutes = _compute_buckets_and_gap(coverage_stream, start, end)
    totals['gap_minutes'] = gap_minutes

    located = [r for r in stream if r.location is not None]
    if len(located) < 2:
        totals['distance_km'] = 0.0
    else:
        distance_m, _ = _fetch_distance_and_simplified_track(serial, user, start, end)
        totals['distance_km'] = round(distance_m / 1000, 1)

    return totals
