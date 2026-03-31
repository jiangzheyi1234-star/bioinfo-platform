from __future__ import annotations

from pathlib import Path

from core.pipeline.chart_data_parser import ChartDataParser


def test_parse_kreport_tree_preserves_taxonomy_hierarchy(tmp_path: Path) -> None:
    kreport = tmp_path / "sample.kreport"
    kreport.write_text(
        "\n".join(
            [
                "100.00\t1000\t0\tR\t1\troot",
                "90.00\t900\t0\tD\t10239\t  Viruses",
                "60.00\t600\t0\tP\t2732396\t    Negarnaviricota",
                "30.00\t300\t0\tC\t2559587\t      Insthoviricetes",
                "20.00\t200\t0\tP\t1111\t    Cressdnaviricota",
                "10.00\t100\t0\tC\t2222\t      Arfiviricetes",
                "5.00\t50\t0\tD\t2\t  Bacteria",
                "4.00\t40\t0\tP\t1224\t    Pseudomonadota",
                "2.00\t20\t0\tC\t1236\t      Gammaproteobacteria",
            ]
        ),
        encoding="utf-8",
    )

    chart = ChartDataParser.parse_kreport_tree(str(kreport))

    assert chart["type"] == "sunburst"
    assert len(chart["data"]) == 2

    viruses = chart["data"][0]
    bacteria = chart["data"][1]

    assert viruses["name"] == "Viruses"
    assert [child["name"] for child in viruses["children"]] == [
        "Negarnaviricota",
        "Cressdnaviricota",
    ]
    assert [child["name"] for child in viruses["children"][0]["children"]] == [
        "Insthoviricetes",
    ]
    assert [child["name"] for child in viruses["children"][1]["children"]] == [
        "Arfiviricetes",
    ]

    assert bacteria["name"] == "Bacteria"
    assert [child["name"] for child in bacteria["children"]] == [
        "Pseudomonadota",
    ]
    assert [child["name"] for child in bacteria["children"][0]["children"]] == [
        "Gammaproteobacteria",
    ]
