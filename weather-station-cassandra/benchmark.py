"""Đo hiệu năng ghi / đọc trên Cassandra (SV3) — dùng số liệu cho phần Kiểm thử trong báo cáo.

Kịch bản: tạo trạm tạm BENCH01, cho N luồng (1, 5, 10) cùng ghi liên tục, mỗi luồng ghi `--per-thread`
bản ghi (mỗi lần ghi chờ phản hồi xong mới ghi tiếp). Đo tốc độ ghi, độ trễ ghi (trung bình, p50, p95, p99,
lớn nhất) và tỷ lệ lỗi. Sau đó đo độ trễ truy vấn dải thời gian "2 giờ qua" và đếm số dòng trên partition.
Cuối cùng xóa trạm BENCH01 để không làm bẩn dữ liệu demo.

Chạy:  python benchmark.py                          # 1, 5, 10 luồng x 40 bản ghi
       python benchmark.py --per-thread 100 --threads 1 5 10 20
Kết quả cũng được ghi vào docs/ket-qua-do/benchmark_result.md (dán vào docs/BAO_CAO.md).
Lưu ý: DB Astra ở Mỹ nên độ trễ gồm cả mạng từ Việt Nam; nên ghi rõ điều kiện đo trong báo cáo.
"""
import argparse
from pathlib import Path
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import db
import repo

BENCH_ID = "BENCH01"


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, max(0, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def run_level(threads, per_thread, counter, lock):
    base = repo.utcnow()
    lat, errors = [], [0]

    def worker(_):
        local, err = [], 0
        for _i in range(per_thread):
            with lock:
                counter[0] += 1
                k = counter[0]
            ts = base - timedelta(milliseconds=k)  # mỗi bản ghi một ts riêng -> không ghi đè nhau
            t0 = time.perf_counter()
            try:
                repo.insert_log(BENCH_ID, ts, 25 + (k % 50) / 10, 70 + (k % 30) / 10, 1010 + (k % 20) / 10)
                local.append((time.perf_counter() - t0) * 1000)
            except Exception as e:
                err += 1
                print("  lỗi ghi:", type(e).__name__, str(e)[:80])
        with lock:
            lat.extend(local)
            errors[0] += err

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        list(ex.map(worker, range(threads)))
    wall = time.perf_counter() - t_start
    total = threads * per_thread
    lat.sort()
    return {
        "threads": threads, "total": total, "ok": len(lat), "errors": errors[0],
        "wall": wall, "tput": len(lat) / wall if wall else 0,
        "avg": statistics.mean(lat) if lat else float("nan"),
        "p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99), "max": lat[-1] if lat else float("nan"),
        "err_rate": errors[0] / total * 100,
    }


def query_bench(station, runs=5):
    end = repo.utcnow()
    start = end - timedelta(hours=2)
    repo.query_range(station, start, end)  # khởi động (bỏ qua)
    times, n = [], 0
    for _ in range(runs):
        t0 = time.perf_counter()
        n = len(repo.query_range(station, start, end))
        times.append((time.perf_counter() - t0) * 1000)
    return times, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, nargs="+", default=[1, 5, 10])
    ap.add_argument("--per-thread", type=int, default=40)
    ap.add_argument("--query-station", default="ST01", help="trạm có sẵn dữ liệu để đo truy vấn dải thời gian")
    ap.add_argument("--keep", action="store_true", help="không xóa trạm BENCH01 sau khi đo")
    args = ap.parse_args()

    print("Kết nối...")
    repo.create_station(BENCH_ID, "Trạm đo hiệu năng", "benchmark", 0.0, 0.0)
    counter, lock = [0], threading.Lock()
    mode = "Astra DB" if db.is_astra() else "Cassandra cục bộ"
    results = []
    try:
        for n in args.threads:
            print(f"\n== {n} luồng x {args.per_thread} bản ghi ==")
            r = run_level(n, args.per_thread, counter, lock)
            results.append(r)
            print(f"  ghi {r['ok']}/{r['total']} trong {r['wall']:.1f}s -> {r['tput']:.1f} bản ghi/s | "
                  f"TB {r['avg']:.0f} ms, p95 {r['p95']:.0f} ms | lỗi {r['err_rate']:.1f}%")

        today = repo.utcnow().date()
        cnt = db.get_session().execute(
            "SELECT COUNT(*) FROM sensor_logs WHERE station_id=%s AND log_date=%s", (BENCH_ID, today)
        ).one()[0]
        print(f"\nPartition ('{BENCH_ID}', {today}) hiện có {cnt} dòng (COUNT trên một partition).")

        qt, nrows = query_bench(args.query_station)
        qavg = statistics.mean(qt)
        print(f"Truy vấn 2 giờ qua của {args.query_station}: {nrows} dòng, "
              f"TB {qavg:.0f} ms (min {min(qt):.0f}, max {max(qt):.0f}) qua {len(qt)} lần chạy")
    finally:
        if not args.keep:
            repo.delete_station(BENCH_ID)
            print(f"\nĐã xóa trạm {BENCH_ID}.")

    lines = [f"Chế độ: {mode}. Mỗi luồng ghi {args.per_thread} bản ghi tuần tự (chờ phản hồi mới ghi tiếp), consistency LOCAL_QUORUM.",
             "", "| Số luồng | Bản ghi | Thành công | Thời gian (s) | Tốc độ (bản ghi/s) | TB (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Lỗi (%) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['threads']} | {r['total']} | {r['ok']} | {r['wall']:.1f} | {r['tput']:.1f} | {r['avg']:.0f} | "
                     f"{r['p50']:.0f} | {r['p95']:.0f} | {r['p99']:.0f} | {r['err_rate']:.1f} |")
    lines += ["", f"Truy vấn dải thời gian (2 giờ, trạm {args.query_station}, {nrows} dòng): "
                  f"TB {qavg:.0f} ms, min {min(qt):.0f} ms, max {max(qt):.0f} ms ({len(qt)} lần)."]
    out = Path(__file__).parent / "docs" / "ket-qua-do" / "benchmark_result.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nĐã ghi {out}")
    db.close()


if __name__ == "__main__":
    main()
