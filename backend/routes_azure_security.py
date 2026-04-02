"""Azure security workspace routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import require_authenticated_user
from models import (
    SecurityAccessReviewResponse,
    SecurityAppHygieneResponse,
    SecurityBreakGlassValidationResponse,
    SecurityDirectoryRoleReviewResponse,
)
from security_application_hygiene import build_security_application_hygiene
from security_access_review import build_security_access_review
from security_break_glass_validation import build_security_break_glass_validation
from security_directory_role_review import build_security_directory_role_review
from site_context import get_current_site_scope

router = APIRouter(prefix="/api/azure/security")


def _ensure_azure_site() -> None:
    if get_current_site_scope() != "azure":
        raise HTTPException(
            status_code=404,
            detail="Azure security APIs are only available on azure.movedocs.com",
        )


@router.get("/access-review", response_model=SecurityAccessReviewResponse)
def get_security_access_review(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityAccessReviewResponse:
    _ensure_azure_site()
    return build_security_access_review()


@router.get("/app-hygiene", response_model=SecurityAppHygieneResponse)
def get_security_app_hygiene(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityAppHygieneResponse:
    _ensure_azure_site()
    return build_security_application_hygiene()


@router.get("/break-glass-validation", response_model=SecurityBreakGlassValidationResponse)
def get_security_break_glass_validation(
    _session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityBreakGlassValidationResponse:
    _ensure_azure_site()
    return build_security_break_glass_validation()


@router.get("/directory-role-review", response_model=SecurityDirectoryRoleReviewResponse)
def get_security_directory_role_review(
    session: dict[str, Any] = Depends(require_authenticated_user),
) -> SecurityDirectoryRoleReviewResponse:
    _ensure_azure_site()
    return build_security_directory_role_review(session)
