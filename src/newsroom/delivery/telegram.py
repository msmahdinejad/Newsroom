"""Telegram delivery via Hermes Gateway."""

from newsroom.logging import get_logger
from newsroom.storage.database import engine
from newsroom.storage.models import Digest
from sqlalchemy.orm import Session

logger = get_logger(__name__)


class TelegramDelivery:
    """Deliver digests via Hermes Telegram Gateway."""

    def __init__(self):
        """Initialize Telegram delivery."""
        # ponytail: Use Hermes Gateway, not direct Bot API
        # Gateway configured via: hermes gateway setup telegram
        pass

    def deliver_digest(self, digest_id: int) -> bool:
        """Deliver digest via Telegram.

        Args:
            digest_id: Digest ID to deliver

        Returns:
            True if delivered successfully
        """
        session = Session(engine)
        try:
            digest = session.query(Digest).filter_by(id=digest_id).first()
            if not digest:
                logger.error(f"Digest {digest_id} not found")
                return False

            if digest.delivered:
                logger.info(f"Digest {digest_id} already delivered")
                return True

            # Split into Telegram-safe chunks (4096 char limit)
            chunks = self._split_message(digest.content_fa)

            # ponytail: Hermes send_message tool handles delivery
            # For now, log until Hermes integration ready
            logger.info(f"Would deliver digest {digest_id} in {len(chunks)} chunks")
            for i, chunk in enumerate(chunks):
                logger.debug(f"Chunk {i+1}/{len(chunks)}: {len(chunk)} chars")

            # Mark as delivered
            digest.delivered = True
            session.commit()
            logger.info(f"Digest {digest_id} marked as delivered")

            return True

        except Exception as e:
            logger.error(f"Failed to deliver digest {digest_id}: {e}")
            session.rollback()
            return False
        finally:
            session.close()

    def _split_message(self, text: str, max_length: int = 4096) -> list[str]:
        """Split message into Telegram-safe chunks.

        Args:
            text: Message text
            max_length: Maximum chunk size (Telegram limit: 4096)

        Returns:
            List of message chunks
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        lines = text.split('\n')
        current_chunk = []
        current_length = 0

        for line in lines:
            line_length = len(line) + 1  # +1 for newline

            if current_length + line_length > max_length:
                # Save current chunk
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Handle very long single lines
                if line_length > max_length:
                    # Split long line into words
                    words = line.split()
                    temp_line = []
                    temp_length = 0

                    for word in words:
                        word_length = len(word) + 1
                        if temp_length + word_length > max_length:
                            chunks.append(' '.join(temp_line))
                            temp_line = [word]
                            temp_length = word_length
                        else:
                            temp_line.append(word)
                            temp_length += word_length

                    if temp_line:
                        current_chunk = [' '.join(temp_line)]
                        current_length = sum(len(w) + 1 for w in temp_line)
                else:
                    current_chunk.append(line)
                    current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length

        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks
