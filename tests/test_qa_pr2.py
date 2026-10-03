"""Additional QA tests for PR #2 (sandbx-testing).

Complements tests/test_main.py. Uses only a throwaway token ("test-token") that is
set per-test via monkeypatch; nothing here needs a real secret.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main

TOKEN = "test-token"
AUTH = {"X-Admin-Token": TOKEN}


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Set a throwaway ADMIN_TOKEN and reset in-memory USERS/ORDERS/_next_order_id."""
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    users = [u.model_copy() for u in main.USERS]
    orders = [o.model_copy() for o in main.ORDERS]
    next_id = main._next_order_id
    yield
    main.USERS[:] = users
    main.ORDERS[:] = orders
    main._next_order_id = next_id


@pytest.fixture
def client():
    return TestClient(main.app)


def order_ids():
    return [o.id for o in main.ORDERS]


# --------------------------------------------------------------------------
# /health and /version (characterization only)
# --------------------------------------------------------------------------

def test_health_characterization_current_behaviour(client):
    """Records what /health does on this branch today (simulated-failure variant).

    NOTE: the module docstring says /health is healthy on main, but the code returns
    the broken 500 variant. This test pins current behaviour only; it does not assert
    a desired contract.
    """
    r = client.get("/health")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "unhealthy"
    assert body["version"] == "broken"
    assert body["reason"] == "simulated deployment failure"


def test_version_endpoint(client):
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json() == {"version": main.APP_VERSION}
    assert r.json()["version"] == "v1"


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

def test_list_users(client):
    r = client.get("/api/users")
    assert r.status_code == 200
    assert [u["id"] for u in r.json()] == [1, 2, 3]


@pytest.mark.parametrize(
    "user_id,name,email",
    [
        (1, "Alice Johnson", "alice@example.com"),
        (2, "Bob Smith", "bob@example.com"),
        (3, "Carol Lee", "carol@example.com"),
    ],
)
def test_get_user_each_seed_user(client, user_id, name, email):
    r = client.get(f"/api/users/{user_id}")
    assert r.status_code == 200
    assert r.json() == {"id": user_id, "name": name, "email": email}


@pytest.mark.parametrize("user_id", [0, -1, 99])
def test_get_user_unknown_is_404(client, user_id):
    r = client.get(f"/api/users/{user_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "User not found"


@pytest.mark.parametrize("user_id", ["abc", "1.5", "1;2"])
def test_get_user_non_int_is_422(client, user_id):
    assert client.get(f"/api/users/{user_id}").status_code == 422


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def test_search_normal_queries(client):
    r = client.get("/api/search", params={"q": "bob"})
    assert r.status_code == 200
    assert [u["id"] for u in r.json()] == [2]
    # substring + case-insensitive; matches names only (not email)
    assert [u["id"] for u in client.get("/api/search", params={"q": "OHN"}).json()] == [1]
    assert client.get("/api/search", params={"q": "example.com"}).json() == []
    assert client.get("/api/search", params={"q": "zzz"}).json() == []


def test_search_requires_q(client):
    assert client.get("/api/search").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        "__import__('os').getpid()",
        "1 == 1",
        "True",
        "' or '1'='1",
        "user.name",
        "[u for u in USERS]",
        "{{7*7}}",
    ],
)
def test_search_harmless_payloads_are_treated_as_plain_text(client, payload):
    r = client.get("/api/search", params={"q": payload})
    assert r.status_code == 200
    assert r.json() == []
    # state untouched
    assert [u.id for u in main.USERS] == [1, 2, 3]
    assert order_ids() == [1, 2, 3]


def test_search_payload_does_not_execute_code(client):
    """A payload that would mutate state if evaluated must have no effect."""
    payload = "ORDERS.clear()"
    r = client.get("/api/search", params={"q": payload})
    assert r.status_code == 200
    assert order_ids() == [1, 2, 3]


# --------------------------------------------------------------------------
# Auth on admin routes
# --------------------------------------------------------------------------

ADMIN_CALLS = [
    ("get", "/api/admin/dump", None),
    ("patch", "/api/orders/1", {"status": "paid"}),
    ("delete", "/api/orders/1", None),
]


def _call(client, method, url, body, headers=None):
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(url, **kwargs)


@pytest.mark.parametrize("method,url,body", ADMIN_CALLS)
def test_admin_routes_503_when_token_unset(client, monkeypatch, method, url, body):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    r = _call(client, method, url, body, AUTH)
    assert r.status_code == 503
    assert r.json()["detail"] == "Admin authentication is not configured"
    assert TOKEN not in r.text
    assert order_ids() == [1, 2, 3]
    assert main.ORDERS[0].status == "shipped"


