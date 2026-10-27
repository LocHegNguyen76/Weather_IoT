"""Flask API + Web Dashboard cho hệ thống giám sát Weather Station (Cassandra / Astra DB).

Chạy:  python app.py     rồi mở http://localhost:5000  (đổi cổng: biến PORT)
"""
import os
import random
import re
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from cassandra import OperationTimedOut, ReadTimeout, Unavailable, WriteTimeout
from cassandra.cluster import NoHostAvailable

import repo
from stations_data import base_for, make_walker, sample

app = Flask(__name__)
app.json.ensure_ascii = False

ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
LIMITS = {"temperature": (-90, 60), "humidity": (0, 100), "pressure": (800, 1100)}


class BadRequest(Exception):
    pass


@app.errorhandler(BadRequest)
def _bad(e):
    return jsonify({"error": str(e)}), 400


DB_ERRORS = (OperationTimedOut, ReadTimeout, WriteTimeout, Unavailable, NoHostAvailable)


@app.errorhandler(Exception)
def _err(e):
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, DB_ERRORS):
        app.logger.warning("Lỗi kết nối cơ sở dữ liệu: %s", e)
        return jsonify({"error": "Không kết nối được cơ sở dữ liệu (quá thời gian hoặc database đang hibernate). "
                                 "Hãy kiểm tra Astra (bấm Resume) rồi thử lại."}), 503
    app.logger.exception(e)
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


# ------------------------------------------------------------ tiện ích
def _num(body, key, required=True, lo=None, hi=None):
    v = body.get(key)
    if v in (None, ""):
        if required:
            raise BadRequest(f"Thiếu trường '{key}'")
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' phải là số")
    if lo is not None and not (lo <= v <= hi):
        raise BadRequest(f"'{key}' phải nằm trong khoảng [{lo}, {hi}]")
    return v


def _check_id(station_id):
    if not ID_RE.match(station_id or ""):
        raise BadRequest("Mã trạm gồm 2–20 ký tự chữ, số, '-' hoặc '_'")
    return station_id


