# Gate 2 — Partial Delivery Recovery Verification

## Scenario

Required scenario (from spec):
1. Report requires at least 5 chunks
2. Chunks 1-3 send successfully
3. Chunk 4 fails with injected temporary error
4. Delivery persisted as partial
5. Retry resumes safely
6. Chunks 1-3 not sent again
7. Chunk 4 and remaining chunks complete
8. All Telegram message IDs recorded
9. Final delivery status becomes confirmed

## Test Implementation

File: `tests/integration/test_partial_delivery.py`
Test: `test_partial_delivery_recovery`

### Setup
- Creates a report with ~22500 chars of Persian content
- Renders to 6+ chunks (chunk_size=3800)
- Mock client `_FailOnChunk4`: succeeds on chunks 0-2, fails on chunk 3 with `SERVER_ERROR`

### Phase 1: Partial Failure
- Delivery attempted with failing client
- Chunks 0-2 sent successfully (message_ids: 10000, 10001, 10002)
- Chunk 3 fails with `server_error`
- Delivery status: `partial`
- delivered_chunks: 3
- Chunk 3 status: `failed`, error_category: `server_error`

### Phase 2: Recovery
- Retry with working client `_SuccessClient`
- Resume starts from chunk 3 (first non-sent chunk)
- Chunks 0-2 NOT sent again (send_count = chunk_count - 3)
- All remaining chunks sent successfully
- All chunk records updated to status=sent
- Delivery status: `delivered`
- delivered_at timestamp set
- All message IDs recorded in delivery.message_ids

### Verification Points
1. ✅ Report requires 6+ chunks (asserted)
2. ✅ Chunks 1-3 send successfully (message_ids 10000-10002)
3. ✅ Chunk 4 fails with injected error (server_error)
4. ✅ Delivery persisted as partial (status="partial")
5. ✅ Retry resumes from chunk 4 (not from start)
6. ✅ Chunks 1-3 not sent again (send_count verified)
7. ✅ Chunk 4 and remaining complete (all chunks status=sent)
8. ✅ All message IDs recorded (len(delivery.message_ids) == chunk_count)
9. ✅ Final status: delivered

## Additional Delivery Tests

- `test_cursor_advances_on_complete_delivery` — cursor advances after full delivery
- `test_cursor_does_not_advance_on_partial` — partial delivery doesn't advance cursor
- `test_cursor_no_double_advance` — repeated confirmation is idempotent
- `test_idempotent_delivery_no_duplicate` — already-delivered report not re-sent

All 5 integration tests pass against real PostgreSQL.

## Live Verification

Status: pending credentials
