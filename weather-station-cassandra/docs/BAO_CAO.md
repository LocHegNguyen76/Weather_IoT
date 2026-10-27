# BÁO CÁO: HỆ THỐNG GIÁM SÁT DỮ LIỆU CẢM BIẾN IOT WEATHER STATION

**Môn:** NoSQL · **Đề tài 08** · **CSDL chính:** Apache Cassandra (Column Family), triển khai trên DataStax Astra DB (Cassandra 4.0.x)
**Nhóm:** 3 sinh viên

| Thành viên | Vai trò |
|---|---|
| [Họ tên SV1] – MSSV | Data Architect & CRUD Lead |
| [Họ tên SV2] – MSSV | Advanced Query Specialist |
| [Họ tên SV3] – MSSV | Fullstack Integrator & DB Tester |

---

## 1. Giới thiệu bài toán và kiến trúc

Các trạm quan trắc thời tiết liên tục gửi số liệu **nhiệt độ, độ ẩm, áp suất** về hệ thống. Ứng dụng cần:
(1) tiếp nhận luồng dữ liệu chuỗi thời gian với tốc độ ghi cao, (2) truy vấn nhanh theo trạm và theo dải thời gian,
(3) vẽ biểu đồ theo dõi liên tục trên web.

```
 10 trạm / cảm biến giả lập            Flask API + Web Dashboard              Astra DB (Cassandra)
 ┌──────────────────────┐   ghi log    ┌──────────────────────────┐   CQL    ┌───────────────────────┐
 │ simulator.py         │ ───────────▶ │ repo.py  (prepared stmt) │ ───────▶ │ keyspace: weather     │
 │ seed_data.py         │              │ app.py   (REST /api/...) │ ◀─────── │  stations             │
 └──────────────────────┘              │ index.html (Chart.js,    │          │  sensor_config        │
                                       │  Leaflet map)            │          │  sensor_logs          │
        Trình duyệt ◀── biểu đồ ────── └──────────────────────────┘          └───────────────────────┘
        CQL Console (CQLSH trên web Astra) ─────── truy vấn trực tiếp ──────────────▲
```

Công nghệ: Python 3 (cassandra-driver, Flask), Chart.js (biểu đồ đường), Leaflet + OpenStreetMap (bản đồ), kết nối Astra bằng Secure Connect Bundle và Application Token.

## 2. Vì sao chọn Cassandra cho dữ liệu Time-series (1.0đ)

**Đặc điểm của workload**: ghi rất nhiều (write-heavy), dữ liệu chỉ thêm mới theo thời gian (append-only), hầu như không cập nhật,
đọc theo mẫu cố định "một trạm – một khoảng thời gian".

| Yêu cầu của bài toán | Cách Cassandra đáp ứng |
|---|---|
| Ghi tốc độ cao | Kiến trúc **LSM-tree**: mỗi lần ghi chỉ ghi tuần tự vào *commit log* (đĩa) và *memtable* (RAM), không đọc-trước-khi-ghi, không khóa dòng; sau đó memtable được flush thành SSTable bất biến. Nhờ vậy độ trễ ghi ở phía máy chủ rất thấp và thông lượng cao. |
| Mở rộng khi số trạm tăng | **Masterless / peer-to-peer**: mọi node ngang hàng, thêm node là tăng gần tuyến tính dung lượng và thông lượng ghi; dữ liệu phân tán theo hash của Partition Key. |
| Sẵn sàng cao | Sao chép dữ liệu nhiều bản (replication factor), không có điểm lỗi đơn (SPOF). |
| Truy vấn theo thời gian nhanh | Trong một partition, dữ liệu được **sắp xếp vật lý theo Clustering Key** (thời gian), nên đọc dải thời gian là đọc tuần tự một đoạn liên tục. |
| Quản lý vòng đời dữ liệu | Hỗ trợ **TTL** (tự xoá dữ liệu cũ) và chiến lược nén **TimeWindowCompactionStrategy** dành cho chuỗi thời gian. |
| Dữ liệu cảm biến mỏng, ít quan hệ | Không cần JOIN hay giao dịch phức tạp; mô hình wide-column phù hợp. |

