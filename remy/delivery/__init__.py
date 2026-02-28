"""Outbound message delivery with write-ahead queue for crash recovery."""

from remy.delivery.queue import OutboundQueue, QueueStats

__all__ = ["OutboundQueue", "QueueStats"]
