"""Deploy CrewOps to AWS, after checking it can only land in the right place.

    uv run python scripts/deploy.py --bootstrap   # once per account and region
    uv run python scripts/deploy.py               # build and deploy
    uv run python scripts/deploy.py --destroy     # remove the stack and its data

It refuses to run unless the AWS profile is ``crewops-meta``, the signed-in identity is the
``crewops-meta-deployer`` user, and the region is ap-south-1. Every stack it touches is named
``crewops-meta-<stage>``, so nothing else in the account can be changed by it.

Settings come from ``.env``: the model keys, ``CREWOPS_ALERT_EMAIL`` for desk alerts, and
``CREWOPS_DEMO_PASSWORD`` for the demo accounts (made up and saved there on first deploy).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "crewops-meta"
REGION = "ap-south-1"
DEPLOYER = ":user/crewops-meta-deployer"
CDK = "aws-cdk@latest"


def dotenv() -> dict[str, str]:
    path = ROOT / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


def check_identity() -> str:
    import boto3

    stray = [
        k
        for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
        if os.environ.get(k)
    ]
    if stray:
        sys.exit(
            f"remove {', '.join(stray)} from the environment: they would override the "
            f"{PROFILE} profile"
        )
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    identity = session.client("sts").get_caller_identity()
    if not identity["Arn"].endswith(DEPLOYER):
        sys.exit(
            f"refusing to deploy as {identity['Arn']}: expected the crewops-meta-deployer user"
        )
    print(f"deploying as {identity['Arn']} to {REGION}")
    return identity["Account"]


def ensure_password(values: dict[str, str]) -> str:
    password = values.get("CREWOPS_DEMO_PASSWORD", "")
    if not password:
        password = "Crew-" + secrets.token_urlsafe(9)
        with (ROOT / ".env").open("a", encoding="utf-8") as env:
            env.write(
                f"\n# Password for the demo accounts (shared with judges)\n"
                f"CREWOPS_DEMO_PASSWORD={password}\n"
            )
        print("made a demo password and saved it to .env")
    return password


def npx() -> str:
    found = shutil.which("npx") or shutil.which("npx.cmd")
    if not found:
        sys.exit("Node.js (npx) is needed for the CDK; install Node 22 LTS")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy CrewOps to AWS.")
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--bootstrap", action="store_true", help="prepare the account for CDK")
    parser.add_argument("--destroy", action="store_true", help="delete the stack and its data")
    args = parser.parse_args()
    if not args.stage.isalnum():
        sys.exit("the stage must be letters and digits")

    values = dotenv()
    if values.get("AWS_PROFILE", PROFILE) != PROFILE:
        sys.exit(f"AWS_PROFILE in .env must be {PROFILE}")
    account = check_identity()
    env = {
        **os.environ,
        **values,
        "AWS_PROFILE": PROFILE,
        "AWS_REGION": REGION,
        "CDK_DEFAULT_ACCOUNT": account,
        "CDK_DEFAULT_REGION": REGION,
    }
    env["CREWOPS_DEMO_PASSWORD"] = ensure_password(values)
    cdk = [npx(), "--yes", CDK]
    common = ["--profile", PROFILE, "-c", f"stage={args.stage}"]
    stack = f"crewops-meta-{args.stage}"

    if args.bootstrap:
        subprocess.run(
            [*cdk, "bootstrap", f"aws://{account}/{REGION}", "--profile", PROFILE],
            check=True,
            cwd=ROOT / "infra",
            env=env,
        )
        return
    if args.destroy:
        subprocess.run(
            [*cdk, "destroy", stack, "--force", *common], check=True, cwd=ROOT / "infra", env=env
        )
        return

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_lambda.py")], check=True)
    outputs = ROOT / "build" / "outputs.json"
    subprocess.run(
        [
            *cdk,
            "deploy",
            stack,
            "--require-approval",
            "never",
            "--outputs-file",
            str(outputs),
            *common,
        ],
        check=True,
        cwd=ROOT / "infra",
        env=env,
    )
    out = json.loads(outputs.read_text())[stack]
    print("\nCrewOps is live.")
    print(f"  Console: {out['ConsoleUrl']}")
    print(f"  Board:   {out['BoardUrl']}")
    print("  Demo accounts: m.iyer, s.reddy (controllers), ops.board (viewer),")
    print("                 anjali (crew C-1157), pooja.f (crew C-1167)")
    print(f"  Password: {env['CREWOPS_DEMO_PASSWORD']}")
    if values.get("CREWOPS_ALERT_EMAIL"):
        print(f"  Confirm the alert subscription email sent to {values['CREWOPS_ALERT_EMAIL']}.")


if __name__ == "__main__":
    main()
