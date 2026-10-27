"""Tầng truy cập dữ liệu (CQL) cho hệ thống Weather Station.

Mọi truy vấn đều đi theo nguyên tắc Query-driven design: có Partition Key đầy đủ
(station_id, log_date), lọc thời gian trên Clustering Key ts, KHÔNG sort ở tầng ứng dụng.
"""
import time
from datetime import date, datetime, timedelta, timezone

from cassandra.concurrent import execute_concurrent_with_args

from db import get_session

METRICS = ("temperature", "humidity", "pressure")

DEFAULT_SENSORS = {
    "temperature": {"unit": "°C", "min_value": 15.0, "max_value": 38.0},
    "humidity": {"unit": "%", "min_value": 30.0, "max_value": 95.0},
    "pressure": {"unit": "hPa", "min_value": 990.0, "max_value": 1030.0},
}

# ---------------------------------------------------------------- CQL
Q_INSERT_STATION = (
    "INSERT INTO stations (station_id, name, location, latitude, longitude, status, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) IF NOT EXISTS"
)
Q_UPDATE_STATION = (
    "UPDATE stations SET name=?, location=?, latitude=?, longitude=?, status=? "
    "WHERE station_id=? IF EXISTS"
)
Q_GET_STATION = "SELECT * FROM stations WHERE station_id=?"
Q_LIST_STATIONS = "SELECT * FROM stations"
Q_DELETE_STATION = "DELETE FROM stations WHERE station_id=?"

