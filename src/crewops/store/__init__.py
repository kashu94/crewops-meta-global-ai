"""The database: the operation's records, the roster and every change made to it."""

from crewops.settings import Settings
from crewops.store.memory import MemoryStore
from crewops.store.roster import RosterChange, StaleTrip, Store


def open_store(config: Settings) -> Store | MemoryStore:
    """The store named by ``CREWOPS_STORE``. A memory store starts loaded with the demo data."""
    if config.store == "dynamodb":
        return Store.connect(config)
    from crewops.seed import load_dataset, read_meta

    store = MemoryStore()
    store.load(load_dataset(config.seed_dir), read_meta(config.seed_dir))
    return store


__all__ = ["MemoryStore", "RosterChange", "StaleTrip", "Store", "open_store"]
