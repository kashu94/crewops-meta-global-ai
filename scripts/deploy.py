"""Deploy CrewOps to AWS, after checking it can only land in the right place.

    uv run python scripts/deploy.py --bootstrap   # once per account and region
    uv run python scripts/deploy.py               # build and deploy
    uv run python scripts/deploy.py --destroy     # remove the stack and its data

It refuses to run unless the AWS profile is ``crewops-meta``, the signed-in identity is the
``crewops-meta-deployer`` user, and the region is ap-southeast-2. Every stack it touches is named
``crewops-meta-<stage>``, and it bootstraps with its own toolkit stack (``CrewOpsMetaToolkit``)
and qualifier, so nothing else in the account can be changed by it.

After the stack, it builds the web console (``npm ci``, ``next build``) with the API's address
and publishes it to the stack's own Amplify app, ``crewops-meta-<stage>-console``.

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
REGION = "ap-southeast-2"
# CDK's own bootstrap stack, kept apart from any other project's CDKToolkit in the account.
TOOLKIT = "CrewOpsMetaToolkit"
QUALIFIER = "crewmeta"
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


def build_console(api_url: str) -> Path:
    """The web console as static files, built to call the API at ``api_url``."""
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm is not installed: the web console is built with Node.js")
    web = ROOT / "web"
    env = {**os.environ, "NEXT_PUBLIC_CREWOPS_API": api_url.rstrip("/")}
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], check=True, cwd=web, env=env)
    subprocess.run([npm, "run", "build"], check=True, cwd=web, env=env)
    out = web / "out"
    if not (out / "index.html").is_file():
        sys.exit("the console build did not produce web/out/index.html")
    return out


def publish_console(site: Path, app_id: str, branch: str) -> None:
    """Upload ``site`` to the Amplify app as a manual deployment and wait for it to go live."""
    import time
    import urllib.request
    import zipfile

    import boto3

    archive = ROOT / "build" / "console.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(site.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(site).as_posix())
    amplify = boto3.Session(profile_name=PROFILE, region_name=REGION).client("amplify")
    job = amplify.create_deployment(appId=app_id, branchName=branch)
    upload = urllib.request.Request(
        job["zipUploadUrl"],
        data=archive.read_bytes(),
        method="PUT",
        headers={"Content-Type": "application/zip"},
    )
    with urllib.request.urlopen(upload) as reply:
        if reply.status >= 300:
            sys.exit(f"uploading the console failed: HTTP {reply.status}")
    amplify.start_deployment(appId=app_id, branchName=branch, jobId=job["jobId"])
    print(f"publishing the console to Amplify ({app_id}, branch {branch})", flush=True)
    for _ in range(120):
        status = amplify.get_job(appId=app_id, branchName=branch, jobId=job["jobId"])["job"][
            "summary"
        ]["status"]
        if status == "SUCCEED":
            return
        if status in ("FAILED", "CANCELLED"):
            sys.exit(f"the Amplify deployment {job['jobId']} {status.lower()}")
        time.sleep(5)
    sys.exit("the Amplify deployment did not finish within 10 minutes")


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
    common = ["--profile", PROFILE, "--toolkit-stack-name", TOOLKIT, "-c", f"stage={args.stage}"]
    stack = f"crewops-meta-{args.stage}"

    if args.bootstrap:
        # From the repo root, away from infra/cdk.json: bootstrapping needs no app.
        subprocess.run(
            [
                *cdk,
                "bootstrap",
                f"aws://{account}/{REGION}",
                "--toolkit-stack-name",
                TOOLKIT,
                "--qualifier",
                QUALIFIER,
                "--profile",
                PROFILE,
            ],
            check=True,
            cwd=ROOT,
            env=env,
        )
        return

    # The app is synthesised for deploy and destroy alike, and it needs the bundle.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_lambda.py")], check=True)
    if args.destroy:
        subprocess.run(
            [*cdk, "destroy", stack, "--force", *common], check=True, cwd=ROOT / "infra", env=env
        )
        return

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
    site = build_console(out["ApiUrl"])
    publish_console(site, out["ConsoleAppId"], out["ConsoleBranch"])
    print("\nCrewOps is live.")
    print(f"  Console: {out['ConsoleUrl']}")
    print(f"  Board:   {out['BoardUrl']}")
    print(f"  Speaker: {out['ConsoleUrl'].rstrip('/')}/speaker/")
    print(f"  API:     {out['ApiUrl']}")
    print("  Demo accounts: m.iyer, s.reddy, d.rao (controllers, desks 1-3), a.nair (approver),")
    print("                 ops.hyd (reporter), v.shah (auditor), k.menon (admin),")
    print("                 r.kapoor (super admin), ops.speaker (speaker),")
    print("                 anjali (crew C-1157), pooja.f (crew C-1167)")
    print(f"  Password: {env['CREWOPS_DEMO_PASSWORD']}")
    if values.get("CREWOPS_ALERT_EMAIL"):
        print(f"  Confirm the alert subscription email sent to {values['CREWOPS_ALERT_EMAIL']}.")


if __name__ == "__main__":
    main()
