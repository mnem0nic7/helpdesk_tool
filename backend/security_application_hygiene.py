"""Azure application hygiene helpers for the Security workspace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from azure_cache import azure_cache
from models import (
    SecurityAppHygieneApp,
    SecurityAppHygieneCredential,
    SecurityAppHygieneMetric,
    SecurityAppHygieneResponse,
)

_STALE_DATA_HOURS = 4
_EXPIRING_SOON_DAYS = 30
_EXPIRING_WARN_DAYS = 90
_INTERNAL_AUDIENCES = {"AzureADMyOrg"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dataset_last_refresh(status: dict[str, Any], dataset_key: str) -> str:
    datasets = status.get("datasets") if isinstance(status.get("datasets"), list) else []
    for dataset in datasets:
        if str(dataset.get("key") or "").strip().lower() == dataset_key.lower():
            return str(dataset.get("last_refresh") or "")
    return ""


def _dataset_is_stale(value: str, *, hours: int = _STALE_DATA_HOURS) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return True
    return parsed <= datetime.now(timezone.utc) - timedelta(hours=hours)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _fallback_application_security_rows() -> list[dict[str, Any]]:
    rows = azure_cache._snapshot("applications") or []
    result: list[dict[str, Any]] = []
    for row in rows:
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        owner_names = [
            item.strip()
            for item in str(extra.get("owner_names") or "").split(",")
            if item.strip()
        ]
        result.append(
            {
                "id": str(row.get("id") or ""),
                "app_id": str(row.get("app_id") or ""),
                "display_name": str(row.get("display_name") or ""),
                "sign_in_audience": str(extra.get("sign_in_audience") or ""),
                "created_datetime": str(extra.get("created_datetime") or ""),
                "publisher_domain": str(extra.get("publisher_domain") or ""),
                "verified_publisher_name": str(extra.get("verified_publisher_name") or ""),
                "owner_count": _int_value(extra.get("owner_count")),
                "owners": [
                    {"display_name": owner_name, "principal_name": owner_name}
                    for owner_name in owner_names
                ],
                "owner_lookup_error": "",
                "credential_count": _int_value(extra.get("credential_count")),
                "password_credential_count": _int_value(extra.get("password_credential_count")),
                "key_credential_count": _int_value(extra.get("certificate_credential_count")),
                "next_credential_expiry": str(extra.get("next_credential_expiry") or ""),
                "credentials": [],
                "notes": "",
            }
        )
    return result


def _owner_names(row: dict[str, Any]) -> list[str]:
    owners = row.get("owners") if isinstance(row.get("owners"), list) else []
    names: list[str] = []
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        name = str(owner.get("display_name") or owner.get("principal_name") or "").strip()
        if name:
            names.append(name)
    return names


def _credential_row(
    app_row: dict[str, Any],
    credential: dict[str, Any],
) -> SecurityAppHygieneCredential:
    end_date_time = str(credential.get("end_date_time") or "")
    parsed_end = _parse_datetime(end_date_time)
    days_until_expiry: int | None = None
    status = "unknown"
    now = datetime.now(timezone.utc)
    if parsed_end is not None:
        days_until_expiry = (parsed_end - now).days
        if parsed_end < now:
            status = "expired"
        elif parsed_end <= now + timedelta(days=_EXPIRING_SOON_DAYS):
            status = "expiring"
        else:
            status = "active"

    owner_names = _owner_names(app_row)
    flags: list[str] = []
    if status == "expired":
        flags.append("Credential is already expired.")
    elif status == "expiring":
        flags.append(f"Credential expires within {_EXPIRING_SOON_DAYS} days.")
    if not owner_names and not str(app_row.get("owner_lookup_error") or "").strip():
        flags.append("No application owners are recorded for this app registration.")
    if str(app_row.get("owner_lookup_error") or "").strip():
        flags.append(str(app_row.get("owner_lookup_error") or "").strip())

    return SecurityAppHygieneCredential(
        application_id=str(app_row.get("id") or ""),
        app_id=str(app_row.get("app_id") or ""),
        application_display_name=str(app_row.get("display_name") or ""),
        credential_type=str(credential.get("credential_type") or "secret"),  # type: ignore[arg-type]
        display_name=str(credential.get("display_name") or ""),
        key_id=str(credential.get("key_id") or ""),
        start_date_time=str(credential.get("start_date_time") or ""),
        end_date_time=end_date_time,
        days_until_expiry=days_until_expiry,
        status=status,  # type: ignore[arg-type]
        owner_count=len(owner_names),
        owners=owner_names,
        flags=flags,
    )


def build_security_application_hygiene() -> SecurityAppHygieneResponse:
    status = azure_cache.status()
    directory_last_refresh = _dataset_last_refresh(status, "directory")
    warnings: list[str] = []
    if _dataset_is_stale(directory_last_refresh):
        warnings.append("Azure directory cache data is older than 4 hours, so app owner and credential status may be stale.")

    raw_rows = azure_cache._snapshot("application_security") or []
    if not raw_rows:
        raw_rows = _fallback_application_security_rows()
        if raw_rows:
            warnings.append(
                "Detailed app credential and owner metadata will fill in after the next Azure directory refresh under the upgraded collector."
            )

    flagged_apps: list[SecurityAppHygieneApp] = []
    credential_rows: list[SecurityAppHygieneCredential] = []
    total_credentials = 0
    expiring_soon_credentials = 0
    expired_credentials = 0
    apps_without_owners = 0
    external_audience_apps = 0

    for row in raw_rows:
        owner_names = _owner_names(row)
        owner_lookup_error = str(row.get("owner_lookup_error") or "").strip()
        sign_in_audience = str(row.get("sign_in_audience") or "")
        credentials = row.get("credentials") if isinstance(row.get("credentials"), list) else []
        app_credential_rows = [_credential_row(row, credential) for credential in credentials if isinstance(credential, dict)]

        credential_count = len(app_credential_rows) if app_credential_rows else _int_value(row.get("credential_count"))
        password_credential_count = (
            len([credential for credential in app_credential_rows if credential.credential_type == "secret"])
            if app_credential_rows
            else _int_value(row.get("password_credential_count"))
        )
        key_credential_count = (
            len([credential for credential in app_credential_rows if credential.credential_type == "certificate"])
            if app_credential_rows
            else _int_value(row.get("key_credential_count"))
        )
        app_expired_count = len([credential for credential in app_credential_rows if credential.status == "expired"])
        app_expiring_soon_count = len([credential for credential in app_credential_rows if credential.status == "expiring"])
        app_expiring_warn_count = len(
            [
                credential
                for credential in app_credential_rows
                if credential.days_until_expiry is not None
                and 0 <= credential.days_until_expiry <= _EXPIRING_WARN_DAYS
            ]
        )

        total_credentials += credential_count
        expired_credentials += app_expired_count
        expiring_soon_credentials += app_expiring_soon_count

        flags: list[str] = []
        if app_expired_count:
            flags.append(f"{app_expired_count} credential(s) are already expired.")
        if app_expiring_soon_count:
            flags.append(f"{app_expiring_soon_count} credential(s) expire within {_EXPIRING_SOON_DAYS} days.")
        elif app_expiring_warn_count:
            flags.append(f"{app_expiring_warn_count} credential(s) expire within {_EXPIRING_WARN_DAYS} days.")
        if not owner_names and not owner_lookup_error:
            flags.append("No application owners are recorded.")
            apps_without_owners += 1
        if owner_lookup_error:
            flags.append(owner_lookup_error)
        if sign_in_audience and sign_in_audience not in _INTERNAL_AUDIENCES:
            flags.append("App allows sign-ins outside the home tenant.")
            external_audience_apps += 1
        if sign_in_audience and sign_in_audience not in _INTERNAL_AUDIENCES and not str(row.get("verified_publisher_name") or "").strip():
            flags.append("External audience app is not tied to a verified publisher.")
        if credential_count == 0:
            flags.append("No credentials are currently cached for this app registration.")

        if app_expired_count or ((not owner_names and not owner_lookup_error) and sign_in_audience not in _INTERNAL_AUDIENCES):
            status_value = "critical"
        elif flags:
            status_value = "warning"
        elif credential_count > 0:
            status_value = "healthy"
        else:
            status_value = "info"

        app_row = SecurityAppHygieneApp(
            application_id=str(row.get("id") or ""),
            app_id=str(row.get("app_id") or ""),
            display_name=str(row.get("display_name") or ""),
            sign_in_audience=sign_in_audience,
            created_datetime=str(row.get("created_datetime") or ""),
            publisher_domain=str(row.get("publisher_domain") or ""),
            verified_publisher_name=str(row.get("verified_publisher_name") or ""),
            owner_count=len(owner_names),
            owners=owner_names,
            owner_lookup_error=owner_lookup_error,
            credential_count=credential_count,
            password_credential_count=password_credential_count,
            key_credential_count=key_credential_count,
            next_credential_expiry=str(row.get("next_credential_expiry") or ""),
            expired_credential_count=app_expired_count,
            expiring_30d_count=app_expiring_soon_count,
            expiring_90d_count=app_expiring_warn_count,
            status=status_value,  # type: ignore[arg-type]
            flags=flags,
        )
        if flags:
            flagged_apps.append(app_row)
        credential_rows.extend(app_credential_rows)

    flagged_apps.sort(
        key=lambda item: (
            0 if item.status == "critical" else 1 if item.status == "warning" else 2,
            -item.expired_credential_count,
            -item.expiring_30d_count,
            item.display_name.lower(),
        )
    )
    credential_rows.sort(
        key=lambda item: (
            0 if item.status == "expired" else 1 if item.status == "expiring" else 2 if item.status == "active" else 3,
            item.days_until_expiry if item.days_until_expiry is not None else 99999,
            item.application_display_name.lower(),
        )
    )

    metrics = [
        SecurityAppHygieneMetric(
            key="app_registrations",
            label="App registrations",
            value=len(raw_rows),
            detail="Cached app registrations available for application hygiene review.",
            tone="sky",
        ),
        SecurityAppHygieneMetric(
            key="expired_credentials",
            label="Expired credentials",
            value=expired_credentials,
            detail="Client secrets or certificates that are already past their end date.",
            tone="rose",
        ),
        SecurityAppHygieneMetric(
            key="expiring_soon",
            label="Expiring in 30 days",
            value=expiring_soon_credentials,
            detail="Credentials that need rotation soon to avoid outages or emergency work.",
            tone="amber",
        ),
        SecurityAppHygieneMetric(
            key="apps_without_owners",
            label="Apps without owners",
            value=apps_without_owners,
            detail="Registrations that currently have no owner coverage in the cached directory data.",
            tone="amber",
        ),
        SecurityAppHygieneMetric(
            key="external_audience",
            label="External audience apps",
            value=external_audience_apps,
            detail="App registrations that allow sign-ins beyond the home tenant.",
            tone="slate",
        ),
        SecurityAppHygieneMetric(
            key="total_credentials",
            label="Tracked credentials",
            value=total_credentials,
            detail="Client secrets and certificates observed in the cached app registration dataset.",
            tone="emerald",
        ),
    ]

    scope_notes = [
        "This v1 review uses cached app registration metadata from Microsoft Graph, including password and key credential expiration data.",
        "Owner coverage comes from batched Microsoft Graph owner lookups during the Azure directory refresh.",
        "Enterprise app permission grants and delegated consent review are still separate follow-on security lanes.",
    ]

    return SecurityAppHygieneResponse(
        generated_at=_utc_now(),
        directory_last_refresh=directory_last_refresh,
        metrics=metrics,
        flagged_apps=flagged_apps[:50],
        credentials=credential_rows[:250],
        warnings=warnings,
        scope_notes=scope_notes,
    )
