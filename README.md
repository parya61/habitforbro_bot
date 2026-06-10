# 📔 Дневник привычек — Telegram-бот

Закрытый бот для отслеживания привычек и ведения личного дневника в группе
до 50 человек (друзья и семья). Мотивация через прогресс: серии (streak),
статистика, рейтинг, реакции и достижения.

## Возможности

- ✅ Привычки: бинарные (да/нет) и количественные (например, 50 отжиманий).
- 🔐 **Приватность привычки выбирается при создании**: «видят все участники»
  или «скрыть ото всех» (видишь только ты). Меняется в карточке привычки.
- 🔁 Периодичность: каждый день / по дням недели / N раз в неделю.
- 🔥 Серии с учётом периодичности и «заморозкой» (до 2 пропусков в месяц).
- 📈 Текстовый трекер за 30 дней, статистика за неделю/месяц.
- 📔 Дневник с подсказками дня и настроением (по умолчанию приватный).
- 🏆 Рейтинг участников (по проценту/серии/отметкам) — только по публичным привычкам.
- 👥 Раздел «Участники» с публичными привычками и реакциями (🔥 👏 💪).
- 🏅 Достижения за серии 7/30/100 дней, ранние отметки и т.п.
- ⏰ Напоминания, утренние/вечерние рассылки и еженедельный отчёт.

## Технологии

Python 3.11+, aiogram 3.x, SQLAlchemy 2.x (async) + SQLite (aiosqlite),
APScheduler, python-dotenv. Работает через long polling — публичный IP не нужен.

## Установка

1. Создай бота у [@BotFather](https://t.me/BotFather) командой `/newbot` и получи токен.
   Свой `telegram_id` можно узнать у [@userinfobot](https://t.me/userinfobot).
2. Установи зависимости:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Скопируй `.env.example` в `.env` и заполни:
   ```env
   BOT_TOKEN=токен_от_botfather
   ADMIN_ID=твой_telegram_id
   INVITE_CODE=кодовое_слово   # бот спросит его при первом /start
   ALLOWED_IDS=                # либо список разрешённых id через запятую
   DEFAULT_TIMEZONE=Europe/Moscow
   DB_PATH=habits.db
   ```

## Запуск локально

```bash
python bot.py
```

База `habits.db` создастся автоматически при первом запуске.

## Контроль доступа

Бот закрытый. Пускаем по правилам (в порядке приоритета):
- `ADMIN_ID` и id из `ALLOWED_IDS` входят без кода;
- если задан `INVITE_CODE` — новый пользователь вводит его при первом `/start`;
- если `INVITE_CODE` пуст и `ALLOWED_IDS` пуст — вход открыт всем (для теста).

## Команды

`/start`, `/today`, `/habits`, `/diary`, `/stats`, `/leaderboard`, `/help`,
`/settings`, `/members`.

## Развёртывание на сервере/ноутбуке (systemd)

Создай `/etc/systemd/system/habits-bot.service`:

```ini
[Unit]
Description=Telegram Habits Bot
After=network-online.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/habits-bot
ExecStart=/home/youruser/habits-bot/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Активация и автозапуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now habits-bot
sudo systemctl status habits-bot   # проверить статус
journalctl -u habits-bot -f        # смотреть логи
```

## Структура проекта

```
habits-bot/
├── bot.py              # точка входа (long polling)
├── config.py           # конфигурация из .env
├── states.py           # FSM-состояния
├── db/                 # модели и запросы (SQLAlchemy async)
├── handlers/           # обработчики разделов бота
├── keyboards/          # клавиатуры интерфейса
├── middlewares/        # контроль доступа + сессия БД
└── services/           # серии, статистика, достижения, планировщик
```
