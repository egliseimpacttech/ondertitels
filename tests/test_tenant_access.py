import pytest
from starlette.requests import Request
from starlette.responses import Response

from backend import main


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer test-token")],
            "server": ("test", 80),
            "client": ("test", 1234),
        }
    )


@pytest.mark.asyncio
async def test_inactive_paid_church_is_blocked(monkeypatch):
    monkeypatch.setattr(main, "_init_firebase", lambda: True)
    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        lambda token: {
            "email": "member@example.com",
            "uid": "member-uid",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        main.tenants,
        "get_membership",
        lambda email: {"church_id": "church-1", "role": "member"},
    )
    monkeypatch.setattr(
        main.tenants,
        "get_church",
        lambda church_id: {
            "id": church_id,
            "plan": "paid",
            "subscription_status": "past_due",
            "storage_limit_bytes": 100,
        },
    )
    called = False

    async def call_next(request):
        nonlocal called
        called = True
        return Response("unexpected")

    response = await main._firebase_auth_middleware(_request("/api/library"), call_next)

    assert response.status_code == 402
    assert not called


@pytest.mark.asyncio
async def test_unverified_email_cannot_access_any_church_workspace(monkeypatch):
    monkeypatch.setattr(main, "_init_firebase", lambda: True)
    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        lambda token: {
            "email": "kaat.dbolle@gmail.com",
            "uid": "unverified-uid",
            "email_verified": False,
        },
    )
    called = False

    async def call_next(request):
        nonlocal called
        called = True
        return Response("unexpected")

    response = await main._firebase_auth_middleware(_request("/api/tenant/status"), call_next)

    assert response.status_code == 403
    assert not called


@pytest.mark.asyncio
async def test_active_paid_church_receives_its_storage_scope(monkeypatch):
    monkeypatch.setattr(main, "_init_firebase", lambda: True)
    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        lambda token: {
            "email": "member@example.com",
            "uid": "member-uid",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        main.tenants,
        "get_membership",
        lambda email: {"church_id": "church-1", "role": "member"},
    )
    monkeypatch.setattr(
        main.tenants,
        "get_church",
        lambda church_id: {
            "id": church_id,
            "plan": "paid",
            "subscription_status": "active",
            "storage_limit_bytes": 100,
        },
    )

    async def call_next(request):
        assert main.library._tenant_id.get() == "church-1"
        assert main.library._storage_limit.get() == 100
        return Response("ok")

    response = await main._firebase_auth_middleware(_request("/api/library"), call_next)

    assert response.status_code == 200
    assert main.library._tenant_id.get() is None
