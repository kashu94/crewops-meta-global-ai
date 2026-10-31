"""Putting the advisor together from the settings."""

from __future__ import annotations

from crewops.agent.advisor import Advisor
from crewops.agent.guard import GuardChain, PatternGuard, PromptGuard
from crewops.agent.router import Router
from crewops.agent.verify import EvidenceVerifier
from crewops.models import Endpoint, Ledger, ModelClient
from crewops.ops import CalloutDesk, Outbox, StoreOutbox
from crewops.settings import Settings
from crewops.store import MemoryStore, Store


def build_advisor(
    config: Settings, store: Store | MemoryStore, outbox: Outbox | None = None
) -> Advisor:
    """Muse Spark plans; Muse Spark Open routes when its key is set, Muse Spark otherwise.

    Callouts are kept in the store, and their messages too unless another outbox is given,
    so any server can carry on a callout another one started.
    """
    ledger = Ledger(config.usage_log)
    planner = ModelClient(Endpoint.meta(config), ledger)
    router_model = (
        ModelClient(Endpoint.open_weights(config), ledger) if config.has_open_model else planner
    )
    guards = [PatternGuard()]
    if config.prompt_guard_url:
        guards.append(PromptGuard(config.prompt_guard_url, config.prompt_guard_token))
    rules = store.dataset().rules
    return Advisor(
        store,
        planner,
        rules,
        router=Router(router_model),
        guard=GuardChain(guards),
        verifier=EvidenceVerifier("\n".join(f"{r.rule_id} {r.text}" for r in rules)),
        desk=CalloutDesk(store, outbox or StoreOutbox(store), docs=store),
    )
