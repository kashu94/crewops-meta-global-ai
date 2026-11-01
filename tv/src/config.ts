/**
 * Where the board reads from: the CrewOps console address, with no trailing slash.
 *
 * Set it to the ConsoleUrl the deploy prints (the Lambda function URL), or to the laptop
 * running `uv run python -m crewops.api --host 0.0.0.0` on the same network.
 */
export const API_BASE =
  'https://ahn6eequcfrw7k7enwythkg5je0hcwqo.lambda-url.ap-southeast-2.on.aws';

/** How often the board refreshes, in milliseconds. */
export const REFRESH_MS = 15000;
