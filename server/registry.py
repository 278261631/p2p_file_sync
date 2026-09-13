"""In-memory registry of published shares and presence tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Share:
    id: str
    owner: str
    peer_id: str
    name: str
    entries: list[dict] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(1 for entry in self.entries if entry.get("type") == "file")

    @property
    def total_size(self) -> int:
        return sum(int(entry.get("size", 0)) for entry in self.entries if entry.get("type") == "file")

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "online": True,
            "file_count": self.file_count,
            "total_size": self.total_size,
        }


class Registry:
    """One share per publisher connection (re-publishing replaces the old one)."""

    def __init__(self) -> None:
        self._shares: dict[str, Share] = {}

    def publish(self, owner: str, peer_id: str, name: str, entries: list[dict]) -> Share:
        self.remove_peer(peer_id)
        share = Share(uuid.uuid4().hex[:12], owner, peer_id, name, entries)
        self._shares[share.id] = share
        return share

    def get(self, share_id: str | None) -> Share | None:
        return self._shares.get(share_id) if share_id else None

    def by_name(self, name: str) -> Share | None:
        for share in self._shares.values():
            if share.name == name:
                return share
        return None

    def remove_peer(self, peer_id: str) -> None:
        for share_id in [s.id for s in self._shares.values() if s.peer_id == peer_id]:
            self._shares.pop(share_id, None)

    def list(self) -> list[Share]:
        return sorted(self._shares.values(), key=lambda s: (s.owner, s.name))
