Chế độ: Astra DB. Mỗi luồng ghi 40 bản ghi tuần tự (chờ phản hồi mới ghi tiếp), consistency LOCAL_QUORUM.

| Số luồng | Bản ghi | Thành công | Thời gian (s) | Tốc độ (bản ghi/s) | TB (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Lỗi (%) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 40 | 40 | 27.0 | 1.5 | 675 | 604 | 1136 | 2542 | 0.0 |
| 5 | 200 | 200 | 38.3 | 5.2 | 923 | 853 | 1530 | 1849 | 0.0 |
| 10 | 400 | 400 | 57.3 | 7.0 | 1375 | 1162 | 2324 | 7000 | 0.0 |

Truy vấn dải thời gian (2 giờ, trạm ST01, 793 dòng): TB 2531 ms, min 1262 ms, max 5119 ms (5 lần).
