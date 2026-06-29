from __future__ import annotations

from typing import Any


DATABASE_LIST = "database.list"
DATABASE_TEMPLATE_LIST = "database_template.list"
DATABASE_PACK_LIST = "database_pack.list"
DATABASE_PACK_READY_SCAN = "database_pack.ready_scan"
DATABASE_CREATE = "database.create"
DATABASE_UPDATE = "database.update"
DATABASE_DELETE = "database.delete"
DATABASE_CHECK = "database.check"


DATABASE_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    DATABASE_LIST: {
        "method": "GET",
        "path_template": "/api/v1/databases",
        "operation_id": "listDatabases",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "database-list.v1",
        "cache_scope": "database-read-model",
        "response_item_key": "items",
    },
    DATABASE_TEMPLATE_LIST: {
        "method": "GET",
        "path_template": "/api/v1/database-templates",
        "operation_id": "listDatabaseTemplates",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "database-template-list.v1",
        "cache_scope": "database-template-read-model",
        "response_item_key": "items",
    },
    DATABASE_PACK_LIST: {
        "method": "GET",
        "path_template": "/api/v1/database-packs",
        "operation_id": "listDatabasePacks",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "database-pack-list.v1",
        "cache_scope": "database-pack-read-model",
    },
    DATABASE_PACK_READY_SCAN: {
        "method": "POST",
        "path_template": "/api/v1/database-pack-ready-scans",
        "operation_id": "scanDatabasePackReady",
        "governance_action": "database_pack.ready_scan",
        "request_schema": "database-pack-ready-scan-request.v1",
        "response_schema": "database-pack-ready-scan-result.v1",
        "cache_scope": "database-pack-command",
    },
    DATABASE_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/databases",
        "operation_id": "createDatabase",
        "governance_action": "database.create",
        "request_schema": "database-manifest-request.v1",
        "response_schema": "database.v1",
        "cache_scope": "database-command",
        "invalidates": ("database-read-model", "workflow-catalog-read-model"),
        "accepted_statuses": (201,),
    },
    DATABASE_UPDATE: {
        "method": "PATCH",
        "path_template": "/api/v1/databases/{database_id}",
        "operation_id": "updateDatabase",
        "governance_action": "database.update",
        "request_schema": "database-update-request.v1",
        "response_schema": "database.v1",
        "cache_scope": "database-command",
        "invalidates": ("database-read-model", "workflow-catalog-read-model"),
    },
    DATABASE_DELETE: {
        "method": "DELETE",
        "path_template": "/api/v1/databases/{database_id}",
        "operation_id": "deleteDatabase",
        "governance_action": "database.delete",
        "request_schema": None,
        "response_schema": "database-delete-result.v1",
        "cache_scope": "database-command",
        "invalidates": ("database-read-model", "workflow-catalog-read-model"),
    },
    DATABASE_CHECK: {
        "method": "POST",
        "path_template": "/api/v1/databases/{database_id}/check",
        "operation_id": "checkDatabase",
        "governance_action": "database.check",
        "request_schema": None,
        "response_schema": "database.v1",
        "cache_scope": "database-command",
        "invalidates": ("database-read-model",),
    },
}
