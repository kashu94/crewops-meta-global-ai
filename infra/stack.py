"""Everything CrewOps needs on AWS, named ``crewops-meta-<stage>-...`` in ap-southeast-2.

* DynamoDB: the operation, callouts, conversations and notices, in one table.
* Lambda behind a function URL: the API the console, the board and the TV app call. A function
  URL rather than API Gateway, because planning an answer can take longer than a gateway's 30
  seconds. It answers browsers from the console's Amplify address only (CORS).
* Amplify Hosting: the web console, a static Next.js export, as app
  ``crewops-meta-<stage>-console``. ``scripts/deploy.py`` builds it and uploads it.
* A second Lambda on a 10-minute schedule: moves unanswered callout offers on, and emails the
  crew desk about new problems the watch finds (SNS).
* S3: the board's artwork from Muse Image.
* Cognito: sign-in, with the eight roles as groups and the demo accounts created at deploy
  time. Admins manage accounts from the console.

Model keys come from the deploying machine's ``.env`` and are set on the functions; they are
never committed. This is a demo stack: deleting it deletes its data.
"""

import os

import aws_cdk as cdk
from aws_cdk import aws_amplify as amplify
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from aws_cdk import custom_resources as cr
from constructs import Construct

from crewops.agent.tools import Role
from crewops.ops.accounts import DEMO_ACCOUNTS

BUNDLE = os.path.join(os.path.dirname(__file__), "..", "build", "lambda")
PASSED_THROUGH = (
    "MODEL_API_KEY",
    "META_BASE_URL",
    "CREWOPS_ADVISOR_MODEL",
    "CREWOPS_VISION_MODEL",
    "CREWOPS_TRANSCRIBE_MODEL",
    "CREWOPS_SEGMENT_MODEL",
    "CREWOPS_WONDER_MODEL",
    "CREWOPS_IMAGE_MODEL",
    "OPEN_MODEL_API_KEY",
    "OPEN_MODEL_BASE_URL",
    "CREWOPS_OPEN_MODEL",
    "CREWOPS_DAILY_ASKS",
)
DEMO_USERS = tuple((a.user, str(a.role), a.crew_id) for a in DEMO_ACCOUNTS)
ROLES = tuple(str(r) for r in Role)


class CrewOpsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        prefix = f"crewops-meta-{stage}"

        table = dynamodb.Table(
            self,
            "Operation",
            table_name=f"{prefix}-operation",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        bucket = s3.Bucket(
            self,
            "Images",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        topic = sns.Topic(self, "Alerts", topic_name=f"{prefix}-alerts")
        email = os.environ.get("CREWOPS_ALERT_EMAIL", "").strip()
        if email:
            topic.add_subscription(subscriptions.EmailSubscription(email))

        pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name=f"{prefix}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True),
            custom_attributes={"crew_id": cognito.StringAttribute(mutable=True)},
            password_policy=cognito.PasswordPolicy(min_length=10, require_symbols=False),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        client = pool.add_client(
            "Console",
            auth_flows=cognito.AuthFlow(user_password=True),
            generate_secret=False,
            id_token_validity=cdk.Duration.hours(8),
        )
        groups = {
            role: cognito.CfnUserPoolGroup(
                self,
                f"Group{role.title().replace('_', '')}",
                user_pool_id=pool.user_pool_id,
                group_name=role,
            )
            for role in ROLES
        }
        password = os.environ.get("CREWOPS_DEMO_PASSWORD", "")
        if password:
            self.demo_users(pool, groups, password)

        environment = {
            "CREWOPS_ROOT": "/var/task",
            "CREWOPS_SEED_DIR": "/var/task/data/seed",
            "CREWOPS_STAGE": stage,
            "CREWOPS_STORE": "dynamodb",
            "CREWOPS_TABLE": table.table_name,
            "CREWOPS_BUCKET": bucket.bucket_name,
            "CREWOPS_AUTH": "cognito",
            "CREWOPS_LIVE_CLOCK": "true",
            "COGNITO_POOL_ID": pool.user_pool_id,
            "COGNITO_CLIENT_ID": client.user_pool_client_id,
            "CREWOPS_ALERT_TOPIC_ARN": topic.topic_arn,
            **{k: os.environ[k] for k in PASSED_THROUGH if os.environ.get(k)},
        }
        code = lambda_.Code.from_asset(BUNDLE)
        api = lambda_.Function(
            self,
            "Api",
            function_name=f"{prefix}-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="crewops.api.aws.handler",
            code=code,
            memory_size=1536,
            timeout=cdk.Duration.seconds(180),
            environment=environment,
        )
        console = amplify.CfnApp(
            self,
            "ConsoleApp",
            name=f"{prefix}-console",
            description="CrewOps Meta web console (static Next.js export)",
            platform="WEB",
            custom_rules=[
                amplify.CfnApp.CustomRuleProperty(source="/<*>", target="/404.html", status="404")
            ],
            tags=[cdk.CfnTag(key="project", value="crewops-meta")],
        )
        branch = amplify.CfnBranch(
            self,
            "ConsoleAppBranch",
            app_id=console.attr_app_id,
            branch_name=stage,
            stage="PRODUCTION",
            enable_auto_build=False,
        )
        console_url = f"https://{branch.branch_name}.{console.attr_default_domain}"
        url = api.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=[console_url, "http://localhost:3000"],
                allowed_methods=[lambda_.HttpMethod.ALL],
                allowed_headers=["authorization", "content-type"],
                max_age=cdk.Duration.hours(1),
            ),
        )
        watch = lambda_.Function(
            self,
            "Watch",
            function_name=f"{prefix}-watch",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler="crewops.api.aws.scheduled",
            code=code,
            memory_size=1024,
            timeout=cdk.Duration.seconds(120),
            environment=environment,
        )
        events.Rule(
            self,
            "Every10Minutes",
            rule_name=f"{prefix}-watch",
            schedule=events.Schedule.rate(cdk.Duration.minutes(10)),
            targets=[targets.LambdaFunction(watch)],
        )
        for fn in (api, watch):
            table.grant_read_write_data(fn)
            bucket.grant_read_write(fn)
            topic.grant_publish(fn)
        # Admins manage the team's accounts and the alert addresses from the console.
        api.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:ListUsers",
                    "cognito-idp:AdminGetUser",
                    "cognito-idp:AdminListGroupsForUser",
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminAddUserToGroup",
                    "cognito-idp:AdminRemoveUserFromGroup",
                    "cognito-idp:AdminEnableUser",
                    "cognito-idp:AdminDisableUser",
                    "cognito-idp:AdminSetUserPassword",
                ],
                resources=[pool.user_pool_arn],
            )
        )
        api.add_to_role_policy(
            iam.PolicyStatement(actions=["sns:Subscribe"], resources=[topic.topic_arn])
        )
        api.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sns:Unsubscribe", "sns:GetSubscriptionAttributes"], resources=["*"]
            )
        )

        cdk.CfnOutput(self, "ConsoleUrl", value=f"{console_url}/")
        cdk.CfnOutput(self, "BoardUrl", value=f"{console_url}/board/")
        cdk.CfnOutput(self, "ApiUrl", value=url.url)
        cdk.CfnOutput(self, "ConsoleAppId", value=console.attr_app_id)
        cdk.CfnOutput(self, "ConsoleBranch", value=branch.branch_name)
        cdk.CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        cdk.CfnOutput(self, "ClientId", value=client.user_pool_client_id)
        cdk.CfnOutput(self, "TableName", value=table.table_name)

    def demo_users(self, pool: cognito.UserPool, groups: dict, password: str) -> None:
        """The demo accounts, with a known password so judges can sign in.

        Every call runs as one role with one statement. Left to itself, each custom resource adds
        its own statement to the provider's role, and a few dozen of them pass IAM's 10 KB limit
        on a role's inline policies.
        """
        runner = iam.Role(
            self,
            "DemoUsersRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        runner.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:AdminCreateUser",
                    "cognito-idp:AdminDeleteUser",
                    "cognito-idp:AdminSetUserPassword",
                    "cognito-idp:AdminAddUserToGroup",
                ],
                resources=[pool.user_pool_arn],
            )
        )
        for username, role, crew_id in DEMO_USERS:
            attributes = [{"Name": "custom:crew_id", "Value": crew_id}] if crew_id else []
            key = username.replace(".", "")
            create = cr.AwsCustomResource(
                self,
                f"Create{key}",
                on_create=cr.AwsSdkCall(
                    service="CognitoIdentityServiceProvider",
                    action="adminCreateUser",
                    parameters={
                        "UserPoolId": pool.user_pool_id,
                        "Username": username,
                        "MessageAction": "SUPPRESS",
                        "UserAttributes": attributes,
                    },
                    physical_resource_id=cr.PhysicalResourceId.of(f"user-{username}"),
                ),
                on_delete=cr.AwsSdkCall(
                    service="CognitoIdentityServiceProvider",
                    action="adminDeleteUser",
                    parameters={"UserPoolId": pool.user_pool_id, "Username": username},
                    ignore_error_codes_matching="UserNotFoundException",
                ),
                role=runner,
                install_latest_aws_sdk=False,
            )
            set_password = cr.AwsSdkCall(
                service="CognitoIdentityServiceProvider",
                action="adminSetUserPassword",
                parameters={
                    "UserPoolId": pool.user_pool_id,
                    "Username": username,
                    "Password": password,
                    "Permanent": True,
                },
                physical_resource_id=cr.PhysicalResourceId.of(f"password-{username}"),
            )
            secret = cr.AwsCustomResource(
                self,
                f"Password{key}",
                on_create=set_password,
                on_update=set_password,
                role=runner,
                install_latest_aws_sdk=False,
            )
            secret.node.add_dependency(create)
            member = cr.AwsCustomResource(
                self,
                f"Group{key}",
                on_create=cr.AwsSdkCall(
                    service="CognitoIdentityServiceProvider",
                    action="adminAddUserToGroup",
                    parameters={
                        "UserPoolId": pool.user_pool_id,
                        "Username": username,
                        "GroupName": role,
                    },
                    physical_resource_id=cr.PhysicalResourceId.of(f"group-{username}"),
                ),
                role=runner,
                install_latest_aws_sdk=False,
            )
            member.node.add_dependency(create, groups[role])
