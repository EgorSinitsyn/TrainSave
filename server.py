# server.py
from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import ipaddress
import requests

# Загружаем переменные окружения
load_dotenv()

# Конфигурация БД (для проверки логина/пароля)
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": "TrainSafe"
}

# Разрешённые IP
ALLOWED_IP_RANGES = [
    "127.0.0.1",
    "192.168.1.100/24"
]

# URL микросервиса 2FA
TWO_FACTOR_SERVICE_URL = "http://127.0.0.1:6001"

app = Flask(__name__)

# ========== ФУНКЦИИ ДЛЯ ПОДКЛЮЧЕНИЯ К БД ==========
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
    """Проверяем, входит ли IP-адрес в разрешенные диапазоны."""
    for allowed_range in ALLOWED_IP_RANGES:
        if ipaddress.ip_address(ip) in ipaddress.ip_network(allowed_range):
            return True
    return False

# ========== РЕАЛИЗАЦИЯ ЦЕПОЧКИ ОТВЕТСТВЕННОСТИ ==========

class Handler:
    """Базовый обработчик в цепочке ответственности."""
    def __init__(self):
        self._next_handler = None

    def set_next(self, handler):
        """Устанавливаем следующий обработчик в цепочке."""
        self._next_handler = handler
        return handler  # Позволяет делать chain.set_next(a).set_next(b)...

    def handle(self, data):
        """
        Пытается обработать запрос.
        Если обработчик не может/не хочет обрабатывать, передаёт дальше.
        """
        if self._next_handler:
            return self._next_handler.handle(data)
        return data  # По умолчанию возвращаем data без изменений

# 1. Проверка IP
class IPCheckHandler(Handler):
    def handle(self, data):
        client_ip = data.get("client_ip")
        if not is_ip_allowed(client_ip):
            # Прерываем цепочку и возвращаем ошибку
            return {"error": "Access denied: Invalid IP address"}, 403
        # Иначе передаём управление дальше
        return super().handle(data)

# 2. Проверка логина/пароля
class LoginHandler(Handler):
    def handle(self, data):
        username = data.get("username")
        password = data.get("password")

        conn = get_db_connection()
        if not conn:
            return {"error": "Failed to connect to the database"}, 500

        try:
            cursor = conn.cursor()
            query = "SELECT id, role FROM users WHERE username = %s AND password = %s;"
            cursor.execute(query, (username, password))
            result = cursor.fetchone()

            if result:
                user_id, role = result
                data["user_id"] = user_id
                data["role"] = role
            else:
                return {"error": "Invalid username or password"}, 401
        except Error as e:
            return {"error": f"Database error: {e}"}, 500
        finally:
            cursor.close()
            conn.close()

        # Передаём управление дальше
        return super().handle(data)

# 3. Генерация 2FA (запрос к микросервису)
class Generate2FAHandler(Handler):
    def handle(self, data):
        user_id = data.get("user_id")
        if not user_id:
            # По логике, если user_id не установлен, это значит,
            # что предыдущая проверка (логин) не прошла.
            return {"error": "No user_id provided"}, 400

        # Запрос к микросервису 2FA для генерации кода
        response = requests.post(
            f"{TWO_FACTOR_SERVICE_URL}/generate_2fa",
            json={"user_id": user_id}
        )

        if response.status_code == 200:
            # Дополняем данные ответа
            data["2fa_generated"] = True
            return super().handle(data)
        else:
            # Если не удалось сгенерировать
            return {"error": "Failed to generate 2FA code"}, 500

# ========== РОУТЫ FLASK-ПРИЛОЖЕНИЯ ==========

@app.route('/login', methods=['POST'])
def login():
    """
    Пример использования цепочки:
    1) Проверяем IP
    2) Проверяем логин/пароль
    3) Генерируем 2FA
    Если что-то пошло не так, цепочка прерывается и возвращается ошибка.
    """
    data = request.json or {}
    data["client_ip"] = request.remote_addr

    # Формируем цепочку обработчиков
    ip_check_handler = IPCheckHandler()
    login_handler = LoginHandler()
    generate_2fa_handler = Generate2FAHandler()

    ip_check_handler.set_next(login_handler).set_next(generate_2fa_handler)

    # Передаём data в первый обработчик
    result = ip_check_handler.handle(data)

    # Если результат — кортеж (dict, код ответа), возвращаем ошибку
    if isinstance(result, tuple):
        body, status_code = result
        return jsonify(body), status_code

    # Если дошли сюда, значит цепочка успешно пройдена
    user_id = result.get("user_id")
    role = result.get("role")

    return jsonify({
        "message": "Login successful. 2FA code generated.",
        "role": role,
        "user_id": user_id
    }), 200

@app.route('/validate_2fa', methods=['POST'])
def validate_2fa():
    """
    Эндпоинт для проверки 2FA-кода.
    Но здесь — без цепочки, т.к. логика 2FA вынесена в отдельный микросервис.
    Мы просто перенаправляем запрос на two_factor_service.
    """
    data = request.json
    response = requests.post(f"{TWO_FACTOR_SERVICE_URL}/validate_2fa", json=data)
    return (response.content, response.status_code, response.headers.items())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6000, debug=True)