from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import ipaddress
from two_factor_module import generate_2fa_code, validate_2fa_code

# Загрузка переменных окружения из .env файла
load_dotenv()

# Конфигурация базы данных
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": "TrainSafe"
}

# Разрешенные IP-адреса
ALLOWED_IP_RANGES = ["127.0.0.1",
               "192.168.1.100/24"
               ]

# Создание приложения Flask
app = Flask(__name__)

def get_db_connection():
    """Подключение к базе данных"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None

def is_ip_allowed(ip):
    """Проверяет, входит ли IP-адрес в разрешённые диапазоны"""
    for allowed_range in ALLOWED_IP_RANGES:
        if ipaddress.ip_address(ip) in ipaddress.ip_network(allowed_range):
            return True
    return False

@app.route('/login', methods=['POST'])
def login():
    """Обработчик маршрута для авторизации"""
    # Получение данных из запроса
    data = request.json
    username = data.get("username")
    password = data.get("password")
    client_ip = request.remote_addr

    # Проверка IP-адреса
    if not is_ip_allowed(client_ip):
        return jsonify({"message": "Access denied: Invalid IP address"}), 403

    # Проверка логина и пароля в базе данных
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "SELECT id, role FROM users WHERE username = %s AND password = %s;"
            cursor.execute(query, (username, password))
            result = cursor.fetchone()

            # Если результат найден
            if result:
                user_id, role = result
                # Генерация 2FA-кода для пользователя
                code = generate_2fa_code(user_id)
                return jsonify({
                    "message": "Login successful. 2FA code generated.",
                    "role": role,
                    "user_id": user_id
                }), 200
            else:
                return jsonify({"message": "Invalid username or password"}), 401
        except Error as e:
            return jsonify({"message": f"Database error: {e}"}), 500
        finally:
            # Убедитесь, что курсор и соединение закрыты
            if cursor:
                cursor.close()
            conn.close()
    else:
        return jsonify({"message": "Failed to connect to the database"}), 500

@app.route('/validate_2fa', methods=['POST'])
def validate_2fa():
    """Эндпоинт для проверки 2FA-кода."""
    data = request.json
    user_id = data.get("user_id")
    input_code = data.get("code")

    if not user_id or not input_code:
        return jsonify({"message": "User ID and code are required"}), 400

    is_valid, message = validate_2fa_code(user_id, input_code)
    if is_valid:
        return jsonify({"message": "2FA validation successful"}), 200
    else:
        return jsonify({"message": message}), 401

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6000, debug=True)