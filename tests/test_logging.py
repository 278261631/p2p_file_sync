import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

import pytest

from pfs.common.logging_setup import setup_logging

_EXTRA = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _marked(logger):
    return [h for h in logger.handlers if getattr(h, "_pfs_handler", False)]


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    for logger in [logging.getLogger()] + [logging.getLogger(n) for n in _EXTRA]:
        for handler in _marked(logger):
            logger.removeHandler(handler)
            handler.close()


def test_file_logging_creates_rotating_handler(tmp_path, monkeypatch):
    monkeypatch.delenv("PFS_LOG_MAX_BYTES", raising=False)
    path = setup_logging("test", log_dir=tmp_path, console=False)
    assert path == str(tmp_path / "test.log")

    handlers = _marked(logging.getLogger())
    assert any(isinstance(h, TimedRotatingFileHandler) for h in handlers)

    logging.getLogger("pfs.test").warning("hello file")
    for handler in handlers:
        handler.flush()
    assert "hello file" in (tmp_path / "test.log").read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("PFS_LOG_MAX_BYTES", raising=False)
    setup_logging("a", log_dir=tmp_path, console=False)
    setup_logging("a", log_dir=tmp_path, console=False)
    assert len(_marked(logging.getLogger())) == 1


def test_size_based_rotation_when_max_bytes_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PFS_LOG_MAX_BYTES", "1024")
    setup_logging("test", log_dir=tmp_path, console=False)
    handlers = _marked(logging.getLogger())
    assert any(isinstance(h, RotatingFileHandler) for h in handlers)
    assert not any(isinstance(h, TimedRotatingFileHandler) for h in handlers)


def test_console_only_without_log_dir(monkeypatch):
    monkeypatch.delenv("PFS_LOG_DIR", raising=False)
    assert setup_logging("test", console=True) is None
    assert len(_marked(logging.getLogger())) == 1
