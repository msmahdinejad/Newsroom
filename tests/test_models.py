"""Test database models."""

from newsroom.storage.models import Source


def test_source_creation(db_session):
    """Test creating a source."""
    source = Source(
        name="Test Feed",
        type="rss",
        url="https://example.com/feed.xml",
        language="en",
        priority="high",
    )
    db_session.add(source)
    db_session.commit()

    assert source.id is not None
    assert source.name == "Test Feed"
    assert source.consecutive_failures == 0
    assert source.enabled is True
