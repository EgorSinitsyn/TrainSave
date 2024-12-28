import tkinter as tk
from tkinter import messagebox
import requests

# URL микросервиса авторизации
AUTH_URL = "http://127.0.0.1:6000/login"
VERIFY_2FA_URL = "http://127.0.0.1:6000/validate_2fa"

def login():
    username = username_entry.get()
    password = password_entry.get()

    # Отправка запроса на сервер
    response = requests.post(AUTH_URL, json={"username": username, "password": password})

    # Обработка ответа
    if response.status_code == 200:
        data = response.json()
        user_id = data.get("user_id")
        role = data.get("role")
        messagebox.showinfo("Success", f"Login successful! Role: {role}")
        show_2fa_prompt(user_id)
    elif response.status_code == 401:
        messagebox.showerror("Error", "Invalid username or password!")
    elif response.status_code == 403:
        messagebox.showerror("Error", "Access denied: Invalid IP address!")
    else:
        messagebox.showerror("Error", "Unexpected error occurred!")

def verify_2fa(user_id):
    code = twofa_entry.get()

    # Отправка запроса на сервер для проверки 2FA
    response = requests.post(VERIFY_2FA_URL, json={"user_id": user_id, "code": code})

    # Обработка ответа
    if response.status_code == 200:
        messagebox.showinfo("Success", "2FA verified successfully!")
        twofa_window.destroy()
    else:
        messagebox.showerror("Error", "Invalid 2FA code!")

def show_2fa_prompt(user_id):
    global twofa_window, twofa_entry

    # Создание нового окна для ввода 2FA
    twofa_window = tk.Toplevel(root)
    twofa_window.title("2FA Verification")

    tk.Label(twofa_window, text="Enter 2FA Code:").pack(padx=10, pady=10)
    twofa_entry = tk.Entry(twofa_window)
    twofa_entry.pack(padx=10, pady=10)

    tk.Button(twofa_window, text="Verify", command=lambda: verify_2fa(user_id)).pack(pady=10)

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