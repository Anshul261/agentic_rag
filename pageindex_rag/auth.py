"""Authentication hook. There is no auth today: every request is the local user.

To plug in an auth service later, replace `get_principal` with a dependency that
validates the request (e.g. a bearer token or session cookie from your identity
provider) and returns a Principal, raising HTTPException(401) otherwise. Every
API route already depends on it, so nothing else has to change; use
`principal.user_id` to scope collections per user when you need that.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class Principal:
    user_id: str
    authenticated: bool


LOCAL_USER = Principal(user_id="local", authenticated=False)


async def get_principal(request: Request) -> Principal:
    return LOCAL_USER
