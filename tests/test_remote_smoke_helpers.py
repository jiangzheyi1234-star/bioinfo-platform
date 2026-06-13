from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_smoke_helpers  # noqa: E402


class RemoteSmokeHelpersTest(unittest.TestCase):
    def test_server_items_from_payload_requires_contract_items_list(self) -> None:
        payload = {"data": {"items": [{"serverId": "srv_1"}]}}

        self.assertEqual(remote_smoke_helpers.server_items_from_payload(payload), [{"serverId": "srv_1"}])

    def test_server_items_from_payload_rejects_missing_data_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "servers response data must be an object"):
            remote_smoke_helpers.server_items_from_payload({"items": []})

    def test_ready_ok_from_health_payload_requires_ready_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "server health ready must be an object"):
            remote_smoke_helpers.ready_ok_from_health_payload({"data": {"ready": True}})

    def test_server_context_normalizes_camel_case_service_port(self) -> None:
        context = remote_smoke_helpers.server_context(
            {
                "serverId": "srv_1",
                "label": "remote",
                "connected": True,
                "ready": True,
                "servicePort": "9234",
            },
            stale_port=8876,
        )

        self.assertEqual(context["service_port"], 9234)
        self.assertEqual(context["dynamic_port_expected"], True)


if __name__ == "__main__":
    unittest.main()
