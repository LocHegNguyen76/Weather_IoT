# Hướng dẫn cài đặt, chạy và demo trên macOS

## A. Chuẩn bị (một lần)
1. Giải nén thư mục dự án, mở **Terminal**, `cd` vào thư mục (kéo thả thư mục vào Terminal sau chữ `cd `).
2. Cần Python 3.9+: kiểm tra `python3 --version`; chưa có thì `brew install python`.
3. Chép từ máy Windows sang thư mục này **2 thứ bí mật** (không có trong gói vì lý do bảo mật):
   - file `secure-connect-weather-station.zip` (không giải nén);
   - file `.env` (hoặc `cp .env.example .env` rồi điền `ASTRA_DB_TOKEN=AstraCS:...`, `ASTRA_DB_BUNDLE=./secure-connect-weather-station.zip`, `ASTRA_KEYSPACE=weather`).
   > File `.env` bắt đầu bằng dấu chấm nên bị ẩn: nhấn **Cmd + Shift + .** trong Finder để hiện.
4. Cài đặt:
   ```bash
   chmod +x setup_mac.sh run_mac.sh
   ./setup_mac.sh
   ```
5. Mở trang Astra, nếu database đang *Hibernated* thì bấm **Resume** và chờ *Active*.

## B. Chạy
```bash
./run_mac.sh check     # thử kết nối (lần đầu ~40 giây), in phiên bản Cassandra
./run_mac.sh init      # tạo 3 bảng (bỏ qua nếu đã tạo trên Astra)
./run_mac.sh seed      # nạp 10 trạm x 240 bản ghi (bỏ qua nếu dữ liệu đã có)
./run_mac.sh app       # chạy dashboard → mở http://localhost:5001
```
Dùng cổng **5001** vì macOS chiếm cổng 5000 cho AirPlay Receiver. Muốn đổi: `PORT=8080 ./run_mac.sh app`.

Terminal thứ hai (Cmd + T), cùng thư mục:
```bash
./run_mac.sh sim       # 12 vòng x 10 trạm, cách 3 giây
./run_mac.sh forever   # chạy mãi, Ctrl + C để dừng
```

## C. Kịch bản demo (≈ 8 phút)
Trước giờ demo: `./run_mac.sh check`, chạy `./run_mac.sh appnosim`, mở dashboard, chọn **ST01**, khoảng **30 phút qua**, làm mới **2 giây**. Mở Astra → CQL console → gõ `USE weather;`.

| Bước | Thao tác | Nói gì |
|---|---|---|
| 1. Thiết kế | Mở `docs/BAO_CAO.md` hoặc slide 4–6 | Query-driven: `PRIMARY KEY ((station_id, log_date), ts)`, `CLUSTERING ORDER BY (ts DESC)`; partition theo ngày để không phình vô hạn |
| 2. Ghi nhiều | Terminal 2: `./run_mac.sh sim` | 10 cảm biến ghi liên tục, 120 bản ghi, prepared statement + ghi đồng thời |
| 3. Biểu đồ trực tiếp | Dashboard | Đường biểu đồ kéo dài theo từng vòng; badge *Truy vấn: x ms* |
| 4. Truy vấn dải thời gian | `./run_mac.sh query ST01 2`, dán CQL vào CQL console | `ts >= ? AND ts <= ?` trên 1 partition, kết quả mới → cũ, không sort ở ứng dụng; giờ CQL là UTC (VN − 7) |
| 5. CRUD | Dashboard: **+ Trạm mới** (chọn trên bản đồ), **Ghi log thủ công**, **Cấu hình cảm biến**, **Xóa trạm** | Tạo trạm có LWT (`IF NOT EXISTS`); trạm mới tự nạp 4 giờ lịch sử, bật `./run_mac.sh app` (có luồng nền) để thấy dữ liệu chảy |
| 6. Quản trị | CQL console: `DESCRIBE KEYSPACE weather;`, `SELECT COUNT(*) FROM sensor_logs WHERE station_id='ST01' AND log_date='2026-10-27';` | COUNT chỉ nên theo 1 partition |
| 7. Kiểm thử hiệu năng | Slide 10 / `docs/ket-qua-do/benchmark_result.md` (hoặc chạy `./run_mac.sh bench`, ~1 phút) | 1/5/10 luồng: 1,5 / 5,2 / 7,0 bản ghi/giây, 0% lỗi; độ trễ cao do mạng Việt Nam → Mỹ |

Lưu ý: bước 2 dùng `appnosim` để luồng nền của `app.py` và `simulator` không ghi chồng nhau; bước 5 thì tắt `appnosim` rồi chạy lại `./run_mac.sh app`.

## D. Sự cố thường gặp trên Mac
| Hiện tượng | Cách xử lý |
|---|---|
| Mở localhost:5000 báo 403 | Đó là AirPlay; dùng cổng 5001 như hướng dẫn |
| `permission denied: ./run_mac.sh` | `chmod +x setup_mac.sh run_mac.sh` |
| `Unable to load a default connection class` / thiếu `asyncore` | `source .venv/bin/activate && pip install pyasyncore` (Python 3.12+) |
| `Không tìm thấy Secure Connect Bundle` | Kiểm tra đường dẫn `ASTRA_DB_BUNDLE` trong `.env`, file zip còn nguyên |
| `AuthenticationFailed` | Token sai/hết hạn: tạo token mới trong Astra |
| Treo ở lần kết nối đầu | Database hibernate: bấm *Resume* trên Astra, đợi *Active* |
| SSL / certificate lỗi | Chạy `/Applications/Python\ 3.x/Install\ Certificates.command` (Python tải từ python.org) |
