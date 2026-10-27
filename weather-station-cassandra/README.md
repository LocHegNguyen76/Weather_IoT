# Hệ thống giám sát dữ liệu cảm biến IoT Weather Station

Đề tài 08 – môn NoSQL · Apache Cassandra (DataStax Astra DB) · Python Flask + Chart.js

## Cấu trúc thư mục

```
weather-station-cassandra/
├── app.py  repo.py  db.py  stations_data.py    # mã nguồn chính (Flask API, tầng CQL, kết nối Astra)
├── init_schema.py  seed_data.py  simulator.py  # khởi tạo bảng, dữ liệu mẫu, giả lập cảm biến
├── benchmark.py  demo_query.py                 # đo hiệu năng, in câu CQL cho demo
├── templates/index.html                        # Web Dashboard
├── cql/            schema.cql, queries.cql     # thiết kế bảng và câu lệnh CQLSH
├── docs/           BAO_CAO.md, ket-qua-do/     # báo cáo và số liệu đo (benchmark, bảng tính)
├── _luu-tru/                                   # bản sao lưu cũ (không dùng khi chạy)
├── .env  .env.example  requirements.txt  secure-connect-weather-station.zip
└── README.md
```

### Mô tả từng file

| File | Mô tả | Phụ trách |
|---|---|---|
| `cql/schema.cql` | Thiết kế bảng (Partition Key, Clustering Key) | SV1 |
| `repo.py` | Tầng CQL: CRUD trạm / cảm biến / log đo, truy vấn dải thời gian | SV1 + SV2 |
| `app.py` | Flask API (CRUD, `/api/logs`, `/api/latest`, …) | SV1 + SV3 |
| `cql/queries.cql`, `demo_query.py` | Câu lệnh CQL lọc chuỗi thời gian để demo trên CQLSH | SV2 |
| `benchmark.py` | Đo tốc độ ghi, độ trễ, tỷ lệ lỗi theo 1/5/10 luồng | SV3 |
| `simulator.py`, `seed_data.py`, `init_schema.py`, `db.py`, `stations_data.py` | Giả lập 10 trạm, dữ liệu mẫu, khởi tạo bảng, kết nối Astra | SV3 |
| `templates/index.html` | Web Dashboard (biểu đồ, bản đồ, tạo trạm bằng bản đồ) | SV3 |
| `docs/BAO_CAO.md` | Báo cáo & giải trình thiết kế CSDL | cả nhóm |

## 1. Chuẩn bị trên Astra DB (làm một lần)

1. **Tạo database**: *Create Database* → **Serverless (non-vector)** → tên `weather-station`, keyspace `weather`,
   provider AWS, region còn mở khóa (gói miễn phí: `us-east-2`). Chờ trạng thái **Active** (2–3 phút).
   *(Astra không cho `CREATE KEYSPACE` bằng CQL; keyspace tạo ngay ở bước này hoặc bằng nút **Add Keyspace**.)*
2. **Application Token**: trang database → mục *Generate application token* (hoặc *Settings → Token Management*)
   → mô tả `weather-app` → **Generate token** → copy chuỗi `AstraCS:...` (chỉ hiện **một lần**).
3. **Secure Connect Bundle**: *Download SCB* → chọn region `us-east-2` và domain `astra.datastax.com` → **Download Secure Bundle**.
   File `secure-connect-weather-station.zip` đặt vào thư mục project, **không giải nén**.
4. Sao chép `.env.example` thành `.env` và điền:
   ```
   ASTRA_DB_BUNDLE=./secure-connect-weather-station.zip
   ASTRA_DB_TOKEN=AstraCS:...
   ASTRA_KEYSPACE=weather
   ```

> ⚠ Token là mật khẩu: không đưa lên GitHub (`.gitignore` đã chặn `.env`), không gửi qua chat. Sau đồ án hãy *Revoke* token.
> Database miễn phí sẽ **hibernate** nếu lâu không dùng: mở trang database và bấm *Resume* trước khi demo.

## 2. Cài đặt và chạy (Windows PowerShell)

Cần Python ≥ 3.9. Với Python **3.12 trở lên**, `requirements.txt` đã có `pyasyncore` (driver cần module `asyncore`).