def _parse_dt(s):
    try:
        return repo.to_utc_naive(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except Exception:
        raise BadRequest(f"Thời gian không hợp lệ: {s} (dùng ISO 8601, ví dụ 2026-10-21T08:00:00Z)")


def _require_station(station_id):
    st = repo.get_station(station_id)
    if not st:
        return None, (jsonify({"error": f"Không tìm thấy trạm {station_id}"}), 404)
    return st, None


# ------------------------------------------------------------ trang chủ
@app.get("/api/health")
def health():
    """Kiểm tra nhanh kết nối Cassandra (thời gian phản hồi)."""
    t0 = time.perf_counter()
    repo.get_session().execute("SELECT release_version FROM system.local").one()
    return jsonify({"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)})


@app.get("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------ CRUD trạm
@app.get("/api/stations")
def stations_list():
    return jsonify(repo.list_stations())


@app.post("/api/stations")
def stations_create():
    b = request.get_json(silent=True) or {}
    sid = _check_id((b.get("station_id") or "").strip())
    name = (b.get("name") or "").strip()
    if not name:
        raise BadRequest("Thiếu tên trạm")
    lat = _num(b, "latitude", required=False, lo=-90, hi=90)
    lon = _num(b, "longitude", required=False, lo=-180, hi=180)
    if not repo.create_station(sid, name, (b.get("location") or "").strip(), lat, lon):
        return jsonify({"error": f"Mã trạm {sid} đã tồn tại"}), 409
    st = repo.get_station(sid)
    _backfill(st)  # trạm mới có sẵn 4 giờ lịch sử, không cần chạy seed_data.py
    return jsonify(st), 201


@app.put("/api/stations/<station_id>")
def stations_update(station_id):
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip()
    if not name:
        raise BadRequest("Thiếu tên trạm")
    status = b.get("status", "active")
    if status not in ("active", "inactive"):
        raise BadRequest("status phải là active hoặc inactive")
    lat = _num(b, "latitude", required=False, lo=-90, hi=90)
    lon = _num(b, "longitude", required=False, lo=-180, hi=180)
    if not repo.update_station(station_id, name, (b.get("location") or "").strip(), lat, lon, status):
        return jsonify({"error": f"Không tìm thấy trạm {station_id}"}), 404
    return jsonify(repo.get_station(station_id))


@app.delete("/api/stations/<station_id>")
def stations_delete(station_id):
    _, err = _require_station(station_id)
    if err:
        return err
    repo.delete_station(station_id)
    return jsonify({"deleted": station_id})


# ------------------------------------------------------------ cấu hình cảm biến
@app.get("/api/stations/<station_id>/sensors")
def sensors_get(station_id):
    return jsonify(repo.get_sensors(station_id))


@app.put("/api/stations/<station_id>/sensors/<sensor_type>")
def sensors_put(station_id, sensor_type):
    if sensor_type not in repo.METRICS:
        raise BadRequest(f"Loại cảm biến phải thuộc {list(repo.METRICS)}")
    _, err = _require_station(station_id)
    if err:
        return err
    b = request.get_json(silent=True) or {}
    lo_, hi_ = LIMITS[sensor_type]
    mn = _num(b, "min_value", lo=lo_, hi=hi_)
    mx = _num(b, "max_value", lo=lo_, hi=hi_)
    if mn >= mx:
        raise BadRequest("Ngưỡng dưới phải nhỏ hơn ngưỡng trên")
    interval = int(_num(b, "interval_sec", lo=1, hi=86400))
    unit = b.get("unit") or repo.DEFAULT_SENSORS[sensor_type]["unit"]
    repo.set_sensor(station_id, sensor_type, unit, mn, mx, interval, bool(b.get("enabled", True)))
    return jsonify({"ok": True})


# ------------------------------------------------------------ log đo
@app.post("/api/logs")
def logs_create():
    b = request.get_json(silent=True) or {}
    sid = _check_id((b.get("station_id") or "").strip())
    _, err = _require_station(sid)
    if err:
        return err
    vals = {m: _num(b, m, lo=LIMITS[m][0], hi=LIMITS[m][1]) for m in repo.METRICS}
    ts = _parse_dt(b["ts"]) if b.get("ts") else repo.utcnow()
    repo.insert_log(sid, ts, **vals)
    return jsonify({"ok": True, "ts": repo.iso_z(ts)}), 201


@app.get("/api/logs")
def logs_range():
    """Dữ liệu một trạm trong dải thời gian, đã sắp xếp cũ -> mới bởi Cassandra
    (ORDER BY ts ASC trong từng partition), kèm thời gian truy vấn (ms)."""
    sid = _check_id(request.args.get("station_id", ""))
    if request.args.get("start"):
        start = _parse_dt(request.args["start"])
        end = _parse_dt(request.args["end"]) if request.args.get("end") else repo.utcnow()
    else:
        minutes = request.args.get("minutes", "120", type=int)
        if not 1 <= minutes <= 3 * 24 * 60:
            raise BadRequest("minutes phải trong khoảng 1–4320")
        end = repo.utcnow()
        start = end - timedelta(minutes=minutes)
    if start > end:
        raise BadRequest("Thời điểm bắt đầu phải trước thời điểm kết thúc")
    t0 = time.perf_counter()
    rows = repo.query_range(sid, start, end, ascending=True)
    ms = (time.perf_counter() - t0) * 1000
    return jsonify(
        {
            "station_id": sid,
            "start": repo.iso_z(start),
            "end": repo.iso_z(end),
            "count": len(rows),
            "query_ms": round(ms, 1),
            "stats": repo.stats(rows),
            "rows": rows,
        }
    )


@app.get("/api/latest")
def logs_latest():
    sid = _check_id(request.args.get("station_id", ""))
    limit = max(1, min(request.args.get("limit", 10, type=int), 200))
    t0 = time.perf_counter()
    rows = repo.latest(sid, limit)
    ms = (time.perf_counter() - t0) * 1000
    return jsonify({"station_id": sid, "query_ms": round(ms, 1), "rows": rows})


@app.get("/api/overview")
def overview():
    """Bản ghi mới nhất của tất cả các trạm."""
    stations = repo.list_stations()
    last = repo.latest_all([s["station_id"] for s in stations])
    return jsonify([{**s, "latest": last.get(s["station_id"])} for s in stations])


# ---------------------------------------------------------------------------
# Tự động hoá dữ liệu cho trạm mới
# ---------------------------------------------------------------------------
def _backfill(station, points=240, step=1):
    """Nạp lịch sử (mặc định 4 giờ, mỗi phút) cho một trạm vừa tạo."""
    try:
        now = repo.utcnow().replace(second=0, microsecond=0)
        rng = random.Random()
        base = base_for(station)
        rows = []
        for i in range(points):
            ts = now - timedelta(minutes=step * i)
            t, h, p = sample(base, ts.hour * 60 + ts.minute, rng)
            rows.append((station["station_id"], ts, t, h, p))
        repo.insert_logs(rows)
    except Exception as e:  # không để lỗi nạp lịch sử làm hỏng việc tạo trạm
        print(f"[backfill] lỗi: {e}")


def _live_simulator(interval):
    """Luồng nền: mỗi `interval` giây ghi 1 bản ghi/trạm đang hoạt động (kể cả trạm mới)."""
    rng = random.Random()
    walkers = {}
    rnd = 0
    while True:
        try:
            if rnd % 3 == 0:  # đọc lại danh sách trạm mỗi 3 vòng
                cur = {s["station_id"]: s for s in repo.list_stations() if s.get("status") != "inactive"}
                for sid in [k for k in walkers if k not in cur]:
                    del walkers[sid]
                for sid, st in cur.items():
                    if sid not in walkers:
                        walkers[sid] = make_walker(base_for(st), rng)
            now = repo.utcnow()
            minute = now.hour * 60 + now.minute
            if walkers:
                repo.insert_logs([(sid, now, *w(minute)) for sid, w in walkers.items()])
        except Exception as e:
            print(f"[auto-sim] lỗi: {e}")
        rnd += 1
        time.sleep(interval)


if __name__ == "__main__":
    # Mặc định bật giả lập nền để mọi trạm luôn có dữ liệu mới.
    # Tắt khi demo bước simulator riêng:  python app.py --no-sim   (hoặc đặt AUTO_SIM=0 trong .env)
    auto = "--no-sim" not in sys.argv and os.getenv("AUTO_SIM", "1") != "0"
    if auto:
        threading.Thread(target=_live_simulator, args=(5.0,), daemon=True).start()
        print("Giả lập nền: BẬT (mỗi 5 giây ghi 1 bản ghi cho mỗi trạm). Tắt bằng: python app.py --no-sim")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False, threaded=True)
