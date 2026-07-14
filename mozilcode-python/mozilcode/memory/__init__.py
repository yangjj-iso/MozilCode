"""长期记忆与会话持久化包。"""

from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.instructions import load_instructions, process_includes
from mozilcode.memory.recall import (
    RelevantMemory,
    find_relevant_memories,
    render_reminder,
)
from mozilcode.memory.providers import (
    BaseMemoryProvider,
    MEMORY_EVENT_SESSION_END,
    MEMORY_EVENT_TURN_COMMITTED,
    MEMORY_EVENT_TURN_COMPLETED,
    MemoryEvent,
    MemoryHub,
    MemoryItem,
    MemoryProvider,
    MemoryProviderLoadError,
    MemoryScope,
    MarkdownMemoryProvider,
    build_memory_hub,
)
from mozilcode.memory.session import (
    ResumeResult,
    Session,
    SessionManager,
    SessionMeta,
    generate_session_summary,
)
from mozilcode.memory.session_records import (
    SessionRecord,
    make_compact_boundary,
    parse_compact_boundary,
    validate_message_chain,
)


__all__ = [
    "MemoryManager",
    "BaseMemoryProvider",
    "MEMORY_EVENT_SESSION_END",
    "MEMORY_EVENT_TURN_COMMITTED",
    "MEMORY_EVENT_TURN_COMPLETED",
    "MemoryEvent",
    "MemoryHub",
    "MemoryItem",
    "MemoryProvider",
    "MemoryProviderLoadError",
    "MemoryScope",
    "MarkdownMemoryProvider",
    "RelevantMemory",
    "build_memory_hub",
    "ResumeResult",
    "Session",
    "SessionManager",
    "SessionMeta",
    "SessionRecord",
    "find_relevant_memories",
    "generate_session_summary",
    "load_instructions",
    "make_compact_boundary",
    "parse_compact_boundary",
    "process_includes",
    "render_reminder",
    "validate_message_chain",
]
