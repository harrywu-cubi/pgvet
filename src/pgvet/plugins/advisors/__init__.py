"""Builtin advisor registration entry point (used by Registry.load_builtins)."""

from pgvet.plugins.advisors.nested_loop import NestedLoopAdvisor
from pgvet.plugins.advisors.row_estimate import RowEstimateAdvisor
from pgvet.plugins.advisors.seq_scan import SeqScanAdvisor
from pgvet.plugins.advisors.sort_spill import SortSpillAdvisor
from pgvet.plugins.advisors.unused_index import UnusedIndexAdvisor

_BUILTINS = [
    SeqScanAdvisor,
    RowEstimateAdvisor,
    SortSpillAdvisor,
    NestedLoopAdvisor,
    UnusedIndexAdvisor,
]


def register_builtins(registry) -> None:
    for advisor_cls in _BUILTINS:
        registry.register(advisor_cls())
