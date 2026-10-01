import ipaddress
import socket
from pathlib import Path

import pytest

from pair_harness.desktop_backend.application_service import build_demo_service
from tests.service_helpers import EventLog

# 本机协议回放夹具：dashscope_server（DashScope 推理 WebSocket）、replay_http（HTTP JSON 接口）
pytest_plugins = ["tests.fixtures.dashscope_ws", "tests.fixtures.replay_http"]

_real_getaddrinfo = socket.getaddrinfo


def _is_local(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(str(host).strip("[]"))
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


# 离线测试只允许解析本机地址，避免测试替身失配时请求真实模型或 DashScope；
# live / live_qwen 标记的联调测试不受限制。
@pytest.fixture(autouse=True)
def _offline_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("live_qwen"):
        return

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            raise OSError(f"离线测试不得访问外部网络：{host}")
        return _real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


# 演示运行时的桌面服务，使用临时目录中的真实 SQLite 库；
# 事件记录在 service.event_log，临时目录在 service.tmp_path。
@pytest.fixture
async def service(tmp_path: Path):
    log = EventLog()
    svc = build_demo_service(
        database=tmp_path / "data" / "pair_harness.db",
        project_root=tmp_path,
        event_sink=log,
    )
    svc.event_log = log
    svc.tmp_path = tmp_path
    yield svc
    await svc.shutdown()
