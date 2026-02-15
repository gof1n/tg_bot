"""
FSM-состояния для ботов Augsburg Liquid.
"""

from aiogram.fsm.state import State, StatesGroup


class CheckoutStates(StatesGroup):
    """Оформление заказа (User Bot)."""
    input_name = State()
    input_contact = State()
    input_city = State()
    confirm = State()


class AdminStatsStates(StatesGroup):
    """Выбор своего периода для статистики (Admin Bot)."""
    start_date = State()
    end_date = State()


class AdminBroadcastStates(StatesGroup):
    """Рассылка: фото + текст + кнопка (Admin Bot)."""
    photo = State()
    text = State()
    button_text = State()
    button_url = State()
    confirm = State()


class AdminOrderEditStates(StatesGroup):
    """Редактирование заказа админом: новый items_json + admin_note."""
    items_json = State()
    admin_note = State()