@pytest.mark.parametrize("method,url,body", ADMIN_CALLS)
def test_admin_routes_503_when_token_unset_and_no_header(client, monkeypatch, method, url, body):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert _call(client, method, url, body).status_code == 503


@pytest.mark.parametrize("method,url,body", ADMIN_CALLS)
def test_admin_routes_reject_missing_token(client, method, url, body):
    r = _call(client, method, url, body)
    assert r.status_code in (401, 403)
    assert TOKEN not in r.text
    assert order_ids() == [1, 2, 3]
    assert main.ORDERS[0].status == "shipped"


@pytest.mark.parametrize("bad", ["wrong", "", "test-toke", "test-token ", "TEST-TOKEN", "test-token2"])
@pytest.mark.parametrize("method,url,body", ADMIN_CALLS)
def test_admin_routes_reject_wrong_token(client, method, url, body, bad):
    r = _call(client, method, url, body, {"X-Admin-Token": bad})
    assert r.status_code in (401, 403)
    assert TOKEN not in r.text
    assert order_ids() == [1, 2, 3]
    assert main.ORDERS[0].status == "shipped"


def test_token_header_name_is_case_insensitive(client):
    r = client.get("/api/admin/dump", headers={"x-admin-token": TOKEN})
    assert r.status_code == 200


def test_token_not_leaked_in_successful_responses(client):
    assert TOKEN not in client.get("/api/admin/dump", headers=AUTH).text
    assert TOKEN not in client.patch("/api/orders/1", headers=AUTH, json={"status": "paid"}).text
    assert TOKEN not in client.delete("/api/orders/1", headers=AUTH).text


def test_unauthenticated_request_does_not_reveal_whether_order_exists(client):
    unknown = client.patch("/api/orders/9999", json={"status": "paid"})
    known = client.patch("/api/orders/1", json={"status": "paid"})
    assert unknown.status_code == known.status_code
    assert unknown.json() == known.json()
    unknown_d = client.delete("/api/orders/9999")
    known_d = client.delete("/api/orders/1")
    assert unknown_d.status_code == known_d.status_code


def test_admin_token_is_read_per_request(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "rotated-token")
    assert client.get("/api/admin/dump", headers=AUTH).status_code == 401
    assert client.get("/api/admin/dump", headers={"X-Admin-Token": "rotated-token"}).status_code == 200


def test_admin_dump_contents(client):
    body = client.get("/api/admin/dump", headers=AUTH).json()
    assert set(body) == {"users", "orders", "next_order_id"}
    assert body["next_order_id"] == 4
    assert len(body["users"]) == 3 and len(body["orders"]) == 3


def test_non_ascii_token_header_is_rejected_not_500():
    """APP BUG (app/main.py:117): secrets.compare_digest raises TypeError for
    non-ASCII str input, so a non-ASCII X-Admin-Token causes an unhandled 500
    instead of 401. Expected: 401/403."""
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get("/api/admin/dump", headers={"X-Admin-Token": "caf\u00e9".encode("latin-1")})
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# Orders: read / filter
# --------------------------------------------------------------------------

def test_list_orders_unfiltered(client):
    r = client.get("/api/orders")
    assert r.status_code == 200
    assert [o["id"] for o in r.json()] == [1, 2, 3]


def test_list_orders_filter_by_user_only(client):
    assert [o["id"] for o in client.get("/api/orders", params={"user_id": 1}).json()] == [1, 3]
    assert client.get("/api/orders", params={"user_id": 3}).json() == []
    assert client.get("/api/orders", params={"user_id": 999}).json() == []


def test_list_orders_filter_by_status_only(client):
    r = client.get("/api/orders", params={"status": "delivered"})
    assert [o["id"] for o in r.json()] == [3]
    assert client.get("/api/orders", params={"status": "cancelled"}).json() == []


def test_list_orders_user_and_status_combined(client):
    r = client.get("/api/orders", params={"user_id": 1, "status": "delivered"})
    assert [o["id"] for o in r.json()] == [3]
    r = client.get("/api/orders", params={"status": "delivered", "user_id": 1})
    assert [o["id"] for o in r.json()] == [3]
    # user 1 has orders, status exists for another user -> empty
    assert client.get("/api/orders", params={"user_id": 1, "status": "pending"}).json() == []


