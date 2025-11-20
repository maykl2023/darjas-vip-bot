import asyncio
import logging
import sqlite3
import datetime
import sys
from os import getenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice,
    PreCheckoutQuery, CallbackQuery, ChatMemberUpdated
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# ──────────────────────── НАСТРОЙКИ ─────────────────────────
TOKEN = '8409972026:AAH4xZ99d-Zx2e0eIwm6PVVd5XCM23cFRfY'
ADMIN_ID = 7761264987  # ← ТУДА ПРИХОДЯТ КВИТАНЦИИ (твой личный ID)

PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132

USDT_TRC20 = 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK'
LTC_ADDRESS = 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz'

WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret"
BASE_WEBHOOK_URL = "https://darjas-vip-bot.onrender.com"

# ──────────────────────── ЦЕНЫ ─────────────────────
STAR_RATE = 0.025
def usd_to_stars(usd): return int(usd / STAR_RATE)

PRICES = {
    'private': {'week': 6,  'month': 18},
    'vip':     {'week': 12, 'month': 36},
    'both':    {'week': 16, 'month': 43}
}

# ──────────────────────── ТЕКСТЫ ─────────────────────
TEXTS = {
    'ru': {
        'greeting': 'Детка я рада тебя видеть\nТебя ожидает невероятное путешествие',
        'welcome': 'Выберите подписку:',
        'choose_duration': 'Выберите срок для {channel}:',
        'price': 'Цена: {price}$ ({stars} Stars)',
        'pay_stars': 'Оплатить Stars',
        'pay_crypto': 'Оплатить криптой',
        'crypto_choice': 'Выберите криптовалюту:',
        'address_msg': '<b>Отправьте ровно {amount}$</b>\n\nАдрес:\n<code>{address}</code>\nСеть: <b>{network}</b>\n\nНажмите на адрес — он скопируется',
        'proof_msg': 'Пришлите фото/скриншот перевода сюда ↓\nЯ проверю и выдам доступ за 1–3 минуты',
        'access_granted': 'Ссылка для вступления:\n{link}\n\nСрок начнётся после вступления в канал',
        'subscription_started': 'Подписка активирована!\nЗаканчивается: <b>{date}</b>',
        'back': 'Назад',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'both_button': 'Private+VIP (скидка)',
        'check_received': 'Чек получен! Ожидайте — проверяю (1–3 мин)'
    }
}

# ──────────────────────── БАЗА ДАННЫХ ─────────────────────
conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, channel TEXT, end_date TEXT, duration TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru')''')
cursor.execute('''CREATE TABLE IF NOT EXISTS crypto_pending (user_id INTEGER PRIMARY KEY, channel TEXT, duration TEXT, crypto TEXT, amount REAL)''')
conn.commit()

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

def get_lang(user_id):
    cursor.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
    r = cursor.fetchone()
    return r[0] if r else 'ru'

async def set_lang(user_id, lang='ru'):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)', (user_id, lang))
    conn.commit()

async def get_days(duration):
    return 7 if duration == 'week' else 30

async def create_invite(user_id, channel_id):
    try:
        link = await bot.create_chat_invite_link(channel_id, member_limit=1)
        return link.invite_link
    except Exception as e:
        await bot.send_message(ADMIN_ID, f'Ошибка ссылки для {user_id}: {e}')
        return 'Ошибка генерации ссылки'

async def kick_user(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except: pass

# ──────────────────────── СТАРТ ─────────────────────
@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    texts = TEXTS['ru']  # пока только русский

    await message.answer(texts['greeting'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data='channel_private')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data='channel_vip')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data='channel_both')],
    ])
    await message.answer(texts['welcome'], reply_markup=kb)

# ──────────────────────── ВЫБОР КАНАЛА И СРОКА ─────────────────────
@router.callback_query(F.data.startswith('channel_'))
async def choose_duration(callback: CallbackQuery):
    channel = callback.data.split('_')[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1 неделя', callback_data=f'duration_{channel}_week')],
        [InlineKeyboardButton(text='1 месяц', callback_data=f'duration_{channel}_month')],
        [InlineKeyboardButton(text='Назад', callback_data='back_main')],
    ])
    await callback.message.edit_text(f"Выберите срок для {channel.upper()}:", reply_markup=kb)

@router.callback_query(F.data == 'back_main')
async def back_main(callback: CallbackQuery):
    await start(callback.message)

@router.callback_query(F.data.startswith('duration_'))
async def choose_payment(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration = parts[1], parts[2]
    price = PRICES[channel][duration]
    stars = usd_to_stars(price)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Оплатить Stars', callback_data=f'pay_stars_{channel}_{duration}')],
        [InlineKeyboardButton(text='Оплатить криптой', callback_data=f'pay_crypto_{channel}_{duration}')],
        [InlineKeyboardButton(text='Назад', callback_data=f'channel_{channel}')],
    ])
    await callback.message.edit_text(f"Цена: {price}$ ({stars} Stars)", reply_markup=kb)

