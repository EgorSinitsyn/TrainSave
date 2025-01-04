from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import ipaddress
import requests
from datetime import datetime, timedelta

load_dotenv()

# ------------------------------------
# Конфигурация БД (TrainSafe)
# ------------------------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": "TrainSafe"
}

# Разрешённые IP-адреса/подсети
ALLOWED_IP_RANGES = [
    "127.0.0.1",
    "192.168.1.100/24"
]

# URLs микросервисов
TWO_FACTOR_SERVICE_URL = "http://127.0.0.1:6001"
REQUEST_SERVICE_URL = "http://127.0.0.1:6002"

app = Flask(__name__)

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def get_db_connection():
    """
    Возвращает соединение к базе данных TrainSafe.
    """
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
    return None

def is_ip_allowed(ip):
    """
    Проверяем, находится ли IP в списке/подсети ALLOWED_IP_RANGES.
    """
    for allowed_range in ALLOWED_IP_RANGES:
        if ipaddress.ip_address(ip) in ipaddress.ip_network(allowed_range):
            return True
    return False


# =============================================================================
# ЦЕПОЧКА ОБРАБОТЧИКОВ (HANDLERS)
# =============================================================================

class Handler:
    def __init__(self):
        self._next_handler = None

    def set_next(self, handler):
        self._next_handler = handler
        return handler

    def handle(self, data):
        """
        Если обработчик не может/не хочет обрабатывать,
        передаёт дальше; иначе возвращает (body, code) или dict.
        """
        if self._next_handler:
            return self._next_handler.handle(data)
        return data


# -----------------------------------------------------------------------------
# Handlers для /login
# -----------------------------------------------------------------------------

class IPCheckHandler(Handler):
    """
    Проверка IP-адреса.
    """
    def handle(self, data):
        ip_addr = data.get("client_ip")
        if not is_ip_allowed(ip_addr):
            return {"error": "Invalid IP address"}, 403
        return super().handle(data)

class LoginHandler(Handler):
    """
    Проверка логина/пароля.
    """
    def handle(self, data):
        username = data.get("username")
        password = data.get("password")

        conn = get_db_connection()
        if not conn:
            return {"error": "Failed to connect DB"}, 500
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, role FROM users WHERE username=%s AND password=%s",
                (username, password)
            )
            result = cursor.fetchone()
            if not result:
                return {"error": "Invalid username/password"}, 401
            user_id, role = result
            data["user_id"] = user_id
            data["role"] = role
        except Error as e:
            return {"error": f"Database error: {e}"}, 500
        finally:
            cursor.close()
            conn.close()

        return super().handle(data)

class Generate2FAHandler(Handler):
    """
    Генерация 2FA-кода через сервис two_factor_service.
    """
    def handle(self, data):
        user_id = data["user_id"]
        try:
            resp = requests.post(
                f"{TWO_FACTOR_SERVICE_URL}/generate_2fa",
                json={"user_id": user_id}
            )
            if resp.status_code != 200:
                return {"error": "Failed to generate 2FA"}, 500
        except requests.RequestException as e:
            return {"error": f"2FA service error: {e}"}, 500

        return super().handle(data)


# -----------------------------------------------------------------------------
# Handler для /execute - вариант с проверкой «активной 2FA-сессии»
# -----------------------------------------------------------------------------

