"""
Password hashing: where it runs.

Lives here rather than in tests/unit because argon2-cffi ships in the ``api`` extra,
which CI's unit job does not install.
"""

import threading

import pytest

pytest.importorskip("argon2")
pytest.importorskip("fastapi")

from chesssnake.api import auth  # noqa: E402


def test_argon2_only_ever_runs_on_the_dedicated_pool(monkeypatch):
    """
    Regression for 0.12.0. Argon2 allocates 19 MiB per hash, and glibc keeps that
    in the allocating thread's arena after it is freed. A cap on concurrency
    alone let every one of the server's 40 worker threads keep its own block:
    measured at 700+ MiB after one burst of 40 logins, pinning a 512 MiB container
    at its limit. Only a fixed set of threads may hash.
    """
    real = auth._hasher()
    seen = set()
    lock = threading.Lock()

    class Recording:
        """Stands in for the PasswordHasher (which has __slots__), noting the thread."""

        def __getattr__(self, name):
            attr = getattr(real, name)
            if name not in ("hash", "verify"):
                return attr

            def wrapper(*args, **kwargs):
                with lock:
                    seen.add(threading.current_thread().name)
                return attr(*args, **kwargs)

            return wrapper

    monkeypatch.setattr(auth, "_hasher", lambda: Recording())
    stored = auth.hash_password("correct-horse-battery")

    callers = [
        threading.Thread(target=auth.verify_password, args=(stored if i % 2 else None, "correct-horse-battery"))
        for i in range(12)
    ]
    for t in callers:
        t.start()
    for t in callers:
        t.join(timeout=30)

    assert seen, "nothing was hashed"
    assert all(name.startswith("chesssnake-argon2") for name in seen), seen
    assert len(seen) <= auth.MAX_CONCURRENT_HASHES, seen


def test_hashing_still_round_trips():
    stored = auth.hash_password("correct-horse-battery")
    assert auth.verify_password(stored, "correct-horse-battery") is True
    assert auth.verify_password(stored, "wrong-horse-battery") is False
    assert auth.verify_password(None, "anything-at-all") is False
