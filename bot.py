import asyncio
import json
import logging
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery
)

# Токен подтягивается автоматически из настроек Render
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

STAFF_FILE = "staff.json"

DEFAULT_STAFF = [
    "Тактаров Роман",
    "Ганоченко Евгений",
    "Золоторева Юлия",
    "Цехан Виталий",
    "Хоменко Иван",
    "Сторонская Вероника",
    "Гаркушина Елена",
    "Глуговская Арина",
    "Зайченко Даниил",
    "Раку Леонид",
    "Гнесная Мирра",
    "Кухарик Елизавета",
    "Смага Виктор",
    "Зенин Артём",
    "Остроушко Виктория",
    "Кульпина Люси"
]

def load_staff():
    if os.path.exists(STAFF_FILE):
        with open(STAFF_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_STAFF

def save_staff(staff_list):
    with open(STAFF_FILE, "w", encoding="utf-8") as f:
        json.dump(staff_list, f, ensure_ascii=False, indent=2)

class StaffStates(StatesGroup):
    waiting_for_names = State()

class CalcStates(StatesGroup):
    waiting_for_cash = State()
    asking_waiter_card = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я бот для быстрого расчёта «кружки» чаевых.\n\n"
        "📌 **Команды:**\n"
        "• /calc — Начать ежедневный подсчёт\n"
        "• /staff — Посмотреть или изменить список персонала"
    )

@dp.message(Command("staff"))
async def cmd_staff(message: Message, state: FSMContext):
    staff_list = load_staff()
    names_str = "\n• ".join(staff_list) if staff_list else "Список пуст"
    await message.answer(
        f"📋 **Закреплённый список персонала ({len(staff_list)} чел.):**\n• {names_str}\n\n"
        "Чтобы заменить список, отправьте новые ФИО через запятую или с новой строки."
    )
    await state.set_state(StaffStates.waiting_for_names)

@dp.message(StaffStates.waiting_for_names)
async def process_new_staff(message: Message, state: FSMContext):
    raw_input = message.text.replace('\n', ',')
    names = [name.strip() for name in raw_input.split(',') if name.strip()]
    
    if not names:
        await message.answer("⚠️ Пожалуйста, введите хотя бы одно имя.")
        return

    save_staff(names)
    await message.answer(f"✅ Новый список персонала сохранён ({len(names)} чел.)!\n• " + "\n• ".join(names))
    await state.clear()

def get_waiter_action_keyboard():
    buttons = [
        [InlineKeyboardButton(text="0 грн (без безнала)", callback_data="card_0")],
        [InlineKeyboardButton(text="❌ Не работал(а) сегодня", callback_data="card_absent")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("calc"))
async def start_calc(message: Message, state: FSMContext):
    await state.clear()
    staff_list = load_staff()
    
    if not staff_list:
        await message.answer("⚠️ Список персонала пуст. Настройте его командой /staff")
        return

    await message.answer("💵 Введите общую сумму **наличных в кружке** (грн):")
    await state.set_state(CalcStates.waiting_for_cash)

@dp.message(CalcStates.waiting_for_cash)
async def process_cash(message: Message, state: FSMContext):
    try:
        cash = float(message.text.replace(',', '.'))
        if cash < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите корректную сумму числом.")
        return

    staff_list = load_staff()
    await state.update_data(
        cash=cash, 
        staff_list=staff_list, 
        current_index=0, 
        active_waiters={}, 
    )

    first_waiter = staff_list[0]
    await message.answer(
        f"👤 Официант (1/{len(staff_list)}): **{first_waiter}**\n\n"
        "Введите сумму поступлений на карту (числом) или выберите вариант ниже:",
        reply_markup=get_waiter_action_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(CalcStates.asking_waiter_card)

async def ask_next_waiter_or_finish(message_or_callback, state: FSMContext):
    data = await state.get_data()
    staff_list = data["staff_list"]
    idx = data["current_index"] + 1

    if idx < len(staff_list):
        await state.update_data(current_index=idx)
        next_waiter = staff_list[idx]
        
        text = (
            f"👤 Официант ({idx + 1}/{len(staff_list)}): **{next_waiter}**\n\n"
            "Введите сумму поступлений на карту (числом) или выберите вариант ниже:"
        )
        markup = get_waiter_action_keyboard()

        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        else:
            await message_or_callback.answer(text, reply_markup=markup, parse_mode="Markdown")
    else:
        cash = data["cash"]
        active_waiters = data["active_waiters"]
        
        if not active_waiters:
            text = "⚠️ Ни один сотрудник не работал сегодня. Расчёт отменён."
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.message.edit_text(text)
            else:
                await message_or_callback.answer(text)
            await state.clear()
            return

        total_card = sum(active_waiters.values())
        total_bank = cash + total_card
        count = len(active_waiters)
        per_person = total_bank / count

        response_lines = [
            "📊 **Результаты расчёта чаевых**\n",
            f"• Наличные в кружке: `{cash:.2f} грн`",
            f"• Безнал на картах: `{total_card:.2f} грн`",
            f"• Общий банк: `{total_bank:.2f} грн`",
            f"• **Доля на одного ({count} чел.):** `{per_person:.2f} грн`\n",
            "**Выплаты из наличной кружки:**"
        ]

        for name, card_val in active_waiters.items():
            payout = per_person - card_val
            if payout > 0:
                response_lines.append(f"• **{name}**: получает **{payout:.2f} грн** из кружки (на карте `{card_val:.2f} грн`)")
            elif payout == 0:
                response_lines.append(f"• **{name}**: **ничего не берёт** из кружки (вся доля на карте)")
            else:
                debt = abs(payout)
                response_lines.append(f"• **{name}**: **полагает {debt:.2f} грн** в кружку (перебор на карте)")

        response_lines.append("\nДля нового расчёта нажмите /calc")
        final_text = "\n".join(response_lines)

        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(final_text, parse_mode="Markdown")
        else:
            await message_or_callback.answer(final_text, parse_mode="Markdown")

        await state.clear()

@dp.message(CalcStates.asking_waiter_card)
async def process_card_text(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введите корректную сумму числом или нажмите одну из кнопок.")
        return

    data = await state.get_data()
    current_waiter = data["staff_list"][data["current_index"]]
    active_waiters = data["active_waiters"]
    active_waiters[current_waiter] = amount

    await state.update_data(active_waiters=active_waiters)
    await ask_next_waiter_or_finish(message, state)

@dp.callback_query(CalcStates.asking_waiter_card, F.data.in_({"card_0", "card_absent"}))
async def process_card_button(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_waiter = data["staff_list"][data["current_index"]]
    active_waiters = data["active_waiters"]

    if callback.data == "card_0":
        active_waiters[current_waiter] = 0.0

    await state.update_data(active_waiters=active_waiters)
    await callback.answer()
    await ask_next_waiter_or_finish(callback, state)

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
      
