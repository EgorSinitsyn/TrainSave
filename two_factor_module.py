import random
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
# from twilio.rest import Client  # Установите Twilio, если планируете отправлять SMS

# Загружаем переменные окружения из .env файла
load_dotenv()

def get_db_connection():
    """Подключение к MySQL."""
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database="TrainSafe"
        )
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к MySQL: {e}")
        return None

def generate_2fa_code(user_id):
    """Генерация 2FA-кода и сохранение в таблицу."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            code = f"{random.randint(100000, 999999)}"
            expires_at = datetime.now() + timedelta(minutes=5)  # Код действует 5 минут

            # Сохранение кода в таблицу
            insert_query = '''
                INSERT INTO two_factor_codes (user_id, code, expires_at)
                VALUES (%s, %s, %s);
            '''
            cursor.execute(insert_query, (user_id, code, expires_at))
            conn.commit()

            # Получение номера телефона пользователя
            cursor.execute("SELECT phone_number FROM users WHERE id = %s;", (user_id,))
            phone_number = cursor.fetchone()[0]

            print(f"Сгенерирован 2FA-код: {code} для пользователя {user_id}. Телефон: {phone_number}")

            # Отправка SMS (реализуйте с Twilio или другим API)
            # send_sms(phone_number, code)

            return code
        except Error as e:
            print(f"Ошибка при генерации 2FA-кода: {e}")
        finally:
            cursor.close()
            conn.close()

def validate_2fa_code(user_id, input_code):
    """Проверка 2FA-кода."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Проверяем код
            query = '''
                SELECT code, expires_at 
                FROM two_factor_codes
                WHERE user_id = %s
                ORDER BY expires_at DESC 
                LIMIT 1;
            '''
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if not result:
                return False, "Неверный код."

            code, expires_at = result

            # Проверка на истечение срока действия
            if datetime.now() > expires_at:
                return False, "Код истёк."

            if code != input_code:
                return False, "Неверный код."

            # Удаление использованного кода
            delete_query = "DELETE FROM two_factor_codes WHERE user_id = %s;"
            cursor.execute(delete_query, (user_id,))
            conn.commit()

            return True, "Код успешно подтверждён."
        except Error as e:
            print(f"Ошибка при проверке 2FA-кода: {e}")
            return False, "Ошибка системы."
        finally:
            if cursor:
                cursor.close()
            conn.close()
    else:
        return False, "Ошибка подключения к базе данных."

# Реализация функции отправки SMS
# def send_sms(phone_number, code):
#     """Отправка SMS с помощью Twilio."""
#     account_sid = os.getenv("TWILIO_ACCOUNT_SID")
#     auth_token = os.getenv("TWILIO_AUTH_TOKEN")
#     from_number = os.getenv("TWILIO_PHONE_NUMBER")
#
#     client = Client(account_sid, auth_token)
#     message = client.messages.create(
#         body=f"Ваш одноразовый код: {code}",
#         from_=from_number,
#         to=phone_number
#     )
#     print(f"SMS отправлено на номер {phone_number}: {message.sid}")