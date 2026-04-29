"""Configuration model for etc-platform.

Config is loaded from `etc-platform.yaml` in the project root (or specified via --config).
Env var interpolation: `${VAR_NAME}` or `${VAR_NAME:-default}`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${ENV_VAR} and ${ENV_VAR:-default} in strings."""
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            var, default = m.group(1), m.group(2) or ""
            return os.environ.get(var, default)
        return ENV_VAR_PATTERN.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(x) for x in value]
    return value


# ─────────────────────────── Nested config models ───────────────────────────

class ProjectConfig(BaseModel):
    name: str = Field(description="Vietnamese project display name")
    code: str = Field(default="", description="Project code for cover pages")
    client: str = Field(default="", description="Tên khách hàng / chủ đầu tư")
    dev_unit: str = Field(
        default="Công ty CP Hệ thống Công nghệ ETC",
        description="Đơn vị phát triển",
    )


class RepoConfig(BaseModel):
    path: str = Field(default=".", description="Path to source code repo")
    services_root: str | None = Field(
        default=None,
        description="Monorepo services folder (e.g. src/services/)",
    )
    apps_root: str | None = Field(
        default=None,
        description="Monorepo apps folder (e.g. src/apps/)",
    )


class DockerConfig(BaseModel):
    compose_file: str = Field(default="docker-compose.yml")
    auto_discover_services: bool = True
    services: dict[str, int] = Field(
        default_factory=dict,
        description="service_name → port mapping (optional manual override)",
    )


class AuthConfig(BaseModel):
    base_url: str = Field(description="Base URL for Playwright capture")
    login_url: str = "/login"
    username_env: str = Field(
        default="DOCGEN_USERNAME",
        description="Env var containing username (never commit credentials)",
    )
    password_env: str = "DOCGEN_PASSWORD"
    mode: Literal["auto", "recording", "unauthenticated"] = "auto"
    post_login_url: str | None = None


class CaptureConfig(BaseModel):
    profile: str | list[str] = Field(
        default="desktop",
        description="desktop | mobile | tablet, or list for multi-profile capture",
    )
    concurrency: int = Field(default=5, ge=1, le=20)


class OutputConfig(BaseModel):
    path: str = Field(default="docs/generated")
    formats: list[str] = Field(default_factory=lambda: ["docx", "xlsx"])
    sharding: Literal["monolithic", "by_service", "by_module"] = "monolithic"

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, v: list[str]) -> list[str]:
        allowed = {"docx", "xlsx", "pdf", "web"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Unknown formats: {invalid}. Allowed: {allowed}")
        return v


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "ollama", "none"] = "none"
    model: str = "claude-sonnet-4-5"
    data_model: str = "claude-sonnet-4-5"
    batch_mode: bool = False
    max_parallel: int = Field(default=5, ge=1, le=50)


class JiraXrayConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    project_key: str = ""
    client_id_env: str = "XRAY_CLIENT_ID"
    client_secret_env: str = "XRAY_CLIENT_SECRET"


class ConfluenceConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    space_key: str = ""
    parent_page_id: str = ""


class IntegrationsConfig(BaseModel):
    jira_xray: JiraXrayConfig = Field(default_factory=JiraXrayConfig)
    confluence: ConfluenceConfig = Field(default_factory=ConfluenceConfig)


class GitConfig(BaseModel):
    incremental: bool = False
    ignore_paths: list[str] = Field(default_factory=lambda: ["test/", "docs/"])


class TemplatesConfig(BaseModel):
    """Override bundled templates — null/unset means use built-in."""
    hdsd: str | None = None
    tkkt: str | None = None
    tkcs: str | None = None
    test_case: str | None = None


# ─────────────────────────── Root config ───────────────────────────

class Config(BaseModel):
    """Root configuration loaded from etc-platform.yaml."""
    version: str = "1.0"
    project: ProjectConfig
    repo: RepoConfig = Field(default_factory=RepoConfig)
    docker: DockerConfig = Field(default_factory=DockerConfig)
    auth: AuthConfig | None = None
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    templates: TemplatesConfig = Field(default_factory=TemplatesConfig)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def get_credential(self, which: Literal["username", "password"]) -> str:
        """Resolve credential from environment — never stored in config."""
        if not self.auth:
            raise ValueError("Auth section not configured")
        env_var = self.auth.username_env if which == "username" else self.auth.password_env
        value = os.environ.get(env_var, "")
        if not value:
            raise ValueError(
                f"Env var {env_var} not set. Required for Playwright auth."
            )
        return value


# ─────────────────────────── Loader ───────────────────────────

def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML file, expanding env vars.

    Search order if path not given:
      1. $ETC_PLATFORM_CONFIG env var
      2. ./etc-platform.yaml
      3. ./.etc-platform.yaml (hidden)
      4. ~/.config/etc-platform/config.yaml
    """
    if path is None:
        env_path = os.environ.get("ETC_PLATFORM_CONFIG")
        candidates = [
            Path(env_path) if env_path else None,
            Path("etc-platform.yaml"),
            Path(".etc-platform.yaml"),
            Path.home() / ".config" / "etc-platform" / "config.yaml",
        ]
        path = next((p for p in candidates if p and p.exists()), None)
        if path is None:
            raise FileNotFoundError(
                "No etc-platform.yaml found. Run `etc-platform init` to create one."
            )
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError(f"Empty config file: {path}")

    expanded = _expand_env_vars(raw)
    return Config.model_validate(expanded)


def write_example_config(path: str | Path) -> Path:
    """Emit a commented example config file for `etc-platform init`."""
    content = """# etc-platform configuration — see docs/config-reference.md for all options
version: "1.0"

project:
  name: "Hệ thống Quản lý Tác nghiệp"
  code: "QLTN-2026"
  client: "Bộ Tài Chính"
  dev_unit: "Công ty CP Hệ thống Công nghệ ETC"

repo:
  path: "."
  # For monorepo, uncomment:
  # services_root: "src/services"
  # apps_root: "src/apps"

docker:
  compose_file: "docker-compose.yml"
  auto_discover_services: true
  # Or override manually:
  # services:
  #   api: 3000
  #   web: 5173

auth:
  base_url: "http://localhost:3000"
  login_url: "/login"
  # Credentials from env vars — never commit:
  username_env: "DOCGEN_USERNAME"
  password_env: "DOCGEN_PASSWORD"
  mode: auto                           # auto | recording | unauthenticated

capture:
  profile: desktop                     # or [desktop, mobile]
  concurrency: 5

output:
  path: "docs/generated"
  formats: [docx, xlsx]                # add: pdf, web
  sharding: monolithic                 # monolithic | by_service | by_module

llm:
  provider: none                       # none | anthropic | openai | gemini
  # model: claude-opus-4-5             # For research FLOW phase
  # data_model: claude-sonnet-4-5      # For data-writer phase

# integrations:
#   jira_xray:
#     enabled: false
#     url: "https://etc.atlassian.net"
#     project_key: "QLTN"

git:
  incremental: false
  ignore_paths: ["test/", "docs/"]
"""
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    return p
