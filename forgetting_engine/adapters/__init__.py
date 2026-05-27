"""Domain adapters for the Forgetting Engine.

Each adapter implements the DomainAdapter interface to teach the engine
about a specific domain: skincare, coding, parenting, etc.
"""

from forgetting_engine.adapters.skincare import SkincareAdapter

__all__ = ["SkincareAdapter"]
