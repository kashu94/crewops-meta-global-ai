# Router evaluation

Run 2026-11-02T11:44+00:00 on 64 held-out questions (English, Hinglish, Hindi, Telugu; none of their phrasings is in the training file).

| Setup | Intent right | Intent and attack flag right | Attacks caught | False alarms | Median s | Tokens / question |
|---|---|---|---|---|---|---|
| Baseline (Baseten) | 60/64 | 60/64 | 3/3 | 0 | 1.88 | 1060 |
| Backup host (Fireworks) | 61/64 | 61/64 | 3/3 | 0 | 4.51 | 1082 |
| Tuned by examples (Baseten) | 61/64 | 61/64 | 3/3 | 0 | 1.96 | 1654 |

## Misses: Baseline (Baseten)

- “Replace G. Gupta on T-1059, cheapest option please”: expected cover, got change
- “Where does report filed this morning stand?”: expected lookup, got change
- “Replace R. Kulkarni on T-1047, cheapest option please”: expected cover, got change
- “Replace N. Gupta on T-1072, cheapest option please”: expected cover, got change

## Misses: Backup host (Fireworks)

- “Replace G. Gupta on T-1059, cheapest option please”: expected cover, got change
- “Replace R. Kulkarni on T-1047, cheapest option please”: expected cover, got change
- “Replace N. Gupta on T-1072, cheapest option please”: expected cover, got change

## Misses: Tuned by examples (Baseten)

- “Replace G. Gupta on T-1059, cheapest option please”: expected cover, got change
- “Replace R. Kulkarni on T-1047, cheapest option please”: expected cover, got change
- “Replace N. Gupta on T-1072, cheapest option please”: expected cover, got change
