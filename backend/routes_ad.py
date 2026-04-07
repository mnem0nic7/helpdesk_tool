"""Active Directory management routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import require_admin, require_authenticated_user
import ad_client as ad

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ad")


def _ad_error(exc: ad.ADError) -> HTTPException:
    if isinstance(exc, ad.ADNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status(_session=Depends(require_authenticated_user)) -> dict[str, Any]:
    return ad.get_status()


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------


@router.get("/search")
def global_search(
    q: str = Query(""),
    _session=Depends(require_authenticated_user),
) -> list[dict[str, Any]]:
    try:
        return ad.global_search(q)
    except ad.ADError as exc:
        raise _ad_error(exc)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(
    q: str = Query(""),
    ou: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.search_users(query=q, ou_dn=ou, page=page, limit=limit)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.get("/users/{sam}")
def get_user(
    sam: str,
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.get_user(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


class CreateUserRequest(BaseModel):
    sam: str
    upn: str
    display_name: str
    given_name: str
    surname: str
    ou_dn: str
    password: str | None = None
    email: str = ""
    title: str = ""
    department: str = ""
    description: str = ""


@router.post("/users")
def create_user(
    body: CreateUserRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.create_user(
            sam=body.sam,
            upn=body.upn,
            display_name=body.display_name,
            given_name=body.given_name,
            surname=body.surname,
            ou_dn=body.ou_dn,
            password=body.password,
            email=body.email,
            title=body.title,
            department=body.department,
            description=body.description,
        )
    except ad.ADError as exc:
        raise _ad_error(exc)


class UpdateUserRequest(BaseModel):
    attributes: dict[str, str]


@router.post("/users/{sam}/update")
def update_user(
    sam: str,
    body: UpdateUserRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.update_user(sam, body.attributes)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.post("/users/{sam}/enable")
def enable_user(
    sam: str,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.enable_user(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.post("/users/{sam}/disable")
def disable_user(
    sam: str,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.disable_user(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.post("/users/{sam}/unlock")
def unlock_user(
    sam: str,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.unlock_user(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


class ResetPasswordRequest(BaseModel):
    new_password: str
    must_change: bool = True


@router.post("/users/{sam}/reset-password")
def reset_password(
    sam: str,
    body: ResetPasswordRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        ad.reset_password(sam, body.new_password, must_change=body.must_change)
        return {"ok": True}
    except ad.ADError as exc:
        raise _ad_error(exc)


class MoveRequest(BaseModel):
    new_ou_dn: str


@router.post("/users/{sam}/move")
def move_user(
    sam: str,
    body: MoveRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        user = ad.get_user(sam)
        ad.move_object(user["dn"], body.new_ou_dn)
        return ad.get_user(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.delete("/users/{sam}")
def delete_user(
    sam: str,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        user = ad.get_user(sam)
        ad.delete_object(user["dn"])
        return {"deleted": True, "dn": user["dn"]}
    except ad.ADError as exc:
        raise _ad_error(exc)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@router.get("/groups")
def list_groups(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.search_groups(query=q, page=page, limit=limit)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.get("/groups/{sam}")
def get_group(
    sam: str,
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.get_group(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


class CreateGroupRequest(BaseModel):
    name: str
    sam: str
    ou_dn: str
    group_type: int = -2147483646  # Global Security
    description: str = ""
    email: str = ""


@router.post("/groups")
def create_group(
    body: CreateGroupRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.create_group(
            name=body.name,
            sam=body.sam,
            ou_dn=body.ou_dn,
            group_type=body.group_type,
            description=body.description,
            email=body.email,
        )
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.delete("/groups/{sam}")
def delete_group(
    sam: str,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        group = ad.get_group(sam)
        ad.delete_object(group["dn"])
        return {"deleted": True, "dn": group["dn"]}
    except ad.ADError as exc:
        raise _ad_error(exc)


class MemberRequest(BaseModel):
    member_dn: str


@router.post("/groups/{sam}/members")
def add_member(
    sam: str,
    body: MemberRequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        ad.add_group_member(sam, body.member_dn)
        return ad.get_group(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.delete("/groups/{sam}/members")
def remove_member(
    sam: str,
    member_dn: str = Query(...),
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        ad.remove_group_member(sam, member_dn)
        return ad.get_group(sam)
    except ad.ADError as exc:
        raise _ad_error(exc)


# ---------------------------------------------------------------------------
# Computers
# ---------------------------------------------------------------------------


@router.get("/computers")
def list_computers(
    q: str = Query(""),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.search_computers(query=q, page=page, limit=limit)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.get("/computers/{cn}")
def get_computer(
    cn: str,
    _session=Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        return ad.get_computer(cn)
    except ad.ADError as exc:
        raise _ad_error(exc)


# ---------------------------------------------------------------------------
# Organizational Units
# ---------------------------------------------------------------------------


@router.get("/ous")
def list_ous(
    base_dn: str = Query(""),
    _session=Depends(require_authenticated_user),
) -> list[dict[str, Any]]:
    try:
        return ad.list_ous(base_dn)
    except ad.ADError as exc:
        raise _ad_error(exc)


class CreateOURequest(BaseModel):
    name: str
    parent_dn: str
    description: str = ""


@router.post("/ous")
def create_ou(
    body: CreateOURequest,
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        return ad.create_ou(body.name, body.parent_dn, body.description)
    except ad.ADError as exc:
        raise _ad_error(exc)


@router.delete("/ous")
def delete_ou(
    dn: str = Query(...),
    _session=Depends(require_admin),
) -> dict[str, Any]:
    try:
        ad.delete_object(dn)
        return {"deleted": True, "dn": dn}
    except ad.ADError as exc:
        raise _ad_error(exc)
