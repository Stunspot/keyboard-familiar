from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from familiar.adapters.steelseries.transport import GameSenseTransport, ScreenFrame, SteelSeriesError


class _GameSenseHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict]] = []
    response_status = 200
    response_body = b""

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append((self.path, payload))
        self.send_response(self.__class__.response_status)
        self.end_headers()
        self.wfile.write(self.__class__.response_body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def test_gamesense_transport_discovers_binds_sends_and_heartbeats(tmp_path: Path) -> None:
    _GameSenseHandler.requests = []
    _GameSenseHandler.response_status = 200
    _GameSenseHandler.response_body = b""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GameSenseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    props = tmp_path / "coreProps.json"
    props.write_text(json.dumps({"address": f"127.0.0.1:{server.server_port}"}), encoding="utf-8")

    async def run() -> None:
        transport = GameSenseTransport(core_props_path=props, timeout_seconds=1)
        await transport.send_frame(ScreenFrame(title="VRAM 92%", body="11.1/12.0 GiB"))
        await transport.heartbeat()

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert [path for path, _ in _GameSenseHandler.requests] == [
        "/game_metadata",
        "/bind_game_event",
        "/game_event",
        "/game_heartbeat",
    ]
    binding = _GameSenseHandler.requests[1][1]
    assert binding["handlers"][0]["device-type"] == "screened"
    assert binding["handlers"][0]["zone"] == "one"
    event = _GameSenseHandler.requests[2][1]
    assert event["data"]["frame"] == {"title": "VRAM 92%", "body": "11.1/12.0 GiB"}


def test_gamesense_transport_rejects_missing_discovery_file(tmp_path: Path) -> None:
    transport = GameSenseTransport(core_props_path=tmp_path / "missing.json")
    with pytest.raises(SteelSeriesError, match="Install and start SteelSeries GG"):
        transport.discover()


def test_gamesense_transport_rejects_non_loopback_address(tmp_path: Path) -> None:
    props = tmp_path / "coreProps.json"
    props.write_text('{"address": "example.com:1234"}', encoding="utf-8")
    transport = GameSenseTransport(core_props_path=props)
    with pytest.raises(SteelSeriesError, match="only a loopback host"):
        transport.discover()


def test_gamesense_transport_surfaces_engine_error(tmp_path: Path) -> None:
    _GameSenseHandler.requests = []
    _GameSenseHandler.response_status = 500
    _GameSenseHandler.response_body = b"engine unavailable"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _GameSenseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    props = tmp_path / "coreProps.json"
    props.write_text(json.dumps({"address": f"127.0.0.1:{server.server_port}"}), encoding="utf-8")

    try:
        with pytest.raises(SteelSeriesError, match="HTTP 500: engine unavailable"):
            asyncio.run(GameSenseTransport(core_props_path=props).initialize())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        _GameSenseHandler.response_status = 200
        _GameSenseHandler.response_body = b""
