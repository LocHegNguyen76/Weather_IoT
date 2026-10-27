"""Danh sách 10 trạm quan trắc mẫu + mô hình sinh số liệu thời tiết giả lập
(dùng chung cho seed_data.py và simulator.py)."""
import math
import random

# station_id, tên, địa điểm, vĩ độ, kinh độ, (nhiệt độ nền °C, độ ẩm nền %, áp suất nền hPa)
STATIONS = [
    ("ST01", "Trạm Hà Nội", "Hà Nội", 21.0285, 105.8542, (24.0, 75, 1012)),
    ("ST02", "Trạm TP. Hồ Chí Minh", "TP. Hồ Chí Minh", 10.8231, 106.6297, (30.0, 70, 1009)),
    ("ST03", "Trạm Đà Nẵng", "Đà Nẵng", 16.0544, 108.2022, (27.0, 76, 1010)),
    ("ST04", "Trạm Hải Phòng", "Hải Phòng", 20.8449, 106.6881, (24.0, 78, 1013)),
    ("ST05", "Trạm Cần Thơ", "Cần Thơ", 10.0452, 105.7469, (29.0, 74, 1009)),
    ("ST06", "Trạm Huế", "Thừa Thiên Huế", 16.4637, 107.5909, (26.0, 80, 1011)),
    ("ST07", "Trạm Nha Trang", "Khánh Hòa", 12.2388, 109.1967, (28.0, 72, 1010)),
    ("ST08", "Trạm Đà Lạt", "Lâm Đồng", 11.9404, 108.4583, (19.0, 82, 1018)),
    ("ST09", "Trạm Vũng Tàu", "Bà Rịa - Vũng Tàu", 10.3460, 107.0843, (29.0, 73, 1010)),
    ("ST10", "Trạm Buôn Ma Thuột", "Đắk Lắk", 12.6667, 108.0500, (25.0, 70, 1014)),
]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def base_values(base, minute_of_day):
    """Giá trị 'trung bình' theo giờ trong ngày: nóng nhất ~14h, ẩm nhất lúc sáng sớm."""
    t0, h0, p0 = base
    phase = 2 * math.pi * (minute_of_day - 14 * 60) / (24 * 60)
    temp = t0 + 4.0 * math.cos(phase)
    hum = h0 - 10.0 * math.cos(phase)
    pres = p0 + 1.5 * math.cos(2 * phase)
    return temp, hum, pres


def sample(base, minute_of_day, rng=random):
    """Một lần đo: giá trị nền theo giờ + nhiễu ngẫu nhiên."""
    t, h, p = base_values(base, minute_of_day)
    t += rng.gauss(0, 0.4)
    h += rng.gauss(0, 1.5)
    p += rng.gauss(0, 0.3)
    return _clamp(t, -10, 50), _clamp(h, 5, 100), _clamp(p, 900, 1080)


def make_walker(base, rng=random):
    """Cảm biến giả lập đổi giá trị nhỏ và liên tục giữa hai lần đo (giống cảm biến thật),
    có xu hướng bám theo giá trị nền của giờ hiện tại."""
    state = None

    def step(minute_of_day):
        nonlocal state
        target = base_values(base, minute_of_day)
        if state is None:
            state = list(target)
        sigma = (0.04, 0.15, 0.03)
        for i in range(3):
            state[i] += (target[i] - state[i]) * 0.05 + rng.gauss(0, sigma[i])
        t, h, p = state
        return _clamp(t, -10, 50), _clamp(h, 5, 100), _clamp(p, 900, 1080)

    return step


BASES = {st[0]: st[5] for st in STATIONS}


def base_for(station):
    """Giá trị nền (nhiệt độ, độ ẩm, áp suất) của một trạm (dict lấy từ CSDL).
    Trạm mẫu dùng giá trị định sẵn; trạm tạo thêm được ước lượng theo vĩ độ."""
    if station["station_id"] in BASES:
        return BASES[station["station_id"]]
    lat = station.get("latitude")
    lat = 14.0 if lat is None else lat
    return (round(30.0 - 0.35 * max(lat - 10.0, 0.0), 1), 76.0, 1011.0)
