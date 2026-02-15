"""
Admin Bot — CRM: обновление базы из CSV (Google Sheets), уведомления о заказах, просмотр и приём заказов, статистика.
Доступ только для ADMIN_IDS.
"""

import os
import re
from datetime import datetime, timedelta

import asyncio
import io
import csv

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Database
from keyboards import (
    get_admin_main_keyboard,
    get_order_actions_keyboard,
    get_admin_orders_menu_keyboard,
    get_admin_stats_back_keyboard,
    get_admin_stats_period_keyboard,
    get_sync_result_delete_keyboard,
)
from states import AdminStatsStates, AdminOrderEditStates, AdminBroadcastStates
from utils import throttle_callback

router = Router()


def register_admin_handlers(
    router: Router,
    db: Database,
    bot,
    csv_url: str,
    admin_chat_id: int,
    admin_ids: list,
):
    """
    Регистрация хендлеров Admin Bot.
    bot — экземпляр Admin Bot (для отправки фото при синхронизации и сообщений).
    """
    adm_ids = list(admin_ids) if admin_ids else [admin_chat_id]

    @router.message(CommandStart())
    async def cmd_start(message: Message):
        if message.from_user.id not in adm_ids:
            await message.answer("⛔ У вас нет доступа к этому боту.")
            return
        await message.answer(
            "👋 <b>Admin Augsburg Liquid</b>\n\n"
            "📊 Статистика — метрики по периодам\n"
            "📋 Заказы — активные и история\n"
            "🔄 Обновить базу — синхронизация из таблицы\n\n"
            "Команды: /broadcast, /export, /ban, /unban, /find",
            reply_markup=get_admin_main_keyboard(),
        )

    def _parse_date_dmy(text: str):
        """Парсит дату из ДД.ММ.ГГГГ или ДД.ММ.ГГ. Возвращает (YYYY-MM-DD) или None."""
        text = (text or "").strip()
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$", text)
        if not m:
            return None
        d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000 if y < 50 else 1900
        try:
            dt = datetime(y, mon, d)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    @router.message(F.text == "📊 Статистика")
    async def stats(message: Message):
        if message.from_user.id not in adm_ids:
            await message.answer("⛔ У вас нет доступа.")
            return
        await message.answer(
            "Выберите период:",
            reply_markup=get_admin_stats_period_keyboard(),
        )

    async def _build_stats_blocks(
        start_date: str, end_date: str, period_label: str
    ) -> list:
        """Собрать статистику за период: 4 категории, список текстов (можно разбить на сообщения)."""
        orders_count, orders_sum = await db.get_stats_orders_in_period(start_date, end_date)
        users_in_period = await db.get_stats_users_in_period(start_date, end_date)
        avg_check = round(orders_sum / orders_count, 2) if orders_count else 0
        ltv = await db.get_stats_ltv_in_period(start_date, end_date)
        repeat_users, total_users = await db.get_stats_retention_in_period(start_date, end_date)
        retention_pct = round(repeat_users / total_users * 100, 1) if total_users else 0
        churned, before = await db.get_stats_churn(start_date, end_date)
        churn_pct = round(churned / before * 100, 1) if before else 0
        total_registered = await db.get_stats_total_users_registered()
        total_with_orders = await db.get_stats_total_users_with_orders()
        conversion_pct = round(total_with_orders / total_registered * 100, 1) if total_registered else 0
        pending_carts = await db.get_stats_pending_carts()
        avg_dau, mau = await db.get_stats_dau_mau(start_date, end_date)
        stickiness = round(avg_dau / mau * 100, 1) if mau else 0
        top = await db.get_stats_top_products_in_period(start_date, end_date, limit=10)

        header = f"📊 <b>Статистика</b> — {period_label}\n📅 {start_date} — {end_date}\n"
        blocks = []

        block1 = (
            header
            + "\n<b>💰 Финансовые метрики</b>\n"
            + f"Выручка: <b>{orders_sum:.2f}€</b>\n"
            + f"Количество заказов: <b>{orders_count}</b>\n"
            + f"Средний чек: <b>{avg_check:.2f}€</b>\n"
            + f"LTV (выручка на пользователя за период): <b>{ltv:.2f}€</b>\n"
        )
        blocks.append(block1)

        block2 = (
            "<b>🔄 Метрики удержания</b>\n"
            + f"Retention Rate (доля с 2+ заказами в периоде): <b>{retention_pct}%</b>\n"
            + f"Churn Rate (заказывали до периода, не в периоде): <b>{churn_pct}%</b> ({churned} из {before})\n"
        )
        blocks.append(block2)

        block3 = (
            "<b>📈 Метрики конверсии</b>\n"
            + f"Conversion rate в покупку (всего оформивших заказ / зарегистрированных): <b>{conversion_pct}%</b>\n"
            + f"Брошенные корзины (текущие неоформленные): <b>{pending_carts}</b>\n"
            + f"Пользователей с заказами: {total_with_orders}, всего в базе: {total_registered}\n"
        )
        blocks.append(block3)

        block4 = (
            "<b>👥 DAU/MAU</b> (по заказам)\n"
            + f"Среднее уникальных заказчиков в день (DAU): <b>{avg_dau}</b>\n"
            + f"Уникальных заказчиков за период (MAU): <b>{mau}</b>\n"
            + f"Stickiness (DAU/MAU): <b>{stickiness}%</b>\n\n"
            + "<b>🏆 Топ продаж:</b>\n"
        )
        for i, (name, qty) in enumerate(top, 1):
            block4 += f"  {i}. {name[:40]} — {qty} шт\n"
        if not top:
            block4 += "  — нет данных\n"
        blocks.append(block4)

        return blocks

    async def _build_stats_for_period(
        start_date: str, end_date: str, period_label: str
    ) -> str:
        """Один блок статистики (для обратной совместимости)."""
        blocks = await _build_stats_blocks(start_date, end_date, period_label)
        return "\n".join(blocks)

    @router.callback_query(F.data.startswith("stats_period:"))
    async def stats_period_selected(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        period = callback.data.split(":", 1)[1]
        today = datetime.now().date()
        if period == "week":
            start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")
            label = "неделя"
        elif period == "month":
            start = (today - timedelta(days=29)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")
            label = "месяц"
        elif period == "year":
            start = (today - timedelta(days=364)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")
            label = "год"
        elif period == "custom":
            try:
                await callback.message.delete()
            except Exception:
                pass
            await state.set_state(AdminStatsStates.start_date)
            await callback.message.answer(
                "Введите дату <b>начала</b> периода в формате ДД.ММ.ГГГГ\n"
                "Например: 01.01.2025",
            )
            return
        else:
            return
        try:
            await callback.message.delete()
        except Exception:
            pass
        blocks = await _build_stats_blocks(start, end, label)
        for i, text in enumerate(blocks):
            await callback.message.answer(
                text,
                reply_markup=get_admin_stats_back_keyboard() if i == len(blocks) - 1 else None,
            )

    @router.callback_query(F.data == "admin_back_to_main")
    async def admin_back_to_main(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        await state.clear()
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "👋 Главное меню",
            reply_markup=get_admin_main_keyboard(),
        )

    @router.callback_query(F.data == "admin_delete_msg")
    async def admin_delete_msg(callback: CallbackQuery):
        """Удалить сообщение (например итог синхронизации) по кнопке."""
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass

    @router.message(AdminStatsStates.start_date, F.text)
    async def stats_custom_start_date(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        start_iso = _parse_date_dmy(message.text)
        if not start_iso:
            await message.answer("Неверный формат. Введите дату начала в формате ДД.ММ.ГГГГ (например: 01.01.2025)")
            return
        await state.update_data(stats_start_date=start_iso)
        await state.set_state(AdminStatsStates.end_date)
        await message.answer("Введите дату <b>окончания</b> периода в формате ДД.ММ.ГГГГ")

    @router.message(AdminStatsStates.end_date, F.text)
    async def stats_custom_end_date(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        end_iso = _parse_date_dmy(message.text)
        if not end_iso:
            await message.answer("Неверный формат. Введите дату окончания в формате ДД.ММ.ГГГГ")
            return
        data = await state.get_data()
        start_iso = data.get("stats_start_date")
        await state.clear()
        if not start_iso or end_iso < start_iso:
            await message.answer("Дата окончания должна быть не раньше даты начала. Начните заново: нажмите 📊 Статистика → Свой период.")
            return
        blocks = await _build_stats_blocks(start_iso, end_iso, "свой период")
        for i, text in enumerate(blocks):
            await message.answer(
                text,
                reply_markup=get_admin_stats_back_keyboard() if i == len(blocks) - 1 else None,
            )

    async def _run_sync(status_msg, clear_first: bool = False):
        """Общая логика синхронизации. clear_first: сначала очистить товары и корзину."""
        if not (csv_url and csv_url.strip()):
            await status_msg.edit_text(
                "❌ Задайте <code>CSV_URL</code> в .env — ссылка на экспорт Google Sheets в CSV."
            )
            return
        try:
            try:
                from sync_service import sync_products
            except ModuleNotFoundError as e:
                await status_msg.edit_text(
                    "❌ Для синхронизации установите зависимости:\n"
                    "<code>pip install pandas aiohttp</code>\n\n"
                    f"Ошибка: {e}"
                )
                return
            if clear_first:
                await db.clear_products_and_cart()
                try:
                    await status_msg.edit_text("⏳ База очищена. Загрузка данных из таблицы...")
                except Exception:
                    pass
            last_progress = [0]

            async def on_progress(current: int, total: int, text: str):
                if current - last_progress[0] >= 10 or current == total:
                    last_progress[0] = current
                    try:
                        await status_msg.edit_text(
                            f"⏳ {text}\n{current} / {total} товаров..."
                        )
                    except Exception:
                        pass

            # Чат, откуда запущена синхронизация — сюда же грузим фото, если ADMIN_CHAT_ID не задан
            upload_chat_id = getattr(status_msg, "chat", None) and getattr(status_msg.chat, "id", None) or None
            count, count_with_photo = await sync_products(
                db=db,
                csv_url=csv_url,
                bot=bot,
                admin_chat_id=admin_chat_id,
                on_progress=on_progress,
                upload_chat_id=upload_chat_id,
            )
            hint = ""
            if count_with_photo == 0 and count > 0:
                hint = (
                    "\n\n⚠️ Фото не загружены. Проверьте: 1) В .env задан <code>ADMIN_CHAT_ID</code> (ваш Telegram ID). "
                    "2) В таблице есть колонка «Ссылка на фото» со ссылками https://... "
                    "3) Напишите боту @order_augsburg_liquid_bot в личку (чтобы бот мог отправить туда фото)."
                )
            elif not admin_chat_id:
                hint = "\n\n⚠️ Задайте <code>ADMIN_CHAT_ID</code> в .env для загрузки фото в карточки товаров."
            await status_msg.edit_text(
                f"✅ Синхронизация завершена.\n\n📦 Добавлено/обновлено товаров: <b>{count}</b>\n"
                f"📷 С фото: <b>{count_with_photo}</b> из {count}{hint}",
                reply_markup=get_sync_result_delete_keyboard(),
            )
        except Exception as e:
            await status_msg.edit_text(
                f"❌ Ошибка синхронизации:\n<code>{str(e)}</code>"
            )

    @router.message(F.text == "🔄 Обновить базу")
    async def sync_db(message: Message):
        if message.from_user.id not in adm_ids:
            await message.answer("⛔ У вас нет доступа.")
            return
        status_msg = await message.answer("⏳ Начало синхронизации...")
        await _run_sync(status_msg, clear_first=False)

    @router.message(F.text == "🗑 Очистить и загрузить заново")
    async def clear_and_sync(message: Message):
        if message.from_user.id not in adm_ids:
            await message.answer("⛔ У вас нет доступа.")
            return
        status_msg = await message.answer("⏳ Очищаю базу товаров, затем загружаю данные из таблицы...")
        await _run_sync(status_msg, clear_first=True)

    def _format_order_message(order: dict, user_info: dict = None, status_label: str = None) -> str:
        """Текст сообщения по заказу для админа. status_label — для истории (Принят/Отклонён)."""
        lines = [
            f"📦 <b>Заказ #{order['order_id']}</b>",
            f"🆔 User ID: {order['user_id']}",
        ]
        if status_label:
            lines.append(f"📌 Статус: {status_label}")
        if user_info:
            lines.append(f"👤 {user_info.get('full_name') or '—'}")
            lines.append(f"📱 {user_info.get('phone') or '—'}")
            lines.append(f"🏙 {user_info.get('city') or '—'}")
        if order.get("admin_note"):
            lines.append(f"📝 <i>Изменено админом: {order['admin_note']}</i>")
        lines.append("")
        lines.append("<b>🛒 Товары:</b>")
        for it in order.get("items", []):
            name = it.get("name", it.get("group_name", "—"))
            detail = ""
            if it.get("puffs"):
                detail = f"{it['puffs']} тяг"
            else:
                detail = f"{it.get('volume') or '-'}, {it.get('strength') or '-'}"
            lines.append(f"• <b>Артикул:</b> {it.get('sku', '—')} — {name} ({detail}) — {it.get('quantity', 0)} шт × {it.get('price', 0)}€")
        lines.append(f"\n💰 <b>Итого: {order.get('total_amount', 0):.2f}€</b>")
        return "\n".join(lines)

    @router.message(F.text == "📋 Заказы")
    async def orders_menu(message: Message):
        if message.from_user.id not in adm_ids:
            await message.answer("⛔ У вас нет доступа.")
            return
        await message.answer(
            "Заказы: выберите раздел.",
            reply_markup=get_admin_orders_menu_keyboard(),
        )

    @router.callback_query(F.data == "orders:active")
    async def orders_active(callback: CallbackQuery):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        orders = await db.get_orders_by_status("new")
        if not orders:
            await callback.message.answer(
                "Нет активных заказов (все приняты или отклонены).",
                reply_markup=get_admin_orders_menu_keyboard(),
            )
            return
        for order in orders:
            user_info = await db.get_user(order["user_id"])
            text = _format_order_message(order, user_info)
            await callback.message.answer(
                text,
                reply_markup=get_order_actions_keyboard(order["order_id"]),
            )
        await callback.message.answer("◀️ Назад в меню заказов:", reply_markup=get_admin_orders_menu_keyboard())

    @router.callback_query(F.data == "orders:history")
    async def orders_history(callback: CallbackQuery):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        orders = await db.get_orders_by_statuses(["accepted", "rejected"])
        if not orders:
            await callback.message.answer(
                "История заказов пуста.",
                reply_markup=get_admin_orders_menu_keyboard(),
            )
            return
        status_names = {"accepted": "✅ Принят", "rejected": "❌ Отклонён"}
        for order in orders:
            user_info = await db.get_user(order["user_id"])
            status_label = status_names.get(order.get("status"), order.get("status"))
            text = _format_order_message(order, user_info, status_label=status_label)
            await callback.message.answer(text)
        await callback.message.answer("◀️ Назад в меню заказов:", reply_markup=get_admin_orders_menu_keyboard())

    @router.callback_query(F.data.startswith("order_accept:"))
    async def order_accept(callback: CallbackQuery):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (IndexError, ValueError):
            return
        await db.update_order_status(order_id, "accepted")
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ <b>Статус: Принят</b>",
                reply_markup=None,
            )
        except Exception:
            pass

    @router.callback_query(F.data.startswith("order_reject:"))
    async def order_reject(callback: CallbackQuery):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (IndexError, ValueError):
            return
        await db.update_order_status(order_id, "rejected")
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ <b>Статус: Отклонён</b>",
                reply_markup=None,
            )
        except Exception:
            pass

    @router.callback_query(F.data.startswith("order_edit:"))
    async def order_edit_start(callback: CallbackQuery, state: FSMContext):
        if callback.from_user.id not in adm_ids:
            await callback.answer("⛔ Нет доступа.", show_alert=True)
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        try:
            order_id = int(callback.data.split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer()
            return
        order = await db.get_order(order_id)
        if not order or order.get("status") != "new":
            await callback.answer("Заказ не найден или уже обработан.", show_alert=True)
            return
        await callback.answer()
        await state.update_data(edit_order_id=order_id, edit_order_items=order["items"])
        await state.set_state(AdminOrderEditStates.admin_note)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "Введите <b>комментарий к изменению</b> (admin_note). Например: исправлено количество по просьбе клиента.\n"
            "Или отправьте — чтобы пропустить."
        )

    @router.message(AdminOrderEditStates.admin_note, F.text)
    async def order_edit_note(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        note = (message.text or "").strip() or "(без комментария)"
        await state.update_data(edit_admin_note=note)
        await state.set_state(AdminOrderEditStates.items_json)
        data = await state.get_data()
        items = data.get("edit_order_items", [])
        lines = ["Текущий состав заказа. Отправьте новый в формате (каждая строка): <code>SKU количество</code>", ""]
        for it in items:
            lines.append(f"  {it.get('sku', '—')} — {it.get('quantity', 1)} шт")
        lines.append("")
        lines.append("Пример:\n<code>ART_30_2 2\nART_60_5 1</code>")
        await message.answer("\n".join(lines))

    @router.message(AdminOrderEditStates.items_json, F.text)
    async def order_edit_apply(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        text = (message.text or "").strip()
        data = await state.get_data()
        order_id = data.get("edit_order_id")
        admin_note = data.get("edit_admin_note", "")
        if not order_id:
            await state.clear()
            await message.answer("Сессия сброшена. Начните редактирование заново.")
            return
        new_items = []
        total = 0.0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                qty = int(parts[-1])
            except ValueError:
                continue
            sku = " ".join(parts[:-1]).strip()
            product = await db.get_product_by_sku(sku)
            if not product:
                await message.answer(f"Товар с артикулом <code>{sku}</code> не найден. Введите состав заново.")
                return
            price = float(product.get("price", 0))
            name = product.get("group_name", "—")
            new_items.append({
                "name": name, "sku": sku, "quantity": qty, "price": price,
                "volume": product.get("volume"), "strength": product.get("strength"), "puffs": product.get("puffs"),
            })
            total += price * qty
        if not new_items:
            await message.answer("Не удалось разобрать ни одной позиции. Формат: SKU количество")
            return
        await db.update_order_items_and_note(order_id, new_items, round(total, 2), admin_note)
        await state.clear()
        order = await db.get_order(order_id)
        user_info = await db.get_user(order["user_id"])
        await message.answer(
            "✅ Заказ обновлён.\n\n" + _format_order_message(order, user_info)
            + f"\n\n📝 <i>Изменено админом: {admin_note}</i>",
            reply_markup=get_order_actions_keyboard(order_id),
        )

    # --- /broadcast ---
    @router.message(Command("broadcast"))
    async def cmd_broadcast(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            return
        await state.clear()
        await state.set_state(AdminBroadcastStates.photo)
        await message.answer(
            "📢 <b>Рассылка</b>\n\nОтправьте <b>фото</b> (или текст без фото — тогда отправьте любое сообщение текстом).\n"
            "Для рассылки только текстом отправьте: <code>—</code>"
        )

    @router.message(AdminBroadcastStates.photo, F.photo)
    async def broadcast_photo_received(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        photo = message.photo[-1]
        await state.update_data(broadcast_photo_id=photo.file_id, broadcast_has_photo=True)
        await state.set_state(AdminBroadcastStates.text)
        await message.answer("Отправьте <b>текст</b> рассылки (подпись к фото или сам текст).")

    @router.message(AdminBroadcastStates.photo, F.text)
    async def broadcast_text_only(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        if (message.text or "").strip() == "—":
            await state.update_data(broadcast_has_photo=False)
            await state.set_state(AdminBroadcastStates.text)
            await message.answer("Отправьте <b>текст</b> рассылки.")
            return
        await state.update_data(broadcast_has_photo=False, broadcast_text=(message.text or "").strip())
        await state.set_state(AdminBroadcastStates.button_text)
        await message.answer(
            "Отправьте кнопку в формате: <code>Текст кнопки | https://ссылка.com</code>\n"
            "Или <code>—</code> без кнопки."
        )

    @router.message(AdminBroadcastStates.text, F.text)
    async def broadcast_text_received(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        await state.update_data(broadcast_text=(message.text or "").strip())
        await state.set_state(AdminBroadcastStates.button_text)
        await message.answer(
            "Отправьте кнопку в формате: <code>Текст кнопки | https://ссылка.com</code>\n"
            "Или <code>—</code> без кнопки."
        )

    @router.message(AdminBroadcastStates.button_text, F.text)
    async def broadcast_button_received(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        text = (message.text or "").strip()
        btn_text, btn_url = None, None
        if text != "—" and "|" in text:
            parts = text.split("|", 1)
            btn_text = parts[0].strip()
            btn_url = parts[1].strip()
        await state.update_data(broadcast_btn_text=btn_text, broadcast_btn_url=btn_url)
        await state.set_state(AdminBroadcastStates.confirm)
        data = await state.get_data()
        preview = "Превью:\n\n" + (data.get("broadcast_text") or "(нет текста)")
        if data.get("broadcast_has_photo"):
            preview = "📷 Фото + подпись:\n\n" + preview
        if btn_text and btn_url:
            preview += f"\n\nКнопка: {btn_text} → {btn_url}"
        await message.answer(preview + "\n\nОтправьте <b>да</b> для запуска рассылки или <b>нет</b> для отмены.")

    @router.message(AdminBroadcastStates.confirm, F.text)
    async def broadcast_confirm(message: Message, state: FSMContext):
        if message.from_user.id not in adm_ids:
            await state.clear()
            return
        if (message.text or "").strip().lower() not in ("да", "yes"):
            await state.clear()
            await message.answer("Рассылка отменена.")
            return
        data = await state.get_data()
        await state.clear()
        user_ids = await db.get_all_user_ids()
        has_photo = data.get("broadcast_has_photo")
        text = data.get("broadcast_text") or ""
        btn_text = data.get("broadcast_btn_text")
        btn_url = data.get("broadcast_btn_url")
        markup = None
        if btn_text and btn_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_text, url=btn_url)]])
        status = await message.answer(f"⏳ Рассылка запущена. Получателей: {len(user_ids)}")
        sent, fail = 0, 0
        for uid in user_ids:
            try:
                if has_photo and data.get("broadcast_photo_id"):
                    await bot.send_photo(uid, data["broadcast_photo_id"], caption=text or None, reply_markup=markup)
                else:
                    await bot.send_message(uid, text or "—", reply_markup=markup)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail += 1
        await status.edit_text(f"✅ Рассылка завершена. Доставлено: {sent}, не доставлено: {fail}")

    # --- /export ---
    @router.message(Command("export"))
    async def cmd_export(message: Message):
        if message.from_user.id not in adm_ids:
            return
        orders = await db.get_all_orders_for_export()
        users = await db.get_all_users_for_export()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["order_id", "user_id", "status", "total_amount", "created_at", "admin_note", "items_json"])
        for o in orders:
            w.writerow([
                o.get("order_id"), o.get("user_id"), o.get("status"), o.get("total_amount"),
                o.get("created_at"), o.get("admin_note") or "", o.get("items_json", ""),
            ])
        from aiogram.types import BufferedInputFile
        buf_orders = buf.getvalue().encode("utf-8-sig")
        await message.answer_document(
            BufferedInputFile(buf_orders, filename="orders.csv"),
            caption="Выгрузка заказов (CSV)",
        )
        buf2 = io.StringIO()
        w2 = csv.writer(buf2)
        w2.writerow(["user_id", "username", "full_name", "phone", "city", "created_at"])
        for u in users:
            w2.writerow([
                u.get("user_id"), u.get("username") or "", u.get("full_name") or "",
                u.get("phone") or "", u.get("city") or "", u.get("created_at") or "",
            ])
        buf_users = buf2.getvalue().encode("utf-8-sig")
        await message.answer_document(
            BufferedInputFile(buf_users, filename="users.csv"),
            caption="Выгрузка пользователей (CSV)",
        )

    # --- /ban ---
    @router.message(Command("ban"))
    async def cmd_ban(message: Message):
        if message.from_user.id not in adm_ids:
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: <code>/ban user_id</code>\nПример: /ban 123456789")
            return
        try:
            user_id = int(parts[1])
        except ValueError:
            await message.answer("user_id должен быть числом.")
            return
        await db.add_to_blacklist(user_id)
        await message.answer(f"🚫 Пользователь {user_id} добавлен в чёрный список (заблокирован).")

    # --- /unban ---
    @router.message(Command("unban"))
    async def cmd_unban(message: Message):
        if message.from_user.id not in adm_ids:
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: <code>/unban user_id</code>\nПример: /unban 123456789")
            return
        try:
            user_id = int(parts[1])
        except ValueError:
            await message.answer("user_id должен быть числом.")
            return
        await db.remove_from_blacklist(user_id)
        await message.answer(f"✅ Пользователь {user_id} разблокирован (удалён из чёрного списка).")

    # --- /find ---
    @router.message(Command("find"))
    async def cmd_find(message: Message):
        if message.from_user.id not in adm_ids:
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "Использование: <code>/find ник</code>\n"
                "Пример: /find username или /find @username\n"
                "Поиск по Telegram-нику (username) в базе пользователей."
            )
            return
        nick = parts[1].strip()
        users = await db.find_users_by_username(nick)
        if not users:
            await message.answer(f"По нику «{nick}» пользователи не найдены.")
            return
        lines = [f"Найдено: {len(users)} чел.\n"]
        for u in users[:20]:
            uid = u.get("user_id")
            username = u.get("username") or "—"
            full_name = u.get("full_name") or "—"
            lines.append(f"🆔 <b>{uid}</b> | @{username} | {full_name}")
        if len(users) > 20:
            lines.append(f"\n... и ещё {len(users) - 20}")
        await message.answer("\n".join(lines))
