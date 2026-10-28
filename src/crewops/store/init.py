"""Load the demo operation into the DynamoDB table.

    uv run python -m crewops.store.init                  # only if the table is empty
    uv run python -m crewops.store.init --reset          # wipe and reload
    uv run python -m crewops.store.init --create-table   # DynamoDB Local only

The table, profile and region come from the settings (``CREWOPS_TABLE``, ``AWS_PROFILE``,
``AWS_REGION``). In AWS the table is created by the infrastructure code, not here.
"""

from __future__ import annotations

import argparse

from crewops.seed import load_dataset, read_meta
from crewops.settings import settings
from crewops.store.roster import Store
from crewops.store.schema import create_table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="wipe the table and reload")
    parser.add_argument(
        "--create-table", action="store_true", help="create the table first (DynamoDB Local)"
    )
    args = parser.parse_args()

    config = settings()
    store = Store.connect(config)
    if args.create_table:
        create_table(store.dynamodb, config.table_name)
    if not store.is_empty() and not args.reset:
        print("the table already holds an operation; use --reset to reload it")
        return
    data = load_dataset(config.seed_dir)
    store.load(data, read_meta(config.seed_dir))
    print(f"loaded {len(data.trips)} trips and {len(data.crew)} crew into {config.table_name}")


if __name__ == "__main__":
    main()
