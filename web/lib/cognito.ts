/* Sign-in against the Cognito user pool, straight from the browser (the console is a static
   site, so there is no server of its own to do it). After an admin resets a password the pool
   answers with the NEW_PASSWORD_REQUIRED challenge; the person then picks a new password and
   it is sent back with RespondToAuthChallenge. */

import { loadConfig, setToken } from "./api";

type AuthResult = { IdToken: string };
type Answer = {
  AuthenticationResult?: AuthResult;
  ChallengeName?: string;
  Session?: string;
  ChallengeParameters?: Record<string, string>;
  message?: string;
  __type?: string;
};

export type Challenge = { name: "NEW_PASSWORD_REQUIRED"; session: string; username: string };

async function call(target: string, body: unknown): Promise<Answer> {
  const config = await loadConfig();
  if (!config.region || !config.client_id) throw new Error("Sign-in is not configured on this server.");
  let res: Response;
  try {
    res = await fetch(`https://cognito-idp.${config.region}.amazonaws.com/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify({ ...(body as object), ClientId: config.client_id }),
    });
  } catch {
    throw new Error("The sign-in service cannot be reached.");
  }
  const out = (await res.json().catch(() => ({}))) as Answer;
  if (!res.ok) {
    const kind = String(out.__type ?? "");
    if (kind.includes("NotAuthorized")) throw new Error(out.message || "Wrong username or password.");
    if (kind.includes("InvalidPassword")) throw new Error(out.message || "That password does not meet the rules.");
    throw new Error(out.message || "Sign-in failed.");
  }
  return out;
}

/** Signs in. Returns a challenge when the person must choose a new password first. */
export async function signIn(username: string, password: string): Promise<Challenge | null> {
  const out = await call("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  if (out.AuthenticationResult?.IdToken) {
    setToken(out.AuthenticationResult.IdToken);
    return null;
  }
  if (out.ChallengeName === "NEW_PASSWORD_REQUIRED" && out.Session) {
    return { name: "NEW_PASSWORD_REQUIRED", session: out.Session, username: out.ChallengeParameters?.USER_ID_FOR_SRP ?? username };
  }
  throw new Error(out.ChallengeName ? `Sign-in needs ${out.ChallengeName}, which this console does not support.` : "Sign-in failed.");
}

export async function setNewPassword(challenge: Challenge, password: string): Promise<void> {
  const out = await call("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    Session: challenge.session,
    ChallengeResponses: { USERNAME: challenge.username, NEW_PASSWORD: password },
  });
  if (!out.AuthenticationResult?.IdToken) throw new Error("The new password was not accepted.");
  setToken(out.AuthenticationResult.IdToken);
}
