FROM python:3.11-slim

# Устанавливаем Chrome и драйвер
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium

WORKDIR /app

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё остальное
COPY . .

# Запускаем приложение
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]