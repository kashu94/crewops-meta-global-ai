"""Who is calling.

Two modes, set by ``CREWOPS_AUTH``:

* ``demo``: the caller picks a demo identity with ``X-Demo-User``, ``X-Demo-Role`` and
  ``X-Demo-Crew-Id`` headers. For running on a laptop; never deployed.
* ``cognito``: the caller signs in to the Cognito user pool and sends the ID token as a
  bearer token. The token's signature, issuer, audience and expiry are checked here, and the
  role comes from the user's group (``controller``, ``viewer`` or ``crew``) and their crew id
  from the ``custom:crew_id`` attribute.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import HTTPException, Request

from crewops.agent.tools import Caller, Role
from crewops.settings import Settings

ROLE_ORDER = (Role.CONTROLLER, Role.VIEWER, Role.CREW)


@lru_cache(maxsize=4)
def _keys(region: str, pool_id: str) -> jwt.PyJWKClient:
    url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True)


def issuer(config: Settings) -> str:
    return f"https://cognito-idp.{config.aws_region}.amazonaws.com/{config.cognito_pool_id}"


def caller_from_claims(claims: dict) -> Caller:
    groups = set(claims.get("cognito:groups") or [])
    role = next((r for r in ROLE_ORDER if r.value in groups), None)
    if role is None:
        raise HTTPException(403, "this account has no CrewOps role")
    user = claims.get("cognito:username") or claims.get("email") or claims["sub"]
    crew_id = claims.get("custom:crew_id") or None
    if role is Role.CREW and not crew_id:
        raise HTTPException(403, "this crew account has no crew id")
    return Caller(user, role, crew_id)


def verify(token: str, config: Settings, keys: jwt.PyJWKClient | None = None) -> dict:
    keys = keys or _keys(config.aws_region, config.cognito_pool_id)
    try:
        key = keys.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=config.cognito_client_id,
            issuer=issuer(config),
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as err:
        raise HTTPException(401, f"sign in again ({err})") from err


def caller_from(request: Request, config: Settings) -> Caller:
    if config.auth == "demo":
        role = request.headers.get("x-demo-role", Role.CONTROLLER.value)
        try:
            return Caller(
                request.headers.get("x-demo-user", "m.iyer"),
                Role(role),
                request.headers.get("x-demo-crew-id") or None,
            )
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "sign in first")
    claims = verify(header.split(" ", 1)[1], config)
    if claims.get("token_use") != "id":
        raise HTTPException(401, "send the ID token")
    return caller_from_claims(claims)