```powershell
cd D:\Weather-app\weather-station-cassandra
python -m venv .venv
.venv\Scripts\activate            # nếu báo ExecutionPolicy: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
pip install -r requirements.txt

python db.py                      # kiểm tra kết nối (in phiên bản Cassandra) – lần đầu mất ~40 giây
python init_schema.py             # tạo 3 bảng
python seed_data.py               # 10 trạm x 240 bản ghi (mỗi phút, 4 giờ gần nhất) = 2.400 log (dummy data)
python app.py                     # mở http://localhost:5000
```

Ở một cửa sổ PowerShell khác (nhớ `cd` vào thư mục project và `.venv\Scripts\activate`), giả lập dữ liệu chảy liên tục:

```powershell
python simulator.py                          # 12 vòng x 10 trạm = 120 bản ghi, mỗi vòng cách 3 giây
python simulator.py --forever --interval 2   # chạy mãi (Ctrl+C để dừng)
```

**Trạm tạo thêm trên dashboard** tự có dữ liệu: khi tạo trạm, `app.py` nạp sẵn 4 giờ lịch sử (240 bản ghi), và một luồng
giả lập nền ghi thêm 1 bản ghi/trạm mỗi 5 giây (kể cả trạm mới), nên chỉ cần chạy `python app.py`.
Khi demo bước "SV3 chạy simulator riêng", chạy `python app.py --no-sim` (hoặc `AUTO_SIM=0` trong `.env`) để tắt luồng nền, rồi chạy `python simulator.py`.
`simulator.py` cũng tự nhận trạm mới; `python seed_data.py --station ST11` vẫn dùng được để nạp lịch sử thủ công.

Nếu chữ tiếng Việt trong terminal bị lỗi font: `chcp 65001` và `$env:PYTHONUTF8 = "1"` rồi chạy lại.

## 3. Kịch bản demo bảo vệ

**Chuẩn bị (trước giờ demo ít nhất vài phút):**
- Chạy `python app.py` và mở dashboard (kết nối lần đầu mất ~45 giây; `app.py` giữ kết nối nên các lần sau nhanh).
- Dashboard: chọn trạm `ST01`, khoảng **2 giờ qua**, tự làm mới **mỗi 2 giây**.
- Trang Astra → database → tab **CQL console**, gõ `USE weather;`.
- Chạy thử toàn bộ một lần trước đó.

| Bước | Ai | Thao tác | Điều cần nói / chứng minh |
|---|---|---|---|
| 1 | SV3 | `python simulator.py --rounds 12 --interval 3` | 10 cảm biến gửi liên tục, 120 bản ghi, log in thời gian ghi mỗi vòng → khả năng *write-heavy* |
| 2 | SV2 | `python demo_query.py ST01 2` rồi dán câu CQL vào **CQL console** | Lọc 2 giờ qua bằng `ts >= … AND ts <= …` trên một partition, kết quả mới → cũ, **không** `ORDER BY`/sort ở ứng dụng |
| 3 | SV1 + SV3 | Mở dashboard, chạy lại simulator (hoặc `--forever`) | Đường biểu đồ tự kéo dài; biểu đồ "Thời gian truy vấn" và badge *Truy vấn: x ms*; giải thích Partition Key `(station_id, log_date)` + Clustering Key `ts DESC` |
| Thêm | SV1 | **+ Trạm mới** (chọn trên bản đồ), **Ghi log thủ công**, **Cấu hình cảm biến**, **Xóa trạm** | Chức năng CRUD nền tảng |
| Thêm | SV3 | CQL console: `DESCRIBE KEYSPACE weather;`, các lệnh `COUNT(*)` trong `cql/queries.cql` | Quản trị keyspace trên CQLSH, số bản ghi theo partition |

**Mẹo xem cho rõ:** khi demo bước 3, chọn khoảng **30 phút qua** để thấy từng điểm mới hiện dần theo từng vòng simulator; khoảng 2 giờ trở lên dashboard gộp trung bình theo phút nên dữ liệu dày không bị dồn thành cục (bỏ tích *Gộp trung bình theo khoảng* để xem dữ liệu gốc).

**Về con số "mili-giây":** database ở Mỹ nên mỗi lần truy vấn từ Việt Nam khoảng 0,5–1 s (đã gồm độ trễ mạng). Hãy nói rõ điều này; thời gian không tăng khi dữ liệu tăng vì chỉ đọc một partition.

