"""Giả lập các trạm/cảm biến gửi dữ liệu liên tục vào Cassandra (SV3).

Mỗi vòng: mỗi trạm đang hoạt động gửi 1 bản ghi (nhiệt độ, độ ẩm, áp suất) tại thời điểm hiện tại.
Trạm mới tạo trên dashboard cũng được đưa vào tự động (danh sách trạm được kiểm tra lại mỗi 5 vòng).

Chạy:  python simulator.py                      # 12 vòng x số trạm, mỗi vòng cách 3s
       python simulator.py --rounds 30 --interval 1
       python simulator.py --forever --interval 2    # chạy liên tục tới khi Ctrl+C
"""
import argparse
import random
import time

import db
import repo
from stations_data import STATIONS, base_for, make_walker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=12, help="số vòng gửi (mỗi vòng = 1 bản ghi/trạm)")
    ap.add_argument("--interval", type=float, default=3.0, help="giây giữa hai vòng")
    ap.add_argument("--forever", action="store_true", help="chạy mãi tới khi bấm Ctrl+C")
    args = ap.parse_args()

    # Chưa có trạm nào (CSDL trống) thì tạo 10 trạm mẫu
    if not repo.list_stations():
        for sid, name, loc, lat, lon, _ in STATIONS:
            repo.create_station(sid, name, loc, lat, lon)

    rng = random.Random()
    walkers = {}

    def sync_walkers():
        current = {s["station_id"]: s for s in repo.list_stations() if s.get("status") != "inactive"}
        for sid in [k for k in walkers if k not in current]:
            del walkers[sid]
        for sid, st in current.items():
            if sid not in walkers:
                walkers[sid] = make_walker(base_for(st), rng)
                print(f"  + đưa trạm {sid} - {st['name']} vào giả lập")

    total, rnd = 0, 0
    t_start = time.perf_counter()
    print("Bắt đầu giả lập cảm biến... (Ctrl+C để dừng)")
    try:
        while args.forever or rnd < args.rounds:
            rnd += 1
            if rnd == 1 or rnd % 5 == 0:
                sync_walkers()
            if not walkers:
                print("Chưa có trạm nào để giả lập. Hãy tạo trạm trên dashboard hoặc chạy seed_data.py.")
                break
            now = repo.utcnow()
            minute = now.hour * 60 + now.minute
            batch = [(sid, now, *w(minute)) for sid, w in walkers.items()]
            t0 = time.perf_counter()
            ok = repo.insert_logs(batch)
            ms = (time.perf_counter() - t0) * 1000
            total += ok
            sample_row = batch[0]
            print(
                f"[vòng {rnd:>3}] ghi {ok}/{len(batch)} bản ghi trong {ms:6.1f} ms | "
                f"{sample_row[0]}: {sample_row[2]:.1f}°C, {sample_row[3]:.1f}%, {sample_row[4]:.1f} hPa | "
                f"tổng: {total}"
            )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    dt = time.perf_counter() - t_start
    print(f"Hoàn tất: {total} bản ghi trong {dt:.1f}s.")
    db.close()


if __name__ == "__main__":
    main()
