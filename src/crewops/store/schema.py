"""The DynamoDB table.

One table holds the whole operation, keyed by a partition ``pk`` and a sort key ``sk``:

    pk               sk                              holds
    REC#<kind>       record id (crew id, leg id...)  one airline, crew member, leg, rule...
    TRIP             trip id                         the trip and its version number
    CHANGE           <time>#<trip id>#<version>      one change to a trip's crew
    META             roster_version                  bumped by every roster change

Reference data is stored as one validated JSON document per record: it is read whole into
memory and never queried field by field, so attributes would add nothing. Trips are what
controllers change, so each carries a version that every change is conditioned on.

The deployed table is created by the infrastructure code with this same key schema;
``create_table`` is for tests and DynamoDB Local.
"""

from __future__ import annotations

from typing import Any

import boto3

from crewops.settings import Settings

KEY_SCHEMA = [
    {"AttributeName": "pk", "KeyType": "HASH"},
    {"AttributeName": "sk", "KeyType": "RANGE"},
]
ATTRIBUTES = [
    {"AttributeName": "pk", "AttributeType": "S"},
    {"AttributeName": "sk", "AttributeType": "S"},
]


def client(config: Settings) -> Any:
    """A DynamoDB client for the configured profile, region and endpoint.

    Without ``AWS_PROFILE`` boto3 uses its usual chain, which is what a deployed function wants.
    """
    session = boto3.session.Session(
        profile_name=config.aws_profile or None, region_name=config.aws_region
    )
    return session.client("dynamodb", endpoint_url=config.dynamodb_endpoint or None)


def create_table(dynamodb: Any, name: str) -> None:
    dynamodb.create_table(
        TableName=name,
        KeySchema=KEY_SCHEMA,
        AttributeDefinitions=ATTRIBUTES,
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.get_waiter("table_exists").wait(TableName=name)
