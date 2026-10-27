-- =====================================================================
-- CÁC CÂU LỆNH CQL DÙNG ĐỂ DEMO TRÊN CQLSH / ASTRA CQL CONSOLE (SV2, SV3)
-- Thay '2026-10-21' và khung giờ bằng ngày/giờ UTC thực tế của bạn
-- (giờ Việt Nam = UTC + 7).
-- Tip: chạy `python demo_query.py ST01 2` để in sẵn câu lệnh cho "2 giờ qua".
-- =====================================================================
USE weather;

-- 0) Quản trị keyspace và kiểm tra thiết kế bảng (SV3) -----------------
DESCRIBE KEYSPACE weather;
DESCRIBE TABLE sensor_logs;     -- thấy PRIMARY KEY ((station_id, log_date), ts) và CLUSTERING ORDER BY (ts DESC)

-- 1) Xem các trạm và cấu hình cảm biến ---------------------------------
SELECT * FROM stations;
SELECT * FROM sensor_config WHERE station_id = 'ST01';

-- 2) 10 bản ghi MỚI NHẤT của trạm (nhờ CLUSTERING ORDER BY ts DESC,
--    Cassandra chỉ đọc đầu partition, không cần ORDER BY) -----------------
SELECT * FROM sensor_logs
WHERE station_id = 'ST01' AND log_date = '2026-10-21'
LIMIT 10;

-- 3) Truy vấn dải thời gian: ts >= ... AND ts <= ... -------------------
--    (CQL không có BETWEEN; cặp >= / <= tương đương BETWEEN)
SELECT station_id, log_date, ts, temperature, humidity, pressure FROM sensor_logs
WHERE station_id = 'ST01'
  AND log_date   = '2026-10-21'
  AND ts >= '2026-10-21 05:10:40+0000'
  AND ts <= '2026-10-21 07:10:40+0000';

-- 4) Chỉ dùng một cận: sau mốc / trước mốc ----------------------------
SELECT ts, temperature FROM sensor_logs
WHERE station_id = 'ST01' AND log_date = '2026-10-21'
  AND ts > '2026-10-21 06:00:00+0000';

SELECT ts, temperature FROM sensor_logs
WHERE station_id = 'ST01' AND log_date = '2026-10-21'
  AND ts < '2026-10-21 06:00:00+0000';

-- 5) Đảo chiều đọc (cũ -> mới) mà vẫn KHÔNG sort ở ứng dụng ------------
SELECT ts, temperature FROM sensor_logs
WHERE station_id = 'ST01' AND log_date = '2026-10-21'
  AND ts >= '2026-10-21 05:00:00+0000' AND ts <= '2026-10-21 07:00:00+0000'
ORDER BY ts ASC;

-- 6) Khoảng thời gian vắt qua nửa đêm UTC (2 partition) -----------------
SELECT ts, temperature FROM sensor_logs
WHERE station_id = 'ST01'
  AND log_date IN ('2026-10-20', '2026-10-21')
  AND ts >= '2026-10-20 22:00:00+0000' AND ts <= '2026-10-21 02:00:00+0000';

-- 7) Đếm số bản ghi trên TỪNG partition (an toàn, hiệu quả) -------------
--    Kết quả thực tế: 41 + 171 = 212 bản ghi cho ST01 (10 trạm ~ 2.120)
SELECT COUNT(*) FROM sensor_logs WHERE station_id = 'ST01' AND log_date = '2026-10-20';
SELECT COUNT(*) FROM sensor_logs WHERE station_id = 'ST01' AND log_date = '2026-10-21';

-- 8) Hàm tổng hợp trên MỘT partition (hiệu quả) -------------------------
SELECT COUNT(*) AS so_ban_ghi, MIN(temperature) AS t_min, MAX(temperature) AS t_max,
       AVG(temperature) AS t_tb
FROM sensor_logs
WHERE station_id = 'ST01' AND log_date = '2026-10-21';

-- 9) Truy vấn SAI thiết kế (chỉ để giải thích khi vấn đáp, KHÔNG nên chạy) ----
-- Thiếu log_date => Cassandra từ chối (cần ALLOW FILTERING = quét toàn cụm):
-- SELECT * FROM sensor_logs WHERE station_id = 'ST01' AND ts > '2026-10-21 08:00:00+0000';
-- Lọc theo cột thường mà không có index/SAI:
-- SELECT * FROM sensor_logs WHERE station_id='ST01' AND log_date='2026-10-21' AND temperature > 30;
-- Đếm toàn bảng (quét tất cả partition, dễ timeout):
-- SELECT COUNT(*) FROM sensor_logs;
