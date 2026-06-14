from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bio_tool_pack_routes_pin_review_import_enable_contracts() -> None:
    route_source = (ROOT / "apps/api/tool_capability_routes.py").read_text(encoding="utf-8")
    service_source = (ROOT / "apps/api/tool_capability_service.py").read_text(encoding="utf-8")

    for service_name in [
        "list_bio_tool_packs_from_request",
        "review_bio_tool_pack_from_request",
        "import_bio_tool_pack_from_request",
        "enable_bio_tool_pack_from_request",
        "disable_bio_tool_pack_from_request",
    ]:
        assert service_name in route_source
        assert f"def {service_name}(" in service_source

    for route, operation_id in [
        ('@router.get("/api/v1/tool-capabilities/tool-packs"', "listBioToolPacks"),
        ('@router.post("/api/v1/tool-capabilities/tool-packs/review"', "reviewBioToolPack"),
        ('@router.post("/api/v1/tool-capabilities/tool-packs"', "importBioToolPack"),
        ('@router.post("/api/v1/tool-capabilities/tool-packs/{pack_id}/enable"', "enableBioToolPack"),
        ('@router.post("/api/v1/tool-capabilities/tool-packs/{pack_id}/disable"', "disableBioToolPack"),
    ]:
        assert route in route_source
        assert f'operation_id="{operation_id}"' in route_source

    assert "review_bio_tool_pack_manifest(payload)" in service_source
    assert "import_bio_tool_pack_manifest(payload, enable=enable)" in service_source
