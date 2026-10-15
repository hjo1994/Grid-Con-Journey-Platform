"""Authentication/authorization via the internal eg-auth package.

Same integration form as the AI Cockpit backend: `authorizer()` is a FastAPI
dependency (`Depends` instance) put on the data routers, and `/api/auth/rights`
tells the frontend what the signed-in user may do.

`eg-auth` is installed from the company mirror in the cluster; locally the stub
in `local_stubs/` stands in (EG_AUTH_DEV_MODE=True only, see its README).
"""
from typing import Annotated, List

from eg_auth import BaseRights, BooleanRightClaim
from eg_auth.fastapi import FastAPIResourceProtector, UserInfo
from fastapi import APIRouter

AUTH_TAG = "auth"


class Rights(BaseRights):
    canViewGridConnectionRequests: BooleanRightClaim


def map_groups_to_rights(ldap_groups: List[str]) -> Rights:
    # TODO: placeholder group taken over from the AI Cockpit — replace with the
    # real group once Grid Con has its own OIDC client. Today the API only
    # requires a signed-in user (`authorizer()` without a right); this right is
    # informational for the frontend until someone decides to gate on it.
    return Rights(canViewGridConnectionRequests="app_50hzt_aap_communities_all__x" in ldap_groups)


authorizer = FastAPIResourceProtector(groups_to_rights=map_groups_to_rights)

auth_router = APIRouter(prefix="/api", tags=[AUTH_TAG])


@auth_router.get("/auth/rights")
def get_user_rights(user_info: Annotated[UserInfo, authorizer()]):
    return {"user": user_info.name, "rights": user_info.rights}
