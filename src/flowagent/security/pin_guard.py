from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session

from flowagent.db.app_settings import SettingKey, delete_setting, get_setting, set_setting
from flowagent.security.pin import hash_pin, validate_new_pin, verify_pin

MAX_PIN_ATTEMPTS = 5
PIN_LOCKOUT_MINUTES = 5
PIN_LOCKOUT = timedelta(minutes=PIN_LOCKOUT_MINUTES)
RESET_SETTING_KEYS = (
    SettingKey.PIN_HASH,
    SettingKey.PIN_FAILED_ATTEMPTS,
    SettingKey.PIN_LOCKED_UNTIL,
    SettingKey.GEMINI_API_KEY,
    SettingKey.GROQ_API_KEY,
)


@dataclass(frozen=True)
class UnlockResult:
    is_unlocked: bool
    message: str


def has_pin(session: Session) -> bool:
    """Report whether a PIN has been created yet."""
    return get_setting(session, SettingKey.PIN_HASH) is not None


def reset_pin_and_api_keys(session: Session) -> None:
    """Remove the PIN, its lockout state and saved API keys while keeping tasks and models."""
    for key in RESET_SETTING_KEYS:
        delete_setting(session, key)


def create_pin(session: Session, pin: str, confirmation: str) -> None:
    """Validate and store a new PIN, replacing any previous one."""
    validate_new_pin(pin, confirmation)
    set_setting(session, SettingKey.PIN_HASH, hash_pin(pin))
    reset_failed_attempts(session)


def locked_until(session: Session, now: datetime) -> datetime | None:
    """Return when the current lockout ends, or None if the PIN is not locked."""
    stored = get_setting(session, SettingKey.PIN_LOCKED_UNTIL)
    if stored is None:
        return None
    lock_end = datetime.fromisoformat(stored)
    return lock_end if lock_end > now else None


def reset_failed_attempts(session: Session) -> None:
    """Clear the failure counter and any lockout."""
    delete_setting(session, SettingKey.PIN_FAILED_ATTEMPTS)
    delete_setting(session, SettingKey.PIN_LOCKED_UNTIL)


def record_failed_attempt(session: Session, now: datetime) -> int:
    """Count a wrong PIN, start a lockout at the limit, and return attempts left."""
    failed_attempts = int(get_setting(session, SettingKey.PIN_FAILED_ATTEMPTS) or 0) + 1
    if failed_attempts >= MAX_PIN_ATTEMPTS:
        set_setting(session, SettingKey.PIN_LOCKED_UNTIL, (now + PIN_LOCKOUT).isoformat())
        delete_setting(session, SettingKey.PIN_FAILED_ATTEMPTS)
        return 0
    set_setting(session, SettingKey.PIN_FAILED_ATTEMPTS, str(failed_attempts))
    return MAX_PIN_ATTEMPTS - failed_attempts


def attempt_unlock(session: Session, pin: str, now: datetime) -> UnlockResult:
    """Check a PIN, counting failures; returns a result instead of raising so failures persist."""
    lock_end = locked_until(session, now)
    if lock_end is not None:
        return UnlockResult(False, f"Nhập sai quá nhiều lần, thử lại sau {lock_end:%H:%M}.")
    if verify_pin(pin, get_setting(session, SettingKey.PIN_HASH) or ""):
        reset_failed_attempts(session)
        return UnlockResult(True, "Đã mở khoá.")
    attempts_left = record_failed_attempt(session, now)
    if attempts_left == 0:
        return UnlockResult(
            False,
            f"Nhập sai {MAX_PIN_ATTEMPTS} lần, trang bị khoá trong {PIN_LOCKOUT_MINUTES} phút.",
        )
    return UnlockResult(False, f"Mã PIN không đúng, còn {attempts_left} lần thử.")


def change_pin(
    session: Session, current_pin: str, new_pin: str, confirmation: str, now: datetime
) -> UnlockResult:
    """Replace the PIN only after the current one is verified."""
    validate_new_pin(new_pin, confirmation)
    result = attempt_unlock(session, current_pin, now)
    if result.is_unlocked:
        create_pin(session, new_pin, confirmation)
    return result
