# Используем Python 3.13 (как в вашем проекте)
FROM python:3.13-slim

# Используем официальный образ Playwright, где всё уже настроено
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем ваши Python-пакеты
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Браузеры уже есть в образе, но на всякий случай проверяем именно Chromium
RUN playwright install chromium

# Копируем остальной код проекта
COPY . .

# Запуск бота
CMD ["python", "main.py"]
