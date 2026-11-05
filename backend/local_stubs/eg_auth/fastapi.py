"""Stub of eg_auth.fastapi, hardened to the real integration form.

authorizer(...) must return a ``Depends`` instance — a naked function would make
FastAPI treat the parameter as user input and answer 422 (Fallenkatalog). The
stub only supports EG_AUTH_DEV_MODE=True; it cannot and must not fake a real
OIDC validation.
"""
from dataclasses import dataclass
from typing import Callable, List

from fastapi import Depends, HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict

from eg_auth import BaseRights


class _AuthDevSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EG_AUTH_", extra="ignore")

    dev_mode: bool = False
    dev_groups: List[str] = []


@dataclass
class UserInfo:
    name: str
    email: str
    groups: List[str]
    rights: BaseRights


class FastAPIResourceProtector:
    def __init__(self, groups_to_rights: Callable[[List[str]], BaseRights]):
        self._groups_to_rights = groups_to_rights

    def __call__(self, **required_claims: bool):
        def dependency() -> UserInfo:
            settings = _AuthDevSettings()
            if not settings.dev_mode:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "eg-auth stub: only EG_AUTH_DEV_MODE=True is supported locally. "
                        "Real OIDC validation requires the real eg-auth package."
                    ),
                )
            rights = self._groups_to_rights(settings.dev_groups)
            for claim, expected in required_claims.items():
                if getattr(rights, claim, None) != expected:
                    raise HTTPException(status_code=403, detail=f"Missing right: {claim}")
            return UserInfo(
                name="Dev User",
                email="dev.user@example.com",
                groups=settings.dev_groups,
                rights=rights,
            )

        return Depends(dependency)
