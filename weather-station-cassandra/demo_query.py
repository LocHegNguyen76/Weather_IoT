"""In ra (và chạy thử) câu lệnh CQL lọc dữ liệu 2 giờ qua của một trạm,
để SV2 dán vào CQLSH / CQL Console khi demo.

Chạy:  python demo_query.py            (trạm ST01, 2 giờ qua)
       python demo_query.py ST05 3     (trạm ST05, 3 giờ qua)
"""
import sys
import time
from datetime import timedelta

import db
import repo


def cql_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S+0000")


def main():
    station = sys.argv[1] if len(sys.argv) > 1 else "ST01"
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 2
    end = repo.utcnow()
    start = end - timedelta(hours=hours)

    print("-- Dán các lệnh sau vào CQLSH / CQL Console (nhớ USE <keyspace>; trước):\n")
    for d in repo._dates(start, end):
        print(
            "SELECT station_id, log_date, ts, temperature, humidity, pressure\n"
            "FROM sensor_logs\n"
            f"WHERE station_id = '{station}'\n"
            f"  AND log_date = '{d}'\n"
            f"  AND ts >= '{cql_ts(start)}'\n"
            f"  AND ts <= '{cql_ts(end)}';\n"
        )
    print("-- (Cột ts đã được Cassandra sắp xếp sẵn mới -> cũ nhờ CLUSTERING ORDER BY (ts DESC))\n")

    # Khởi động trước (mở kết nối + chuẩn bị câu lệnh) để KHÔNG tính vào thời gian truy vấn
    t_conn = time.perf_counter()
    repo.query_range(station, start, end, ascending=False)
    conn_ms = (time.perf_counter() - t_conn) * 1000
    print(f"Khởi động kết nối + lần truy vấn đầu: {conn_ms:.0f} ms (không tính vào hiệu năng truy vấn)")

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        rows = repo.query_range(station, start, end, ascending=False)
        times.append((time.perf_counter() - t0) * 1000)
    print(
        f"Truy vấn dải thời gian: {len(rows)} bản ghi | 5 lần đo: "
        f"min {min(times):.1f} ms, TB {sum(times) / len(times):.1f} ms, max {max(times):.1f} ms. "
        "5 dòng mới nhất:"
    )
    for r in rows[:5]:
        print(f"  {r['ts']}  {r['temperature']:>6.2f}°C  {r['humidity']:>6.2f}%  {r['pressure']:>8.2f} hPa")
    db.close()


if __name__ == "__main__":
    main()
