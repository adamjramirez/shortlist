"""Fly Machines abstraction for spawning pipeline workers.

Production: calls Fly Machines REST API to create ephemeral workers.
Tests: no-op fake via dependency override.
"""
import os
from typing import Protocol

import httpx


class MachineSpawner(Protocol):
    async def spawn(self, run_id: int, env: dict[str, str]) -> str | None:
        """Spawn a worker machine. Returns machine_id or None on failure."""
        ...


class FlyMachineSpawner:
    """Spawn ephemeral Fly Machines for pipeline runs."""

    def __init__(self):
        self._app = os.environ.get("FLY_WORKER_APP", "shortlist-workers")
        self._token = os.environ["FLY_WORKER_TOKEN"]
        self._image = os.environ.get(
            "FLY_WORKER_IMAGE", "registry.fly.io/shortlist-web:latest"
        )

    async def spawn(self, run_id: int, env: dict[str, str]) -> str | None:
        machine_env = {
            "MODE": "worker",
            "RUN_ID": str(run_id),
            **env,
        }
        payload = {
            "config": {
                "image": self._image,
                "env": machine_env,
                "auto_destroy": True,
                "restart": {"policy": "no"},
                "guest": {
                    "cpu_kind": "shared",
                    "cpus": 1,
                    "memory_mb": 1024,
                },
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.machines.dev/v1/apps/{self._app}/machines",
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("id")
            return None


class FakeMachineSpawner:
    """No-op spawner for tests. Records calls."""

    def __init__(self):
        self.spawned: list[dict] = []

    async def spawn(self, run_id: int, env: dict[str, str]) -> str:
        self.spawned.append({"run_id": run_id, "env": env})
        return f"fake-machine-{run_id}"


def get_machine_spawner() -> MachineSpawner:
    """FastAPI dependency. Override in tests with FakeMachineSpawner."""
    return FlyMachineSpawner()
