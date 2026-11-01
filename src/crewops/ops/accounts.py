"""Team accounts: who can sign in, with which role, and password resets.

An admin looks after the team's accounts: adds people, changes their role, switches an
account off, and resets a forgotten password. A reset gives a temporary password, shown once,
which the person must replace the next time they sign in. Admin accounts themselves, and
making anyone an admin, are for a super admin only, so an admin cannot raise their own
standing or lock out the people above them. Nobody changes or switches off their own account.

Deployed, accounts are the Cognito user pool's users and a role is a pool group. On a laptop
they live in the store, seeded with the demo accounts.
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from crewops.agent.tools import Role

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
ADMIN_ROLES = frozenset({Role.ADMIN, Role.SUPER_ADMIN})


@dataclass(frozen=True, slots=True)
class DemoAccount:
    user: str
    role: Role
    crew_id: str | None
    label: str


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount("m.iyer", Role.CONTROLLER, None, "Meera Iyer, desk 1"),
    DemoAccount("s.reddy", Role.CONTROLLER, None, "Sandeep Reddy, desk 2"),
    DemoAccount("d.rao", Role.CONTROLLER, None, "Divya Rao, desk 3"),
    DemoAccount("a.nair", Role.APPROVER, None, "Arun Nair"),
    DemoAccount("ops.hyd", Role.REPORTER, None, "HYD station duty manager"),
    DemoAccount("v.shah", Role.AUDITOR, None, "Vandana Shah"),
    DemoAccount("k.menon", Role.ADMIN, None, "Kiran Menon"),
    DemoAccount("r.kapoor", Role.SUPER_ADMIN, None, "Ritu Kapoor"),
    DemoAccount("ops.speaker", Role.SPEAKER, None, "Ops-room speaker"),
    DemoAccount("anjali", Role.CREW, "C-1157", "Anjali Goud, captain"),
    DemoAccount("pooja.f", Role.CREW, "C-1167", "Pooja Fernandes, captain"),
)


class AccountError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Account:
    username: str
    role: str
    crew_id: str | None
    enabled: bool
    status: str
    """``active``, or ``must change password`` after a reset or a new account."""
    created: str


def temporary_password() -> str:
    """Twelve characters with every class the pool's policy asks for."""
    pools = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!#%+-=?@")
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice("".join(pools)) for _ in range(8)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def check_may_manage(by_role: Role, by: str, username: str, role: Role | None, current: str | None):
    """Raise unless ``by`` may give ``username`` the ``role`` (or change them at all)."""
    if username == by:
        raise AccountError("you cannot change your own account")
    if by_role is not Role.SUPER_ADMIN:
        if role in ADMIN_ROLES:
            raise AccountError("only a super admin can make someone an admin")
        if current in {str(r) for r in ADMIN_ROLES}:
            raise AccountError("only a super admin can change an admin's account")


class Accounts(Protocol):
    def list(self) -> list[Account]: ...
    def create(self, username: str, role: Role, crew_id: str | None, email: str | None) -> str: ...
    def set_role(self, username: str, role: Role) -> None: ...
    def set_enabled(self, username: str, enabled: bool) -> None: ...
    def reset_password(self, username: str) -> str: ...


class StoreAccounts:
    """Accounts kept as documents, for a laptop and for tests."""

    def __init__(self, docs: Any) -> None:
        self.docs = docs
        if not docs.docs("account"):
            now = datetime.now(UTC).isoformat()
            for a in DEMO_ACCOUNTS:
                self._put(Account(a.user, str(a.role), a.crew_id, True, "active", now))

    def _put(self, account: Account) -> None:
        self.docs.put_doc("account", account.username, asdict(account))

    def _get(self, username: str) -> Account:
        found = self.docs.get_doc("account", username)
        if found is None:
            raise AccountError(f"no account {username}")
        return Account(**found)

    def list(self) -> list[Account]:
        return sorted((Account(**d) for d in self.docs.docs("account")), key=lambda a: a.username)

    def create(self, username: str, role: Role, crew_id: str | None, email: str | None) -> str:
        if self.docs.get_doc("account", username) is not None:
            raise AccountError(f"{username} already exists")
        now = datetime.now(UTC).isoformat()
        self._put(Account(username, str(role), crew_id, True, "must change password", now))
        return temporary_password()

    def set_role(self, username: str, role: Role) -> None:
        a = self._get(username)
        self._put(Account(a.username, str(role), a.crew_id, a.enabled, a.status, a.created))

    def set_enabled(self, username: str, enabled: bool) -> None:
        a = self._get(username)
        self._put(Account(a.username, a.role, a.crew_id, enabled, a.status, a.created))

    def reset_password(self, username: str) -> str:
        a = self._get(username)
        self._put(
            Account(a.username, a.role, a.crew_id, a.enabled, "must change password", a.created)
        )
        return temporary_password()