def test_list_orders_combined_filter_after_new_order(client):
    client.post("/api/orders", json={"user_id": 1, "product": "Mouse", "amount": 10})
    r = client.get("/api/orders", params={"user_id": 1, "status": "pending"})
    assert [o["id"] for o in r.json()] == [4]
    r = client.get("/api/orders", params={"user_id": 2, "status": "pending"})
    assert [o["id"] for o in r.json()] == [2]


def test_list_orders_invalid_filter_values(client):
    assert client.get("/api/orders", params={"user_id": "abc"}).status_code == 422
    assert client.get("/api/orders", params={"status": "bogus"}).status_code == 422


def test_get_order_by_id(client):
    r = client.get("/api/orders/3")
    assert r.status_code == 200
    assert r.json() == {"id": 3, "user_id": 1, "product": "Monitor", "amount": 349.0, "status": "delivered"}
    assert client.get("/api/orders/0").status_code == 404
    assert client.get("/api/orders/abc").status_code == 422


# --------------------------------------------------------------------------
# Orders: create
# --------------------------------------------------------------------------

def test_create_order_defaults_and_persistence(client):
    r = client.post("/api/orders", json={"user_id": 3, "product": "Cable", "amount": 12.5})
    assert r.status_code == 201
    assert r.json() == {"id": 4, "user_id": 3, "product": "Cable", "amount": 12.5, "status": "pending"}
    assert client.get("/api/orders/4").json()["product"] == "Cable"
    assert order_ids() == [1, 2, 3, 4]


def test_create_order_ids_are_unique_and_not_reused_after_deleting_last(client):
    first = client.post("/api/orders", json={"user_id": 1, "product": "A", "amount": 1}).json()
    assert first["id"] == 4
    assert client.delete("/api/orders/4", headers=AUTH).status_code == 204
    second = client.post("/api/orders", json={"user_id": 1, "product": "B", "amount": 1}).json()
    assert second["id"] == 5  # no duplicate / reused id
    ids = order_ids()
    assert len(ids) == len(set(ids))


def test_create_order_many_have_no_duplicate_ids(client):
    for i in range(5):
        assert client.post("/api/orders", json={"user_id": 2, "product": f"P{i}", "amount": 1}).status_code == 201
    ids = order_ids()
    assert ids == [1, 2, 3, 4, 5, 6, 7, 8]
    assert len(ids) == len(set(ids))


def test_create_order_discount_math(client):
    r = client.post(
        "/api/orders",
        json={"user_id": 1, "product": "X", "amount": 200, "discount_percent": 50},
    )
    assert r.status_code == 201
    assert r.json()["amount"] == pytest.approx(100)
    r = client.post(
        "/api/orders",
        json={"user_id": 1, "product": "X", "amount": 200, "discount_percent": 99.5},
    )
    assert r.status_code == 201
    assert r.json()["amount"] == pytest.approx(1)


def test_create_order_100_percent_discount_rejected_without_side_effects(client):
    r = client.post(
        "/api/orders",
        json={"user_id": 1, "product": "X", "amount": 10, "discount_percent": 100},
    )
    assert r.status_code == 422
    assert order_ids() == [1, 2, 3]
    assert main._next_order_id == 4


def test_create_order_unknown_user_does_not_consume_id(client):
    r = client.post("/api/orders", json={"user_id": 42, "product": "X", "amount": 10})
    assert r.status_code == 404
    assert main._next_order_id == 4
    ok = client.post("/api/orders", json={"user_id": 1, "product": "X", "amount": 10})
    assert ok.json()["id"] == 4


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"user_id": 1},
        {"user_id": 1, "product": "X"},
        {"product": "X", "amount": 10},
        {"user_id": "abc", "product": "X", "amount": 10},
        {"user_id": 1, "product": "X", "amount": "abc"},
        {"user_id": 1, "product": None, "amount": 10},
        {"user_id": 1, "product": "X", "amount": 0.0},
        {"user_id": 1, "product": "X", "amount": -0.01},
        {"user_id": 1, "product": "X", "amount": 10, "discount_percent": "lots"},
    ],
)
def test_create_order_invalid_payloads(client, payload):
    r = client.post("/api/orders", json=payload)
    assert r.status_code == 422
    assert order_ids() == [1, 2, 3]
    assert main._next_order_id == 4


