# Railway: сборка без Nixpacks/mise — используем официальный образ Python
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД по умолчанию в /app; на Railway задайте DATABASE_PATH=/data/augsburg_liquid.db и смонтируйте Volume в /data
CMD ["python", "main.py"]
