"""Tests for the order API security and correctness fixes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app

TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": TOKEN}


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    users = [user.model_copy() for user in main.USERS]
    orders = [order.model_copy() for order in main.ORDERS]
    next_id = main._next_order_id
    yield
    main.USERS[:] = [user.model_copy() for user in users]
    main.ORDERS[:] = [order.model_copy() for order in orders]
    main._next_order_id = next_id


@pytest.fixture
def client():
    return TestClient(app)


def test_health_demo_path_unchanged(client):
    response = client.get("/health")
    assert response.status_code == 500
    assert response.json() == {
        "status": "unhealthy",
        "version": "broken",
        "reason": "simulated deployment failure",
    }


def test_source_has_no_eval_or_hardcoded_admin_token():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source
    assert "admin-secret-token" not in source
    assert "except:" not in source


def test_search_is_name_substring_and_does_not_execute_code(client, tmp_path):
    marker = tmp_path / "pwned"
    payload = f"__import__('pathlib').Path({str(marker)!r}).write_text('x') or True"
    response = client.get("/api/search", params={"q": payload})
    assert response.status_code == 200
    assert response.json() == []
    assert not marker.exists()

    # eval("True") would match every user; a name search must not.
    response = client.get("/api/search", params={"q": "True"})
    assert response.status_code == 200
    assert response.json() == []

    response = client.get("/api/search", params={"q": "ALI"})
    assert response.status_code == 200
    body = response.json()
    assert [user["name"] for user in body] == ["Alice Johnson"]

    response = client.get("/api/search", params={"q": "lee"})
    assert [user["id"] for user in response.json()] == [3]


def test_admin_dump_requires_token_and_does_not_leak_it(client):
    missing = client.get("/api/admin/dump")
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Invalid or missing admin token"
    assert TOKEN not in missing.text

    wrong = client.get("/api/admin/dump", headers={"X-Admin-Token": "nope"})
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Invalid or missing admin token"
    assert TOKEN not in wrong.text
    assert "nope" not in wrong.text

    ok = client.get("/api/admin/dump", headers=AUTH)
    assert ok.status_code == 200
    body = ok.json()
    assert "admin_token" not in body
    assert TOKEN not in ok.text
    assert body["next_order_id"] == 4
    assert {user["id"] for user in body["users"]} == {1, 2, 3}
    assert {order["id"] for order in body["orders"]} == {1, 2, 3}


def test_admin_routes_fail_closed_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    dump = client.get("/api/admin/dump", headers=AUTH)
    assert dump.status_code == 503
    assert dump.json()["detail"] == "Admin authentication is not configured"
    assert TOKEN not in dump.text

    patch = client.patch(
        "/api/orders/1",
        headers=AUTH,
        json={"status": "cancelled"},
    )
    assert patch.status_code == 503
    delete = client.delete("/api/orders/1", headers=AUTH)
    assert delete.status_code == 503
    assert [order.id for order in main.ORDERS] == [1, 2, 3]
    assert main.ORDERS[0].status == "shipped"


def test_admin_routes_fail_closed_when_token_empty(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "")
    response = client.get("/api/admin/dump", headers={"X-Admin-Token": ""})
    assert response.status_code == 503
    assert TOKEN not in response.text
    assert [order.id for order in main.ORDERS] == [1, 2, 3]


def test_get_user_matches_requested_id(client):
    alice = client.get("/api/users/1")
    assert alice.status_code == 200
    assert alice.json()["name"] == "Alice Johnson"
    assert alice.json()["id"] == 1

    bob = client.get("/api/users/2")
    assert bob.json()["id"] == 2
    assert bob.json()["name"] == "Bob Smith"

    missing = client.get("/api/users/99")
    assert missing.status_code == 404


def test_get_order_missing_is_404(client):
    found = client.get("/api/orders/1")
    assert found.status_code == 200
    assert found.json()["product"] == "Laptop"

    missing = client.get("/api/orders/999")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Order not found"


def test_list_orders_applies_filters_together(client):
    shipped_for_alice = client.get("/api/orders", params={"user_id": 1, "status": "shipped"})
    assert shipped_for_alice.status_code == 200
    assert [order["id"] for order in shipped_for_alice.json()] == [1]

    pending_for_alice = client.get("/api/orders", params={"user_id": 1, "status": "pending"})
    assert pending_for_alice.json() == []

    pending_for_bob = client.get("/api/orders", params={"user_id": 2, "status": "pending"})
    assert [order["id"] for order in pending_for_bob.json()] == [2]

    # A status-only filter must not drop a previous user filter by restarting
    # from the full list, and a user filter must not ignore status.
    shipped_for_bob = client.get("/api/orders", params={"user_id": 2, "status": "shipped"})
    assert shipped_for_bob.json() == []

    invalid = client.get("/api/orders", params={"status": "not-a-status"})
    assert invalid.status_code == 422


def test_create_order_unknown_user_valid_user_ids_and_discount(client):
    unknown = client.post(
        "/api/orders",
        json={"user_id": 99, "product": "Mouse", "amount": 25},
    )
    assert unknown.status_code == 404
    assert [order.id for order in main.ORDERS] == [1, 2, 3]

    created = client.post(
        "/api/orders",
        json={
            "user_id": 1,
            "product": "Mouse",
            "amount": 200,
            "discount_percent": 25,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["id"] == 4
    assert body["amount"] == 150
    assert body["status"] == "pending"
    assert body["user_id"] == 1

    second = client.post(
        "/api/orders",
        json={"user_id": 2, "product": "Cable", "amount": 80, "discount_percent": 0},
    )
    assert second.status_code == 201
    assert second.json()["id"] == 5
    assert second.json()["amount"] == 80
    assert main._next_order_id == 6
    assert [order.id for order in main.ORDERS] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": 0, "product": "Mouse", "amount": 10},
        {"user_id": -1, "product": "Mouse", "amount": 10},
        {"user_id": 1, "product": "Mouse", "amount": 0},
        {"user_id": 1, "product": "Mouse", "amount": -5},
        {"user_id": 1, "product": "", "amount": 10},
        {"user_id": 1, "product": "Mouse", "amount": 10, "discount_percent": -1},
        {"user_id": 1, "product": "Mouse", "amount": 10, "discount_percent": 101},
        {"user_id": 1, "product": "Mouse", "amount": 10, "discount_percent": 100},
    ],
)
def test_create_order_validation(client, payload):
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422
    assert [order.id for order in main.ORDERS] == [1, 2, 3]


@pytest.mark.parametrize(
    "amount_literal",
    ["Infinity", "-Infinity", "NaN"],
)
def test_create_and_patch_reject_non_finite_amounts(client, amount_literal):
    # httpx refuses non-finite floats, so send the JSON tokens the server accepts.
    created = client.post(
        "/api/orders",
        content=f'{{"user_id": 1, "product": "Mouse", "amount": {amount_literal}}}',
        headers={"Content-Type": "application/json"},
    )
    assert created.status_code == 422
    assert [order.id for order in main.ORDERS] == [1, 2, 3]

    patched = client.patch(
        "/api/orders/1",
        content=f'{{"amount": {amount_literal}}}',
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert patched.status_code == 422
    assert main.ORDERS[0].amount == 1299.99


def test_non_ascii_admin_token_returns_401(client):
    # Header values are latin-1 on the wire; httpx will not encode a non-ASCII str.
    response = client.get(
        "/api/admin/dump",
        headers={"X-Admin-Token": "tökën".encode("latin-1")},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing admin token"


def test_product_longer_than_200_is_rejected(client):
    response = client.post(
        "/api/orders",
        json={"user_id": 1, "product": "x" * 201, "amount": 10},
    )
    assert response.status_code == 422
    assert [order.id for order in main.ORDERS] == [1, 2, 3]


def test_patch_and_delete_require_auth_and_mutate_the_right_order(client):
    unauth_patch = client.patch("/api/orders/1", json={"status": "paid", "amount": 10})
    assert unauth_patch.status_code == 401
    assert unauth_patch.json()["detail"] == "Invalid or missing admin token"
    assert main.ORDERS[0].status == "shipped"
    assert main.ORDERS[0].amount == 1299.99

    wrong = client.patch(
        "/api/orders/1",
        headers={"X-Admin-Token": "other"},
        json={"status": "paid"},
    )
    assert wrong.status_code == 401
    assert main.ORDERS[0].status == "shipped"

    invalid_status = client.patch(
        "/api/orders/1",
        headers=AUTH,
        json={"status": "teleported"},
    )
    assert invalid_status.status_code == 422

    invalid_amount = client.patch(
        "/api/orders/1",
        headers=AUTH,
        json={"amount": 0},
    )
    assert invalid_amount.status_code == 422
    negative_amount = client.patch(
        "/api/orders/1",
        headers=AUTH,
        json={"amount": -1},
    )
    assert negative_amount.status_code == 422
    assert main.ORDERS[0].amount == 1299.99

    updated = client.patch(
        "/api/orders/2",
        headers=AUTH,
        json={"status": "paid", "amount": 70},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "paid"
    assert updated.json()["amount"] == 70
    assert main.ORDERS[1].status == "paid"
    assert main.ORDERS[1].amount == 70

    # Assigning the current amount must still succeed and keep other updates.
    same_amount = client.patch(
        "/api/orders/2",
        headers=AUTH,
        json={"status": "shipped", "amount": 70},
    )
    assert same_amount.status_code == 200
    assert same_amount.json()["status"] == "shipped"
    assert same_amount.json()["amount"] == 70

    unauth_delete = client.delete("/api/orders/2")
    assert unauth_delete.status_code == 401
    assert [order.id for order in main.ORDERS] == [1, 2, 3]

    deleted = client.delete("/api/orders/2", headers=AUTH)
    assert deleted.status_code == 204
    assert [order.id for order in main.ORDERS] == [1, 3]
    assert client.get("/api/orders/2").status_code == 404
    assert client.get("/api/orders/3").status_code == 200

    missing = client.delete("/api/orders/2", headers=AUTH)
    assert missing.status_code == 404

    last = client.delete("/api/orders/3", headers=AUTH)
    assert last.status_code == 204
    assert [order.id for order in main.ORDERS] == [1]