def test_create_order_infinite_amount_is_rejected(client):
    """APP BUG (app/main.py:57 OrderCreate.amount): `gt=0` accepts +Infinity (a JSON body
    of 1e400 parses to inf). The order is stored and the response has "amount": null,
    violating the Order schema. Expected: 422 and nothing stored."""
    r = client.post(
        "/api/orders",
        content=b'{"user_id": 1, "product": "X", "amount": 1e400}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422
    assert order_ids() == [1, 2, 3]


# --------------------------------------------------------------------------
# Orders: update
# --------------------------------------------------------------------------

@pytest.mark.parametrize("new_status", ["pending", "paid", "shipped", "delivered", "cancelled"])
def test_patch_each_valid_status(client, new_status):
    r = client.patch("/api/orders/2", headers=AUTH, json={"status": new_status})
    assert r.status_code == 200
    assert r.json()["status"] == new_status
    assert client.get("/api/orders/2").json()["status"] == new_status


def test_patch_only_amount_keeps_status(client):
    r = client.patch("/api/orders/2", headers=AUTH, json={"amount": 12.34})
    assert r.status_code == 200
    assert r.json()["amount"] == 12.34
    assert r.json()["status"] == "pending"


def test_patch_only_status_keeps_amount(client):
    r = client.patch("/api/orders/2", headers=AUTH, json={"status": "paid"})
    assert r.json()["amount"] == 79.5


def test_patch_empty_body_is_noop(client):
    r = client.patch("/api/orders/2", headers=AUTH, json={})
    assert r.status_code == 200
    assert r.json() == {"id": 2, "user_id": 2, "product": "Keyboard", "amount": 79.5, "status": "pending"}


def test_patch_only_touches_requested_order(client):
    before = {o.id: o.model_dump() for o in main.ORDERS}
    client.patch("/api/orders/2", headers=AUTH, json={"status": "cancelled", "amount": 1})
    after = {o.id: o.model_dump() for o in main.ORDERS}
    assert after[1] == before[1]
    assert after[3] == before[3]
    assert after[2]["status"] == "cancelled"


def test_patch_unknown_order_is_404(client):
    r = client.patch("/api/orders/999", headers=AUTH, json={"status": "paid"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Order not found"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "teleported"},
        {"status": 5},
        {"amount": 0},
        {"amount": -3},
        {"amount": "free"},
        {"status": "paid", "amount": 0},
    ],
)
def test_patch_invalid_payloads_do_not_mutate(client, payload):
    r = client.patch("/api/orders/2", headers=AUTH, json=payload)
    assert r.status_code == 422
    assert main.ORDERS[1].status == "pending"
    assert main.ORDERS[1].amount == 79.5


def test_patch_non_int_order_id_is_422(client):
    assert client.patch("/api/orders/abc", headers=AUTH, json={"status": "paid"}).status_code == 422


def test_patch_infinite_amount_is_rejected(client):
    """APP BUG (app/main.py:68 OrderUpdate.amount): same `gt=0` / +Infinity gap as create.
    Expected: 422 and amount unchanged."""
    r = client.patch(
        "/api/orders/2",
        headers={**AUTH, "content-type": "application/json"},
        content=b'{"amount": 1e400}',
    )
    assert r.status_code == 422
    assert main.ORDERS[1].amount == 79.5


# --------------------------------------------------------------------------
# Orders: delete
# --------------------------------------------------------------------------

def test_delete_removes_only_requested_order(client):
    r = client.delete("/api/orders/1", headers=AUTH)
    assert r.status_code == 204
    assert r.content == b""
    assert order_ids() == [2, 3]
    assert client.get("/api/orders/1").status_code == 404
    assert client.get("/api/orders/2").status_code == 200
    assert client.get("/api/orders/3").status_code == 200


def test_delete_middle_order(client):
    assert client.delete("/api/orders/2", headers=AUTH).status_code == 204
    assert order_ids() == [1, 3]


def test_delete_unknown_and_repeated_delete_is_404(client):
    assert client.delete("/api/orders/999", headers=AUTH).status_code == 404
    assert client.delete("/api/orders/1", headers=AUTH).status_code == 204
    assert client.delete("/api/orders/1", headers=AUTH).status_code == 404
    assert order_ids() == [2, 3]


def test_delete_non_int_order_id_is_422(client):
    assert client.delete("/api/orders/abc", headers=AUTH).status_code == 422


def test_delete_all_orders_including_last_then_list_and_create(client):
    for oid in (1, 2, 3):
        assert client.delete(f"/api/orders/{oid}", headers=AUTH).status_code == 204
    assert main.ORDERS == []
    assert client.get("/api/orders").json() == []
    assert client.get("/api/orders", params={"user_id": 1, "status": "pending"}).json() == []
    dump = client.get("/api/admin/dump", headers=AUTH).json()
    assert dump["orders"] == []
    created = client.post("/api/orders", json={"user_id": 1, "product": "New", "amount": 5})
    assert created.status_code == 201
    assert created.json()["id"] == 4  # ids are not reused after deletions
