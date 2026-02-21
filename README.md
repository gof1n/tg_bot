# Augsburg Liquid — Telegram Shop Bot

Два бота в одном процессе: **User Bot** (каталог, корзина, заказы) и **Admin Bot** (заказы, статистика, синхронизация из таблицы, рассылка, бан/разбан).

## Быстрый старт

```bash
pip install -r requirements.txt
cp .env.example .env   # заполните токены и CSV_URL
python main.py
```

База по умолчанию **пустая**. Товары в каталоге появятся только после нажатия в админ-боте **«Обновить базу»** (загрузка из таблицы/CSV). Статистика считается по заказам и тоже будет нулевой до первых данных.

Локально можно использовать `./run_single.sh` — скрипт останавливает старые процессы и запускает один `main.py`.

## Переменные окружения

См. `.env.example`. Основные: `USER_BOT_TOKEN`, `ADMIN_BOT_TOKEN`, `ADMIN_CHAT_ID`, `DATABASE_PATH`, `CSV_URL`.

## Структура

- `main.py` — точка входа (оба бота в одном процессе)
- `handlers_user.py` / `handlers_admin.py` — логика ботов
- `database.py` — SQLite, заказы, пользователи, чёрный список
- `sync_service.py` — синхронизация товаров из Google Sheets (CSV)
- `keyboards.py`, `states.py` — клавиатуры и FSM

## Деплой

- **Свой сервер (VPS):** [DEPLOY.md](DEPLOY.md)
- **Railway (Volume для БД):** [RAILWAY.md](RAILWAY.md)

## Полезные скрипты

- `python clear_database.py` — очистка таблиц товаров и корзины
- `python check_table.py` — проверка ссылки на таблицу и фото
- `python reset_webhooks.py` — сброс webhooks (если переходили с webhook на polling)
