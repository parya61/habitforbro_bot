# Образ Telegram-бота «Дневник привычек».
FROM python:3.12-slim

# UTF-8 и небуферизованный вывод — чтобы логи в docker logs были корректными.
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # БД по умолчанию пишем в /data (туда монтируется том для сохранности).
    DB_PATH=/data/habits.db

WORKDIR /app

# Сначала зависимости — кешируется отдельным слоем.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код.
COPY . .

# Непривилегированный пользователь и каталог данных.
RUN useradd --system --create-home app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

VOLUME ["/data"]

CMD ["python", "bot.py"]
