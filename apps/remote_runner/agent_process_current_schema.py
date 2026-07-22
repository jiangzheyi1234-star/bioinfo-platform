"""Fresh-install composition for the current durable Agent process schema."""

from .agent_process_instance_schema import AGENT_PROCESS_INSTANCE_SCHEMA_SQL
from .agent_process_instance_v23_schema import AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL


AGENT_PROCESS_CURRENT_SCHEMA_SQL = (
    AGENT_PROCESS_INSTANCE_SCHEMA_SQL + AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL
)

__all__ = ["AGENT_PROCESS_CURRENT_SCHEMA_SQL"]