class Check2FASessionHandler(Handler):
    """
    Проверяет, есть ли у пользователя «активная 2FA-сессия»
    в таблице sessions.

    Ожидаем, что клиент передаёт: user_id, code (который вернулся ему после
    валидации). is_session_active = TRUE, session_expires_at > now().
    """
    def handle(self, data):
        user_id = data.get("user_id")
        code = data.get("code")
        role = data.get("role")
        query = data.get("query")

        # Для выполнения запроса нужны user_id, code (как "токен"), role, query
        if not user_id or not code or not role or not query:
            return {"error": "user_id, code, role, and query are required"}, 400

        conn = get_db_connection()
        if not conn:
            return {"error": "DB connection error"}, 500

        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT is_session_active, session_expires_at
                FROM sessions
                WHERE user_id = %s AND code = %s
                ORDER BY expires_at DESC
                LIMIT 1
            ''', (user_id, code))
            row = cursor.fetchone()
            if not row:
                return {"error": "Invalid session token"}, 401

            is_active, session_expires = row
            if not is_active:
                return {"error": "Session is not active"}, 401
            if datetime.now() > session_expires:
                return {"error": "Session expired"}, 401

            # Если всё ОК — переходим дальше
            return super().handle(data)
        except Error as e:
            return {"error": f"Database error: {e}"}, 500
        finally:
            cursor.close()
            conn.close()


class RequestServiceHandler(Handler):
    """
    Делегирует запрос к микросервису request_service.py (/execute_sql),
    передавая JSON: {role, query, user_id}.
    """
    def handle(self, data):
        payload = {
            "role": data.get("role"),
            "query": data.get("query"),
            "user_id": data.get("user_id")
        }

        try:
            resp = requests.post(f"{REQUEST_SERVICE_URL}/execute_sql", json=payload)
            return resp.content, resp.status_code, resp.headers.items()
        except requests.RequestException as e:
            return {"error": f"request_service error: {e}"}, 500


# =============================================================================
# FLASK-МАРШРУТЫ
# =============================================================================

@app.route('/login', methods=['POST'])
def login():
    """
    Цепочка для /login:
      1) IPCheckHandler
      2) LoginHandler
      3) Generate2FAHandler

    Возвращает user_id, role, сообщение о генерации кода.
    """
    data = request.json or {}
    data["client_ip"] = request.remote_addr

    ip_handler = IPCheckHandler()
    login_handler = LoginHandler()
    gen_2fa_handler = Generate2FAHandler()

    ip_handler.set_next(login_handler).set_next(gen_2fa_handler)

    result = ip_handler.handle(data)

    if isinstance(result, tuple):
        # (body, code)
        body, code = result
        return jsonify(body), code

    if isinstance(result, dict) and "error" in result:
        return jsonify({"message": result["error"]}), 400

    # Успех
    user_id = data["user_id"]
    role = data["role"]
    return jsonify({
        "message": "Login successful, 2FA generated",
        "user_id": user_id,
        "role": role
    }), 200


@app.route('/validate_2fa', methods=['POST'])
def validate_2fa():
    """
    Проверяет 2FA-код и включает "сессию" на N минут.

    После успешной проверки:
      - is_validated = TRUE
      - is_session_active = TRUE
      - session_expires_at = now() + 30 минут (пример)
    """
    data = request.json or {}
    user_id = data.get("user_id")
    input_code = data.get("code")

    if not user_id or not input_code:
        return jsonify({"message": "User ID and code are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"message": "Failed to connect to DB"}), 500

    try:
        cursor = conn.cursor()
        # Находим последнюю запись для user_id
        query = '''
            SELECT id, code, expires_at, is_validated
            FROM sessions
            WHERE user_id = %s
            ORDER BY expires_at DESC
            LIMIT 1
        '''
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Invalid code"}), 401

        record_id, db_code, db_expires, db_is_valid = row
        if db_is_valid:
            return jsonify({"message": "Code already used"}), 401
        if datetime.now() > db_expires:
            return jsonify({"message": "Code expired"}), 401
        if db_code != input_code:
            return jsonify({"message": "Invalid code"}), 401

        # Настраиваем "долгую сессию" (30 минут)
        session_expires = datetime.now() + timedelta(minutes=30)

        # Помечаем код как использованный, включаем сессию
        update_query = '''
            UPDATE sessions
            SET is_validated = TRUE,
                is_session_active = TRUE,
                session_expires_at = %s
            WHERE id = %s
        '''
        cursor.execute(update_query, (session_expires, record_id))
        conn.commit()

        # Считываем роль
        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        role = cursor.fetchone()[0]

        return jsonify({
            "message": "2FA validated",
            "user_id": user_id,
            "role": role,
            "session_expires": session_expires.isoformat()
        }), 200
    except Error as e:
        return jsonify({"message": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route('/execute', methods=['POST'])
def execute_query():
    """
    Цепочка для /execute:
      1) IPCheckHandler (опционально, если тоже хотим проверить IP)
      2) Check2FASessionHandler (проверяем, что есть активная 2FA-сессия)
      3) RequestServiceHandler (делегируем SQL-запрос)
    """
    data = request.json or {}
    data["client_ip"] = request.remote_addr  # Если хотим проверять IP

    ip_handler = IPCheckHandler()            # Если хотим IPCheck
    session_handler = Check2FASessionHandler()
    request_service = RequestServiceHandler()

    # Связываем
    # Если IPCheck не нужен, начинаем цепочку с session_handler
    ip_handler.set_next(session_handler).set_next(request_service)

    result = ip_handler.handle(data)

    # Обработка возврата
    if isinstance(result, tuple):
        if len(result) == 2:
            body, code = result
            return jsonify(body), code
        elif len(result) == 3:
            content, code, headers = result
            return content, code, headers

    if isinstance(result, dict) and "error" in result:
        return jsonify({"message": result["error"]}), 400

    return jsonify({"message": "Unexpected error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, debug=True)