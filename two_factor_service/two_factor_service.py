from flask import Flask, request, jsonify
import random
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

# Загружаем переменные окружения из .env
load_dotenv()

# Конфигурация базы данных
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": "TrainSafe"
}

app = Flask(__name__)

def get_db_connection():
    """Подключение к базе данных."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
    return None

@app.route('/generate_2fa', methods=['POST'])
def generate_2fa():
    """
    Генерация 2FA-кода и сохранение в базе.
    Принимает JSON с полем user_id.
    """
    data = request.json
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"message": "User ID is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"message": "Failed to connect to the database"}), 500

    try:
        cursor = conn.cursor()

        # Получение username
        cursor.execute("SELECT username FROM users WHERE id = %s;", (user_id,))
        username_row = cursor.fetchone()
        if not username_row:
            return jsonify({"message": "User not found"}), 404
        username = username_row[0]

        # Генерация 2FA-кода
        code = f"{random.randint(100000, 999999)}"
        expires_at = datetime.now() + timedelta(minutes=5)  # Код действует 5 минут

        # Запись кода в таблицу sessions
        insert_query = '''
            INSERT INTO sessions (user_id, username, code, expires_at)
            VALUES (%s, %s, %s, %s);
        '''
        cursor.execute(insert_query, (user_id, username, code, expires_at))
        conn.commit()

        return jsonify({"message": "2FA code generated", "code": code}), 200
    except Error as e:
        return jsonify({"message": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/validate_2fa', methods=['POST'])
def validate_2fa():
    """
    Проверка 2FA-кода.
    Принимает JSON с полями user_id и code.
    Возвращает JSON с полями:
      - "message": текстовое сообщение
      - "user_id": int
      - "role": строка (admin|editor|viewer)
      - "session_id": int
      - "session_expires": строка в ISO-формате
      - "session_token": код 2FA
    """
    data = request.json or {}
    user_id = data.get("user_id")
    input_code = data.get("code")

    if not user_id or not input_code:
        return jsonify({"message": "User ID and code are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"message": "Failed to connect to the database"}), 500

    try:
        cursor = conn.cursor()
        # Берём последнюю запись из sessions
        cursor.execute('''
            SELECT session_id, code, expires_at, is_validated
            FROM sessions
            WHERE user_id = %s
            ORDER BY expires_at DESC
            LIMIT 1
        ''', (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Invalid code"}), 401

        session_id, db_code, db_expires, db_is_validated = row

        # Проверка: не использован ли код ранее
        if db_is_validated:
            return jsonify({"message": "Code already used"}), 401

        # Проверка: не истёк ли
        if datetime.now() > db_expires:
            return jsonify({"message": "Code expired"}), 401

        # Проверка: совпадает ли код
        if db_code != input_code:
            return jsonify({"message": "Invalid code"}), 401

        # Если всё ок, делаем сессию активной
        session_expires = datetime.now() + timedelta(minutes=30)

        update_query = '''
            UPDATE sessions
            SET is_validated = TRUE,
                is_session_active = TRUE,
                session_expires_at = %s
            WHERE session_id = %s
        '''
        cursor.execute(update_query, (session_expires, session_id))
        conn.commit()

        # Получаем роль пользователя
        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        row_role = cursor.fetchone()
        if not row_role:
            return jsonify({"message": "User not found"}), 404
        role = row_role[0]

        return jsonify({
            "message": "2FA validated",
            "user_id": user_id,
            "role": role,
            "session_id": session_id,
            "session_expires": session_expires.isoformat(),
            "session_token": input_code
        }), 200

    except Error as e:
        return jsonify({"message": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


# Если запускаете отдельно:
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6001, debug=True)