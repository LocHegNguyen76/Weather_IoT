-- =====================================================================
-- SCHEMA: HỆ THỐNG GIÁM SÁT DỮ LIỆU CẢM BIẾN IOT WEATHER STATION
-- Apache Cassandra / DataStax Astra DB
--
-- LƯU Ý: Astra DB KHÔNG cho phép CREATE KEYSPACE bằng CQL.
--        Hãy tạo keyspace (ví dụ: weather) trong giao diện Astra trước,
--        rồi chạy:  python init_schema.py   (hoặc dán file này vào CQL Console,
--        sau khi đã gõ: USE weather;)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Q1: Liệt kê / xem thông tin trạm quan trắc
--     SELECT * FROM stations WHERE station_id = ?;
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stations (
    station_id  text PRIMARY KEY,
    name        text,
    location    text,
    latitude    double,
    longitude   double,
    status      text,          -- active | inactive
    created_at  timestamp
);

-- ---------------------------------------------------------------------
-- Q2: Lấy cấu hình các cảm biến của một trạm
--     SELECT * FROM sensor_config WHERE station_id = ?;
-- Partition Key : station_id
-- Clustering Key: sensor_type  (temperature | humidity | pressure)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_config (
    station_id    text,
    sensor_type   text,
    unit          text,
    min_value     double,      -- ngưỡng dưới (cảnh báo)
    max_value     double,      -- ngưỡng trên (cảnh báo)
    interval_sec  int,         -- chu kỳ đo (giây)
    enabled       boolean,
    PRIMARY KEY (station_id, sensor_type)
);

-- ---------------------------------------------------------------------
-- Q3: N bản ghi mới nhất của một trạm
--     SELECT * FROM sensor_logs WHERE station_id=? AND log_date=? LIMIT N;
-- Q4: Dữ liệu của một trạm trong dải thời gian (vd: 2 giờ qua)
--     SELECT * FROM sensor_logs
--      WHERE station_id=? AND log_date=? AND ts >= ? AND ts <= ?;
--
-- Partition Key : (station_id, log_date)   -> chia nhỏ partition theo NGÀY
-- Clustering Key: ts DESC                  -> bản ghi mới nhất nằm đầu partition
--
-- Cột "ts" chính là cột timestamp trong barem (tránh dùng trùng tên kiểu dữ liệu).
-- log_date luôn tính theo UTC.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_logs (
    station_id   text,
    log_date     date,
    ts           timestamp,
    temperature  double,       -- °C
    humidity     double,       -- %
    pressure     double,       -- hPa
    PRIMARY KEY ((station_id, log_date), ts)
) WITH CLUSTERING ORDER BY (ts DESC);

-- Tuỳ chọn (Cassandra tự quản trị, không dùng được trên một số gói Astra):
--   AND compaction = {'class': 'TimeWindowCompactionStrategy',
--                     'compaction_window_unit': 'DAYS',
--                     'compaction_window_size': 1}
--   AND default_time_to_live = 7776000;   -- tự xoá log sau 90 ngày
