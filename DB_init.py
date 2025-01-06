import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import csv

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


def import_csv_to_table(conn, csv_file_path):
    """Импорт данных из CSV в таблицу train_data с обработкой ошибок"""
    if not os.path.exists(csv_file_path):
        print(f"Файл {csv_file_path} не найден!")
        return

    try:
        cursor = conn.cursor()
        with open(csv_file_path, mode='r') as file:
            reader = csv.reader(file)
            headers = next(reader)  # Пропустить заголовки
            for row_number, row in enumerate(reader, start=2):  # Нумерация строк CSV начинается с 2 (1-я строка - заголовок)
                try:
                    insert_query = '''
                        INSERT IGNORE INTO train_data (
                            Loan_ID, Customer_ID, Loan_Status, Current_Loan_Amount, Term,
                            Credit_Score, Annual_Income, Years_in_current_job, Home_Ownership, Purpose,
                            Monthly_Debt, Years_of_Credit_History, Months_since_last_delinquent,
                            Number_of_Open_Accounts, Number_of_Credit_Problems,
                            Current_Credit_Balance, Maximum_Open_Credit, Bankruptcies, Tax_Liens
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    '''
                    cursor.execute(insert_query, row)
                except Error as e:
                    print(f"Ошибка при вставке данных в строке {row_number}: {e}")
            conn.commit()
            print("Данные успешно импортированы в таблицу 'train_data'.")
    except Error as e:
        print(f"Ошибка при импорте данных из CSV: {e}")
    finally:
        cursor.close()

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
                ('admin_user', 'adminpass', 'admin', '88005553535'),
                ('editor_user', 'editorpass', 'editor', '88005553535'),
                ('viewer_user', 'viewerpass', 'viewer', '88005553535');
            '''
            cursor.execute(insert_query)
            conn.commit()
            print("Данные успешно вставлены в таблицу 'users'.")

            # Создание таблицы sessions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    code VARCHAR(6) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    is_validated BOOLEAN DEFAULT FALSE,
                    session_expires_at DATETIME NULL,
                    is_session_active BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
            ''')
            print("Таблица 'sessions' успешно создана или уже существует.")

            # Создание таблицы logs
            cursor.execute('''
                            CREATE TABLE IF NOT EXISTS logs (
                                log_id INT AUTO_INCREMENT PRIMARY KEY,
                                session_id INT NOT NULL,
                                user_id INT NOT NULL,
                                username VARCHAR(50) NOT NULL,
                                action VARCHAR(255) NOT NULL,
                                details TEXT,
                                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                ip_address VARCHAR(45),
                                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                            );
                        ''')
            print("Таблица 'logs' успешно создана или уже существует.")

            # Создание таблицы train_data
            cursor.execute('''
                            CREATE TABLE IF NOT EXISTS train_data (
                                Loan_ID VARCHAR(36) PRIMARY KEY,
                                Customer_ID VARCHAR(36),
                                Loan_Status ENUM('Approved', 'Rejected', 'Fully Paid') NOT NULL,
                                Current_Loan_Amount DECIMAL(10,2),
                                Term VARCHAR(10),
                                Credit_Score INT NULL,
                                Annual_Income FLOAT,
                                Years_in_current_job VARCHAR(50),
                                Home_Ownership ENUM('Rent', 'Mortgage', 'Own', 'Other'),
                                Purpose VARCHAR(255),
                                Monthly_Debt FLOAT,
                                Years_of_Credit_History FLOAT,
                                Months_since_last_delinquent INT NULL,
                                Number_of_Open_Accounts TINYINT,
                                Number_of_Credit_Problems TINYINT,
                                Current_Credit_Balance DECIMAL(15,2),
                                Maximum_Open_Credit DECIMAL(15,2),
                                Bankruptcies TINYINT,
                                Tax_Liens TINYINT
                            );
                        ''')
            print("Таблица 'train_data' успешно создана или уже существует.")

            # Импорт данных из CSV
            import_csv_to_table(conn, 'credit_train.csv')

        except Error as e:
            print(f"Ошибка при инициализации базы данных: {e}")
        finally:
            cursor.close()
            conn.close()
            print("Соединение с MySQL закрыто.")

# Запуск функции
if __name__ == "__main__":
    init_database()