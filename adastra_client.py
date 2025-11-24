from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union, List
import requests
from decouple import config

logger = logging.getLogger("adastra_min_client")


class APIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_text = response_text

    def __str__(self) -> str:
        base = self.message
        if self.status_code is not None:
            base += f" [HTTP {self.status_code}]"
        if self.response_text:
            base += f" :: {self.response_text[:500]}"
        return base


def _infer_web_origin_and_referer(base_url: str):
    origin = "https://connect.ad-astrainc.com"
    referer = "https://connect.ad-astrainc.com/"
    return origin, referer


def _unwrap_items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("data", "results", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return v
        return [data]
    raise APIError("Unexpected response shape; expected list or {'data': [...]}.")


class AdAstraClient:
    """
    Минимальный клиент только для:
      - GET /api/Appoinment/interpreters/{assignment_code}
      - GET /api/accounts/GetAccountDetailByID/{interpreter_id}
      - POST /api/Appoinment/filter/SYSTEM/{system_guid}
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ) -> None:
        # читаем из .env через python-decouple
        self.base_url = (base_url or config("ADASTRA_API_BASE_URL")).rstrip("/")
        self.email = email or config("ADASTRA_EMAIL")
        self.password = password or config("ADASTRA_PASSWORD")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._token: Optional[str] = None

        origin, referer = _infer_web_origin_and_referer(self.base_url)
        self._base_headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Origin": origin,
            "Referer": referer,
        }

        self._max_retries = int(config("AAC_MAX_RETRIES", default=3))
        self._backoff_base = float(config("AAC_BACKOFF_BASE", default=0.5))

    # ------------------- HTTP -------------------

    def _headers(self, with_auth: bool = True) -> Dict[str, str]:
        hdrs = dict(self._base_headers)
        if with_auth:
            if not self._token:
                raise APIError("Not authenticated; call .login() first.")
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        with_auth: bool = True,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = path_or_url if path_or_url.startswith("http") else self._url(path_or_url)
        import time, random

        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                hdrs = headers or self._headers(with_auth=with_auth)
                resp = self._session.request(method, url, headers=hdrs, json=json, params=params, timeout=self.timeout)

                if resp.status_code in (429,) or resp.status_code >= 500:
                    raise APIError("Retryable error", resp.status_code, resp.text)
                if resp.status_code >= 400:
                    raise APIError("Request failed", resp.status_code, resp.text)

                try:
                    return resp.json()
                except Exception:
                    return resp.text
            except Exception as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                time.sleep(self._backoff_base * (2 ** attempt) + random.uniform(0, 0.25))

        assert last_exc is not None
        raise APIError(f"{method} {url} failed after retries: {last_exc}")

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _post(self, path: str, body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json=body or {}, params=params)

    # ------------------- LOGIN -------------------

    def login(self, email: Optional[str] = None, password: Optional[str] = None, remember_me: bool = True) -> str:
        email = email or self.email
        password = password or self.password

        data = self._request(
            "POST",
            self._url("/api/accounts/token"),
            json={"email": email, "password": password, "rememberMe": remember_me},
            with_auth=False,
            headers={"Accept": "*/*", "Content-Type": "application/json"},
        )
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise APIError("Auth response did not include 'token'.")
        self._token = token
        return token

    # ------------------- API -------------------

    def get_interpreters_for_assignment(self, assignment_code: Union[str, int]) -> List[Dict[str, Any]]:
        path = f"/api/Appoinment/interpreters/{assignment_code}"
        data = self._get(path)
        return _unwrap_items(data)

    def get_account_detail_by_id(self, interpreter_id: Union[str, int]) -> Dict[str, Any]:
        path = f"/api/accounts/GetAccountDetailByID/{interpreter_id}"
        data = self._get(path)
        return data if isinstance(data, dict) else {"data": data}
    
    def get_appointment(self, code: Union[str, int]) -> Dict[str, Any]:
        path = f"/api/Appoinment/{code}"
        data = self._get(path)
        return data if isinstance(data, dict) else {"data": data}

    def filter_appointments_system(
        self,
        system_guid: str,
        *,
        filters: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None, 
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = dict(filters or {})

        path = f"/api/Appoinment/filter/SYSTEM/{system_guid}"
        data = self._post(path, body=body, params=params)
        return data if isinstance(data, dict) else {"data": _unwrap_items(data)}

# if __name__ == "__main__":
#     client = AdAstraMinimalClient()
#     token = client.login()
#     print("✅ Logged in, token:", token, "...")

#     # Пример запроса:
#     interpreters = client.get_interpreters_for_assignment("6488")
#     print("Interpreters:", interpreters)