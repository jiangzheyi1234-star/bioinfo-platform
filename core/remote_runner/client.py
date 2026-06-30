from __future__ import annotations

import json
import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

class RemoteRunnerClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class RemoteRunnerConflictError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        super().__init__("remote runner conflict")
        self.payload = payload


def _http_error_detail_value(payload: str) -> Any:
    cleaned = payload.strip()
    if not cleaned:
        return None
    try:
        decoded = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned
    if not isinstance(decoded, dict):
        return cleaned
    return decoded.get("detail")


def _http_error_detail(payload: str) -> str:
    detail = _http_error_detail_value(payload)
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail.strip()
    return json.dumps(detail, ensure_ascii=False, separators=(",", ":"))


@dataclass
class RemoteRunnerHttpClient:
    base_url: str
    token: str
    timeout: int = 5

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        raw_body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        accepted = accepted_statuses or {200}
        enforce_status = accepted_statuses is not None
        if payload is not None and raw_body is not None:
            raise ValueError("REMOTE_RUNNER_REQUEST_BODY_AMBIGUOUS")
        body = None
        if raw_body is not None:
            body = bytes(raw_body)
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            if any(str(key).lower() == "authorization" for key in extra_headers):
                raise ValueError("REMOTE_RUNNER_EXTRA_HEADER_FORBIDDEN: Authorization")
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers=headers,
            data=body,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status_code = int(response.status)
                response_payload = response.read().decode("utf-8")
                if enforce_status and status_code not in accepted:
                    raise RemoteRunnerClientError(
                        f"runner http status {status_code} not accepted for {method} {path}",
                        status_code=status_code,
                        detail={
                            "acceptedStatusCodes": sorted(accepted),
                            "response": _decode_json_object(response_payload),
                            "statusCode": status_code,
                        },
                    )
                return json.loads(response_payload)
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            if exc.code in accepted:
                decoded = json.loads(response_payload or "{}")
                if isinstance(decoded, dict):
                    return decoded
            detail_value = _http_error_detail_value(response_payload)
            if exc.code == 409 and isinstance(detail_value, dict):
                raise RemoteRunnerConflictError(detail_value) from exc
            detail = _http_error_detail(response_payload)
            message = f"runner http error {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RemoteRunnerClientError(message, status_code=exc.code, detail=detail_value) from exc
        except urllib.error.URLError as exc:
            raise RemoteRunnerClientError(str(exc.reason) or "runner unreachable") from exc
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            raise RemoteRunnerClientError(str(exc) or "runner unreachable") from exc

    def _request_bytes(self, method: str, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.token}"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {
                    "statusCode": int(response.status),
                    "content": response.read(),
                    "headers": {key.lower(): value for key, value in response.headers.items()},
                }
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            detail_value = _http_error_detail_value(response_payload)
            detail = _http_error_detail(response_payload)
            message = f"runner http error {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RemoteRunnerClientError(message, status_code=exc.code, detail=detail_value) from exc
        except urllib.error.URLError as exc:
            raise RemoteRunnerClientError(str(exc.reason) or "runner unreachable") from exc
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            raise RemoteRunnerClientError(str(exc) or "runner unreachable") from exc

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        return self._request_json("GET", path, accepted_statuses=accepted_statuses)

    def probe_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        accepted = accepted_statuses or {200}
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {"httpStatus": int(response.status), "body": json.loads(response.read().decode("utf-8"))}
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            if exc.code in accepted:
                return {"httpStatus": int(exc.code), "body": json.loads(response_payload or "{}")}
            return {
                "httpStatus": int(exc.code),
                "body": _decode_json_object(response_payload),
                "error": {
                    "reasonCode": "RUNNER_HTTP_ERROR",
                    "message": str(exc),
                    "errorType": type(exc).__name__,
                },
            }
        except urllib.error.URLError as exc:
            return _runner_unreachable_probe(exc)
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            return _runner_unreachable_probe(exc)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            path,
            payload=payload,
            extra_headers=extra_headers,
            accepted_statuses=accepted_statuses,
        )

    def post_bytes_json(
        self,
        path: str,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            path,
            raw_body=bytes(body),
            extra_headers=extra_headers,
            accepted_statuses=accepted_statuses,
        )

    def patch_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("PATCH", path, payload=payload, accepted_statuses=accepted_statuses)

    def delete_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        return self._request_json("DELETE", path, accepted_statuses=accepted_statuses)

    def download_bytes(self, path: str) -> dict[str, Any]:
        return self._request_bytes("GET", path)


def _decode_json_object(payload: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _runner_unreachable_probe(exc: BaseException) -> dict[str, Any]:
    return {
        "httpStatus": None,
        "body": None,
        "error": {
            "reasonCode": "RUNNER_UNREACHABLE",
            "message": str(exc),
            "errorType": type(exc).__name__,
        },
    }
