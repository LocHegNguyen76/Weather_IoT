"""Nạp dữ liệu mẫu (Dummy Data): 10 trạm x 240 bản ghi (mỗi 1 phút, 4 giờ gần nhất)
= 2.400 bản ghi time-series trải đều theo từng phút, đạt định mức 5–10 trạm và 500–1.000+ bản ghi.

Chạy:  python seed_data.py                     (10 trạm mẫu, 240 điểm/trạm, bước 1 phút)
       python seed_data.py --points 120 --step 5
       python seed_data.py --station ST11      (chỉ nạp dữ liệu quá khứ cho trạm tạo trên dashboard)
"""
import argparse
import random
import time
from datetime import timedelta

import db
import repo
from stations_data import STATIONS, base_for, sample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=240, help="số bản ghi mỗi trạm")
    ap.add_argument("--step", type=int, default=1, help="khoảng cách giữa 2 bản ghi (phút)")
    ap.add_argument("--station", nargs="+", metavar="ID",
                    help="chỉ nạp cho các trạm này (đã tạo sẵn trên dashboard), ví dụ: --station ST11")
    args = ap.parse_args()

    if args.station:
        targets = []
        for sid in args.station:
            st = repo.get_station(sid)
            if not st:
                raise SystemExit(f"Không tìm thấy trạm {sid}. Hãy tạo trạm trên dashboard trước.")
            targets.append((sid, base_for(st)))
    else:
        for sid, name, loc, lat, lon, _ in STATIONS:
            created = repo.create_station(sid, name, loc, lat, lon)
            print(f"{'Tạo' if created else 'Đã có'} trạm {sid} - {name}")
        targets = [(st[0], st[5]) for st in STATIONS]

    now = repo.utcnow().replace(second=0, microsecond=0)
    end = now - timedelta(minutes=now.minute % args.step)
    rng = random.Random(42)

    records = []
    for sid, base in targets:
        for i in range(args.points):
            ts = end - timedelta(minutes=args.step * i)
            t, h, p = sample(base, ts.hour * 60 + ts.minute, rng)
            records.append((sid, ts, t, h, p))

    t0 = time.perf_counter()
    ok = repo.insert_logs(records)
    dt = time.perf_counter() - t0
    print(
        f"\nĐã ghi {ok}/{len(records)} bản ghi cho {len(targets)} trạm "
        f"trong {dt:.2f}s (~{ok / dt:.0f} bản ghi/giây)."
    )
    print(f"Khoảng thời gian: {records[-1][1]} → {records[0][1]} (UTC)")
    db.close()


if __name__ == "__main__":
    main()
