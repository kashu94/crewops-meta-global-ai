/**
 * Where the board reads from: the CrewOps console address, with no trailing slash.
 *
 * Set it to the ConsoleUrl the deploy prints (the Lambda function URL), or to the laptop
 * running `uv run python -m crewops.api --host 0.0.0.0` on the same network.
 */
export const API_BASE = 'http://10.0.2.2:8765';

/** How often the board refreshes, in milliseconds. */
export const REFRESH_MS = 15000;
