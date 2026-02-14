# Используем Python 3.13 (как в вашем проекте)
FROM python:3.13-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем зависимости для компиляции некоторых библиотек
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта в контейнер
COPY . .

# Создаем папку для базы данных (если она лежит в корне)
# Чтобы данные не пропадали при перезагрузке, базу нужно подключать через volumes
RUN mkdir -p database

# Команда для запуска бота
CMD ["python", "main.py"]