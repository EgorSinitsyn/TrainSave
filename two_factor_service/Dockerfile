FROM python:3.11

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY . .

# Открываем порт, указанный в коде (6001)
EXPOSE 6001

# Запускаем приложение
CMD ["python", "two_factor_service.py"]