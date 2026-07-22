# Gate 6 — Live AI Report Evidence

## AI acceptance report

A real scheduled-style hierarchical report ran through the persistent router,
completed without deterministic fallback, and was delivered through the live
Telegram Bot API.

| Field | Persisted result |
|---|---|
| Editorial job | 128 / `scheduled_20260722_1800` |
| Report | 466 |
| Generation method | `ai` |
| Provider/model | Gemini / `gemini-3.5-flash-lite` |
| Map artifacts | 36, 37, 38, 39 |
| Final reduction artifact | 41 |
| Model calls | 5 (4 map + 1 final reduction) |
| Token usage | 47,964 input / 6,530 output |
| Fallback shards | 0 |
| Delivery | 435 / `delivered` |
| Telegram message IDs | `[56]` |
| Scheduled cursor | report 466 / delivery 435 |

Every provider-route attempt is linked to the editorial job, shard/reduction
stage, accepted artifact, and report. The validated final-output story identity
is persisted on the report; stories that were candidates but absent from the
validated final synthesis are not falsely marked delivered.

An earlier acceptance report, 464, was re-delivered idempotently: it returned
delivery 433 with message `[54]`, delivery row count stayed one, and no Telegram
message was sent twice.

## No-news path

A controlled scheduled-mode empty selection produced report 465 and delivery
434 with Telegram message `[55]`. Provider-route attempt count was identical
before and after the run: zero provider calls. Because this verification run
had no schedule label, it did not replace the scheduled cursor. The subsequent
real 18:00 Tehran run advanced it to report 466 only after complete delivery.

## Gate consequence

The AI report and Bot API delivery requirements pass. Gate 6 is still **NOT
VERIFIED** because the mandatory native Telegram MTProto ingestion path cannot
complete a handshake on the current external network route; see
`GATE_6_TELEGRAM_MTPROTO.md`.
