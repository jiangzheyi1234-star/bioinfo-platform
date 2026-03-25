from __future__ import annotations

from core.execution.tool_bridge_service import ToolBridgeService
from core.execution.workbench_view_builders import build_multiplex_view, build_primer_view


def test_build_primer_view_from_text():
    base_view = ToolBridgeService.base_integrated_workbench_config()["views"]["primer_design"]
    view = build_primer_view(
        base_view=base_view,
        primer_result_final_2_text="Virus_A\tregion_1\tAAA\tTTT\t10-120\tATGC\n",
        all_candidates_count=3,
        filtered_count=2,
        dimer_count=1,
        description="desc",
        status={"state": "completed"},
        parameters=[{"label": "x", "value": "y"}],
        artifacts=[{"name": "primer_result_final_2.txt"}],
        remote_result_dir="/remote/path",
    )
    assert view is not None
    assert view["rows"][0]["pathogen"] == "Virus_A"
    assert view["summary"][0]["value"] == "1"
    assert view["remote_result_dir"] == "/remote/path"


def test_build_multiplex_view_from_text():
    content = (
        "pathogen\tregion_id\tforward_primer\treverse_primer\ttm_f\ttm_r\tgc_f\tgc_r\tamplicon_length\tpool_score\tpool_status\n"
        "Virus_A\tregion_1\tAAA\tTTT\t58.0\t58.5\t45\t46\t150\t0\toptimal\n"
    )
    view = build_multiplex_view(
        multiplex_panel_text=content,
        synthesis_count=3,
        optimization_count=2,
        description="desc",
        status={"state": "completed"},
        parameters=[],
        artifacts=[],
        remote_result_dir="/remote/path",
    )
    assert view is not None
    assert view["title"] == "多重引物池设计"
    assert view["rows"][0]["pathogen"] == "Virus_A"
    assert any(item["label"] == "入池病原体" for item in view["summary"])
