"""Plugin discovery + registration. Two sources: builtin registration (in code)
and third-party entry points (importlib.metadata). Discovery is failure-isolated:
a broken plugin logs a warning and is skipped, never crashing pgvet.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points as _entry_points

from pgvet.plugins.base import Family

log = logging.getLogger("pgvet.registry")

ADVISOR_GROUP = "pgvet.advisors"
INFERENCER_GROUP = "pgvet.inferencers"


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[str, object] = {}

    def register(self, plugin) -> None:
        if plugin.id in self._plugins:
            raise ValueError(f"duplicate plugin id: {plugin.id}")
        self._plugins[plugin.id] = plugin

    @property
    def advisors(self) -> list:
        return [p for p in self._plugins.values() if p.family == Family.ADVISOR]

    @property
    def inferencers(self) -> list:
        return [p for p in self._plugins.values() if p.family == Family.INFERENCER]

    def discover(self, entry_points=None, group: str = ADVISOR_GROUP) -> None:
        if entry_points is None:
            entry_points = _entry_points(group=group)
        for ep in entry_points:
            try:
                register_fn = ep.load()
                register_fn(self)
            except Exception as exc:  # noqa: BLE001 — isolation is the whole point
                log.warning("skipping plugin entry point %r: %s", ep.name, exc)

    def load_builtins(self) -> None:
        """Register the advisors and inferencers shipped with pgvet."""
        from pgvet.plugins.advisors import register_builtins as register_advisors
        from pgvet.plugins.inferencers import register_builtins as register_inferencers
        register_advisors(self)
        register_inferencers(self)
