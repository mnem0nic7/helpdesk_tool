"""Grant MDE Red Canary parity app roles to our service principal.

Permissions needed:
  - Machine.StopAndQuarantine  (stop_and_quarantine_file)
  - Machine.Investigate        (start_investigation)
  - Ti.ReadWrite.All           (create/list/delete indicators)

These are application permissions on the WindowsDefenderATP resource SP.
Run once: python scripts/grant_mde_rcanary_permissions.py
"""
from __future__ import annotations

import sys
import os

# Add backend to path so we can reuse azure_client token machinery
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from config import ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_TENANT_ID

# WindowsDefenderATP resource SP (tenant-object-id, not app-id)
_DEFENDER_ATP_SP_ID = "4ab205bd-e547-43ee-b69b-0572f8fcdb29"

_TARGET_ROLES = {
    "Machine.StopAndQuarantine",  # stop_and_quarantine_file
    "Ti.ReadWrite.All",           # create/list/delete indicators
    # NOTE: StartInvestigation requires Machine.ReadWrite.All — grant separately if desired
    # Machine.ReadWrite.All is a superset; grant it consciously from the Entra portal.
}


def get_token() -> str:
    resp = requests.post(
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": ENTRA_CLIENT_ID,
            "client_secret": ENTRA_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def graph_get(token: str, path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"https://graph.microsoft.com/v1.0/{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[return-value]


def graph_post(token: str, path: str, body: dict) -> dict:
    resp = requests.post(
        f"https://graph.microsoft.com/v1.0/{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    if resp.status_code == 409:
        print(f"  [already exists] {path}")
        return {}
    resp.raise_for_status()
    return resp.json()  # type: ignore[return-value]


def main() -> None:
    if not ENTRA_TENANT_ID or not ENTRA_CLIENT_ID or not ENTRA_CLIENT_SECRET:
        print("ERROR: ENTRA_TENANT_ID / ENTRA_CLIENT_ID / ENTRA_CLIENT_SECRET not set")
        sys.exit(1)

    token = get_token()
    print("Token acquired.")

    # 1. Find our app's service principal
    our_sp_resp = graph_get(token, f"servicePrincipals", {"$filter": f"appId eq '{ENTRA_CLIENT_ID}'"})
    our_sp_list = our_sp_resp.get("value", [])
    if not our_sp_list:
        print(f"ERROR: Could not find SP for appId {ENTRA_CLIENT_ID}")
        sys.exit(1)
    our_sp_id = our_sp_list[0]["id"]
    print(f"Our SP: {our_sp_id}")

    # 2. Fetch WindowsDefenderATP SP app roles
    atp_sp = graph_get(token, f"servicePrincipals/{_DEFENDER_ATP_SP_ID}")
    app_roles = atp_sp.get("appRoles", [])
    role_map = {r["value"]: r["id"] for r in app_roles}
    print(f"WindowsDefenderATP SP: {atp_sp.get('displayName')}")
    print(f"Available app roles: {list(role_map.keys())[:20]}")

    # 3. Check which target roles exist
    missing: list[str] = []
    for role_name in _TARGET_ROLES:
        if role_name not in role_map:
            missing.append(role_name)
    if missing:
        print(f"\nWARNING: These roles not found in WindowsDefenderATP appRoles: {missing}")
        print("Available roles:")
        for name, guid in sorted(role_map.items()):
            print(f"  {name}: {guid}")
        sys.exit(1)

    # 4. Get existing assignments to skip duplicates
    existing_resp = graph_get(token, f"servicePrincipals/{our_sp_id}/appRoleAssignments")
    existing_role_ids = {a["appRoleId"] for a in existing_resp.get("value", [])}

    # 5. Grant each missing role
    granted = 0
    skipped = 0
    for role_name in sorted(_TARGET_ROLES):
        role_id = role_map[role_name]
        if role_id in existing_role_ids:
            print(f"  [skip] {role_name} — already assigned")
            skipped += 1
            continue
        print(f"  [grant] {role_name} ({role_id})...")
        result = graph_post(token, f"servicePrincipals/{our_sp_id}/appRoleAssignments", {
            "principalId": our_sp_id,
            "resourceId": _DEFENDER_ATP_SP_ID,
            "appRoleId": role_id,
        })
        if result:
            print(f"    OK: assignment id {result.get('id')}")
        granted += 1

    print(f"\nDone. Granted {granted} new permission(s), {skipped} already existed.")
    print("Note: App role assignments take effect immediately for client_credentials flows.")


if __name__ == "__main__":
    main()
