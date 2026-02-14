import sqlite3

# Укажите имя вашего файла базы данных!
# Если он называется иначе, замените 'database.db' на ваше имя
DB_NAME = 'database.db'


def repair():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Добавляем недостающую колонку физически
        cursor.execute("ALTER TABLE global_settings ADD COLUMN value_str TEXT")

        conn.commit()
        conn.close()
        print("✅ База данных успешно обновлена! Колонка value_str добавлена.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    repair()