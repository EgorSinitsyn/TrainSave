import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os

# Загружаем переменные окружения из .env файла
load_dotenv()

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),  # Адрес сервера MySQL из .env
            port=os.getenv("DB_PORT"),  # Порт из .env
            user=os.getenv("DB_USER"),  # Имя пользователя из .env
            password=os.getenv("DB_PASSWORD"),  # Пароль из .env
        )
        if conn.is_connected():
            print("Подключение к MySQL успешно!")
            return conn
    except Error as e:
        print(f"Ошибка подключения к MySQL: {e}")
        return None

def init_database():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Создание базы данных, если её ещё нет
            cursor.execute("CREATE DATABASE IF NOT EXISTS TrainSafe;")
            print("База данных 'TrainSafe' успешно создана или уже существует.")

            # Подключение к созданной базе данных
            conn.database = 'TrainSafe'

            # Создание таблицы users
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role ENUM('admin', 'editor', 'viewer') DEFAULT 'viewer',
                    phone_number VARCHAR(15)
                );
            ''')
            print("Таблица 'users' успешно создана или уже существует.")

            # Вставка данных в таблицу users
            insert_query = '''
                INSERT INTO users (username, password, role, phone_number) 
                VALUES 
                ('admin_user', 'adminpass', 'admin', '9637855010'),
                ('editor_user', 'editorpass', 'editor', '9637855010'),
                ('viewer_user', 'viewerpass', 'viewer', '9637855010');
            '''
            cursor.execute(insert_query)
            conn.commit()
            print("Данные успешно вставлены в таблицу 'users'.")

            # Создание таблицы 2FA-кодов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS two_factor_codes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    code VARCHAR(6) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
            ''')
            print("Таблица 'two_factor_codes' успешно создана или уже существует.")

            # Создание таблицы logs
            cursor.execute('''
                            CREATE TABLE IF NOT EXISTS logs (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                user_id INT NOT NULL,
                                action VARCHAR(255) NOT NULL,
                                details TEXT,
                                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                ip_address VARCHAR(45),
                                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                            );
                        ''')
            print("Таблица 'logs' успешно создана или уже существует.")

        except Error as e:
            print(f"Ошибка при инициализации базы данных: {e}")
        finally:
            cursor.close()
            conn.close()
            print("Соединение с MySQL закрыто.")

# Запуск функции
if __name__ == "__main__":
    init_database()