"""On-premises Active Directory client using ldap3.

All operations create a new connection per call — appropriate for a low-throughput
admin tool and avoids thread-safety concerns with shared connections.

Password-related operations (create_user with password, reset_password) require
LDAPS (SSL) or StartTLS; they will raise ADError if SSL is not configured.
"""

from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Any

import ldap3
from ldap3 import (
    ALL_ATTRIBUTES,
    BASE,
    Connection,
    MODIFY_REPLACE,
    MODIFY_ADD,
    MODIFY_DELETE,
    Server,
    SUBTREE,
    NTLM,
    SIMPLE,
    Tls,
)
from ldap3.core.exceptions import LDAPException

from config import AD_BASE_DN, AD_BIND_DN, AD_BIND_PASSWORD, AD_PORT, AD_SERVER, AD_USE_SSL, DISABLED_USERS_OU_DN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UAC_NORMAL = 0x200        # 512  – normal account
_UAC_DISABLE = 0x2         # 2    – account disabled bit
_UAC_LOCKOUT = 0x10        # 16   – lockout bit
_UAC_PWD_NOT_REQ = 0x20    # 32
_UAC_NO_EXPIRE = 0x10000   # 65536 – password never expires

_USER_ATTRS = [
    "sAMAccountName", "userPrincipalName", "displayName", "givenName", "sn",
    "mail", "telephoneNumber", "mobile", "department", "title", "manager",
    "description", "streetAddress", "l", "st", "postalCode", "co",
    "userAccountControl", "accountExpires", "pwdLastSet", "lastLogonTimestamp",
    "lockoutTime", "badPwdCount", "distinguishedName", "objectGUID",
    "whenCreated", "whenChanged", "memberOf", "employeeID", "company",
]

_GROUP_ATTRS = [
    "sAMAccountName", "cn", "distinguishedName", "description", "groupType",
    "mail", "whenCreated", "whenChanged", "memberOf", "objectGUID",
]

_COMPUTER_ATTRS = [
    "cn", "dNSHostName", "distinguishedName", "operatingSystem",
    "operatingSystemVersion", "lastLogonTimestamp", "whenCreated",
    "userAccountControl", "description", "objectGUID", "managedBy",
]

_OU_ATTRS = ["ou", "distinguishedName", "description", "whenCreated"]

