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
    "10.0.0.0/8",              # Включает внутренние IP Kubernetes
    "192.168.49.0/24",         # Minikube сеть
    "79.139.0.0/16",           # Московский диапазон Ip-адресов для внешних подключений
    "84.17.0.0/16",            # Польша
    "158.160.37.33",           # Внешний IP сервера
    "158.160.33.170",          # Внешний IP сервера-БД
    "172.0.0.0/8",             # Docker-сеть (для контейнеров)
    "192.168.0.0/16",          # Локальная сеть
    "198.18.0.0/15"            # VPN или тестовая сеть
]

# URLs микросервисов локальные
TWO_FACTOR_SERVICE_URL = "http://127.0.0.1:6001"
REQUEST_SERVICE_URL = "http://127.0.0.1:6002"

# Имена микросервисов внутри одной Docker-сети на изолированной WM в Yandex_cloud
# TWO_FACTOR_SERVICE_URL = "http://two_factor_service:6001"
# REQUEST_SERVICE_URL = "http://request_service:6002"

# URLs микросервисов в Minikube
# TWO_FACTOR_SERVICE_URL = "http://two-factor-service-service:6001"
# REQUEST_SERVICE_URL = "http://request-service-service:6002"

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
# Handler для проверки 2FA по коду (вызывается микросервис)
# -----------------------------------------------------------------------------

class Validate2FAHandler(Handler):
    """
    Делегирует проверку 2FA (код и user_id) на two_factor_service (/validate_2fa).
    Ожидается, что data содержит поля 'user_id' и 'code'.
    """
    def handle(self, data):
        user_id = data.get("user_id")
        input_code = data.get("code")

        if not user_id or not input_code:
            return {"error": "User ID and code are required"}, 400

        # Отправляем запрос к two_factor_service
        try:
            print(f"[DEBUG] Отправляем запрос в two_factor_service: user_id={user_id}, code={input_code}")
            resp = requests.post(
                f"{TWO_FACTOR_SERVICE_URL}/validate_2fa",
                json={"user_id": user_id, "code": input_code}
            )
            resp.raise_for_status()  # Проверяем HTTP статус
        except requests.RequestException as e:
            print(f"[ERROR] Ошибка при вызове two_factor_service: {e}")
            return {"error": f"Failed to call two_factor_service: {e}"}, 500

        if resp.status_code == 200:
            # 2FA прошла успешно
            try:
                resp_data = resp.json()
                print(f"[DEBUG] Ответ от two_factor_service: {resp_data}")

                # Проверяем наличие session_id
                if "session_id" not in resp_data:
                    print("[ERROR] Отсутствует session_id в ответе от two_factor_service")
                    return {"error": "Missing session_id in response"}, 500

                # Добавляем данные в `data`
                data["session_id"] = resp_data.get("session_id")
                data["role"] = resp_data.get("role", data.get("role"))  # возможно обновить
                print(f"[DEBUG] Данные после добавления session_id: {data}")
                return super().handle(data)

            except ValueError as e:
                print(f"[ERROR] Ошибка обработки JSON-ответа от two_factor_service: {e}")
                return {"error": "Invalid JSON response from two_factor_service"}, 500

        else:
            # Обработка ошибки от two_factor_service
            try:
                err_data = resp.json()
                print(f"[ERROR] Ошибка от two_factor_service: {err_data}")
            except ValueError:
                err_data = {"message": "Unknown error from two_factor_service"}
                print(f"[ERROR] Некорректный ответ от two_factor_service")
            return {"error": err_data.get("message", "Invalid 2FA")}, resp.status_code


# ------------------------------------------------------------------------------------------
# Handler для /execute - вариант с проверкой «активной 2FA-сессии» (обращение к микросервису)
# -------------------------------------------------------------------------------------------

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
    """
    Делегирует проверку кода 2FA в two_factor_service.
    """
    data = request.json or {}
    validate_handler = Validate2FAHandler()  # Используем Validate2FAHandler

    # Передача данных обработчику
    result = validate_handler.handle(data)

    # Обработка результата
    if isinstance(result, tuple):
        body, code = result
        return jsonify(body), code
    elif isinstance(result, dict) and "error" in result:
        return jsonify({"message": result["error"]}), 400
    elif isinstance(result, dict):
        # Если всё прошло хорошо и в result есть сгенерированный session_id,
        # просто возвращаем его вместе со всеми полями:
        return jsonify(result), 200
    return jsonify({"message": "2FA validation successful"}), 200


@app.route('/execute', methods=['POST'])
def execute_query():
    """
    Пример цепочки для /execute:
    1) IPCheckHandle
    2) Validate2FAHandler (если вы ожидаете, что пользователь только что ввёл 2FA)
    3) Check2FASessionHandler (если пользователь уже ввёл код ранее, и у него есть активная сессия)
    4) RequestServiceHandler (делегируем в request_service)
    """
    data = request.json or {}
    data["client_ip"] = request.remote_addr

    # Если username отсутствует, возвращаем ошибку
    if "username" not in data:
        return jsonify({"message": "Username is required"}), 400

    ip_handler = IPCheckHandler()

    # Если нужно проверять «живой» код 2FA, используем Validate2FAHandler:
    # validate_2fa_handler = Validate2FAHandler()

    # Если нужно проверять «активную» сессию, используем Check2FASessionHandler:
    session_handler = Check2FASessionHandler()

    request_service = RequestServiceHandler()

    # Пример: сначала IP → потом уже активная сессия (Check2FASessionHandler):
    ip_handler.set_next(session_handler).set_next(request_service)

    # Если бы нужен Validate2FAHandler, делаем так:
    # ip_handler.set_next(validate_2fa_handler).set_next(request_service)

    result = ip_handler.handle(data)

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