Q_UPSERT_SENSOR = (
    "INSERT INTO sensor_config (station_id, sensor_type, unit, min_value, max_value, interval_sec, enabled) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
Q_GET_SENSORS = "SELECT * FROM sensor_config WHERE station_id=?"
Q_DELETE_SENSORS = "DELETE FROM sensor_config WHERE station_id=?"

Q_INSERT_LOG = (
    "INSERT INTO sensor_logs (station_id, log_date, ts, temperature, humidity, pressure) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)
_LOG_COLS = "station_id, log_date, ts, temperature, humidity, pressure"
# Dải thời gian: lọc trực tiếp trên Clustering Key (đọc tuần tự trong 1 partition)
Q_RANGE_ASC = (
    f"SELECT {_LOG_COLS} FROM sensor_logs "
    "WHERE station_id=? AND log_date=? AND ts >= ? AND ts <= ? ORDER BY ts ASC"
)
Q_RANGE_DESC = (
    f"SELECT {_LOG_COLS} FROM sensor_logs "
    "WHERE station_id=? AND log_date=? AND ts >= ? AND ts <= ?"
)  # thứ tự mặc định = CLUSTERING ORDER BY (ts DESC)
Q_LATEST = f"SELECT {_LOG_COLS} FROM sensor_logs WHERE station_id=? AND log_date=? LIMIT ?"
Q_DELETE_LOG_PARTITION = "DELETE FROM sensor_logs WHERE station_id=? AND log_date=?"

_cache = {}


def _prep(cql):
    if cql not in _cache:
        _cache[cql] = get_session().prepare(cql)
    return _cache[cql]


# ---------------------------------------------------------------- tiện ích thời gian
def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, dạng naive (driver hiểu naive = UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso_z(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


def _dates(start: datetime, end: datetime):
    d, out = start.date(), []
    while d <= end.date():
        out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- chuyển Row -> dict
def _station(r):
    return {
        "station_id": r.station_id,
        "name": r.name,
        "location": r.location,
        "latitude": r.latitude,
        "longitude": r.longitude,
        "status": r.status,
        "created_at": iso_z(r.created_at) if r.created_at else None,
    }


def _sensor(r):
    return {
        "sensor_type": r.sensor_type,
        "unit": r.unit,
        "min_value": r.min_value,
        "max_value": r.max_value,
        "interval_sec": r.interval_sec,
        "enabled": r.enabled,
    }


def _log(r):
    return {
        "station_id": r.station_id,
        "log_date": str(r.log_date),
        "ts": iso_z(r.ts),
        "temperature": r.temperature,
        "humidity": r.humidity,
        "pressure": r.pressure,
    }


# ================================================================ CRUD: TRẠM
def create_station(station_id, name, location="", latitude=None, longitude=None, status="active"):
    """Tạo trạm mới + cấu hình mặc định cho 3 cảm biến. Trả về False nếu mã trạm đã tồn tại."""
    s = get_session()
    rs = s.execute(
        _prep(Q_INSERT_STATION),
        (station_id, name, location, latitude, longitude, status, utcnow()),
    )
    if not rs.was_applied:
        return False
    for sensor_type, cfg in DEFAULT_SENSORS.items():
        set_sensor(station_id, sensor_type, cfg["unit"], cfg["min_value"], cfg["max_value"], 60, True)
    return True


def get_station(station_id):
    r = get_session().execute(_prep(Q_GET_STATION), (station_id,)).one()
    return _station(r) if r else None


def list_stations():
    """Bảng stations rất nhỏ (vài chục dòng) nên full scan chấp nhận được."""
    rows = [_station(r) for r in get_session().execute(_prep(Q_LIST_STATIONS))]
    return sorted(rows, key=lambda x: x["station_id"])


def update_station(station_id, name, location, latitude, longitude, status):
    rs = get_session().execute(
        _prep(Q_UPDATE_STATION), (name, location, latitude, longitude, status, station_id)
    )
    return rs.was_applied


def delete_station(station_id, days=14):
    """Xoá trạm, cấu hình cảm biến và log của `days` ngày gần nhất (xoá theo partition).
    Production nên dùng TTL để dữ liệu cũ tự hết hạn thay vì xoá tay."""
    s = get_session()
    s.execute(_prep(Q_DELETE_STATION), (station_id,))
    s.execute(_prep(Q_DELETE_SENSORS), (station_id,))
    today = utcnow().date()
    params = [(station_id, today - timedelta(days=i)) for i in range(days + 1)]
    execute_concurrent_with_args(s, _prep(Q_DELETE_LOG_PARTITION), params, concurrency=20)


# ================================================================ CRUD: CẢM BIẾN
def set_sensor(station_id, sensor_type, unit, min_value, max_value, interval_sec, enabled):
    get_session().execute(
        _prep(Q_UPSERT_SENSOR),
        (station_id, sensor_type, unit, min_value, max_value, interval_sec, enabled),
    )


def get_sensors(station_id):
    rows = [_sensor(r) for r in get_session().execute(_prep(Q_GET_SENSORS), (station_id,))]
    return sorted(rows, key=lambda x: x["sensor_type"])


# ================================================================ CRUD: LOG ĐO
def insert_log(station_id, ts, temperature, humidity, pressure):
    ts = to_utc_naive(ts)
    get_session().execute(
        _prep(Q_INSERT_LOG),
        (station_id, ts.date(), ts, round(temperature, 2), round(humidity, 2), round(pressure, 2)),
    )


def insert_logs(records, concurrency=50, retries=2):
    """Ghi hàng loạt (async, song song). records: iterable (station_id, ts, temp, hum, pres).
    Bản ghi lỗi (timeout, mạng...) được thử lại tối đa `retries` lần; ghi trùng khóa chính là
    idempotent (cùng (station_id, log_date, ts) chỉ ghi đè) nên retry an toàn.
    Trả về số bản ghi ghi thành công."""
    params = []
    for station_id, ts, t, h, p in records:
        ts = to_utc_naive(ts)
        params.append((station_id, ts.date(), ts, round(t, 2), round(h, 2), round(p, 2)))
    total, pending = len(params), params
    for attempt in range(retries + 1):
        results = execute_concurrent_with_args(
            get_session(), _prep(Q_INSERT_LOG), pending, concurrency=concurrency, raise_on_first_error=False
        )
        failed = [(prm, res) for prm, (ok, res) in zip(pending, results) if not ok]
        if not failed:
            return total
        pending = [prm for prm, _ in failed]
        print(f"Lỗi ghi {len(pending)}/{total} bản ghi (lần {attempt + 1}): {failed[0][1]}")
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    return total - len(pending)


# ================================================================ TRUY VẤN CHUỖI THỜI GIAN
def query_range(station_id, start, end, ascending=True):
    """Lấy log của trạm trong [start, end] (UTC naive).

    Mỗi ngày (log_date) là một partition: truy vấn từng partition với điều kiện
    ts >= ? AND ts <= ? rồi nối lại theo thứ tự ngày. Dữ liệu đã được Cassandra sắp xếp
    vật lý theo ts nên KHÔNG cần sort ở ứng dụng.
    """
    start, end = to_utc_naive(start), to_utc_naive(end)
    s = get_session()
    dates = _dates(start, end)
    if not ascending:
        dates.reverse()
    stmt = _prep(Q_RANGE_ASC if ascending else Q_RANGE_DESC)
    out = []
    for d in dates:
        out.extend(_log(r) for r in s.execute(stmt, (station_id, d, start, end)))
    return out


def latest(station_id, limit=10, max_days=3):
    """N bản ghi mới nhất: đọc đầu partition của hôm nay (do CLUSTERING ORDER DESC),
    nếu chưa đủ thì lùi sang ngày trước."""
    s = get_session()
    stmt = _prep(Q_LATEST)
    out, d = [], utcnow().date()
    for _ in range(max_days):
        need = limit - len(out)
        if need <= 0:
            break
        out.extend(_log(r) for r in s.execute(stmt, (station_id, d, need)))
        d -= timedelta(days=1)
    return out


def latest_all(station_ids):
    """Bản ghi mới nhất của mỗi trạm (chạy song song)."""
    s = get_session()
    stmt = _prep(Q_LATEST)
    today = utcnow().date()
    res = {}
    for day in (today, today - timedelta(days=1)):
        todo = [sid for sid in station_ids if sid not in res]
        if not todo:
            break
        out = execute_concurrent_with_args(
            s, stmt, [(sid, day, 1) for sid in todo], concurrency=20, raise_on_first_error=False
        )
        for sid, (ok, rows) in zip(todo, out):
            if ok:
                first = next(iter(rows), None)
                if first is not None:
                    res[sid] = _log(first)
    return res


def stats(rows):
    """Min / Max / Avg mỗi chỉ số từ danh sách log đã lấy."""
    out = {}
    for m in METRICS:
        vals = [r[m] for r in rows if r.get(m) is not None]
        out[m] = (
            {"min": min(vals), "max": max(vals), "avg": round(sum(vals) / len(vals), 2)}
            if vals
            else None
        )
    return out
