"""Kết nối Cassandra: ưu tiên DataStax Astra DB (Secure Connect Bundle + Token),
nếu không cấu hình Astra thì dùng Cassandra cài trên máy (CASSANDRA_HOSTS)."""
import os
from pathlib import Path

from cassandra import ConsistencyLevel
from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
from cassandra.policies import RetryPolicy
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

KEYSPACE = os.getenv("ASTRA_KEYSPACE", "weather")

_cluster = None
_session = None


def is_astra() -> bool:
    return bool(os.getenv("ASTRA_DB_BUNDLE"))


def _profile():
    return ExecutionProfile(
        consistency_level=ConsistencyLevel.LOCAL_QUORUM,
        serial_consistency_level=ConsistencyLevel.LOCAL_SERIAL,
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),  # giây; quá hạn -> OperationTimedOut
        retry_policy=RetryPolicy(),   # retry có kiểm soát của driver (tối đa 1 lần trên cùng/nhẹ lỗi tạm thời)
    )


def _make_cluster() -> Cluster:
    profiles = {EXEC_PROFILE_DEFAULT: _profile()}
    if is_astra():
        bundle = os.path.expanduser(os.environ["ASTRA_DB_BUNDLE"])
        token = os.getenv("ASTRA_DB_TOKEN")
        if not token:
            raise RuntimeError("Thiếu ASTRA_DB_TOKEN trong file .env")
        if not Path(bundle).is_file():
            raise RuntimeError(f"Không tìm thấy Secure Connect Bundle: {bundle}")
        return Cluster(
            cloud={"secure_connect_bundle": bundle},
            auth_provider=PlainTextAuthProvider("token", token),
            execution_profiles=profiles,
            connect_timeout=int(os.getenv("CONNECT_TIMEOUT", "60")),
        )
    hosts = [h.strip() for h in os.getenv("CASSANDRA_HOSTS", "127.0.0.1").split(",")]
    port = int(os.getenv("CASSANDRA_PORT", "9042"))
    return Cluster(hosts, port=port, execution_profiles=profiles)


def get_session(use_keyspace: bool = True):
    """Trả về session dùng chung (tạo lần đầu khi được gọi)."""
    global _cluster, _session
    if _session is None:
        _cluster = _make_cluster()
        _session = _cluster.connect()
        _session.default_fetch_size = 500  # phân trang: mỗi trang tối đa 500 dòng, driver tự lấy trang kế tiếp
    if use_keyspace:
        _session.set_keyspace(KEYSPACE)
    return _session


def close():
    global _cluster, _session
    if _cluster is not None:
        _cluster.shutdown()
    _cluster = _session = None


if __name__ == "__main__":
    s = get_session(use_keyspace=False)
    row = s.execute("SELECT release_version FROM system.local").one()
    print("Kết nối thành công. Phiên bản Cassandra:", row.release_version)
    print("Chế độ:", "Astra DB" if is_astra() else "Cassandra cục bộ", "| keyspace:", KEYSPACE)
    close()
