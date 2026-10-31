"""The CrewOps stack. Deploy it with ``scripts/deploy.py``, which checks the AWS identity first."""

import os

import aws_cdk as cdk
from stack import CrewOpsStack

app = cdk.App()
stage = app.node.try_get_context("stage") or "dev"
name = f"crewops-meta-{stage}"
if not name.startswith("crewops-meta-"):
    raise SystemExit("stack names must start with crewops-meta-")
CrewOpsStack(
    app,
    name,
    stage=stage,
    env=cdk.Environment(account=os.environ["CDK_DEFAULT_ACCOUNT"], region="ap-southeast-2"),
    # Matches the qualifier scripts/deploy.py bootstraps with.
    synthesizer=cdk.DefaultStackSynthesizer(qualifier="crewmeta"),
)
cdk.Tags.of(app).add("project", "crewops-meta")
app.synth()
