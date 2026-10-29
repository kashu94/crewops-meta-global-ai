import boto3
import pytest
from moto import mock_aws

from crewops.seed import load_dataset, read_meta
from crewops.settings import ROOT
from crewops.store import MemoryStore, Store
from crewops.store.schema import create_table

SEED_DIR = ROOT / "data" / "seed"
TABLE = "crewops-meta-test-operation"


@pytest.fixture(scope="session")
def seed():
    return load_dataset(SEED_DIR)


@pytest.fixture(params=["dynamodb", "memory"])
def empty(request, monkeypatch):
    """An empty store of each kind: DynamoDB (simulated) and in memory."""
    if request.param == "memory":
        yield MemoryStore()
        return
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        dynamodb = boto3.client("dynamodb", region_name="ap-south-1")
        create_table(dynamodb, TABLE)
        yield Store(dynamodb, TABLE)


@pytest.fixture
def store(empty, seed):
    empty.load(seed, read_meta(SEED_DIR))
    return empty
