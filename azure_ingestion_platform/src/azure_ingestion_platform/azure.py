from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from urllib.parse import urlencode

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt
from sqlalchemy.orm import Session

from .config import settings
from .models import Tenant, TenantCredential
from .security import cipher


class AzureThrottleError(RuntimeError):
    pass


class AzureRequestError(RuntimeError):
    pass


@dataclass(slots=True)
class TenantAuthMaterial:
    tenant_external_id: str
    client_id: str
    client_secret: str


def build_admin_consent_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.platform_client_id,
            "redirect_uri": settings.platform_redirect_uri,
            "state": state,
        }
    )
    return f"https://login.microsoftonline.com/common/adminconsent?{query}"


def _resolve_auth_material(db: Session, tenant: Tenant) -> TenantAuthMaterial:
    credential = (
        db.query(TenantCredential)
        .filter(TenantCredential.tenant_id == tenant.id, TenantCredential.credential_type == "client_secret")
        .one_or_none()
    )
    if credential and credential.client_id and credential.secret_encrypted:
        return TenantAuthMaterial(
            tenant_external_id=tenant.tenant_external_id,
            client_id=credential.client_id,
            client_secret=cipher.decrypt(credential.secret_encrypted),
        )
    return TenantAuthMaterial(
        tenant_external_id=tenant.tenant_external_id,
        client_id=settings.platform_client_id,
        client_secret=settings.platform_client_secret,
    )


class AzureApiClient:
    def __init__(self, db: Session, tenant: Tenant) -> None:
        self.db = db
        self.tenant = tenant
        self._session = requests.Session()
        self._material = _resolve_auth_material(db, tenant)

    def _token_endpoint(self) -> str:
        return f"https://login.microsoftonline.com/{self._material.tenant_external_id}/oauth2/v2.0/token"

    @retry(
        retry=retry_if_exception_type((requests.RequestException, AzureThrottleError, AzureRequestError)),
        stop=stop_after_attempt(settings.ingestion_max_attempts),
        reraise=True,
    )
    def _post_form(self, url: str, data: dict[str, str], *, source: str) -> dict[str, Any]:
        response = self._session.post(url, data=data, timeout=60)
        if response.status_code == 429:
            self._sleep_retry(response)
            raise AzureThrottleError(f"{source} throttled with 429")
        if response.status_code >= 500:
            self._sleep_retry(response)
            raise AzureRequestError(f"{source} failed with {response.status_code}: {response.text[:400]}")
        response.raise_for_status()
        return response.json()

    @retry(
        retry=retry_if_exception_type((requests.RequestException, AzureThrottleError, AzureRequestError)),
        stop=stop_after_attempt(settings.ingestion_max_attempts),
        reraise=True,
    )
    def _request_json(
        self,
        method: str,
        url: str,
        *,
        source: str,
        token: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        if response.status_code in {429, 503}:
            self._sleep_retry(response)
            raise AzureThrottleError(f"{source} throttled with {response.status_code}")
        if response.status_code >= 500:
            self._sleep_retry(response)
            raise AzureRequestError(f"{source} failed with {response.status_code}: {response.text[:400]}")
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _sleep_retry(self, response: requests.Response) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                time.sleep(min(float(retry_after), settings.retry_max_seconds))
                return
            except ValueError:
                pass
        delay = min(settings.retry_base_seconds * (2 ** random.randint(0, 2)), settings.retry_max_seconds)
        time.sleep(delay + random.random())

    def get_access_token(self, scope: str) -> str:
        payload = self._post_form(
            self._token_endpoint(),
            {
                "client_id": self._material.client_id,
                "client_secret": self._material.client_secret,
                "grant_type": "client_credentials",
                "scope": scope,
            },
            source="oauth",
        )
        token = str(payload.get("access_token") or "")
        if not token:
            raise AzureRequestError("OAuth token response did not contain an access token")
        return token

    def list_subscriptions(self) -> list[dict[str, Any]]:
        token = self.get_access_token("https://management.azure.com/.default")
        payload = self._request_json(
            "GET",
            "https://management.azure.com/subscriptions",
            source="subscriptions",
            token=token,
            params={"api-version": "2022-12-01"},
        )
        return list(payload.get("value") or [])

    def iter_resource_graph_pages(self, subscriptions: list[str], query: str) -> Iterator[dict[str, Any]]:
        token = self.get_access_token("https://management.azure.com/.default")
        url = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
        skip_token = ""
        while True:
            body: dict[str, Any] = {
                "subscriptions": subscriptions,
                "query": query,
                "options": {"$top": 1000},
            }
            if skip_token:
                body["options"]["$skipToken"] = skip_token
            payload = self._request_json(
                "POST",
                url,
                source="resource_graph",
                token=token,
                params={"api-version": "2022-10-01"},
                json_body=body,
            )
            yield payload
            skip_token = str(payload.get("skipToken") or "")
            if not skip_token:
                break

    def iter_activity_log_pages(self, subscription_id: str, start: datetime, end: datetime) -> Iterator[dict[str, Any]]:
        token = self.get_access_token("https://management.azure.com/.default")
        next_url = (
            f"https://management.azure.com/subscriptions/{subscription_id}/providers/microsoft.insights/"
            "eventtypes/management/values"
        )
        params = {
            "api-version": "2015-04-01",
            "$filter": (
                f"eventTimestamp ge '{start.astimezone(timezone.utc).isoformat()}' and "
                f"eventTimestamp le '{end.astimezone(timezone.utc).isoformat()}'"
            ),
        }
        while next_url:
            payload = self._request_json("GET", next_url, source="activity_log", token=token, params=params)
            yield payload
            next_url = str(payload.get("nextLink") or "")
            params = None

    @staticmethod
    def payload_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
