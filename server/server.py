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
    "10.128.0.0/24",           # Подсеть VPC
    "79.139.0.0/16",           # Московский диапазон Ip-адресов для внешних подключений
    "84.17.0.0/16",            # Польша
    "158.160.37.33",           # Внешний IP сервера
    "158.160.33.170",          # Внешний IP сервера-БД
    "172.0.0.0/8",             # Docker-сеть (для контейнеров)
    "192.168.0.0/16",          # Локальная сеть
    "198.18.0.0/15"            # VPN или тестовая сеть
]

# URLs микросервисов локальные
# TWO_FACTOR_SERVICE_URL = "http://127.0.0.1:6001"
# REQUEST_SERVICE_URL = "http://127.0.0.1:6002"

# Имена микросервисов внутри одной Docker-сети на изолированной WM в Yandex_cloud
TWO_FACTOR_SERVICE_URL = "http://two_factor_service:6001"
REQUEST_SERVICE_URL = "http://request_service:6002"

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

    # """
    # Временно отключена проверка IP.
    # """
    # return True

    print(f"Received IP for checking: {ip}")
    for allowed_range in ALLOWED_IP_RANGES:
        print(f"Testing against range: {allowed_range}")
        if ipaddress.ip_address(ip) in ipaddress.ip_network(allowed_range):
            print(f"IP {ip} is allowed")
            return True
    print(f"IP {ip} is not allowed")
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
                SELECT session_id, is_session_active, session_expires_at
                FROM sessions
                WHERE user_id = %s AND code = %s
                ORDER BY expires_at DESC
                LIMIT 1
            ''', (user_id, code))
            row = cursor.fetchone()
            if not row:
                return {"error": "Invalid session token"}, 401

            # row = (session_id, is_active, session_expires)
            session_id, is_active, session_expires = row

            if not is_active:
                return {"error": "Session is not active"}, 401
            if datetime.now() > session_expires:
                return {"error": "Session expired"}, 401

            # Можно при желании data["session_id"] = session_id
            # чтобы дальше логировать в logs.

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
            "user_id": data.get("user_id"),
            "session_id": data.get("session_id"),
            "username": data.get("username", "unknown")
            # Если нужно, можно передать session_id, если его сохранили
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
    """
    try:
        data = request.json or {}
        data["client_ip"] = request.remote_addr

        # Валидация данных
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return jsonify({"message": "Username and password are required"}), 400

        # Проверка через цепочку обработчиков
        ip_handler = IPCheckHandler()
        login_handler = LoginHandler()
        gen_2fa_handler = Generate2FAHandler()
        ip_handler.set_next(login_handler).set_next(gen_2fa_handler)

        result = ip_handler.handle(data)

        if isinstance(result, tuple):
            body, code = result
            return jsonify(body), code

        if isinstance(result, dict) and "error" in result:
            return jsonify({"message": result["error"]}), 400

        user_id = data["user_id"]
        role = data["role"]
        return jsonify({
            "message": "Login successful, 2FA generated",
            "user_id": user_id,
            "role": role
        }), 200

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"message": f"Internal Server Error: {str(e)}"}), 500


@app.route('/validate_2fa', methods=['POST'])
def validate_2fa():
    data = request.json or {}
    user_id = data.get("user_id")
    input_code = data.get("code")

    if not user_id or not input_code:
        return jsonify({"message": "User ID and code are required"}), 400

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"message": "Failed to connect to DB"}), 500

        cursor = conn.cursor()
        query = '''
            SELECT session_id, code, expires_at, is_validated
            FROM sessions
            WHERE user_id = %s
            ORDER BY expires_at DESC
            LIMIT 1
        '''
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"message": "Invalid code"}), 401

        session_id, db_code, db_expires, db_is_valid = row
        if db_is_valid:
            return jsonify({"message": "Code already used"}), 401
        if datetime.now() > db_expires:
            return jsonify({"message": "Code expired"}), 401
        if db_code != input_code:
            return jsonify({"message": "Invalid code"}), 401

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

        cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
        role = cursor.fetchone()[0]

        return jsonify({
            "message": "2FA validated",
            "user_id": user_id,
            "role": role,
            "session_id": session_id,  # Включение session_id
            "session_expires": session_expires.isoformat()
        }), 200

    except Exception as e:
        import traceback
        print("Ошибка на сервере:")
        print(traceback.format_exc())
        return jsonify({"message": f"Internal Server Error: {str(e)}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
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

    # Если username отсутствует в запросе, возвращаем ошибку
    if "username" not in data:
        return jsonify({"message": "Username is required"}), 400

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