**So sánh với RDBMS truyền thống**: B-tree phải cập nhật chỉ mục và ghi ngẫu nhiên trên đĩa cho mỗi bản ghi, scale ghi chủ yếu theo chiều dọc;
Cassandra scale ngang và tối ưu đường ghi.

**Đánh đổi**: không có JOIN, không truy vấn ad-hoc tùy ý (lọc theo cột thường cần index/SAI hoặc `ALLOW FILTERING`), phải thiết kế bảng theo truy vấn,
nhất quán cuối cùng (eventual consistency) theo mặc định – chấp nhận được với dữ liệu cảm biến.

## 3. Thiết kế Data Model theo Query-driven design (1.5đ)

Với Cassandra, ta **bắt đầu từ các truy vấn cần phục vụ**, rồi mới thiết kế bảng cho từng truy vấn.

### 3.1 Danh sách truy vấn

| # | Truy vấn nghiệp vụ | Bảng phục vụ |
|---|---|---|
| Q1 | Xem / liệt kê thông tin các trạm quan trắc | `stations` |
| Q2 | Xem cấu hình cảm biến của một trạm | `sensor_config` |
| Q3 | Lấy N bản ghi **mới nhất** của một trạm | `sensor_logs` |
| Q4 | Lấy log của một trạm trong **dải thời gian** (vd: 2 giờ qua) để vẽ biểu đồ | `sensor_logs` |
| Q5 | Ghi nhận một log đo mới (luồng ghi chính) | `sensor_logs` |

### 3.2 Bảng chính `sensor_logs`

```sql
CREATE TABLE sensor_logs (
    station_id   text,
    log_date     date,
    ts           timestamp,
    temperature  double,
    humidity     double,
    pressure     double,
    PRIMARY KEY ((station_id, log_date), ts)
) WITH CLUSTERING ORDER BY (ts DESC);
```

| Thành phần | Giá trị | Lý do chọn |
|---|---|---|
| **Partition Key** | `(station_id, log_date)` (composite) | Mọi truy vấn đều biết trạm và ngày → chỉ đọc **một** partition (một node). Gộp `log_date` để **chặn partition tăng vô hạn** (time bucketing). |
| **Clustering Key** | `ts`, `CLUSTERING ORDER BY (ts DESC)` | Trong partition, dòng được sắp xếp vật lý theo thời gian **mới nhất trước**: Q3 chỉ đọc đầu partition; Q4 lọc `ts >= ? AND ts <= ?` đọc một đoạn liên tục. Không cần sort ở tầng ứng dụng. |

> Barem ghi cột `timestamp`; bài này đặt tên cột là `ts` để không trùng tên kiểu dữ liệu `timestamp` của CQL. Vai trò hoàn toàn như nhau.
> `log_date` và `ts` lưu theo **UTC**; giao diện web đổi sang giờ địa phương của trình duyệt.

**Tính kích thước partition** (chứng minh bucket theo ngày hợp lý): mỗi dòng gồm `ts` (8 byte) + 3 giá trị `double` (24 byte) + overhead ≈ 60–100 byte.
Với 1 bản ghi/phút: 1.440 dòng/ngày/trạm ≈ 100–150 KB. Với 1 bản ghi/giây: 86.400 dòng ≈ 6–9 MB.
Cả hai đều dưới ngưỡng khuyến nghị (~100 MB, ≤ ~100.000 dòng/partition). Nếu chỉ dùng `station_id` làm Partition Key, một trạm chạy nhiều năm sẽ tạo partition khổng lồ, làm chậm đọc, nén và repair.

**Bằng chứng trên dữ liệu thật** (đếm bằng `SELECT COUNT(*) ... WHERE station_id=? AND log_date=?`):

