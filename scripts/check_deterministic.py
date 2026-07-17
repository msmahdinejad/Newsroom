"""Quick check: deterministic provider generates a report."""

from newsroom.editorial.deterministic_provider import DeterministicEditorialProvider
from newsroom.editorial.schema import (
    EditorialEvidenceSet,
    EditorialRequest,
    EvidenceSourceItem,
    EvidenceStoryPacket,
)

evidence = EditorialEvidenceSet(
    stories=[
        EvidenceStoryPacket(
            story_id=1,
            headline="Test Story",
            facts=["AI is advancing", "New model released"],
            confidence=0.85,
            importance_score=0.8,
            trust_status="confirmed",
            source_count=2,
            item_count=2,
            sources=[
                EvidenceSourceItem(
                    ref_id="ev-1-0",
                    item_id=1,
                    original_url="https://example.com/1",
                    source_name="Test",
                    source_trust="reputable",
                ),
                EvidenceSourceItem(
                    ref_id="ev-1-1",
                    item_id=2,
                    original_url="https://example.com/2",
                    source_name="Test2",
                    source_trust="official",
                ),
            ],
        )
    ]
)

req = EditorialRequest(evidence=evidence)
resp = DeterministicEditorialProvider().generate(req)
print("Provider:", resp.provider)
print("Model:", resp.model)
print("Latency:", resp.latency_ms, "ms")
print("Stories:", len(resp.output.stories))
s = resp.output.stories[0]
print("Headline:", s.headline_fa.encode("utf-8", errors="replace").decode("utf-8"))
print("Summary:", s.summary_fa[:80].encode("utf-8", errors="replace").decode("utf-8"))
print("Why it matters:", s.why_it_matters_fa[:80].encode("utf-8", errors="replace").decode("utf-8"))
print("Claims:", len(s.key_claims))
print("Source links:", s.source_links)
print("Classification:", s.classification)
print("Confidence:", s.confidence_level)
print("Priority:", s.suggested_priority)
print("SUCCESS")
