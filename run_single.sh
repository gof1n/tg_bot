#!/bin/bash
# Запуск одного процесса ботов (main.py). Перед запуском завершаются все старые процессы,
# чтобы не было TelegramConflictError (Conflict: terminated by other getUpdates request).

cd "$(dirname "$0")"

echo "🛑 Останавливаем все процессы ботов..."
pkill -f "python.*main\.py" 2>/dev/null
pkill -f "python.*user_bot\.py" 2>/dev/null
pkill -f "python.*admin_bot\.py" 2>/dev/null
sleep 2

echo "🚀 Запуск одного процесса (User + Admin боты)..."
exec python3 main.py
