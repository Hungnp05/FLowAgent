from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine

from flowagent.db import crud
from flowagent.db.app_settings import SettingKey, get_setting, set_setting
from flowagent.db.schemas import TaskCreate
from flowagent.db.session import session_scope
from flowagent.errors import InvalidPinError, SecretDecryptionError
from flowagent.security import reset_pin
from flowagent.security.pin import hash_pin, validate_new_pin, verify_pin
from flowagent.security.pin_guard import (
    MAX_PIN_ATTEMPTS,
    PIN_LOCKOUT,
    attempt_unlock,
    change_pin,
    create_pin,
    has_pin,
    reset_pin_and_api_keys,
)
from flowagent.security.secret_box import SecretBox, load_or_create_secret_box
from tests.conftest import FIXED_NOW

PIN = "2468"


def test_hash_pin_round_trip_and_rejects_wrong_pin() -> None:
    """A stored hash verifies the original PIN only and never contains it in clear text."""
    stored_hash = hash_pin(PIN)
    assert PIN not in stored_hash
    assert verify_pin(PIN, stored_hash)
    assert not verify_pin("1357", stored_hash)


def test_verify_pin_rejects_malformed_hash() -> None:
    """Garbage in the hash column is treated as a mismatch, not a crash."""
    assert not verify_pin(PIN, "")


@pytest.mark.parametrize(
    ("pin", "confirmation"), [("12", "12"), ("12ab", "12ab"), ("1234", "4321")]
)
def test_validate_new_pin_rejects_bad_input(pin: str, confirmation: str) -> None:
    """PINs must be 4-8 digits and typed the same way twice."""
    with pytest.raises(InvalidPinError):
        validate_new_pin(pin, confirmation)


def create_test_pin(engine: Engine) -> None:
    """Store the shared test PIN."""
    with session_scope(engine) as session:
        create_pin(session, PIN, PIN)


def try_unlock(engine: Engine, pin: str, minutes_later: int = 0) -> bool:
    """Attempt an unlock in its own transaction, like the UI does."""
    with session_scope(engine) as session:
        now = FIXED_NOW + timedelta(minutes=minutes_later)
        return attempt_unlock(session, pin, now).is_unlocked


def test_create_pin_then_unlock(engine: Engine) -> None:
    """After creating a PIN the correct value unlocks and a wrong one does not."""
    create_test_pin(engine)
    with session_scope(engine) as session:
        assert has_pin(session)
    assert try_unlock(engine, PIN)
    assert not try_unlock(engine, "0000")


def test_failed_attempts_persist_and_trigger_lockout(engine: Engine) -> None:
    """Wrong PINs are counted across transactions and the limit locks out even the right PIN."""
    create_test_pin(engine)
    for _ in range(MAX_PIN_ATTEMPTS):
        assert not try_unlock(engine, "0000")
    assert not try_unlock(engine, PIN)
    lockout_minutes = int(PIN_LOCKOUT.total_seconds() // 60) + 1
    assert try_unlock(engine, PIN, minutes_later=lockout_minutes)


def test_change_pin_requires_current_pin(engine: Engine) -> None:
    """The PIN changes only when the current PIN is correct."""
    create_test_pin(engine)
    with session_scope(engine) as session:
        assert not change_pin(session, "0000", "9999", "9999", FIXED_NOW).is_unlocked
    with session_scope(engine) as session:
        assert change_pin(session, PIN, "9999", "9999", FIXED_NOW).is_unlocked
    assert try_unlock(engine, "9999")


def test_secret_box_round_trip(tmp_path: Path) -> None:
    """Encrypted text differs from the secret and decrypts back with the same key file."""
    key_path = tmp_path / "secret.key"
    token = load_or_create_secret_box(key_path).encrypt("my-api-key")
    assert "my-api-key" not in token
    assert load_or_create_secret_box(key_path).decrypt(token) == "my-api-key"


def test_secret_box_with_other_key_raises() -> None:
    """Decrypting with a different key fails with a clear domain error."""
    token = SecretBox(Fernet.generate_key()).encrypt("my-api-key")
    with pytest.raises(SecretDecryptionError):
        SecretBox(Fernet.generate_key()).decrypt(token)


def test_reset_pin_keeps_tasks_and_models(engine: Engine) -> None:
    """Resetting removes the PIN and saved keys but leaves tasks and model choices intact."""
    create_test_pin(engine)
    with session_scope(engine) as session:
        crud.create_task(session, TaskCreate(title="Giữ lại"))
        set_setting(session, SettingKey.GEMINI_API_KEY, "encrypted-key")
        set_setting(session, SettingKey.GEMINI_MODEL, "gemini-main")
    with session_scope(engine) as session:
        reset_pin_and_api_keys(session)
    with session_scope(engine) as session:
        assert not has_pin(session)
        assert get_setting(session, SettingKey.GEMINI_API_KEY) is None
        assert get_setting(session, SettingKey.GEMINI_MODEL) == "gemini-main"
        assert [task.title for task in crud.list_tasks(session)] == ["Giữ lại"]


def test_reset_command_cancels_without_confirmation(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command leaves the PIN alone unless the user types the confirmation word."""
    create_test_pin(engine)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    monkeypatch.setattr(reset_pin, "create_db_engine", lambda url: engine)
    assert reset_pin.main([]) == 1
    with session_scope(engine) as session:
        assert has_pin(session)


def test_reset_command_with_yes_flag_resets(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The --yes flag skips the prompt and removes the PIN."""
    create_test_pin(engine)
    monkeypatch.setattr(reset_pin, "create_db_engine", lambda url: engine)
    assert reset_pin.main(["--yes"]) == 0
    with session_scope(engine) as session:
        assert not has_pin(session)
