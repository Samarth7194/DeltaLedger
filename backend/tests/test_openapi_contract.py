from __future__ import annotations

from app.main import create_app


def test_openapi_operation_ids_are_unique() -> None:
    operation_ids = [
        operation["operationId"]
        for methods in create_app().openapi()["paths"].values()
        for method, operation in methods.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]

    duplicates = {
        operation_id
        for operation_id in operation_ids
        if operation_ids.count(operation_id) > 1
    }

    assert duplicates == set()


def test_openapi_documents_bearer_auth_and_public_route_boundary() -> None:
    schema = create_app().openapi()
    operations = [
        (method.upper(), path, bool(operation.get("security")))
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    public_routes = {(method, path) for method, path, secured in operations if not secured}

    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert public_routes == {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/ready"),
    }
