import argparse
import sys

from flowagent.config import get_settings
from flowagent.db.session import create_db_engine, session_scope
from flowagent.security.pin_guard import reset_pin_and_api_keys

CONFIRMATION_WORD = "RESET"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line options for the reset command."""
    parser = argparse.ArgumentParser(
        description="Xoá mã PIN và API key đã lưu; công việc và dự án được giữ nguyên."
    )
    parser.add_argument("--yes", action="store_true", help="Bỏ qua bước xác nhận.")
    return parser.parse_args(argv)


def is_confirmed() -> bool:
    """Ask the user to type the confirmation word before anything is deleted."""
    answer = input(f"Gõ {CONFIRMATION_WORD} để xoá mã PIN và API key đã lưu: ")
    return answer.strip() == CONFIRMATION_WORD


def main(argv: list[str] | None = None) -> int:
    """Reset the PIN and saved API keys in the configured database."""
    args = parse_args(argv)
    if not args.yes and not is_confirmed():
        print("Đã huỷ, không có gì bị thay đổi.")
        return 1
    with session_scope(create_db_engine(get_settings().database_url)) as session:
        reset_pin_and_api_keys(session)
    print("Đã xoá mã PIN và API key đã lưu. Mở trang Cài đặt API để tạo mã PIN mới.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
