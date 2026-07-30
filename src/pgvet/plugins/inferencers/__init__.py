"""Builtin inferencer registration (used by Registry.load_builtins)."""

from pgvet.plugins.inferencers.enum import EnumInferencer
from pgvet.plugins.inferencers.fk_overlap import FkOverlapInferencer
from pgvet.plugins.inferencers.not_null import NotNullInferencer
from pgvet.plugins.inferencers.unique import UniqueInferencer

_BUILTINS = [NotNullInferencer, UniqueInferencer, EnumInferencer, FkOverlapInferencer]


def register_builtins(registry) -> None:
    for inferencer_cls in _BUILTINS:
        registry.register(inferencer_cls())