class CognitoAccounts:
    """The user pool's users; a role is the one CrewOps group a user is in."""

    def __init__(self, cognito: Any, pool_id: str) -> None:
        self.cognito, self.pool_id = cognito, pool_id

    def _groups(self, username: str) -> list[str]:
        reply = self.cognito.admin_list_groups_for_user(UserPoolId=self.pool_id, Username=username)
        return [g["GroupName"] for g in reply["Groups"]]

    def _role(self, username: str) -> str:
        roles = {str(r) for r in Role}
        return next((g for g in self._groups(username) if g in roles), "")

    def list(self) -> list[Account]:
        out = []
        for page in self.cognito.get_paginator("list_users").paginate(UserPoolId=self.pool_id):
            for u in page["Users"]:
                attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
                out.append(
                    Account(
                        username=u["Username"],
                        role=self._role(u["Username"]),
                        crew_id=attrs.get("custom:crew_id"),
                        enabled=u["Enabled"],
                        status=(
                            "must change password"
                            if u["UserStatus"] == "FORCE_CHANGE_PASSWORD"
                            else "active"
                        ),
                        created=u["UserCreateDate"].astimezone(UTC).isoformat(),
                    )
                )
        return sorted(out, key=lambda a: a.username)

    def _exists(self, username: str) -> bool:
        try:
            self.cognito.admin_get_user(UserPoolId=self.pool_id, Username=username)
        except self.cognito.exceptions.UserNotFoundException:
            return False
        return True

    def create(self, username: str, role: Role, crew_id: str | None, email: str | None) -> str:
        if self._exists(username):
            raise AccountError(f"{username} already exists")
        password = temporary_password()
        attributes = [{"Name": "custom:crew_id", "Value": crew_id}] if crew_id else []
        if email:
            attributes.append({"Name": "email", "Value": email})
        self.cognito.admin_create_user(
            UserPoolId=self.pool_id,
            Username=username,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
            UserAttributes=attributes,
        )
        self.cognito.admin_add_user_to_group(
            UserPoolId=self.pool_id, Username=username, GroupName=str(role)
        )
        return password

    def set_role(self, username: str, role: Role) -> None:
        if not self._exists(username):
            raise AccountError(f"no account {username}")
        for group in self._groups(username):
            if group != str(role):
                self.cognito.admin_remove_user_from_group(
                    UserPoolId=self.pool_id, Username=username, GroupName=group
                )
        self.cognito.admin_add_user_to_group(
            UserPoolId=self.pool_id, Username=username, GroupName=str(role)
        )

    def set_enabled(self, username: str, enabled: bool) -> None:
        if not self._exists(username):
            raise AccountError(f"no account {username}")
        call = self.cognito.admin_enable_user if enabled else self.cognito.admin_disable_user
        call(UserPoolId=self.pool_id, Username=username)

    def reset_password(self, username: str) -> str:
        if not self._exists(username):
            raise AccountError(f"no account {username}")
        password = temporary_password()
        self.cognito.admin_set_user_password(
            UserPoolId=self.pool_id, Username=username, Password=password, Permanent=False
        )
        return password


def current_role(accounts: Accounts, username: str) -> str | None:
    return next((a.role for a in accounts.list() if a.username == username), None)
