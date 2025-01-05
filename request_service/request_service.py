from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
import os
import re

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": "TrainSafe"
}

app = Flask(__name__)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def get_db_connection():
    """Подключение к базе данных."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
    return None


def log_action(session_id, user_id, username, action, details, ip_address):
    """
    Записывает действие в таблицу logs (обновлённая структура).

    Предполагаем, что таблица logs имеет поля:
      log_id (PK, auto-increment),
      session_id, user_id, username, action, details, ip_address, timestamp.

    :param session_id: ID сессии (обязательный, FOREIGN KEY на sessions.session_id)
    :param user_id: ID пользователя
    :param username: имя пользователя (дублируется для удобства в logs)
    :param action: короткое описание действия (например, "EXECUTE_SQL_OK_SELECT")
    :param details: более детальное описание, например сам SQL-запрос или ошибка
    :param ip_address: IP-адрес клиента
    """
    conn_log = get_db_connection()
    if not conn_log:
        print("[WARNING] Не удалось подключиться к БД для логирования.")
        return

    try:
        cursor_log = conn_log.cursor()
        insert_query = """
            INSERT INTO logs (session_id, user_id, username, action, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        cursor_log.execute(insert_query, (session_id, user_id, username, action, details, ip_address))
        conn_log.commit()
    except Error as e:
        print(f"[WARNING] Ошибка при вставке лога: {e}")
    finally:
        cursor_log.close()
        conn_log.close()


# ========================
# ЦЕПОЧКА ОТВЕТСТВЕННОСТИ
# ========================

class Handler:
    def __init__(self):
        self._next_handler = None

    def set_next(self, handler):
        self._next_handler = handler
        return handler

    def handle(self, role, query):
        """
        Возвращает (is_allowed: bool, error_msg: str|None).
        Если не обработали здесь, передаём дальше.
        """
        if self._next_handler:
            return self._next_handler.handle(role, query)
        # По умолчанию — разрешаем
        return True, None


class AdminHandler(Handler):
    """admin — может всё"""

    def handle(self, role, query):
        if role == "admin":
            return True, None
        else:
            return super().handle(role, query)


class EditorHandler(Handler):
    """
    editor — всё, кроме:
    - DROP TABLE, DROP DATABASE, DROP COLUMN
    - CREATE DATABASE
    - TRUNCATE, DELETE (для всех строк)
    - и операции только над таблицей train_data
    """

    def handle(self, role, query):
        if role == "editor":
            upper_q = query.strip().upper()

            # Запрещаем DROP TABLE / DROP DATABASE / CREATE DATABASE / DROP COLUMN / TRUNCATE / DELETE без WHERE
            forbidden_patterns = [
                r"\bDROP\s+TABLE\b",
                r"\bDROP\s+DATABASE\b",
                r"\bDROP\s+COLUMN\b",
                r"\bCREATE\s+DATABASE\b",
                r"\bTRUNCATE\s+TABLE\b",
                # Запрещаем DELETE без WHERE (т.е. удаление всей таблицы)
                r"\bDELETE\b(?!.*WHERE)"
            ]
            for pattern in forbidden_patterns:
                if re.search(pattern, upper_q):
                    return False, f"Editor cannot execute: {pattern}"

            # Разрешаем операции только над train_data
            table_names = re.findall(
                r'\bFROM\s+([\w`"]+)|\bJOIN\s+([\w`"]+)|\bINTO\s+([\w`"]+)|\bUPDATE\s+([\w`"]+)',
                upper_q
            )
            flat_table_names = [t for group in table_names for t in group if t]
            for t in flat_table_names:
                t_clean = t.replace('`', '').replace('"', '')
                if t_clean.upper() != "TRAIN_DATA":
                    return False, f"Editor can only work with train_data, found: {t_clean}"

            return True, None
        else:
            return super().handle(role, query)


class ViewerHandler(Handler):
    """
    viewer — только SELECT, и только над train_data.
    """

    def handle(self, role, query):
        if role == "viewer":
            upper_q = query.strip().upper()

            # Проверяем, что запрос начинается с SELECT
            if not upper_q.startswith("SELECT"):
                return False, "Viewer can only execute SELECT statements."

            # Извлекаем таблицы из запроса
            table_names = re.findall(
                r'\bFROM\s+([\w`"]+)|\bJOIN\s+([\w`"]+)',
                upper_q
            )
            flat_table_names = [t for group in table_names for t in group if t]

            # Проверяем каждую таблицу
            for t in flat_table_names:
                t_clean = t.replace('`', '').replace('"', '')
                if t_clean.upper() != "TRAIN_DATA":
                    return False, f"Viewer can only SELECT from train_data, found: {t_clean}"

            return True, None
        else:
            return super().handle(role, query)


@app.route('/execute_sql', methods=['POST'])
def execute_sql():
    """
    Ожидаем JSON:
    {
      "session_id": 42,             # новый обязательный параметр для логирования
      "user_id": 123,
      "username": "editor_user",
      "role": "admin|editor|viewer",
      "query": "SELECT ..."
    }
    1) Прогоняем через цепочку Handler (Admin → Editor → Viewer).
    2) При успехе — выполняем запрос в БД.
    3) Логируем результат.
    """
    data = request.json or {}

    print(f"[DEBUG] Received payload in request_service: {data}")  # Отладка

    session_id = data.get("session_id")
    user_id = data.get("user_id")
    username = data.get("username") or "unknown"
    role = data.get("role")
    query = data.get("query")
    ip_address = request.remote_addr

    if not session_id or not user_id or not role or not query:
        print(f"[DEBUG] Missing fields in request_service: {data}")  # Отладка
        return jsonify({"message": "role, query, session_id, and user_id are required"}), 400

    # Проверка обязательных полей
    if not role or not query or not session_id or not user_id:
        log_action(
            session_id=session_id if session_id else 0,
            user_id=user_id if user_id else 0,
            username=username,
            action="EXECUTE_SQL_BAD_INPUT",
            details="Missing role or query or session_id or user_id",
            ip_address=ip_address
        )
        return jsonify({"message": "role, query, session_id, and user_id are required"}), 400

    # Цепочка: Admin → Editor → Viewer
    admin_handler = AdminHandler()
    editor_handler = EditorHandler()
    viewer_handler = ViewerHandler()
    admin_handler.set_next(editor_handler).set_next(viewer_handler)

    is_allowed, error_msg = admin_handler.handle(role, query)
    if not is_allowed:
        # Логируем запрет
        log_action(
            session_id=session_id,
            user_id=user_id,
            username=username,
            action="EXECUTE_SQL_DENIED",
            details=f"Role={role}, Query={query}, Error={error_msg}",
            ip_address=ip_address
        )
        return jsonify({"message": error_msg}), 403

    # Если разрешено, выполняем запрос
    conn = get_db_connection()
    if not conn:
        # Логируем ошибку подключения
        log_action(
            session_id=session_id,
            user_id=user_id,
            username=username,
            action="EXECUTE_SQL_DB_CONN_FAIL",
            details="Failed to connect to DB",
            ip_address=ip_address
        )
        return jsonify({"message": "Failed to connect to DB"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(query)

        # Если это SELECT, cursor.with_rows = True
        if cursor.with_rows:
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]

            # Логируем успешный SELECT
            log_action(
                session_id=session_id,
                user_id=user_id,
                username=username,
                action="EXECUTE_SQL_OK_SELECT",
                details=f"{query} - returned {len(rows)} row(s)",
                ip_address=ip_address
            )
            return jsonify({"result": result}), 200
        else:
            # INSERT, UPDATE, DELETE, CREATE TABLE и т. п.
            conn.commit()

            # Логируем успешное изменение (DML/DDL)
            log_action(
                session_id=session_id,
                user_id=user_id,
                username=username,
                action="EXECUTE_SQL_OK_DML",
                details=query,
                ip_address=ip_address
            )
            return jsonify({"message": "Query executed successfully"}), 200

    except Error as e:
        # Логируем ошибку при выполнении SQL
        log_action(
            session_id=session_id,
            user_id=user_id,
            username=username,
            action="EXECUTE_SQL_ERROR",
            details=f"{query} - DB error: {e}",
            ip_address=ip_address
        )
        return jsonify({"message": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)