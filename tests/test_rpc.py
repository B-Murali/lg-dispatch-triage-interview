"""JSON-RPC transport behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dispatch_agent.api import app
from dispatch_agent.services import dispatch_service

client = TestClient(app, raise_server_exceptions=False)

TICKET = {
    "ticket_id": "TCK-RPC",
    "asset_id": "AST-9001",
    "site_code": "SFO-02",
    "issue_code": "NO_POWER",
    "reported_hours_ago": 4,
    "estimated_minutes": 90,
}


def call(payload):
    return client.post("/rpc", json=payload)


def request(method, params=None, id="rpc-1"):
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def notification(method, params=None):
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    return body


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_healthz():
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "dispatch.triage" in body["methods"]


def test_triage_over_rpc():
    body = call(request("dispatch.triage", TICKET)).json()
    assert body["id"] == "rpc-1"
    assert body["result"]["ticket_id"] == "TCK-RPC"


def test_policy_method():
    body = call(request("dispatch.policy")).json()
    assert body["result"]["intake_window_hours"] == 72


def test_agent_describe():
    body = call(request("agent.describe")).json()
    assert body["result"]["protocol"] == "json-rpc-2.0"


# ---------------------------------------------------------------------------
# envelope shape
# ---------------------------------------------------------------------------


def test_success_response_carries_no_error_member():
    body = call(request("dispatch.policy")).json()
    assert "result" in body
    assert "error" not in body


def test_unknown_method_carries_no_result_member():
    body = call(request("dispatch.nope", id="rpc-2")).json()
    assert body["error"]["code"] == -32601
    assert "result" not in body
    assert body["id"] == "rpc-2"


def test_request_without_method_is_invalid_request():
    response = call({"jsonrpc": "2.0", "id": "rpc-3"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32600


def test_wrong_protocol_version_is_invalid_request():
    response = call({"jsonrpc": "1.0", "id": "rpc-4", "method": "dispatch.policy"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32600


def test_non_object_params_is_invalid_request():
    response = call({"jsonrpc": "2.0", "id": "rpc-5", "method": "dispatch.triage", "params": "no"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32600


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


def test_notification_gets_no_response_body():
    response = call(notification("dispatch.triage", TICKET))

    assert response.status_code == 204
    assert response.content == b""


def test_notification_still_does_the_work():
    dispatch_service._RESULTS.clear()

    call(notification("dispatch.triage", TICKET))

    assert "TCK-RPC" in dispatch_service._RESULTS


# ---------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------


def test_batch_returns_one_response_per_call():
    response = call(
        [
            request("dispatch.policy", id="b-1"),
            request("agent.describe", id="b-2"),
        ]
    )

    body = response.json()
    assert isinstance(body, list)
    assert [item["id"] for item in body] == ["b-1", "b-2"]


def test_batch_omits_notifications():
    response = call(
        [
            request("dispatch.policy", id="b-3"),
            notification("agent.describe"),
            request("dispatch.nope", id="b-4"),
        ]
    )

    body = response.json()
    assert [item["id"] for item in body] == ["b-3", "b-4"]
    assert body[1]["error"]["code"] == -32601


def test_batch_of_only_notifications_gets_no_response_body():
    response = call([notification("dispatch.policy"), notification("agent.describe")])

    assert response.status_code == 204
    assert response.content == b""


def test_empty_batch_is_invalid_request():
    response = call([])

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert body["error"]["code"] == -32600