| Lần đếm | Partition | Số dòng |
|---|---|---|
| Trước khi nạp lại dữ liệu (dữ liệu vắt qua nửa đêm UTC) | `('ST01', '2026-10-20')` | 41 |
| | `('ST01', '2026-10-21')` | 171 |
| | **Tổng ST01** | **212** (10 trạm ≈ 2.120 bản ghi) |
| Sau khi nạp lại 2.400 bản ghi (mỗi phút, 04:34–08:33 UTC ngày 21/10) | `('ST01', '2026-10-21')` | 240 (10 trạm = 2.400) |

Lần đếm đầu cho thấy cùng một trạm được chia thành **hai partition theo ngày**, mỗi partition chỉ vài trăm dòng.

### 3.3 Các bảng phụ

```sql
CREATE TABLE stations (
    station_id text PRIMARY KEY,            -- Partition Key
    name text, location text, latitude double, longitude double,
    status text, created_at timestamp
);

CREATE TABLE sensor_config (
    station_id text, sensor_type text,
    unit text, min_value double, max_value double, interval_sec int, enabled boolean,
    PRIMARY KEY (station_id, sensor_type)   -- Partition: station_id; Clustering: sensor_type
);
```

- `stations`: bảng tham chiếu nhỏ (vài chục dòng) nên việc liệt kê toàn bộ chấp nhận được.
- `sensor_config`: lấy cả 3 cảm biến của một trạm bằng **một** truy vấn theo `station_id`.

## 4. Chức năng CRUD nền tảng (2.5đ)

| Chức năng | CQL (trong `repo.py`) | API | Giao diện |
|---|---|---|---|
| Tạo trạm mới (kèm cấu hình mặc định 3 cảm biến) | `INSERT INTO stations … IF NOT EXISTS` (LWT chống trùng mã) + `INSERT INTO sensor_config …` | `POST /api/stations` | Nút **+ Trạm mới**: chọn vị trí trên bản đồ hoặc tìm thành phố, tọa độ tự điền |
| Xem / liệt kê trạm | `SELECT * FROM stations [WHERE station_id=?]` | `GET /api/stations` | Ô chọn trạm, bảng tổng quan, bản đồ |
| Sửa trạm | `UPDATE stations SET … WHERE station_id=? IF EXISTS` | `PUT /api/stations/<id>` | – |
| Xóa trạm | `DELETE` bản ghi `stations`, `sensor_config` và các partition log gần đây | `DELETE /api/stations/<id>` | Nút **Xóa trạm** |
| Cấu hình tham số cảm biến | `INSERT INTO sensor_config …` (upsert) | `PUT /api/stations/<id>/sensors/<loại>` | Nút **Cấu hình cảm biến** (ngưỡng, chu kỳ đo, bật/tắt) |
| Ghi nhận log đo | `INSERT INTO sensor_logs (station_id, log_date, ts, …) VALUES (?,?,?,?,?,?)` | `POST /api/logs` | Nút **Ghi log thủ công**; luồng tự động từ `simulator.py` |

Điểm kỹ thuật: dùng *prepared statement* cho mọi truy vấn lặp lại; ghi hàng loạt bằng `execute_concurrent_with_args` (song song, không dùng batch đa partition vì làm tăng tải coordinator);
kiểm tra dữ liệu đầu vào ở API (mã trạm, khoảng giá trị hợp lệ, ngưỡng dưới < ngưỡng trên); ngưỡng cảnh báo được dashboard dùng để tô đỏ thẻ chỉ số và vẽ đường ngưỡng.

## 5. Chức năng nâng cao đặc trưng (2.5đ)

### 5.1 Cấu trúc khóa chính cho time-series

`PRIMARY KEY ((station_id, log_date), ts)` + `CLUSTERING ORDER BY (ts DESC)`: dữ liệu mới nhất nằm đầu partition, sắp xếp sẵn trên đĩa.

### 5.2 Truy vấn dải thời gian hiệu quả

```sql
SELECT station_id, log_date, ts, temperature, humidity, pressure
FROM sensor_logs
WHERE station_id = 'ST01'
  AND log_date   = '2026-10-21'
  AND ts >= '2026-10-21 05:10:40+0000'
  AND ts <= '2026-10-21 07:10:40+0000';
```

