"""Plugin discovery + registration. Two sources: builtin registration (in code)
and third-party entry points (importlib.metadata). Discovery is failure-isolated:
a broken plugin logs a warning and is skipped, never crashing pgvet.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points as _entry_points

from pgvet.plugins.base import Advisor

log = logging.getLogger("pgvet.registry")

ADVISOR_GROUP = "pgvet.advisors"


class Registry:
    def __init__(self) -> None:
        self._advisors: dict[str, Advisor] = {}

    def register(self, plugin: Advisor) -> None:
        if plugin.id in self._advisors:
            raise ValueError(f"duplicate plugin id: {plugin.id}")
        self._advisors[plugin.id] = plugin

    @property
    def advisors(self) -> list[Advisor]:
        return list(self._advisors.values())

    def discover(self, entry_points=None) -> None:
        """Load plugins from entry points. Each entry point loads to a callable
        `register(registry)`. Pass `entry_points` explicitly in tests."""
        if entry_points is None:
            entry_points = _entry_points(group=ADVISOR_GROUP)
        for ep in entry_points:
            try:
                register_fn = ep.load()
                register_fn(self)
            except Exception as exc:  # noqa: BLE001 — isolation is the whole point
                log.warning("skipping plugin entry point %r: %s", ep.name, exc)

    def load_builtins(self) -> None:
        """Register the advisors shipped in pgvet.plugins.advisors."""
        from pgvet.plugins.advisors import register_builtins

        register_builtins(self)
