# Gate 4 Live Evidence

## Status: PENDING

Live provider testing is pending credential configuration.

## What will be tested

### Provider identity
1. Provider configuration validates
2. Selected model can be reached
3. Minimal structured response succeeds
4. No key appears in logs or health output

### Single-story editorial
5. Official English AI announcement
6. Persian technology story
7. GitHub release
8. Telegram-sourced story
9. Output is natural Persian
10. All factual claims map to evidence

### Multi-source synthesis
11. Combine several sources about one event
12. Avoid repeating the same news
13. Preserve all materially distinct facts
14. Identify official and secondary evidence
15. Retain usable source links

### Conflicting evidence
16. Process a controlled conflicting-evidence fixture
17. Preserve uncertainty
18. Do not invent a resolution
19. Label the story correctly

### Prompt injection
20. Process malicious source text
21. Prove no instruction override
22. Prove no secret request
23. Prove schema remains intact
24. Prove no unauthorized tool behavior occurs

### Unsupported-claim rejection
25-28. Inject unsupported number, date, version — verify grounding rejects

### Full reports
29-34. Generate all report modes, verify /latest performs no model call

### Delivery
35-39. Deliver AI-edited Persian report through Gate 2 bot

### Failure and fallback
40-45. Inject provider errors, prove deterministic fallback delivered

### Restart and idempotency
46-51. Restart during/after editorial, prove state coherent

### Security
52-57. Scan git, Docker, logs, database, evidence for credentials