**Kết quả chạy thật trên CQL Console của Astra** (lần chạy trước khi nạp lại dữ liệu): 28 dòng, dòng đầu `07:09:56.488` và dòng cuối `05:15:00` – tức đã sắp xếp mới → cũ mà câu lệnh **không có `ORDER BY`**.

- `station_id` + `log_date` xác định đúng **một partition**; điều kiện `ts` là **range trên Clustering Key** nên Cassandra chỉ đọc đoạn liên tục cần thiết – không quét toàn bảng, không cần `ALLOW FILTERING`.
- **`BETWEEN`**: CQL không có toán tử này; dùng cặp `>=` / `<=` (hoặc `>` / `<`) với ý nghĩa tương đương.
- Khoảng thời gian vắt qua nửa đêm UTC nằm ở 2 partition: ứng dụng truy vấn từng ngày (hoặc dùng `log_date IN (…)`).
- Đảo chiều đọc không cần sort ở ứng dụng: `ORDER BY ts ASC` được Cassandra thực hiện bằng cách đọc ngược (dùng cho biểu đồ cũ → mới).
- Truy vấn **không** nên làm (để giải thích khi vấn đáp): thiếu `log_date` (cần `ALLOW FILTERING`, quét cả cụm) hoặc `SELECT COUNT(*)` toàn bảng.
- Toàn bộ câu lệnh mẫu có trong `cql/queries.cql`; `demo_query.py` tự in sẵn câu lệnh "2 giờ qua".

## 6. Triển khai trên Astra DB

1. Tạo database *Serverless (non-vector)*, provider AWS, region `us-east-2`, keyspace `weather` (gói miễn phí; Astra không cho `CREATE KEYSPACE` bằng CQL).
2. Tạo Application Token (role Database Administrator) và tải Secure Connect Bundle (`.zip`, không giải nén).
3. Khai báo trong `.env`: đường dẫn bundle, token, keyspace. Kết nối bằng `PlainTextAuthProvider('token', <token>)`, consistency `LOCAL_QUORUM`.
4. `python init_schema.py` tạo 3 bảng; `python seed_data.py` nạp dữ liệu mẫu.

Môi trường chạy: Windows, Python 3.13 (cần thêm gói `pyasyncore` vì Python ≥ 3.12 đã bỏ module `asyncore` mà driver sử dụng).

## 7. Kiểm thử hiệu năng & Demo (2.5đ)

### 7.1 Dummy data (đạt định mức – 1.0đ)

| Tiêu chí | Định mức | Thực hiện |
|---|---|---|
| Trạm quan trắc | 5–10 | **10** (`ST01`…`ST10`) |
| Bản ghi time-series | 500–1.000 | **2.400** bản ghi mẫu trải đều theo từng phút (10 trạm × 240, 4 giờ gần nhất: 04:34–08:33 UTC ngày 21/10/2026), cộng thêm dữ liệu do simulator ghi khi demo |
| Chỉ số | nhiệt độ, độ ẩm, áp suất | đủ 3 chỉ số, mô hình theo chu kỳ ngày + nhiễu nhỏ |

### 7.2 Kết quả đo (ngày 21/10/2026, máy ở Việt Nam, database ở AWS us-east-2)

| Phép đo | Kết quả |
|---|---|
| Nạp dữ liệu mẫu | 2.400/2.400 bản ghi trong 31,26 s (≈ 77 bản ghi/giây); lần nạp trước đó 1.200/1.200 bản ghi trong 22,47 s (≈ 53 bản ghi/giây) |
| Simulator 12 vòng × 10 trạm | 120/120 bản ghi trong 29,8 s; mỗi vòng 10 bản ghi ghi song song mất khoảng 0,86–2,56 s |
| Simulator chạy liên tục | 800/800 bản ghi trong 283,0 s; mỗi vòng khoảng 0,8–3,8 s |
| Truy vấn dải thời gian (ST01, 2 giờ qua, 107 bản ghi) | 5 lần đo: min **534 ms**, TB **741 ms**, max **1.239 ms** |
| Thời gian truy vấn hiển thị trên dashboard | khoảng 0,5–1 s mỗi lần làm mới (TB 809 ms qua một phiên dài, có lúc tăng đột biến) |
| Mở kết nối lần đầu | khoảng 45–49 s (chỉ một lần khi khởi động) |

