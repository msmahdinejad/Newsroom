# Gate 4 Test Results

## Deterministic tests: 50 passed

File: `tests/test_editorial.py`

Coverage:
1. Editorial disabled → deterministic
2. Missing credentials → deterministic
3. Deterministic provider generates valid output
4. Deterministic provider no network
5. Valid structured response passes validation
6. Malformed JSON rejected
7. Malformed JSON in markdown repaired
8. Missing stories field rejected
9. Missing metadata field rejected
10. Unknown story ID rejected
11. Duplicate story entries rejected
12. Invented evidence ref in claim rejected
13. Invented links removed by grounding
14. Unsupported number in claim removed
15. Supported number in claim kept
16. Unsupported date in claim removed
17. Unsupported version in claim removed
18. Conflicting evidence preserved
19. Community rumor labeled
20. Official source labeled
21. Prompt injection inert
22. Fake system message treated as data
23. Source content with JSON delimiters
24. Excessive input stories capped
25. Excessive output rejected
26. Provider timeout raises error
27. Retry limit respected
28. Rate limit error category
29. Provider outage triggers fallback
30. Safety refusal triggers fallback
31. Malformed structured response triggers fallback
32. Cache key deterministic
33. Cache key changes with mode
34. Cache key changes with evidence hash
35. Cache key changes with prompt version
36. Cache key changes with model
37. Invalid confidence clamped
38. Invalid classification rejected
39. Invalid priority repaired
40. Persian Unicode in output
41. RTL content preserved
42. Telegram-safe rendering
43. Evidence hash deterministic
44. Evidence hash changes with content
45. Empty evidence set
46. No chain-of-thought in schema
47. Prompt version in output
48. Schema version in output
49. Fallback not labeled as AI
50. Source trust not affected by content

## PostgreSQL integration tests: 17 passed

File: `tests/integration/test_gate4_editorial.py`

Coverage:
1. Editorial attempt persisted
2. Prompt version persisted
3. Evidence-set hash persisted
4. Structured output persisted
5. Claim-to-evidence refs persisted
6. Cache key unique constraint
7. Cache reuse finds existing
8. Cache reuse no match
9. Validation failure status persisted
10. Fallback persisted
11. Report linkage
12. No API key in attempt table
13. No API key in output JSON
14. Transaction rollback
15. Editorial health singleton
16. Editorial health updated
17. Report mode persisted

## Full suite: 347 passed

- 280 existing tests (Gates 0-3)
- 50 editorial deterministic tests
- 17 editorial integration tests

## Lint and type checking

- Ruff: All checks passed
- MyPy: Success: no issues found in 59 source files
