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

def get_db_connection():
    """Подключение к базе данных."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Ошибка подключения к базе данных: {e}")
    return None


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
            # Нет ограничений
            return True, None
        else:
            return super().handle(role, query)

class EditorHandler(Handler):
    """
    editor — всё, кроме:
    - DROP TABLE, DROP DATABASE
    - CREATE DATABASE
    - и операции только над таблицей train_data
    """
    def handle(self, role, query):
        if role == "editor":
            upper_q = query.strip().upper()

            # Запрещаем DROP TABLE / DROP DATABASE / CREATE DATABASE
            forbidden_patterns = [
                r"\bDROP\s+TABLE\b",
                r"\bDROP\s+DATABASE\b",
                r"\bCREATE\s+DATABASE\b"
            ]
            for pattern in forbidden_patterns:
                if re.search(pattern, upper_q):
                    return False, f"Editor cannot execute: {pattern}"

            # Разрешаем операции только над train_data
            # Ищем упоминания таблиц в FROM, JOIN, INTO, UPDATE
            table_names = re.findall(
                r'\bFROM\s+([\w`"]+)|\bJOIN\s+([\w`"]+)|\bINTO\s+([\w`"]+)|\bUPDATE\s+([\w`"]+)',
                upper_q
            )
            # Преобразуем к единому списку
            flat_table_names = [t for group in table_names for t in group if t]
            for t in flat_table_names:
                # Удаляем кавычки и проверяем имя таблицы
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
                # Убираем кавычки
                t_clean = t.replace('`', '').replace('"', '')
                if t_clean.upper() != "TRAIN_DATA":
                    return False, f"Viewer can only SELECT from train_data, found: {t_clean}"

            # Если все проверки прошли успешно
            return True, None
        else:
            return super().handle(role, query)

@app.route('/execute_sql', methods=['POST'])
def execute_sql():
    """
    Ожидаем JSON:
    {
      "role": "admin|editor|viewer",
      "query": "SELECT ...",
      "user_id": 123  (для логирования, если нужно)
    }
    1) Прогоняем через цепочку Handler (Admin → Editor → Viewer)
    2) При успехе — выполняем запрос в БД
    """
    data = request.json or {}
    role = data.get("role")
    query = data.get("query")
    user_id = data.get("user_id")  # если нужно логировать

    if not role or not query:
        return jsonify({"message": "role and query are required"}), 400

    # Цепочка: Admin → Editor → Viewer
    admin_handler = AdminHandler()
    editor_handler = EditorHandler()
    viewer_handler = ViewerHandler()
    admin_handler.set_next(editor_handler).set_next(viewer_handler)

    is_allowed, error_msg = admin_handler.handle(role, query)
    if not is_allowed:
        return jsonify({"message": error_msg}), 403

    # Если разрешено, выполняем запрос
    conn = get_db_connection()
    if not conn:
        return jsonify({"message": "Failed to connect to DB"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(query)

        # Если это SELECT, cursor.with_rows = True
        if cursor.with_rows:
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
            return jsonify({"result": result}), 200
        else:
            # INSERT, UPDATE, DELETE, CREATE TABLE etc.
            conn.commit()
            return jsonify({"message": "Query executed successfully"}), 200

    except Error as e:
        return jsonify({"message": f"Database error: {e}"}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6002, debug=True)