"""Current baseline SQL with the v21 process namespace removed for migration fixtures."""

from apps.remote_runner.agent_process_instance_schema import (
    AGENT_PROCESS_INSTANCE_SCHEMA_SQL,
)
from apps.remote_runner.agent_process_instance_v23_schema import (
    AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL,
)
from apps.remote_runner.storage_schema import SCHEMA_SQL


PRE_AGENT_PROCESS_INSTANCE_SCHEMA_SQL = SCHEMA_SQL.replace(
    AGENT_PROCESS_INSTANCE_SCHEMA_SQL,
    "",
).replace(AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL, "")
