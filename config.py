"""Конфигурация бота. Все настройки читаются из файла .env."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str) -> set[int]:
    """Парсит строку вида '123,456' в множество telegram_id."""
    result: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return result


@dataclass
class Config:
    bot_token: str
    admin_id: int
    invite_code: str
    allowed_ids: set[int] = field(default_factory=set)
    default_timezone: str = "Europe/Moscow"
    db_path: str = "habits.db"
    group_chat_id: int | None = None
    vpn_prize_urls: list[str] = field(default_factory=list)
    deepseek_api_key: str = ""

    @property
    def db_url(self) -> str:
        """URL для async-движка SQLAlchemy (aiosqlite)."""
        return f"sqlite+aiosqlite:///{self.db_path}"


def load_config() -> Config:
    """Собирает конфигурацию из переменных окружения."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather."
        )

    admin_raw = os.getenv("ADMIN_ID", "0").strip()
    admin_id = int(admin_raw) if admin_raw.isdigit() else 0

    group_raw = os.getenv("GROUP_CHAT_ID", "").strip()
    group_chat_id = int(group_raw) if group_raw.lstrip("-").isdigit() else None

    vpn_urls = []
    for key in ("VPN_PRIZE_1ST", "VPN_PRIZE_2ND", "VPN_PRIZE_3RD"):
        url = os.getenv(key, "").strip()
        if url:
            vpn_urls.append(url)

    return Config(
        bot_token=token,
        admin_id=admin_id,
        invite_code=os.getenv("INVITE_CODE", "").strip(),
        allowed_ids=_parse_ids(os.getenv("ALLOWED_IDS", "")),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow").strip(),
        db_path=os.getenv("DB_PATH", "habits.db").strip(),
        group_chat_id=group_chat_id,
        vpn_prize_urls=vpn_urls,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
    )


# Глобальный экземпляр конфигурации, доступный во всех модулях.
config = load_config()
