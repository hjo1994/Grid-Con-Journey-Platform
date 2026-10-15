"""Local stub for the internal eg-auth package. See local_stubs/README.md."""
from pydantic import BaseModel

BooleanRightClaim = bool


class BaseRights(BaseModel):
    """Base class for application rights, mirrored from the real package surface."""
