"""
tests/test_persistence.py - Persistence adapter regressions.
"""

import sys
import os

# Ensure project root is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from api.persistence import Persistence


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return [{"id": "run-123"}]


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, json, headers):
        self.calls.append({
            "path": path,
            "json": json,
            "headers": headers,
        })
        return _FakeResponse()


def test_save_run_uses_nested_metric_fields():
    persistence = Persistence(url="https://example.supabase.co", service_key="test-key")
    fake_client = _FakeClient()
    persistence._client = fake_client

    run_id = persistence.save_run(
        request={
            "venue_id": "allegiant_stadium",
            "event_type": "nfl",
            "attendance": 65000,
        },
        response={
            "parameters": {"service_rate_tier": "operational"},
            "simulation": {"wait_mean": 11.0},
            "metrics": {
                "experience": {"hes": 81.2},
                "safety": {"srs": 0.33},
                "operational": {"wait_time": {"mean": 7.5}},
            },
        },
    )

    assert run_id == "run-123"
    assert len(fake_client.calls) == 1
    payload = fake_client.calls[0]["json"]
    assert payload["hes"] == 81.2
    assert payload["srs"] == 0.33
    assert payload["wait_mean"] == 7.5
