import sqlite3

def migrate():
    # Укажите точное имя вашего файла базы данных!
    db_name = 'database.db' 
    
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        print("🔍 Начинаю миграцию базы данных...")

        # 1. Добавляем колонку value_str в global_settings (если её еще нет)
        cursor.execute("PRAGMA table_info(global_settings)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'value_str' not in columns:
            cursor.execute("ALTER TABLE global_settings ADD COLUMN value_str TEXT")
            print("✅ Колонка 'value_str' добавлена в global_settings.")

        # 2. Создаем таблицу категорий для магазина
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        print("✅ Таблица 'stock_categories' готова.")

        # 3. Создаем таблицу товаров в наличии
        # ВНИМАНИЕ: Если таблица была создана неправильно ранее, мы её пересоздадим
        cursor.execute("DROP TABLE IF EXISTS stock_items") 
        cursor.execute("""
            CREATE TABLE stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                photo_id TEXT,
                description TEXT,
                size TEXT,
                price REAL,
                is_available BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(category_id) REFERENCES stock_categories(id)
            )
        """)
        print("✅ Таблица 'stock_items' создана и связана с магазином.")

        conn.commit()
        conn.close()
        print("\n🚀 Миграция успешно завершена! Теперь можно запускать бота.")

    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")

if __name__ == "__main__":
    migrate()