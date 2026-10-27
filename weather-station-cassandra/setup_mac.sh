#!/bin/bash
# Cài đặt một lần trên macOS: tạo môi trường ảo, cài thư viện, kiểm tra cấu hình
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3)
[ -z "$PY" ] && { echo "❌ Chưa có Python 3. Cài bằng: brew install python  (hoặc tải ở python.org)"; exit 1; }
echo "▶ Dùng $($PY --version)"
$PY -m venv .venv || exit 1
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt || exit 1
[ -f .env ] || { cp .env.example .env; echo "⚠ Đã tạo .env từ mẫu – hãy mở .env và điền ASTRA_DB_TOKEN (AstraCS:...)"; }
BUNDLE=$(grep -E '^ASTRA_DB_BUNDLE=' .env | cut -d= -f2)
[ -f "$BUNDLE" ] || echo "⚠ Chưa thấy file Secure Connect Bundle ($BUNDLE). Copy file secure-connect-*.zip vào thư mục này và sửa ASTRA_DB_BUNDLE trong .env."
echo "✅ Xong. Bước tiếp: ./run_mac.sh check"