**Nhận xét:** các con số này **gồm độ trễ mạng** từ Việt Nam tới máy chủ ở Mỹ (vài trăm ms mỗi vòng đi–về) và giới hạn tài nguyên của gói miễn phí, nên không phản ánh tốc độ xử lý bên trong Cassandra.
Điểm cần chú ý là thời gian truy vấn **ổn định khi dữ liệu tăng**: bảng đã có hơn 2.000 bản ghi nhưng lấy 107 bản ghi trong dải thời gian vẫn chỉ vài trăm ms vì Cassandra đọc một đoạn liên tục trong một partition thay vì quét bảng.
Để đo thuần hiệu năng của Cassandra, cần chạy cùng mã nguồn với Cassandra cài cục bộ (chỉ đổi file `.env`).

### 7.2b Đo tải nhiều luồng (`benchmark.py`)

Script `benchmark.py` cho 1, 5 và 10 luồng cùng ghi (mỗi luồng ghi tuần tự, chờ phản hồi rồi mới ghi tiếp), đo tốc độ ghi,
độ trễ trung bình / p50 / p95 / p99 và tỷ lệ lỗi, rồi đo truy vấn dải thời gian 2 giờ. Trạm tạm `BENCH01` được xóa sau khi đo.

> **[Dán bảng từ `docs/ket-qua-do/benchmark_result.md` vào đây sau khi chạy `python benchmark.py` trên Astra]**

Nhận xét cần nêu: độ trễ mỗi lần ghi chủ yếu là độ trễ mạng Việt Nam ↔ AWS us-east-2 nên tốc độ ghi tăng gần tuyến tính theo số luồng
(Cassandra không bị nghẽn), tỷ lệ lỗi dự kiến 0%.

### 7.2c Độ bền khi chạy thật

- Timeout mỗi truy vấn 20 s (`REQUEST_TIMEOUT`), driver dùng `RetryPolicy`; ghi hàng loạt tự thử lại tối đa 2 lần. Retry an toàn vì ghi
  trùng `(station_id, log_date, ts)` chỉ ghi đè (idempotent).
- Đọc có phân trang của driver (`fetch_size = 500`), không tải cả lịch sử cùng lúc.
- Lỗi kết nối / timeout được API trả về mã 503 kèm thông báo tiếng Việt thay vì lỗi 500; `/api/health` kiểm tra nhanh kết nối.
- Chỉ dùng LWT (`IF NOT EXISTS`) khi tạo trạm, **không** dùng cho ghi log; không `COUNT(*)` toàn bảng, chỉ đếm theo partition.
- Kích thước partition: mỗi trạm ghi 1 bản ghi/phút ≈ 1.440 dòng/ngày/partition (rất nhỏ). Nếu tần suất lên mỗi giây (86.400 dòng/ngày)
  sẽ chia bucket theo giờ: `((station_id, log_date, hour), ts)`.
- Dashboard hiển thị trạng thái từng trạm theo log cuối: *Hoạt động* (≤ 2 phút), *Mất kết nối* (quá 2 phút), *Chưa có dữ liệu*.

### 7.3 Giả lập luồng dữ liệu

`simulator.py` giả lập 10 cảm biến gửi liên tục (mặc định 12 vòng × 10 trạm = 120 bản ghi); mỗi cảm biến thay đổi giá trị nhỏ và liên tục (mô hình đi bộ ngẫu nhiên bám theo giá trị theo giờ), in thời gian ghi mỗi vòng.

### 7.4 Kịch bản demo (1.5đ)

