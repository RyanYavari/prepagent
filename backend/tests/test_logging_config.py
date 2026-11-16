"""Tests for app logging configuration (main.configure_logging)."""

import logging

import pytest

import main


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    names = main._QUIET_LOGGERS
    saved_levels = {n: logging.getLogger(n).level for n in names}
    yield root
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    for n, lvl in saved_levels.items():
        logging.getLogger(n).setLevel(lvl)


def test_sets_root_level_info_and_format(restore_logging):
    root = restore_logging
    root.setLevel(logging.WARNING)
    root.handlers.clear()

    main.configure_logging()

    assert root.level == logging.INFO
    assert len(root.handlers) == 1
    fmt = root.handlers[0].formatter._fmt
    assert "%(name)s" in fmt and "%(levelname)s" in fmt


def test_info_from_agents_is_emitted(restore_logging, caplog):
    root = restore_logging
    root.setLevel(logging.WARNING)
    main.configure_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("agents.rag").info("hello")
    assert "hello" in caplog.text


def test_does_not_add_duplicate_handlers(restore_logging):
    root = restore_logging
    root.handlers.clear()
    main.configure_logging()
    main.configure_logging()
    assert len(root.handlers) == 1


def test_does_not_touch_uvicorn_loggers(restore_logging):
    before = {
        n: (logging.getLogger(n).level, logging.getLogger(n).propagate)
        for n in ("uvicorn", "uvicorn.access", "uvicorn.error")
    }
    main.configure_logging()
    after = {
        n: (logging.getLogger(n).level, logging.getLogger(n).propagate) for n in before
    }
    assert before == after


@pytest.mark.parametrize("name", ["httpx", "httpcore", "openai", "anthropic"])
def test_noisy_libraries_stay_at_warning(restore_logging, name):
    main.configure_logging()
    assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
