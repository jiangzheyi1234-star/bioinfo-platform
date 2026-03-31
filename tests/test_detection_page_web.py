from pathlib import Path


def test_detection_page_legacy_entry_exists():
    assets_dir = Path(__file__).resolve().parents[1] / "ui" / "pages" / "detection_page_assets"
    legacy_entry = assets_dir / "index_galaxy.html"

    assert legacy_entry.exists()
