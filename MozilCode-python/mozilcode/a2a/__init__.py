"""Local A2A transport adapter for the MozilCode daemon."""

from mozilcode.a2a.bridge import A2ABridge, A2ATask
from mozilcode.a2a.protocol import A2AError

__all__ = [
    "A2ABridge",
    "A2AError",
    "A2ATask",
]
