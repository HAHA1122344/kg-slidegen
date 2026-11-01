"""kgslide — knowledge-graph-constrained slide generation."""

from .constraints import UnitConstraints, build_constraints
from .graph import Graph, Issue
from .llm import LLMClient, LLMConfig, LLMError
from .renderer import RenderResult, render
from .validator import Report, evaluate

__version__ = "0.1.0"
__all__ = [
    "Graph",
    "Issue",
    "UnitConstraints",
    "build_constraints",
    "LLMClient",
    "LLMConfig",
    "LLMError",
    "RenderResult",
    "render",
    "Report",
    "evaluate",
]
