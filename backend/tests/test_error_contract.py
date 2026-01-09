from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.deps import verify_admin_token
from app.core.errors import AppError, register_exception_handlers
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import get_settings


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/app-error")
    async def _app_error() -> None:
        raise AppError(code="TEST_ERROR", message="测试错误", status_code=400)

    @app.get("/http-string")
    async def _http_string() -> None:
        raise HTTPException(status_code=404, detail="资源不存在")

    @app.get("/http-dict")
    async def _http_dict() -> None:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_REQUEST", "message": "bad", "details": {"foo": "bar"}},
        )

    @app.get("/admin", dependencies=[Depends(verify_admin_token)])
    async def _admin() -> dict[str, bool]:
        return {"ok": True}

    return app


def _assert_error_contract(res) -> None:
    request_id = res.headers.get("x-request-id")
    assert request_id

    body = res.json()
    assert body.get("request_id") == request_id
    assert isinstance(body.get("error"), dict)
    assert body["error"].get("code")
    assert body["error"].get("message")


def test_error_contract_app_error() -> None:
    app = _build_app()
    client = TestClient(app)
    res = client.get("/app-error", headers={"X-Request-ID": "rid_test"})
    assert res.status_code == 400
    assert res.headers.get("x-request-id") == "rid_test"
    _assert_error_contract(res)
    assert res.json()["error"]["code"] == "TEST_ERROR"


def test_error_contract_http_string() -> None:
    app = _build_app()
    client = TestClient(app)
    res = client.get("/http-string", headers={"X-Request-ID": "rid_test"})
    assert res.status_code == 404
    _assert_error_contract(res)
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_error_contract_http_dict() -> None:
    app = _build_app()
    client = TestClient(app)
    res = client.get("/http-dict", headers={"X-Request-ID": "rid_test"})
    assert res.status_code == 400
    _assert_error_contract(res)
    assert res.json()["error"]["code"] == "BAD_REQUEST"
    assert res.json()["error"]["details"]["foo"] == "bar"


def test_admin_token_dependency() -> None:
    app = _build_app()
    client = TestClient(app)

    missing = client.get("/admin", headers={"X-Request-ID": "rid_test"})
    assert missing.status_code == 401
    _assert_error_contract(missing)
    assert missing.json()["error"]["code"] == "MISSING_ADMIN_TOKEN"

    ok = client.get(
        "/admin",
        headers={"X-Request-ID": "rid_test", "X-Admin-Token": get_settings().admin_token},
    )
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}
    assert ok.headers.get("x-request-id") == "rid_test"
