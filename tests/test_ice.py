from pfs.net.ice import classify_path


class _Stat:
    def __init__(self, stat_id, stat_type, **fields):
        self.id = stat_id
        self.type = stat_type
        for key, value in fields.items():
            setattr(self, key, value)


def _report(*stats):
    report = {}
    for stat in stats:
        report[stat.id] = stat
    return report


def _pair(state="succeeded", nominated=True):
    return _Stat(
        "pair", "candidate-pair", state=state, nominated=nominated,
        localCandidateId="local", remoteCandidateId="remote",
    )


def test_relay_when_local_candidate_is_relay():
    report = _report(
        _pair(),
        _Stat("local", "local-candidate", candidateType="relay"),
        _Stat("remote", "remote-candidate", candidateType="srflx"),
    )
    assert classify_path(report) == "relay"


def test_relay_when_remote_candidate_is_relay():
    report = _report(
        _pair(),
        _Stat("local", "local-candidate", candidateType="host"),
        _Stat("remote", "remote-candidate", candidateType="relay"),
    )
    assert classify_path(report) == "relay"


def test_direct_when_no_relay():
    report = _report(
        _pair(),
        _Stat("local", "local-candidate", candidateType="host"),
        _Stat("remote", "remote-candidate", candidateType="srflx"),
    )
    assert classify_path(report) == "direct"


def test_ignores_non_succeeded_pairs():
    report = _report(
        _pair(state="failed"),
        _Stat("local", "local-candidate", candidateType="relay"),
        _Stat("remote", "remote-candidate", candidateType="host"),
    )
    assert classify_path(report) is None


def test_none_without_pair_or_types():
    assert classify_path(_report()) is None
    report = _report(_pair())
    assert classify_path(report) is None
