"""
Скрипт для сброса webhook и очистки конфликтующих соединений
"""

import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")


async def reset_webhook(token: str, bot_name: str):
    """Сброс webhook для бота"""
    url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            result = await response.json()
            if result.get('ok'):
                print(f"✅ {bot_name}: Webhook успешно сброшен")
            else:
                print(f"❌ {bot_name}: Ошибка - {result}")


async def main():
    """Основная функция"""
    print("🔄 Сброс webhooks для обоих ботов...\n")
    
    await reset_webhook(USER_BOT_TOKEN, "User Bot")
    await reset_webhook(ADMIN_BOT_TOKEN, "Admin Bot")
    
    print("\n✅ Готово! Теперь можно запускать ботов.")
    print("⏳ Подождите 5 секунд перед запуском...")


if __name__ == "__main__":
    asyncio.run(main())
