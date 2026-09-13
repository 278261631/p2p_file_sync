import json

from server.accounts import AccountStore, hash_password, verify_password_hash
from server.registry import Registry


def test_password_hash_roundtrip():
    encoded = hash_password("s3cret")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password_hash("s3cret", encoded)
    assert not verify_password_hash("wrong", encoded)


def test_account_store_plaintext_and_hash(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {"name": "alice", "password": "pw1"},
                    {"name": "bob", "password_hash": hash_password("pw2")},
                ]
            }
        ),
        encoding="utf-8",
    )
    store = AccountStore(path)
    assert store.names() == ["alice", "bob"]
    assert store.verify("alice", "pw1")
    assert not store.verify("alice", "nope")
    assert store.verify("bob", "pw2")
    assert not store.verify("bob", "pw1")
    assert not store.verify("carol", "pw1")


def test_account_store_reloads_on_change(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"users": [{"name": "alice", "password": "pw"}]}), encoding="utf-8")
    store = AccountStore(path)
    assert store.verify("alice", "pw")

    path.write_text(
        json.dumps({"users": [{"name": "alice", "password": "pw"}, {"name": "carol", "password": "x"}]}),
        encoding="utf-8",
    )
    assert store.names() == ["alice", "carol"]


def test_registry_publish_and_remove():
    registry = Registry()
    entries = [{"path": "a.txt", "type": "file", "size": 10}, {"path": "d", "type": "dir", "size": 0}]
    share = registry.publish("alice", "peer-1", "docs", entries)
    assert registry.get(share.id) is share
    assert registry.by_name("docs") is share
    assert share.file_count == 1
    assert share.total_size == 10
    assert registry.list()[0].summary()["owner"] == "alice"

    registry.remove_peer("peer-1")
    assert registry.get(share.id) is None


def test_registry_republish_replaces_peer_share():
    registry = Registry()
    first = registry.publish("alice", "peer-1", "one", [])
    second = registry.publish("alice", "peer-1", "two", [])
    assert registry.get(first.id) is None
    assert registry.get(second.id) is second
    assert len(registry.list()) == 1
