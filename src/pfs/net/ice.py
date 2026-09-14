"""Classify the active ICE path (direct vs TURN relay) from WebRTC stats.

Kept free of aiortc imports so it can be unit-tested without the native
dependencies; :meth:`pfs.net.peer.Peer.ice_path` feeds it a ``getStats()``
report.
"""

from __future__ import annotations


def classify_path(report) -> str | None:
    """Return ``"relay"``, ``"direct"`` or ``None`` for a ``getStats()`` report.

    A path is a relay when either the local or the remote candidate of the
    selected (succeeded) candidate pair has ``candidateType == "relay"``.
    Returns ``None`` when no succeeded pair or no candidate type is available.
    """
    stats: dict = {}
    try:
        for stat in report.values():
            stats[stat.id] = stat
    except Exception:  # noqa: BLE001 - best-effort
        return None

    pair = None
    for stat in stats.values():
        if getattr(stat, "type", None) != "candidate-pair":
            continue
        if getattr(stat, "state", None) != "succeeded":
            continue
        if getattr(stat, "nominated", False):
            pair = stat
            break
        if pair is None:
            pair = stat
    if pair is None:
        return None

    types = set()
    for attr in ("localCandidateId", "remoteCandidateId"):
        candidate = stats.get(getattr(pair, attr, None))
        ctype = getattr(candidate, "candidateType", None) if candidate is not None else None
        if ctype:
            types.add(ctype)
    if "relay" in types:
        return "relay"
    if types:
        return "direct"
    return None
