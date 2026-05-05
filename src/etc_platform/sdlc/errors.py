"""Uniform error format for SDLC MCP tools (per P0 §2.6).

All SDLC tools return either:

    Success: { "ok": true, "data": {...}, "warnings": [] }
    Failure: { "ok": false, "error": { code, message, details, fix_hint } }

Error codes are namespaced ``MCP_E_<CATEGORY>`` to disambiguate from MCP
protocol errors. Skill callers branch on ``error.code`` to decide retry vs
abort vs ask user.
"""
from __future__ import annotations

from typing import Any


class MCPSdlcError(Exception):
    """Base class for SDLC tool errors. Carries code + details for uniform output."""

    code: str = "MCP_E_INTERNAL"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        fix_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.fix_hint = fix_hint

    def to_response(self) -> dict[str, Any]:
        """Serialize to uniform MCP tool response."""
        err: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }
        if self.fix_hint:
            err["fix_hint"] = self.fix_hint
        return {"ok": False, "error": err}


class InvalidWorkspaceError(MCPSdlcError):
    """Path validation failed (not absolute, traversal, missing marker, etc.)."""

    code = "MCP_E_INVALID_WORKSPACE"


class InvalidInputError(MCPSdlcError):
    """Schema validation failed for tool input."""

    code = "MCP_E_INVALID_INPUT"


class NotFoundError(MCPSdlcError):
    """Entity (module/feature/hotfix/template) not found."""

    code = "MCP_E_NOT_FOUND"


class AlreadyExistsError(MCPSdlcError):
    """Entity already exists where unique expected."""

    code = "MCP_E_ALREADY_EXISTS"


class VersionConflictError(MCPSdlcError):
    """Optimistic concurrency mismatch."""

    code = "MCP_E_VERSION_CONFLICT"


class VerificationFailedError(MCPSdlcError):
    """verify subroutine found HIGH-severity violations under strict_mode=block."""

    code = "MCP_E_VERIFICATION_FAILED"


class TransactionFailedError(MCPSdlcError):
    """Multi-file transaction rolled back due to mid-write failure."""

    code = "MCP_E_TRANSACTION_FAILED"


class ForbiddenError(MCPSdlcError):
    """Operation rejected: e.g. modifying field listed in locked_fields[]."""

    code = "MCP_E_FORBIDDEN"


class TemplateNotFoundError(MCPSdlcError):
    """Template registry missing requested template."""

    code = "MCP_E_TEMPLATE_NOT_FOUND"


class IdCollisionError(MCPSdlcError):
    """ID conflict (F-NNN/M-NNN/H-NNN already used)."""

    code = "MCP_E_ID_COLLISION"


class NameCollisionError(MCPSdlcError):
    """Name/slug already exists where unique required."""

    code = "MCP_E_NAME_COLLISION"


class NotMonoRepoError(MCPSdlcError):
    """Operation requires monorepo workspace, target is mini."""

    code = "MCP_E_NOT_MONO"


class DestructiveNotConfirmedError(MCPSdlcError):
    """autofix called with destructive fix_class but confirm_destructive=false."""

    code = "MCP_E_DESTRUCTIVE_NOT_CONFIRMED"


def success_response(
    data: dict[str, Any], warnings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Build uniform success response."""
    return {"ok": True, "data": data, "warnings": warnings or []}