1. **SV3** chạy `python simulator.py --rounds 12 --interval 3` → 120 bản ghi được nạp.
2. **SV2** chạy `python demo_query.py ST01 2`, dán câu CQL vào **CQL Console** → lọc 2 giờ qua, kết quả mới → cũ, không sort ở ứng dụng.
3. **SV1 & SV3** mở dashboard (`http://localhost:5000`) → biểu đồ đường tự cập nhật mỗi 2 giây, hiển thị thời gian truy vấn (ms).

Hướng dẫn chi tiết trong `README.md` mục 3.

## 8. Web Dashboard

- 3 biểu đồ đường (nhiệt độ, độ ẩm, áp suất) trên **trục thời gian thật**; đường ngắt ở các khoảng không có dữ liệu; nét đứt là ngưỡng cảnh báo.
- Thẻ chỉ số: giá trị hiện tại, xu hướng (▲/▼), min/TB/max, thanh vị trí trong ngưỡng an toàn, tô đỏ khi vượt ngưỡng.
- Biểu đồ **thời gian truy vấn Cassandra (ms)** theo từng lần làm mới.
- Bản đồ các trạm (Leaflet) màu theo nhiệt độ, bảng tổng quan, bảng 10 bản ghi mới nhất, chỉ báo độ mới của dữ liệu, nút tạm dừng.
- Tạo trạm mới bằng bản đồ: bấm lên bản đồ hoặc tìm tên thành phố, tọa độ, tên và địa điểm tự điền.

## 9. Phân công & sản phẩm

| Thành viên | Nhiệm vụ | Sản phẩm |
|---|---|---|
| SV1 | Phân tích query-driven, thiết kế bảng, Partition/Clustering Key, API ghi log | `cql/schema.cql`, `repo.py`, `app.py` (`/api/stations`, `POST /api/logs`) |
| SV2 | Tối ưu truy vấn CQL lọc chuỗi thời gian, không sort ở ứng dụng | `cql/queries.cql`, `demo_query.py`, `repo.query_range()` |
| SV3 | Script giả lập 10 cảm biến, quản trị keyspace trên CQLSH, dashboard, điều phối demo | `simulator.py`, `seed_data.py`, `init_schema.py`, `db.py`, `templates/index.html` |

## 10. Hạn chế và hướng phát triển

- Độ trễ cao do database ở region Mỹ (gói miễn phí không chọn được region gần); cần so sánh với Cassandra cục bộ hoặc nhiều node để đo thuần hiệu năng.
- Xoá trạm chỉ xoá log của 14 ngày gần nhất; môi trường thật nên đặt `default_time_to_live` để dữ liệu cũ tự hết hạn.
- Dùng bảng tổng hợp theo giờ/ngày (rollup) để vẽ biểu đồ khoảng thời gian dài nhanh hơn; dùng WebSocket/SSE thay cho polling 2 giây.
- Ngưỡng cảnh báo hiện chỉ tô đỏ trên giao diện, chưa gửi thông báo.
- Bảo mật: token lưu trong `.env` (đã loại khỏi git); cần thu hồi token sau khi kết thúc đồ án.

## Phụ lục: ảnh minh chứng cần chèn

1. Trang tạo database trên Astra (trạng thái **Active**, keyspace `weather`).
2. CQL Console: `DESCRIBE TABLE sensor_logs;` thấy `PRIMARY KEY ((station_id, log_date), ts)` và `CLUSTERING ORDER BY (ts DESC)`.
3. CQL Console: câu `SELECT` dải thời gian và kết quả (28 dòng).
4. CQL Console: lệnh `COUNT(*)` theo từng partition của ST01 (ghi rõ ngày và số dòng).
5. Terminal `seed_data.py` (1200/1200) và `simulator.py` (120/120).
6. Dashboard đang nhận dữ liệu (biểu đồ, bản đồ, ms truy vấn).
7. Dialog tạo trạm mới với bản đồ; dashboard sau khi tạo trạm.