## 3b. Đo hiệu năng (cho phần kiểm thử)

```powershell
python benchmark.py                        # 1, 5, 10 luồng x 40 bản ghi, tự xóa trạm BENCH01
python benchmark.py --per-thread 100 --threads 1 5 10 20
```

Kết quả in ra màn hình và lưu vào `docs/ket-qua-do/benchmark_result.md` (dán vào `docs/BAO_CAO.md`, mục 7.2b).
Dashboard có cột **Trạng thái** (Hoạt động / Mất kết nối / Chưa có dữ liệu); `GET /api/health` kiểm tra kết nối database.

> ⚠ Khi demo bước simulator riêng, chạy `python app.py --no-sim`, nếu không luồng nền của `app.py` và `simulator.py` sẽ ghi chồng nhau.

## 4. Xem dữ liệu bằng CQLSH

- **Trên web**: Astra → database → tab **CQL console** (chính là CQLSH). Câu lệnh mẫu trong `cql/queries.cql`. Giờ trong CQL là **UTC** (giờ Việt Nam trừ 7 tiếng).
- **Trên máy** (tuỳ chọn): `cqlsh -b secure-connect-weather-station.zip -u token -p <AstraCS:...>` nếu đã cài bản cqlsh hỗ trợ Secure Connect Bundle.

Xoá sạch log để nạp lại (mất toàn bộ dữ liệu log): trong CQL console chạy `TRUNCATE sensor_logs;` rồi `python seed_data.py`.

## 5. Dùng Cassandra cài trên máy (thay vì Astra)

Xoá dòng `ASTRA_DB_BUNDLE` trong `.env`, thêm `CASSANDRA_HOSTS=127.0.0.1`. `init_schema.py` sẽ tự tạo keyspace. Phần code còn lại giữ nguyên.
Cách này cho độ trễ thấp hơn nhiều, hữu ích để so sánh hiệu năng thuần của Cassandra.

## 6. Xử lý sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `Unable to load a default connection class` / không import được `asyncore` | `pip install pyasyncore` (Python ≥ 3.12) |
| `Không tìm thấy Secure Connect Bundle` | File `.zip` phải còn nguyên (không giải nén), đúng đường dẫn trong `.env` |
| Lỗi xác thực / `AuthenticationFailed` | Token sai hoặc đã hết hạn: tạo token mới và sửa `.env` |
| `can't open file 'app.py'` | Chưa `cd` vào đúng thư mục chứa `app.py` |
| `Set-Location : A positional parameter...` | PowerShell không dùng `cd /d`; dùng `cd D:\đường\dẫn` |
| Kết nối treo / báo lỗi sau thời gian không dùng | Database hibernate: vào Astra bấm *Resume* |
| Trạm tạo trước khi cập nhật không có biểu đồ | Chạy `python seed_data.py --station ST13 ST14` để nạp lịch sử; từ giờ trạm mới tự có dữ liệu khi `app.py` chạy |
| Dashboard không có bản đồ / biểu đồ lạ | Cần internet để tải Chart.js và Leaflet; mất mạng thì bản đồ tự ẩn |

## 7. API tóm tắt

| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| GET / POST | `/api/stations` | Danh sách / tạo trạm (kèm cấu hình cảm biến mặc định) |
| PUT / DELETE | `/api/stations/<id>` | Sửa / xóa trạm |
| GET | `/api/stations/<id>/sensors` | Xem cấu hình cảm biến |
| PUT | `/api/stations/<id>/sensors/<temperature\|humidity\|pressure>` | Cập nhật ngưỡng, chu kỳ, bật/tắt |
| POST | `/api/logs` | Ghi một log đo `{station_id, temperature, humidity, pressure, ts?}` |
| GET | `/api/logs?station_id=ST01&minutes=120` | Log theo dải thời gian (cũ → mới) + thống kê + `query_ms` |
| GET | `/api/logs?station_id=ST01&start=…&end=…` | Dải thời gian tuỳ chọn (ISO 8601) |
| GET | `/api/latest?station_id=ST01&limit=10` | N bản ghi mới nhất |
| GET | `/api/overview` | Bản ghi mới nhất của mọi trạm |
