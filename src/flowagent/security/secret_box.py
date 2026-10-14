from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from flowagent.errors import SecretDecryptionError


class SecretBox:
    def __init__(self, key: bytes) -> None:
        """Wrap a Fernet key used to encrypt secrets before they are stored."""
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a secret into a URL-safe token string."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt a token produced by encrypt, failing clearly if the key changed."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as error:
            raise SecretDecryptionError(
                "Không giải mã được API key đã lưu (file khoá bí mật đã thay đổi), hãy nhập lại."
            ) from error


def load_or_create_secret_box(key_path: Path) -> SecretBox:
    """Load the encryption key file, generating it on first use."""
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(Fernet.generate_key())
    return SecretBox(key_path.read_bytes())
