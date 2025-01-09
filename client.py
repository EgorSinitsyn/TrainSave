import tkinter as tk
from tkinter import messagebox, scrolledtext
import requests

# Переменные сервисов, развернутые локально, в Docker-compose и Minikube
AUTH_URL = "http://127.0.0.1:6000/login"
VERIFY_2FA_URL = "http://127.0.0.1:6000/validate_2fa"
EXECUTE_URL = "http://127.0.0.1:6000/execute"

# # Переменные сервисов, развернутые на удаленной виртуальной машине YC в Docker-compose
# AUTH_URL = "http://158.160.37.33:6000/login"
# VERIFY_2FA_URL = "http://158.160.37.33:6000/validate_2fa"
# EXECUTE_URL = "http://158.160.37.33:6000/execute"

# Глобальные переменные для хранения данных пользователя
global_user_id = None
global_role = None
entered_2fa_code = None
global_session_id = None


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def login():
    username = username_entry.get()
    password = password_entry.get()

    # Отправка запроса на сервер (/login)
    try:
        response = requests.post(AUTH_URL, json={"username": username, "password": password})
        response.raise_for_status()
    except requests.RequestException as e:
        messagebox.showerror("Network Error", f"Failed to connect: {e}")
        return

    if response.status_code == 200:
        data = response.json()
        user_id = data.get("user_id")
        role = data.get("role")

        if not user_id or not role:
            messagebox.showerror("Error", "Invalid server response: Missing user_id or role")
            return

        # Сохраняем данные пользователя
        global global_user_id, global_role
        global_user_id = user_id
        global_role = role

        messagebox.showinfo("Success", f"Login successful! Role: {role}")
        show_2fa_prompt(user_id)
    elif response.status_code == 401:
        messagebox.showerror("Error", "Invalid username or password!")
    elif response.status_code == 403:
        messagebox.showerror("Error", "Access denied: Invalid IP address!")
    else:
        messagebox.showerror("Error", f"Unexpected error occurred! (HTTP {response.status_code})")

def verify_2fa(user_id):
    global entered_2fa_code, global_session_id

    code = twofa_entry.get()
    entered_2fa_code = code

    # Отправка запроса на сервер (/validate_2fa)
    try:
        response = requests.post(VERIFY_2FA_URL, json={"user_id": user_id, "code": code})
        response.raise_for_status()
    except requests.RequestException as e:
        messagebox.showerror("Network Error", f"Failed to connect: {e}")
        return

    if response.status_code == 200:
        data = response.json()
        global_session_id = data.get("session_id")  # Сохраняем session_id
        if not global_session_id:
            messagebox.showerror("Error", "Invalid server response: Missing session_id")
            return
        messagebox.showinfo("Success", "2FA verified successfully!")
        twofa_window.destroy()
        open_sql_window()  # Открываем окно для отправки SQL-запросов
    else:
        messagebox.showerror("Error", "Invalid or expired 2FA code!")

def show_2fa_prompt(user_id):
    global twofa_window, twofa_entry

    twofa_window = tk.Toplevel(root)
    twofa_window.title("2FA Verification")

    tk.Label(twofa_window, text="Enter 2FA Code:").pack(padx=10, pady=10)
    twofa_entry = tk.Entry(twofa_window)
    twofa_entry.pack(padx=10, pady=10)

    tk.Button(twofa_window, text="Verify", command=lambda: verify_2fa(user_id)).pack(pady=10)

def open_sql_window():
    """
    Окно для ввода SQL-запросов и их выполнения.
    """
    sql_window = tk.Toplevel(root)
    sql_window.title("SQL Console")

    tk.Label(sql_window, text=f"Logged in as role: {global_role}, user_id: {global_user_id}").pack(pady=5)

    query_label = tk.Label(sql_window, text="Enter SQL query:")
    query_label.pack()

    query_text = scrolledtext.ScrolledText(sql_window, width=60, height=5)
    query_text.pack(padx=10, pady=10)

    def execute_query():
        query = query_text.get("1.0", tk.END).strip()
        if not query:
            messagebox.showwarning("Warning", "SQL query is empty!")
            return

        payload = {
            "session_id": global_session_id,
            "user_id": global_user_id,
            "username": username_entry.get(),
            "role": global_role,
            "code": entered_2fa_code,
            "query": query
        }

        try:
            resp = requests.post(EXECUTE_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "result" in data:
                show_select_result(data["result"])
            else:
                messagebox.showinfo("Info", data.get("message", "Query executed successfully"))
        except requests.HTTPError as e:
            err = resp.json()
            messagebox.showerror("Error", f"HTTP {resp.status_code}: {err.get('message', resp.text)}")
        except requests.RequestException as e:
            messagebox.showerror("Network Error", str(e))

    def show_select_result(rows):
        """
        Отобразить результат запроса (список словарей) в новом окне.
        """
        result_window = tk.Toplevel(sql_window)
        result_window.title("Query Result")

        text_area = scrolledtext.ScrolledText(result_window, width=80, height=20)
        text_area.pack(padx=10, pady=10)

        for row in rows:
            text_area.insert(tk.END, f"{row}\n")
        text_area.config(state=tk.DISABLED)

    execute_button = tk.Button(sql_window, text="Execute", command=execute_query)
    execute_button.pack(pady=5)

    sql_window.focus()


# =============================================================================
# ИНТЕРФЕЙС ПРИЛОЖЕНИЯ
# =============================================================================

# Создание основного окна приложения
root = tk.Tk()
root.title("Login")

# Лейблы и поля ввода для логина
tk.Label(root, text="Username:").grid(row=0, column=0, padx=10, pady=10)
username_entry = tk.Entry(root)
username_entry.grid(row=0, column=1, padx=10, pady=10)

tk.Label(root, text="Password:").grid(row=1, column=0, padx=10, pady=10)
password_entry = tk.Entry(root, show="*")
password_entry.grid(row=1, column=1, padx=10, pady=10)

# Кнопка входа
login_button = tk.Button(root, text="Login", command=login)
login_button.grid(row=2, columnspan=2, pady=20)

# Запуск основного окна
root.mainloop()