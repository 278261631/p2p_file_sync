import hashlib

from pfs.common import protocol as P
from pfs.common.chunker import CHUNK_SIZE, PartialFile, chunk_count, chunk_ranges, file_sha256
from pfs.common.invite import Invite
from pfs.common.manifest import TYPE_DIR, TYPE_FILE, expand_selection, scan_folder


def test_chunk_frame_roundtrip():
    payload = b"hello world" * 1000
    digest = hashlib.sha256(payload).digest()
    frame = P.encode_chunk(7, 123456, digest, payload)
    rid, offset, got_digest, got_payload = P.decode_chunk(frame)
    assert (rid, offset, got_digest, got_payload) == (7, 123456, digest, payload)


def test_chunk_frame_rejects_short_digest():
    try:
        P.encode_chunk(1, 0, b"too short", b"x")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_scan_folder(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"aaa")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"bbbb")
    (tmp_path / "empty").mkdir()

    entries = scan_folder(str(tmp_path))
    by_path = {e.path: e for e in entries}

    assert by_path["a.txt"].type == TYPE_FILE
    assert by_path["a.txt"].size == 3
    assert by_path["sub"].type == TYPE_DIR
    assert by_path["sub/b.bin"].size == 4
    assert by_path["empty"].type == TYPE_DIR


def test_expand_selection(tmp_path):
    (tmp_path / "root.txt").write_bytes(b"r")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "one.txt").write_bytes(b"1")
    (sub / "two.txt").write_bytes(b"22")

    entries = scan_folder(str(tmp_path))

    only = expand_selection(entries, ["sub/one.txt"])
    assert [e.path for e in only] == ["sub/one.txt"]

    whole_dir = expand_selection(entries, ["sub"])
    assert sorted(e.path for e in whole_dir) == ["sub/one.txt", "sub/two.txt"]

    deduped = expand_selection(entries, ["sub", "sub/one.txt"])
    assert sorted(e.path for e in deduped) == ["sub/one.txt", "sub/two.txt"]


def test_chunk_math():
    assert chunk_count(0) == 0
    assert chunk_count(CHUNK_SIZE) == 1
    assert chunk_count(CHUNK_SIZE + 1) == 2
    ranges = list(chunk_ranges(CHUNK_SIZE + 5))
    assert ranges == [(0, 0, CHUNK_SIZE), (1, CHUNK_SIZE, 5)]


def test_partial_file_resume(tmp_path, monkeypatch):
    monkeypatch.setattr("pfs.common.chunker.CHUNK_SIZE", 10)
    target = tmp_path / "out.bin"
    data = b"0123456789" * 2
    partial = PartialFile(str(target), len(data))
    assert partial.total_chunks == 2

    partial.write_chunk(0, data[:10])
    partial.save_state()
    assert partial.missing() == [1]

    resumed = PartialFile(str(target), len(data))
    assert resumed.received == {0}
    resumed.write_chunk(1, data[10:])
    resumed.finish()

    assert target.read_bytes() == data


def test_partial_file_verify(tmp_path):
    target = tmp_path / "v.bin"
    data = b"abcdef"
    partial = PartialFile(str(target), len(data))
    partial.write_chunk(0, data)
    assert partial.compute_sha256() == hashlib.sha256(data).hexdigest()
    partial.finish()
    assert file_sha256(str(target)) == hashlib.sha256(data).hexdigest()


def test_invite_roundtrip():
    inv = Invite("relay.example.com", 8765, "abc123", "tok-xyz", tls=True)
    code = inv.to_code()
    assert code.startswith("PFS1.")
    back = Invite.from_code(code)
    assert back == inv
    assert back.ws_url == "wss://relay.example.com:8765/ws"


def test_invite_rejects_garbage():
    try:
        Invite.from_code("not-a-code")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
