# Product feedback and friction log

What it was like to build CrewOps on Meta's developer platform. Entries are added as they
happen, newest last, so the log reflects the build as it went rather than a summary written
afterwards.

Each entry says what we tried, what happened, what it cost us, how we worked around it, and
what would have helped.

## What worked well

- **OpenAI-compatible API.** The first request to `muse-spark-1.3` worked unchanged from a
  plain `curl` with only the base URL and key swapped, so existing tooling and client libraries
  carry over without an adapter.
- **One key for every model.** Chat, vision, transcription, segmentation and image generation
  sit behind the same key and base URL, which keeps configuration to a handful of settings.

## Friction log

### 2026-10-27 · Muse Spark · Reasoning tokens spent on trivial replies by default

- **Tried:** A one-line test prompt to `muse-spark-1.3` with default settings.
- **Happened:** The reply was a few words, but the usage showed 691 reasoning tokens.
- **Cost:** At the default effort, simple steps such as routing a question or rewording an
  answer would use most of a small credit budget on reasoning nobody reads.
- **Workaround:** Set `reasoning_effort` explicitly on every call: `minimal` or `low` for
  routing and rewording, higher only for planning.
- **Would help:** A lower default effort for short prompts, or the default effort and its
  typical token cost shown on the model's page.

### 2026-10-28 · Model API · No embedding model

- **Tried:** Planning search over the rule book, glossary and past disruptions.
- **Happened:** The documentation lists no embeddings endpoint or embedding model.
- **Cost:** A design change: the rule book goes whole into a cached prompt, and search is
  keyword filtering with Muse Spark ranking the shortlist. That suits our small corpus, but it
  would not scale to a large document archive.
- **Would help:** An embedding model on the same key, or a documented recommendation for
  which open embedding model to pair with Muse Spark.

### 2026-10-28 · Model API · No text-to-speech

- **Tried:** Planning a spoken reply for the hands-free crew desk page.
- **Happened:** Speech-to-text is covered (`muse-voice-transcribe-1.0`, file and realtime),
  but there is no speech output.
- **Workaround:** The browser's built-in speech synthesis reads the answer aloud.
- **Would help:** A TTS model, so a voice agent can stay on one platform end to end.
