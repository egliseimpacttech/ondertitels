import pytest
from google.api_core.exceptions import Forbidden
from google.auth.exceptions import TransportError
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
async def test_firebase_certificate_transport_error_is_retryable(monkeypatch):
    monkeypatch.setattr(main, "_init_firebase", lambda: True)

    def fail_verification(token):
        raise TransportError("certificate endpoint unavailable")

    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        fail_verification,
    )

    async def call_next(request):
        pytest.fail("A failed token verification must not reach the route.")

    response = await main._firebase_auth_middleware(_request("/api/status/job-1"), call_next)
    response_body = response.body.decode("utf-8")

    assert response.status_code == 503
    assert "auth_verification_unavailable" in response_body


@pytest.mark.asyncio
async def test_invalid_firebase_token_remains_unauthorized(monkeypatch):
    monkeypatch.setattr(main, "_init_firebase", lambda: True)

    def fail_verification(token):
        raise ValueError("invalid signature")

    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        fail_verification,
    )

    async def call_next(request):
        pytest.fail("An invalid token must not reach the route.")

    response = await main._firebase_auth_middleware(_request("/api/status/job-1"), call_next)

    assert response.status_code == 401


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


@pytest.mark.asyncio
async def test_ministry_admin_uses_free_workspace_without_firestore_membership(monkeypatch):
    ministry_email = main.tenants.MINISTRY_ADMIN_EMAIL
    monkeypatch.setattr(main, "_init_firebase", lambda: True)
    monkeypatch.setattr(
        main,
        "_verify_firebase_id_token",
        lambda token: {
            "email": ministry_email,
            "uid": "ministry-admin-uid",
            "email_verified": True,
        },
    )
    monkeypatch.setattr(
        main.tenants,
        "get_membership",
        lambda email: pytest.fail("Ministry admin access should not depend on Firestore."),
    )
    monkeypatch.setattr(
        main.tenants,
        "ensure_ministry_membership",
        lambda *args: pytest.fail("Ministry admin access should not write Firestore."),
    )
    monkeypatch.setattr(
        main.tenants,
        "get_church",
        lambda church_id: pytest.fail("Ministry workspace should be configured directly."),
    )

    async def call_next(request):
        assert request.state.tenant_id == main.tenants.MINISTRY_TENANT_ID
        assert request.state.is_admin
        assert main.library._tenant_id.get() == main.tenants.MINISTRY_TENANT_ID
        assert main.library._storage_limit.get() is None
        return Response("ok")

    response = await main._firebase_auth_middleware(_request("/api/library"), call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tenant_status_explains_cloud_storage_access_failure(monkeypatch):
    request = _request("/api/tenant/status")
    request.state.tenant = {
        "id": main.tenants.MINISTRY_TENANT_ID,
        "name": main.tenants.MINISTRY_NAME,
        "plan": "free",
        "subscription_status": "active",
        "storage_limit_bytes": None,
    }
    request.state.tenant_role = "admin"

    def fail_storage_read():
        raise Forbidden("billing account missing")

    monkeypatch.setattr(main.library, "get_storage_usage_bytes", fail_storage_read)

    with pytest.raises(main.HTTPException) as exc_info:
        await main.tenant_status(request)

    assert exc_info.value.status_code == 503
    assert "facturation" in exc_info.value.detail