# ──────────────────────── STARS ─────────────────────
@router.callback_query(F.data.startswith('pay_stars_'))
async def pay_stars(callback: CallbackQuery):
    _, channel, duration = callback.data.split('_', 2)
    price = PRICES[channel][duration]
    stars = usd_to_stars(price)
    title = 'Private + VIP' if channel == 'both' else ('Private' if channel == 'private' else 'VIP')
    title += ' DarjaS'

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description='Доступ к приватному контенту',
        payload=f'{callback.from_user.id}:{channel}:{duration}',
        provider_token='',
        currency='XTR',
        prices=[LabeledPrice(label='Подписка', amount=stars)]
    )

@router.pre_checkout_query()
async def precheckout(q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)

@router.message(F.successful_payment)
async def stars_success(message: Message):
    user_id, channel, duration = message.successful_payment.invoice_payload.split(':')
    user_id = int(user_id)
    channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else \
               [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID]

    links = []
    for ch in channels:
        link = await create_invite(user_id, ch)
        links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL, ?)', (user_id, str(ch), duration))
    conn.commit()

    await message.answer(f"Ссылка для вступления:\n" + "\n".join(links) + "\n\nСрок начнётся после вступления")

# ──────────────────────── КРИПТО ─────────────────────
@router.callback_query(F.data.startswith('pay_crypto_'))
async def crypto_choice(callback: CallbackQuery):
    _, channel, duration = callback.data.split('_', 2)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}')],
        [InlineKeyboardButton(text='Назад', callback_data=f'duration_{channel}_{duration.split("_")[0]}')],
    ])
    await callback.message.edit_text("Выберите криптовалюту:", reply_markup=kb)

@router.callback_query(F.data.startswith('crypto_'))
async def show_crypto_address(callback: CallbackQuery):
    parts = callback.data.split('_')
    crypto, channel, duration = parts[1], parts[2], parts[3]
    amount = PRICES[channel][duration]
    address = USDT_TRC20 if crypto == 'usdt' else LTC_ADDRESS
    network = 'TRC20' if crypto == 'usdt' else 'LTC'

    cursor.execute('INSERT OR REPLACE INTO crypto_pending VALUES (?, ?, ?, ?, ?)',
                   (callback.from_user.id, channel, duration, crypto, amount))
    conn.commit()

    await callback.message.answer(TEXTS['ru']['address_msg'].format(address=address, network=network, amount=amount))
    await callback.message.answer(TEXTS['ru']['proof_msg'])

# ──────────────────────── ПРИЁМ ЧЕКА ─────────────────────
@router.message(F.photo)
async def receive_proof(message: Message):
    cursor.execute('SELECT 1 FROM crypto_pending WHERE user_id = ?', (message.from_user.id,))
    if not cursor.fetchone():
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Подтвердить оплату', callback_data=f'confirm_{message.from_user.id}')],
        [InlineKeyboardButton(text='Отклонить', callback_data=f'reject_{message.from_user.id}')],
    ])

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=message.photo[-1].file_id,
        caption=f"Крипто-чек от {message.from_user.full_name}\nID: {message.from_user.id}\n@{message.from_user.username or '—'}",
        reply_markup=kb
    )
    await message.answer(TEXTS['ru']['check_received'])

# ──────────────────────── ПОДТВЕРЖДЕНИЕ ─────────────────────
@router.callback_query(F.data.startswith('confirm_'))
async def confirm_payment(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    row = cursor.execute('SELECT channel, duration FROM crypto_pending WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        return await callback.answer('Уже обработано')

    channel, duration = row
    channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else \
               [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID]

    links = []
    for ch in channels:
        link = await create_invite(user_id, ch)
        links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL, ?)', (user_id, str(ch), duration))
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

    await bot.send_message(user_id, f"Ссылка для вступления:\n" + "\n".join(links) + "\n\nСрок начнётся после вступления")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\nПодтверждено")
    await callback.answer()

@router.callback_query(F.data.startswith('reject_'))
async def reject_payment(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    await bot.send_message(user_id, "Оплата не подтверждена. Проверьте сумму и адрес.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\nОтклонено")
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

# ──────────────────────── JOIN И КИК ─────────────────────
@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=ChatMemberStatus.MEMBER))
async def on_join(update: ChatMemberUpdated):
    user_id = update.from_user.id
    channel_id = str(update.chat.id)
    row = cursor.execute('SELECT duration FROM subs WHERE user_id = ? AND channel = ? AND end_date IS NULL', (user_id, channel_id)).fetchone()
    if row:
        days = 7 if row[0] == 'week' else 30
        end_date = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime('%d.%m.%Y')
        cursor.execute('UPDATE subs SET end_date = ? WHERE user_id = ? AND channel = ?', (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat(), user_id, channel_id)
        conn.commit()
        await bot.send_message(user_id, f"Подписка активирована!\nЗаканчивается: <b>{end_date}</b>")

async def check_expirations():
    now = datetime.datetime.now().isoformat()
    expired = cursor.execute('SELECT user_id, channel FROM subs WHERE end_date < ? AND end_date IS NOT NULL', (now,)).fetchall()
    for uid, ch in expired:
        await kick_user(int(uid), int(ch))
        cursor.execute('DELETE FROM subs WHERE user_id = ? AND channel = ?', (uid, ch))
    conn.commit()

async def on_startup(_):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expirations, CronTrigger(hour=0, minute=15))
    scheduler.start()
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)

if __name__ == '__main__':
    main()
