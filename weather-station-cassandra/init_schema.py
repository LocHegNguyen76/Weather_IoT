"""Tạo bảng từ cql/schema.cql.  Chạy:  python init_schema.py

- Astra DB: keyspace phải tạo sẵn trong giao diện Astra (không CREATE KEYSPACE bằng CQL được).
- Cassandra cục bộ: script tự tạo keyspace nếu chưa có.
"""
from pathlib import Path

import db


def statements(text: str):
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        stmt = stmt.strip()
        if stmt:
            yield stmt


def main():
    if not db.is_astra():
        s = db.get_session(use_keyspace=False)
        s.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {db.KEYSPACE} "
            "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}"
        )
        print(f"Đã đảm bảo keyspace '{db.KEYSPACE}' tồn tại (Cassandra cục bộ)")
    session = db.get_session()
    text = Path(__file__).parent / "cql" / "schema.cql".read_text(encoding="utf-8")
    for stmt in statements(text):
        session.execute(stmt)
        first = " ".join(stmt.split())[:70]
        print("OK  ", first, "...")
    print("Hoàn tất: các bảng stations, sensor_config, sensor_logs đã sẵn sàng.")
    db.close()


if __name__ == "__main__":
    main()
