from __future__ import annotations

import asyncio
import contextlib
import subprocess
from typing import Any

from familiar.core.events import make_event
from familiar.core.models import PluginManifest


class GpuVramSensor:
    manifest = PluginManifest(name="gpu_vram", version="0.1.0", plugin_type="sensor", emits=["gpu.vram.*"])

    def __init__(
        self,
        every_seconds: int = 3,
        gpu_index: int = 0,
        change_threshold_pct: float = 2.0,
        alert_threshold_pct: float = 90.0,
    ) -> None:
        self.every_seconds = max(1, every_seconds)
        self.gpu_index = gpu_index
        self.change_threshold_pct = change_threshold_pct
        self.alert_threshold_pct = alert_threshold_pct
        self._ctx = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_emitted_percent: float | None = None
        self._nvml_initialized = False
        self._warned_unavailable = False

    async def start(self, ctx) -> None:
        self._ctx = ctx
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._ctx = None
        self._shutdown_nvml()

    async def _loop(self) -> None:
        while self._running and self._ctx:
            metrics = await self._sample()
            if metrics is not None:
                await self._maybe_emit(metrics)
            await asyncio.sleep(self.every_seconds)

    async def _sample(self) -> dict[str, Any] | None:
        metrics = await asyncio.to_thread(self._sample_nvml)
        if metrics is not None:
            return metrics

        metrics = await asyncio.to_thread(self._sample_nvidia_smi)
        if metrics is not None:
            return metrics

        if not self._warned_unavailable and self._ctx:
            self._warned_unavailable = True
            self._ctx.app.trace.append("gpu_vram.unavailable nvml-and-nvidia-smi")
        return None

    def _sample_nvml(self) -> dict[str, Any] | None:
        try:
            import pynvml  # type: ignore

            if not self._nvml_initialized:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            handle = pynvml.nvmlDeviceGetHandleByIndex(self.gpu_index)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        except Exception:
            return None

        return self._metrics_from_bytes(int(info.used), int(info.total), source="nvml", gpu_index=self.gpu_index)

    def _shutdown_nvml(self) -> None:
        if not self._nvml_initialized:
            return
        try:
            import pynvml  # type: ignore

            pynvml.nvmlShutdown()
        except Exception:
            pass
        self._nvml_initialized = False

    def _sample_nvidia_smi(self) -> dict[str, Any] | None:
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                    "-i",
                    str(self.gpu_index),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            line = proc.stdout.strip().splitlines()[0]
            used_mib, total_mib = [int(part.strip()) for part in line.split(",", maxsplit=1)]
        except Exception:
            return None

        used_bytes = used_mib * 1024 * 1024
        total_bytes = total_mib * 1024 * 1024
        return self._metrics_from_bytes(used_bytes, total_bytes, source="nvidia-smi", gpu_index=self.gpu_index)

    @staticmethod
    def _metrics_from_bytes(used_bytes: int, total_bytes: int, source: str, gpu_index: int) -> dict[str, Any]:
        percent_used = 0.0 if total_bytes <= 0 else round((used_bytes / total_bytes) * 100.0, 2)
        gib = 1024**3
        used_gib = round(used_bytes / gib, 2)
        total_gib = round(total_bytes / gib, 2)
        return {
            "gpu_index": gpu_index,
            "used_bytes": used_bytes,
            "total_bytes": total_bytes,
            "used_gib": used_gib,
            "total_gib": total_gib,
            "percent_used": percent_used,
            "sample_source": source,
        }

    async def _maybe_emit(self, metrics: dict[str, Any]) -> None:
        if self._ctx is None:
            return
        percent_used = float(metrics["percent_used"])

        reasons: list[str] = []
        if self._last_emitted_percent is None:
            reasons.append("initial")
        else:
            delta = abs(percent_used - self._last_emitted_percent)
            if delta >= self.change_threshold_pct:
                reasons.append("delta")
            prev = self._last_emitted_percent
            crossed_up = prev < self.alert_threshold_pct <= percent_used
            crossed_down = prev >= self.alert_threshold_pct > percent_used
            if crossed_up or crossed_down:
                reasons.append("threshold")

        if not reasons:
            return

        payload = {
            **metrics,
            "gpu_index": self.gpu_index,
            "alert_threshold_pct": self.alert_threshold_pct,
            "change_threshold_pct": self.change_threshold_pct,
            "change_reasons": reasons,
        }
        await self._ctx.app.publish_event(make_event("gpu.vram.changed", source="gpu_vram", payload=payload))
        self._last_emitted_percent = percent_used

