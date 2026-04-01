from __future__ import annotations

import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


def _format_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value:.1f} B"


def _format_duration(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if parts:
                result[key] = int(parts[0]) * 1024
    return result


@dataclass(frozen=True, slots=True)
class ContainerSnapshot:
    name: str
    status: str
    image: str
    cpu_percent: float | None
    memory_usage_bytes: int | None
    memory_limit_bytes: int | None


class MonitoringService:
    def __init__(self, *, started_at: datetime, docker_socket_path: str = "/var/run/docker.sock") -> None:
        self._started_at = started_at
        self._docker_socket_path = docker_socket_path

    def app_uptime(self) -> str:
        return _format_duration((datetime.now(timezone.utc) - self._started_at).total_seconds())

    def server_snapshot(self) -> str:
        meminfo = _read_meminfo()
        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)
        used = max(total - available, 0)
        load1, load5, load15 = os.getloadavg()
        disk = shutil.disk_usage("/")
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            uptime_seconds = float(handle.read().split()[0])
        return (
            "🖥️ <b>Server snapshot</b>\n\n"
            f"<b>Uptime:</b> {_format_duration(uptime_seconds)}\n"
            f"<b>Load:</b> {load1:.2f} / {load5:.2f} / {load15:.2f}\n"
            f"<b>Memory:</b> {_format_bytes(used)} used / {_format_bytes(total)} total\n"
            f"<b>Available:</b> {_format_bytes(available)}\n"
            f"<b>Disk:</b> {_format_bytes(disk.used)} used / {_format_bytes(disk.total)} total"
        )

    async def list_containers(self) -> list[ContainerSnapshot]:
        transport = httpx.AsyncHTTPTransport(uds=self._docker_socket_path)
        async with httpx.AsyncClient(base_url="http://docker", transport=transport, timeout=10.0) as client:
            containers_response = await client.get("/containers/json", params={"all": 0})
            containers_response.raise_for_status()
            containers = containers_response.json()
            snapshots: list[ContainerSnapshot] = []
            for container in containers:
                container_id = str(container.get("Id", ""))
                stats_response = await client.get(f"/containers/{container_id}/stats", params={"stream": "false"})
                stats_response.raise_for_status()
                stats = stats_response.json()
                snapshots.append(
                    ContainerSnapshot(
                        name=str(container.get("Names", ["unknown"])[0]).lstrip("/"),
                        status=str(container.get("Status", "unknown")),
                        image=str(container.get("Image", "")),
                        cpu_percent=self._calculate_cpu_percent(stats),
                        memory_usage_bytes=self._extract_memory_usage(stats),
                        memory_limit_bytes=self._extract_memory_limit(stats),
                    )
                )
        return sorted(snapshots, key=lambda item: item.name)

    def format_containers(self, snapshots: list[ContainerSnapshot]) -> str:
        lines = ["📦 <b>Containers</b>", ""]
        for snapshot in snapshots:
            cpu = "n/a" if snapshot.cpu_percent is None else f"{snapshot.cpu_percent:.2f}%"
            if snapshot.memory_usage_bytes is None or snapshot.memory_limit_bytes is None:
                memory = "n/a"
            else:
                memory = (
                    f"{_format_bytes(snapshot.memory_usage_bytes)} / "
                    f"{_format_bytes(snapshot.memory_limit_bytes)}"
                )
            lines.append(
                f"• <b>{snapshot.name}</b> — {snapshot.status}\n"
                f"  CPU {cpu} • MEM {memory}"
            )
        if len(lines) == 2:
            lines.append("No running containers found.")
        return "\n".join(lines)

    @staticmethod
    def _extract_memory_usage(stats: dict[str, object]) -> int | None:
        memory_stats = stats.get("memory_stats", {})
        if not isinstance(memory_stats, dict):
            return None
        usage = memory_stats.get("usage")
        cache = 0
        stats_block = memory_stats.get("stats", {})
        if isinstance(stats_block, dict):
            cache = int(stats_block.get("cache", 0) or 0)
        if usage is None:
            return None
        return max(int(usage) - cache, 0)

    @staticmethod
    def _extract_memory_limit(stats: dict[str, object]) -> int | None:
        memory_stats = stats.get("memory_stats", {})
        if not isinstance(memory_stats, dict):
            return None
        limit = memory_stats.get("limit")
        if limit is None:
            return None
        return int(limit)

    @staticmethod
    def _calculate_cpu_percent(stats: dict[str, object]) -> float | None:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        if not isinstance(cpu_stats, dict) or not isinstance(precpu_stats, dict):
            return None
        cpu_total = int(cpu_stats.get("cpu_usage", {}).get("total_usage", 0) or 0)  # type: ignore[union-attr]
        precpu_total = int(precpu_stats.get("cpu_usage", {}).get("total_usage", 0) or 0)  # type: ignore[union-attr]
        system_total = int(cpu_stats.get("system_cpu_usage", 0) or 0)
        presystem_total = int(precpu_stats.get("system_cpu_usage", 0) or 0)
        cpu_delta = cpu_total - precpu_total
        system_delta = system_total - presystem_total
        online_cpus = int(cpu_stats.get("online_cpus", 0) or 0)
        if online_cpus <= 0:
            percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])  # type: ignore[union-attr]
            if isinstance(percpu, list):
                online_cpus = max(len(percpu), 1)
        if cpu_delta <= 0 or system_delta <= 0:
            return 0.0
        return max((cpu_delta / system_delta) * online_cpus * 100.0, 0.0)
