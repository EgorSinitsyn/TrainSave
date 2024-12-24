import tkinter as tk
from tkinter import messagebox
import requests

# URL микросервиса авторизации
AUTH_URL = "http://127.0.0.1:6000/login"

def login():
    username = username_entry.get()
    password = password_entry.get()

    # Отправка запроса на сервер
    response = requests.post(AUTH_URL, json={"username": username, "password": password})

    # Обработка ответа
    if response.status_code == 200:
        messagebox.showinfo("Success", "Login successful!")
    elif response.status_code == 401:
        messagebox.showerror("Error", "Invalid username or password!")
    elif response.status_code == 403:
        messagebox.showerror("Error", "Access denied: Invalid IP address!")
    else:
        messagebox.showerror("Error", "Unexpected error occurred!")

# Создание окна приложения
root = tk.Tk()
root.title("Login")

# Лейблы и поля ввода
tk.Label(root, text="Username:").grid(row=0, column=0, padx=10, pady=10)
username_entry = tk.Entry(root)
username_entry.grid(row=0, column=1, padx=10, pady=10)

tk.Label(root, text="Password:").grid(row=1, column=0, padx=10, pady=10)
password_entry = tk.Entry(root, show="*")
password_entry.grid(row=1, column=1, padx=10, pady=10)

# Кнопка входа
login_button = tk.Button(root, text="Login", command=login)
login_button.grid(row=2, columnspan=2, pady=20)

# Запуск окна
root.mainloop()