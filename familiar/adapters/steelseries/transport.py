from __future__ import annotations


class SteelSeriesTransport:
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.sent: list[dict] = []

    async def send(self, packet: dict) -> None:
        self.sent.append(packet)