_GROUP_SCOPE_MAP = {
    2: "Global",
    4: "Domain Local",
    8: "Universal",
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ADError(Exception):
    """Raised for expected AD operation failures."""


class ADNotConfigured(ADError):
    """Raised when AD connection settings are missing."""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def ad_configured() -> bool:
    return bool(AD_SERVER and AD_BASE_DN and AD_BIND_DN and AD_BIND_PASSWORD)


def _resolve_port() -> int:
    if AD_PORT:
        return AD_PORT
    return 636 if AD_USE_SSL else 389


def _parse_server_host() -> str:
    """Strip ldap:// or ldaps:// scheme from AD_SERVER — ldap3 takes a plain hostname."""
    host = AD_SERVER
    for prefix in ("ldaps://", "ldap://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix):]
            break
    return host.rstrip("/")


def _get_connection() -> Connection:
    if not ad_configured():
        raise ADNotConfigured(
            "Active Directory is not configured. Set AD_SERVER, AD_BASE_DN, "
            "AD_BIND_DN, and AD_BIND_PASSWORD environment variables."
        )
    port = _resolve_port()
    tls = Tls(validate=0) if AD_USE_SSL else None  # validate=0 = ssl.CERT_NONE for self-signed certs
    server = Server(_parse_server_host(), port=port, use_ssl=AD_USE_SSL, tls=tls, get_info=ldap3.NONE)
    conn = Connection(
        server,
        user=AD_BIND_DN,
        password=AD_BIND_PASSWORD,
        authentication=SIMPLE,
        auto_bind=True,
        receive_timeout=15,
    )
    return conn


# ---------------------------------------------------------------------------
# Value converters
# ---------------------------------------------------------------------------


def _ad_ts_to_iso(raw: Any) -> str | None:
    """Convert AD's 100-nanosecond intervals since 1601-01-01 to ISO string."""
    if raw is None:
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    if val in (0, 0x7FFFFFFFFFFFFFFF):
        return None
    # Convert Windows FILETIME to Unix timestamp
    unix_ts = (val - 116444736000000000) / 10_000_000
    try:
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _ad_date_to_iso(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc).isoformat()
    return str(raw)


def _first(val: Any) -> Any:
    if isinstance(val, (list, tuple)):
        return val[0] if val else None
    return val


def _uac_flags(uac: int) -> dict[str, bool]:
    return {
        "enabled": not bool(uac & _UAC_DISABLE),
        "locked": bool(uac & _UAC_LOCKOUT),
        "password_never_expires": bool(uac & _UAC_NO_EXPIRE),
        "password_not_required": bool(uac & _UAC_PWD_NOT_REQ),
    }


def _group_scope_label(group_type: int) -> str:
    # groupType is a signed 32-bit integer; the low bits encode scope
    scope_bits = abs(group_type) & 0xF if group_type else 0
    security = bool(group_type < 0) if group_type else False
    scope = _GROUP_SCOPE_MAP.get(scope_bits, "Unknown")
    kind = "Security" if security else "Distribution"
    return f"{scope} {kind}"


def _entry_to_user(entry: ldap3.Entry) -> dict[str, Any]:
    attrs = entry.entry_attributes_as_dict
    uac = int(_first(attrs.get("userAccountControl") or [512]) or 512)
    return {
        "dn": str(entry.entry_dn),
        "sam_account_name": str(_first(attrs.get("sAMAccountName")) or ""),
        "upn": str(_first(attrs.get("userPrincipalName")) or ""),
        "display_name": str(_first(attrs.get("displayName")) or ""),
        "given_name": str(_first(attrs.get("givenName")) or ""),
        "surname": str(_first(attrs.get("sn")) or ""),
        "email": str(_first(attrs.get("mail")) or ""),
        "phone": str(_first(attrs.get("telephoneNumber")) or ""),
        "mobile": str(_first(attrs.get("mobile")) or ""),
        "department": str(_first(attrs.get("department")) or ""),
        "title": str(_first(attrs.get("title")) or ""),
        "manager_dn": str(_first(attrs.get("manager")) or ""),
        "description": str(_first(attrs.get("description")) or ""),
        "street": str(_first(attrs.get("streetAddress")) or ""),
        "city": str(_first(attrs.get("l")) or ""),
        "state": str(_first(attrs.get("st")) or ""),
        "postal_code": str(_first(attrs.get("postalCode")) or ""),
        "country": str(_first(attrs.get("co")) or ""),
        "company": str(_first(attrs.get("company")) or ""),
        "employee_id": str(_first(attrs.get("employeeID")) or ""),
        "user_account_control": uac,
        "flags": _uac_flags(uac),
        "last_logon": _ad_ts_to_iso(_first(attrs.get("lastLogonTimestamp"))),
        "pwd_last_set": _ad_ts_to_iso(_first(attrs.get("pwdLastSet"))),
        "account_expires": _ad_ts_to_iso(_first(attrs.get("accountExpires"))),
        "lockout_time": _ad_ts_to_iso(_first(attrs.get("lockoutTime"))),
        "bad_pwd_count": int(_first(attrs.get("badPwdCount") or [0]) or 0),
        "when_created": _ad_date_to_iso(_first(attrs.get("whenCreated"))),
        "when_changed": _ad_date_to_iso(_first(attrs.get("whenChanged"))),
        "member_of": [str(g) for g in (attrs.get("memberOf") or [])],
    }


def _entry_to_group(entry: ldap3.Entry) -> dict[str, Any]:
    attrs = entry.entry_attributes_as_dict
    gt = int(_first(attrs.get("groupType") or [0]) or 0)
    return {
        "dn": str(entry.entry_dn),
        "sam_account_name": str(_first(attrs.get("sAMAccountName")) or ""),
        "cn": str(_first(attrs.get("cn")) or ""),
        "description": str(_first(attrs.get("description")) or ""),
        "email": str(_first(attrs.get("mail")) or ""),
        "group_type_raw": gt,
        "group_type_label": _group_scope_label(gt),
        "member_of": [str(g) for g in (attrs.get("memberOf") or [])],
        "when_created": _ad_date_to_iso(_first(attrs.get("whenCreated"))),
        "when_changed": _ad_date_to_iso(_first(attrs.get("whenChanged"))),
    }


def _entry_to_computer(entry: ldap3.Entry) -> dict[str, Any]:
    attrs = entry.entry_attributes_as_dict
    uac = int(_first(attrs.get("userAccountControl") or [4096]) or 4096)
    return {
        "dn": str(entry.entry_dn),
        "cn": str(_first(attrs.get("cn")) or ""),
        "dns_hostname": str(_first(attrs.get("dNSHostName")) or ""),
        "os": str(_first(attrs.get("operatingSystem")) or ""),
        "os_version": str(_first(attrs.get("operatingSystemVersion")) or ""),
        "description": str(_first(attrs.get("description")) or ""),
        "managed_by": str(_first(attrs.get("managedBy")) or ""),
        "enabled": not bool(uac & _UAC_DISABLE),
        "last_logon": _ad_ts_to_iso(_first(attrs.get("lastLogonTimestamp"))),
        "when_created": _ad_date_to_iso(_first(attrs.get("whenCreated"))),
    }


def _entry_to_ou(entry: ldap3.Entry) -> dict[str, Any]:
    attrs = entry.entry_attributes_as_dict
    return {
        "dn": str(entry.entry_dn),
        "ou": str(_first(attrs.get("ou")) or ""),
        "description": str(_first(attrs.get("description")) or ""),
        "when_created": _ad_date_to_iso(_first(attrs.get("whenCreated"))),
    }


def _encode_password(password: str) -> bytes:
    """Encode a password for the unicodePwd attribute."""
    return ('"' + password + '"').encode("utf-16-le")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def get_status() -> dict[str, Any]:
    if not ad_configured():
        return {"configured": False, "connected": False, "server": "", "base_dn": ""}
    try:
        conn = _get_connection()
        conn.unbind()
        return {
            "configured": True,
            "connected": True,
            "server": _parse_server_host(),
            "base_dn": AD_BASE_DN,
            "ssl": AD_USE_SSL,
            "port": _resolve_port(),
        }
    except Exception as exc:
        return {
            "configured": True,
            "connected": False,
            "server": _parse_server_host(),
            "base_dn": AD_BASE_DN,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def search_users(query: str = "", ou_dn: str = "", page: int = 1, limit: int = 50) -> dict[str, Any]:
    base = ou_dn or AD_BASE_DN
    if query:
        escaped = ldap3.utils.conv.escape_filter_chars(query)
        search_filter = (
            f"(&(objectClass=user)(objectCategory=person)"
            f"(|(sAMAccountName=*{escaped}*)(displayName=*{escaped}*)"
            f"(mail=*{escaped}*)(userPrincipalName=*{escaped}*)))"
        )
    else:
        search_filter = "(&(objectClass=user)(objectCategory=person))"
    conn = _get_connection()
    try:
        conn.search(
            search_base=base,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=_USER_ATTRS,
            paged_size=1000,
        )
        entries = conn.entries[:]
    except LDAPException as exc:
        raise ADError(f"User search failed: {exc}") from exc
    finally:
        conn.unbind()

    users = [_entry_to_user(e) for e in entries]
    users.sort(key=lambda u: u["display_name"].lower() or u["sam_account_name"].lower())
    total = len(users)
    start = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "items": users[start: start + limit]}


def get_user(sam: str) -> dict[str, Any]:
    escaped = ldap3.utils.conv.escape_filter_chars(sam)
    search_filter = f"(&(objectClass=user)(objectCategory=person)(sAMAccountName={escaped}))"
    conn = _get_connection()
    try:
        conn.search(AD_BASE_DN, search_filter, SUBTREE, attributes=_USER_ATTRS + ["member"])
        if not conn.entries:
            raise ADError(f"User '{sam}' not found")
        return _entry_to_user(conn.entries[0])
    except LDAPException as exc:
        raise ADError(f"Get user failed: {exc}") from exc
    finally:
        conn.unbind()


def create_user(
    *,
    sam: str,
    upn: str,
    display_name: str,
    given_name: str,
    surname: str,
    ou_dn: str,
    password: str | None = None,
    email: str = "",
    title: str = "",
    department: str = "",
    description: str = "",
) -> dict[str, Any]:
    if not AD_USE_SSL and password:
        raise ADError("Password can only be set over LDAPS (SSL). Set AD_USE_SSL=true.")
    user_dn = f"CN={display_name},{ou_dn}"
    attrs: dict[str, Any] = {
        "objectClass": ["top", "person", "organizationalPerson", "user"],
        "sAMAccountName": sam,
        "userPrincipalName": upn,
        "displayName": display_name,
        "givenName": given_name,
        "sn": surname,
        "userAccountControl": str(_UAC_NORMAL | _UAC_DISABLE),  # create disabled until password set
    }
    if email:
        attrs["mail"] = email
    if title:
        attrs["title"] = title
    if department:
        attrs["department"] = department
    if description:
        attrs["description"] = description

    conn = _get_connection()
    try:
        ok = conn.add(user_dn, attributes=attrs)
        if not ok:
            raise ADError(f"Create user failed: {conn.result.get('description', conn.result)}")

        if password:
            conn.modify(user_dn, {"unicodePwd": [(MODIFY_REPLACE, [_encode_password(password)])]})
            if not conn.result["result"] == 0:
                raise ADError(f"Set password failed: {conn.result.get('description', conn.result)}")
            # Enable the account now that the password is set
            conn.modify(user_dn, {"userAccountControl": [(MODIFY_REPLACE, [str(_UAC_NORMAL)])]})

        return get_user(sam)
    except LDAPException as exc:
        raise ADError(f"Create user failed: {exc}") from exc
    finally:
        conn.unbind()


def update_user(sam: str, attributes: dict[str, str]) -> dict[str, Any]:
    """Update simple string attributes on a user. Not for password/UAC changes."""
    _allowed = {
        "displayName", "givenName", "sn", "mail", "telephoneNumber", "mobile",
        "department", "title", "description", "streetAddress", "l", "st",
        "postalCode", "co", "company", "employeeID", "manager",
    }
    changes: dict[str, list] = {}
    for attr, value in attributes.items():
        if attr not in _allowed:
            continue
        if value:
            changes[attr] = [(MODIFY_REPLACE, [value])]
        else:
            changes[attr] = [(MODIFY_REPLACE, [])]

    if not changes:
        return get_user(sam)

    user = get_user(sam)
    conn = _get_connection()
    try:
        conn.modify(user["dn"], changes)
        if conn.result["result"] != 0:
            raise ADError(f"Update failed: {conn.result.get('description', conn.result)}")
        return get_user(sam)
    except LDAPException as exc:
        raise ADError(f"Update user failed: {exc}") from exc
    finally:
        conn.unbind()


def enable_user(sam: str) -> dict[str, Any]:
    user = get_user(sam)
    uac = user["user_account_control"] & ~_UAC_DISABLE
    conn = _get_connection()
    try:
        conn.modify(user["dn"], {"userAccountControl": [(MODIFY_REPLACE, [str(uac)])]})
        if conn.result["result"] != 0:
            raise ADError(f"Enable failed: {conn.result.get('description', conn.result)}")
        return get_user(sam)
    except LDAPException as exc:
        raise ADError(f"Enable user failed: {exc}") from exc
    finally:
        conn.unbind()


def disable_user(sam: str) -> dict[str, Any]:
    user = get_user(sam)
    uac = user["user_account_control"] | _UAC_DISABLE
    conn = _get_connection()
    try:
        conn.modify(user["dn"], {"userAccountControl": [(MODIFY_REPLACE, [str(uac)])]})
        if conn.result["result"] != 0:
            raise ADError(f"Disable failed: {conn.result.get('description', conn.result)}")
        return get_user(sam)
    except LDAPException as exc:
        raise ADError(f"Disable user failed: {exc}") from exc
    finally:
        conn.unbind()


def unlock_user(sam: str) -> dict[str, Any]:
    user = get_user(sam)
    conn = _get_connection()
    try:
        conn.modify(user["dn"], {"lockoutTime": [(MODIFY_REPLACE, ["0"])]})
        if conn.result["result"] != 0:
            raise ADError(f"Unlock failed: {conn.result.get('description', conn.result)}")
        return get_user(sam)
    except LDAPException as exc:
        raise ADError(f"Unlock user failed: {exc}") from exc
    finally:
        conn.unbind()


def reset_password(sam: str, new_password: str, must_change: bool = True) -> None:
    if not AD_USE_SSL:
        raise ADError("Password reset requires LDAPS (SSL). Set AD_USE_SSL=true.")
    user = get_user(sam)
    conn = _get_connection()
    try:
        changes: dict[str, list] = {
            "unicodePwd": [(MODIFY_REPLACE, [_encode_password(new_password)])],
        }
        if must_change:
            changes["pwdLastSet"] = [(MODIFY_REPLACE, ["0"])]
        conn.modify(user["dn"], changes)
        if conn.result["result"] != 0:
            raise ADError(f"Password reset failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Reset password failed: {exc}") from exc
    finally:
        conn.unbind()


def delete_object(dn: str) -> None:
    conn = _get_connection()
    try:
        conn.delete(dn)
        if conn.result["result"] != 0:
            raise ADError(f"Delete failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Delete failed: {exc}") from exc
    finally:
        conn.unbind()


def move_object(dn: str, new_ou_dn: str) -> None:
    """Move an AD object to a different OU."""
    # The relative distinguished name is the first component of the current DN
    rdn = dn.split(",")[0]
    conn = _get_connection()
    try:
        conn.modify_dn(dn, rdn, new_superior=new_ou_dn)
        if conn.result["result"] != 0:
            raise ADError(f"Move failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Move failed: {exc}") from exc
    finally:
        conn.unbind()


def _group_sam_from_dn(group_dn: str) -> str:
    """Look up sAMAccountName for a group DN. Returns empty string if not found."""
    conn = _get_connection()
    try:
        conn.search(group_dn, "(objectClass=group)", BASE, attributes=["sAMAccountName"])
        if conn.entries:
            attrs = conn.entries[0].entry_attributes_as_dict
            values = attrs.get("sAMAccountName") or []
            if values:
                return str(values[0])
        return ""
    except LDAPException:
        return ""
    finally:
        conn.unbind()


def remove_from_all_groups_except_domain_users(sam: str) -> dict[str, list[str]]:
    """Remove user from all groups except Domain Users. Returns removed/skipped/failures."""
    user = get_user(sam)
    member_of: list[str] = user.get("member_of") or []
    user_dn: str = user["dn"]

    removed: list[str] = []
    skipped: list[str] = []
    failures: list[str] = []

    for group_dn in member_of:
        if group_dn.lower().startswith("cn=domain users,"):
            skipped.append("Domain Users")
            continue

        group_cn = group_dn.split(",")[0].removeprefix("CN=")
        group_sam = _group_sam_from_dn(group_dn)
        if not group_sam:
            failures.append(group_dn)
            continue

        try:
            remove_group_member(group_sam, user_dn)
            removed.append(group_cn)
        except ADError as exc:
            failures.append(f"{group_cn}: {exc}")

    return {"removed": removed, "skipped": skipped, "failures": failures}


def update_termination_attributes(sam: str) -> dict[str, str]:
    """Apply termination attributes: clear phone/manager/dept, stamp disable markers."""
    user = get_user(sam)
    conn = _get_connection()
    try:
        termination_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        changes = {
            "telephoneNumber": [(MODIFY_REPLACE, [])],
            "mailNickname": [(MODIFY_REPLACE, [sam])],
            "physicalDeliveryOfficeName": [(MODIFY_REPLACE, ["DISABLED"])],
            "msExchAssistantName": [(MODIFY_REPLACE, ["HideFromGAL"])],
            "terminationDate": [(MODIFY_REPLACE, [termination_date])],
            "msExchHideFromAddressLists": [(MODIFY_REPLACE, ["TRUE"])],
            "msDS-cloudExtensionAttribute1": [(MODIFY_REPLACE, [])],
            "manager": [(MODIFY_REPLACE, [])],
            "department": [(MODIFY_REPLACE, [])],
        }
        conn.modify(user["dn"], changes)
        if conn.result["result"] != 0:
            raise ADError(f"Termination attributes update failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Termination attributes update failed: {exc}") from exc
    finally:
        conn.unbind()

    return {
        "telephoneNumber": "",
        "mailNickname": sam,
        "physicalDeliveryOfficeName": "DISABLED",
        "msExchAssistantName": "HideFromGAL",
        "terminationDate": termination_date,
        "msExchHideFromAddressLists": "TRUE",
        "msDS-cloudExtensionAttribute1": "",
        "manager": "",
        "department": "",
    }


def move_to_disabled_users_ou(sam: str) -> str:
    """Move user to the DISABLED_USERS_OU_DN. Returns the new DN."""
    if not DISABLED_USERS_OU_DN:
        raise ADError("DISABLED_USERS_OU_DN is not configured")
    user = get_user(sam)
    move_object(user["dn"], DISABLED_USERS_OU_DN)
    return user["dn"].split(",")[0] + "," + DISABLED_USERS_OU_DN


def reset_password_random(sam: str) -> str:
    """Reset AD password to a 20-char random complex password. Returns the generated password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    random_pw = "".join(secrets.choice(alphabet) for _ in range(20))
    # Ensure complexity: uppercase, lowercase, digit, special
    random_pw = (
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%^&*")
        + random_pw[4:]
    )
    reset_password(sam, random_pw, must_change=False)
    return random_pw


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def search_groups(query: str = "", page: int = 1, limit: int = 50) -> dict[str, Any]:
    if query:
        escaped = ldap3.utils.conv.escape_filter_chars(query)
        search_filter = (
            f"(&(objectClass=group)"
            f"(|(sAMAccountName=*{escaped}*)(cn=*{escaped}*)(mail=*{escaped}*)))"
        )
    else:
        search_filter = "(objectClass=group)"
    conn = _get_connection()
    try:
        conn.search(AD_BASE_DN, search_filter, SUBTREE, attributes=_GROUP_ATTRS)
        entries = conn.entries[:]
    except LDAPException as exc:
        raise ADError(f"Group search failed: {exc}") from exc
    finally:
        conn.unbind()

    groups = [_entry_to_group(e) for e in entries]
    groups.sort(key=lambda g: g["cn"].lower())
    total = len(groups)
    start = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "items": groups[start: start + limit]}


def get_group(sam: str) -> dict[str, Any]:
    escaped = ldap3.utils.conv.escape_filter_chars(sam)
    conn = _get_connection()
    try:
        conn.search(
            AD_BASE_DN,
            f"(&(objectClass=group)(sAMAccountName={escaped}))",
            SUBTREE,
            attributes=_GROUP_ATTRS + ["member"],
        )
        if not conn.entries:
            raise ADError(f"Group '{sam}' not found")
        entry = conn.entries[0]
        result = _entry_to_group(entry)
        attrs = entry.entry_attributes_as_dict
        result["members"] = [str(m) for m in (attrs.get("member") or [])]
        return result
    except LDAPException as exc:
        raise ADError(f"Get group failed: {exc}") from exc
    finally:
        conn.unbind()


def create_group(
    *,
    name: str,
    sam: str,
    ou_dn: str,
    group_type: int = -2147483646,  # Global Security by default
    description: str = "",
    email: str = "",
) -> dict[str, Any]:
    dn = f"CN={name},{ou_dn}"
    attrs: dict[str, Any] = {
        "objectClass": ["top", "group"],
        "cn": name,
        "sAMAccountName": sam,
        "groupType": str(group_type),
    }
    if description:
        attrs["description"] = description
    if email:
        attrs["mail"] = email
    conn = _get_connection()
    try:
        ok = conn.add(dn, attributes=attrs)
        if not ok:
            raise ADError(f"Create group failed: {conn.result.get('description', conn.result)}")
        return get_group(sam)
    except LDAPException as exc:
        raise ADError(f"Create group failed: {exc}") from exc
    finally:
        conn.unbind()


def add_group_member(group_sam: str, member_dn: str) -> None:
    group = get_group(group_sam)
    conn = _get_connection()
    try:
        conn.modify(group["dn"], {"member": [(MODIFY_ADD, [member_dn])]})
        if conn.result["result"] != 0:
            raise ADError(f"Add member failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Add group member failed: {exc}") from exc
    finally:
        conn.unbind()


def remove_group_member(group_sam: str, member_dn: str) -> None:
    group = get_group(group_sam)
    conn = _get_connection()
    try:
        conn.modify(group["dn"], {"member": [(MODIFY_DELETE, [member_dn])]})
        if conn.result["result"] != 0:
            raise ADError(f"Remove member failed: {conn.result.get('description', conn.result)}")
    except LDAPException as exc:
        raise ADError(f"Remove group member failed: {exc}") from exc
    finally:
        conn.unbind()


# ---------------------------------------------------------------------------
# Computers
# ---------------------------------------------------------------------------


def search_computers(query: str = "", page: int = 1, limit: int = 50) -> dict[str, Any]:
    if query:
        escaped = ldap3.utils.conv.escape_filter_chars(query)
        search_filter = (
            f"(&(objectClass=computer)"
            f"(|(cn=*{escaped}*)(dNSHostName=*{escaped}*)(description=*{escaped}*)))"
        )
    else:
        search_filter = "(objectClass=computer)"
    conn = _get_connection()
    try:
        conn.search(AD_BASE_DN, search_filter, SUBTREE, attributes=_COMPUTER_ATTRS)
        entries = conn.entries[:]
    except LDAPException as exc:
        raise ADError(f"Computer search failed: {exc}") from exc
    finally:
        conn.unbind()

    computers = [_entry_to_computer(e) for e in entries]
    computers.sort(key=lambda c: c["cn"].lower())
    total = len(computers)
    start = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "items": computers[start: start + limit]}


def get_computer(cn_name: str) -> dict[str, Any]:
    escaped = ldap3.utils.conv.escape_filter_chars(cn_name)
    conn = _get_connection()
    try:
        conn.search(
            AD_BASE_DN,
            f"(&(objectClass=computer)(cn={escaped}))",
            SUBTREE,
            attributes=_COMPUTER_ATTRS,
        )
        if not conn.entries:
            raise ADError(f"Computer '{cn_name}' not found")
        return _entry_to_computer(conn.entries[0])
    except LDAPException as exc:
        raise ADError(f"Get computer failed: {exc}") from exc
    finally:
        conn.unbind()


# ---------------------------------------------------------------------------
# Organizational Units
# ---------------------------------------------------------------------------


def list_ous(base_dn: str = "") -> list[dict[str, Any]]:
    base = base_dn or AD_BASE_DN
    conn = _get_connection()
    try:
        conn.search(base, "(objectClass=organizationalUnit)", SUBTREE, attributes=_OU_ATTRS)
        entries = conn.entries[:]
    except LDAPException as exc:
        raise ADError(f"OU list failed: {exc}") from exc
    finally:
        conn.unbind()

    ous = [_entry_to_ou(e) for e in entries]
    ous.sort(key=lambda o: o["dn"])
    return ous


def create_ou(name: str, parent_dn: str, description: str = "") -> dict[str, Any]:
    dn = f"OU={name},{parent_dn}"
    attrs: dict[str, Any] = {"objectClass": ["top", "organizationalUnit"], "ou": name}
    if description:
        attrs["description"] = description
    conn = _get_connection()
    try:
        ok = conn.add(dn, attributes=attrs)
        if not ok:
            raise ADError(f"Create OU failed: {conn.result.get('description', conn.result)}")
        return {"dn": dn, "ou": name, "description": description, "when_created": None}
    except LDAPException as exc:
        raise ADError(f"Create OU failed: {exc}") from exc
    finally:
        conn.unbind()


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------


def global_search(query: str, limit: int = 30) -> list[dict[str, Any]]:
    if not query or len(query) < 2:
        return []
    escaped = ldap3.utils.conv.escape_filter_chars(query)
    search_filter = (
        f"(|(sAMAccountName=*{escaped}*)(displayName=*{escaped}*)"
        f"(cn=*{escaped}*)(mail=*{escaped}*))"
    )
    conn = _get_connection()
    try:
        conn.search(
            AD_BASE_DN,
            search_filter,
            SUBTREE,
            attributes=["objectClass", "sAMAccountName", "displayName", "cn", "mail",
                        "distinguishedName", "userAccountControl"],
            paged_size=limit,
        )
        entries = conn.entries[:limit]
    except LDAPException as exc:
        raise ADError(f"Global search failed: {exc}") from exc
    finally:
        conn.unbind()

    results = []
    for entry in entries:
        attrs = entry.entry_attributes_as_dict
        classes = [str(c).lower() for c in (attrs.get("objectClass") or [])]
        if "computer" in classes:
            kind = "computer"
            label = str(_first(attrs.get("cn")) or "")
        elif "group" in classes:
            kind = "group"
            label = str(_first(attrs.get("cn")) or "")
        elif "person" in classes or "user" in classes:
            kind = "user"
            label = str(_first(attrs.get("displayName")) or _first(attrs.get("sAMAccountName")) or "")
        elif "organizationalunit" in classes:
            kind = "ou"
            label = str(_first(attrs.get("cn")) or "")
        else:
            continue
        results.append({
            "kind": kind,
            "label": label,
            "sam": str(_first(attrs.get("sAMAccountName")) or ""),
            "dn": str(entry.entry_dn),
            "email": str(_first(attrs.get("mail")) or ""),
        })
    return results
