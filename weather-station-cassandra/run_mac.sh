#!/bin/bash
# Dùng:  ./run_mac.sh check | init | seed | app | sim | query | bench
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate || { echo "Chạy ./setup_mac.sh trước"; exit 1; }
export PYTHONUTF8=1 PORT=${PORT:-5001}   # macOS dùng cổng 5000 cho AirPlay nên đổi sang 5001
case "$1" in
  check) python db.py ;;
  init)  python init_schema.py ;;
  seed)  python seed_data.py ;;
  app)   echo "Mở http://localhost:$PORT"; python app.py ;;
  appnosim) python app.py --no-sim ;;
  sim)   python simulator.py --rounds 12 --interval 3 ;;
  forever) python simulator.py --forever --interval 2 ;;
  query) python demo_query.py "${2:-ST01}" "${3:-2}" ;;
  bench) python benchmark.py ;;
  *) echo "Dùng: ./run_mac.sh check|init|seed|app|appnosim|sim|forever|query [trạm giờ]|bench" ;;
esac
