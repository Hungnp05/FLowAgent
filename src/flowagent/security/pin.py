import hashlib
import hmac
import re
import secrets

from flowagent.errors import InvalidPinError

PIN_PATTERN = re.compile(r"\d{4,8}")
HASH_SCHEME = "scrypt"
SALT_BYTES = 16
SCRYPT_COST = 2**14
SCRYPT_BLOCK_SIZE = 8
SCRYPT_PARALLELISM = 1
HASH_SEPARATOR = "$"


def validate_new_pin(pin: str, confirmation: str) -> None:
    """Require a 4-8 digit PIN typed identically twice."""
    if not PIN_PATTERN.fullmatch(pin):
        raise InvalidPinError("Mã PIN phải gồm 4 đến 8 chữ số.")
    if pin != confirmation:
        raise InvalidPinError("Hai lần nhập mã PIN không khớp.")


def derive_pin_hash(pin: str, salt: bytes) -> bytes:
    """Stretch a PIN with scrypt so stored hashes are slow to brute-force."""
    return hashlib.scrypt(
        pin.encode(), salt=salt, n=SCRYPT_COST, r=SCRYPT_BLOCK_SIZE, p=SCRYPT_PARALLELISM
    )


def hash_pin(pin: str) -> str:
    """Return a self-describing 'scrypt$salt$hash' string for storage."""
    salt = secrets.token_bytes(SALT_BYTES)
    return HASH_SEPARATOR.join((HASH_SCHEME, salt.hex(), derive_pin_hash(pin, salt).hex()))


def verify_pin(pin: str, stored_hash: str) -> bool:
    """Check a PIN against a stored hash in constant time."""
    parts = stored_hash.split(HASH_SEPARATOR)
    if len(parts) != len(("scheme", "salt", "hash")) or parts[0] != HASH_SCHEME:
        return False
    _, salt_hex, hash_hex = parts
    return hmac.compare_digest(derive_pin_hash(pin, bytes.fromhex(salt_hex)).hex(), hash_hex)
