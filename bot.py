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
ADMIN_USERNAME = 'darivo_s'  # Куда приходят квитанции (можно и ID, но username надёжнее)
ADMIN_ID = 7761264987  # Оставил на всякий случай (для уведомлений)

PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132

# Крипто-адреса
USDT_TRC20 = 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK'
LTC_ADDRESS = 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz'

WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret"
BASE_WEBHOOK_URL = "https://darjas-vip-bot.onrender.com"

# ──────────────────────── ЦЕНЫ (нормальные) ─────────────────────
STAR_RATE = 0.025
def usd_to_stars(usd): return int(usd / STAR_RATE)

PRICES = {
    'private': {'week': 6,  'month': 18},
    'vip':     {'week': 12, 'month': 36},
    'both':    {'week': 16, 'month': 43}
}

# ──────────────────────── ТЕКСТЫ (исправлено) ─────────────────────
TEXTS = {
    'ru': {
        'greeting': 'Детка я рада тебя видеть\nТебя ожидает невероятное путешествие',
        'welcome': 'Выберите подписку:',
        'choose_duration': 'Выберите срок для {channel}:',
        'price': 'Цена: {price}$ ({stars} Stars)',
        'pay_stars': 'Оплатить Stars',
        'pay_crypto': 'Оплатить криптой',
        'crypto_choice': 'Выберите криптовалюту:',
        'address_msg': 'Адрес для оплаты:\n\n<code>{address}</code>\n\nСеть: <b>{network}</b>\nСумма: <b>{amount}$</b>',
        'proof_msg': 'Пришлите сюда фото/скриншот перевода\nЯ проверю и моментально выдам доступ',
        'access_granted': 'Ссылка для вступления:\n{link}\n\nСрок начнётся после вступления в канал',
        'subscription_started': 'Подписка активирована!\nЗаканчивается: <b>{date}</b>',
        'back': 'Назад',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'both_button': 'Private+VIP (скидка)',
        'confirm_payment': 'Подтвердить оплату',
        'payment_confirmed': 'Оплата подтверждена! Выдаю доступ',
        'check_received': 'Чек получен! Ожидайте подтверждения (обычно 1–5 мин)'
    },
    'en': {
        'greeting': 'Baby, I\'m glad to see you\nYou are in for an incredible journey',
        'welcome': 'Choose subscription:',
        'choose_duration': 'Choose duration for {channel}:',
        'price': 'Price: {price}$ ({stars} Stars)',
        'pay_stars': 'Pay with Stars',
        'pay_crypto': 'Pay with crypto',
        'crypto_choice': 'Choose cryptocurrency:',
        'address_msg': 'Payment address:\n\n<code>{address}</code>\n\nNetwork: <b>{network}</b>\nAmount: <b>{amount}$</b>',
        'proof_msg': 'Send here a photo/screenshot of the transfer\nI will check and give access immediately',
        'access_granted': 'Join link:\n{link}\n\nSubscription starts after you join the channel',
        'subscription_started': 'Subscription activated!\nEnds on: <b>{date}</b>',
        'back': 'Back',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'both_button': 'Private+VIP (discount)',
        'confirm_payment': 'Confirm payment',
        'payment_confirmed': 'Payment confirmed! Giving access',
        'check_received': 'Check received! Please wait for confirmation (usually 1–5 min)'
    }
}

# ──────────────────────── БАЗА ДАННЫХ ───────────────────────────
conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS subs 
                  (user_id INTEGER, channel TEXT, end_date TEXT, duration TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                  (user_id INTEGER PRIMARY KEY, lang TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS crypto_pending 
                  (user_id INTEGER PRIMARY KEY, channel TEXT, duration TEXT, crypto TEXT, amount REAL)''')
conn.commit()

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ──────────────────────── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ───────────────
def get_lang(user_id):
    cursor.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
    r = cursor.fetchone()
    return r[0] if r else 'ru'

async def set_lang(user_id, lang):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)', (user_id, lang))
    conn.commit()

async def get_days(duration):
    return 7 if duration == 'week' else 30

async def create_invite(user_id, channel_id):
    try:
        link = await bot.create_chat_invite_link(channel_id, member_limit=1)
        return link.invite_link
    except Exception as e:
        await bot.send_message(ADMIN_ID, f'Ошибка создания ссылки для {user_id}: {e}')
        return None

async def kick_user(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except: pass

# ──────────────────────── СТАРТ И ЯЗЫК ───────────────────────
@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    if lang not in ['ru', 'en']:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Русский', callback_data='lang_ru')],
            [InlineKeyboardButton(text='English', callback_data='lang_en')]
        ])
        return await message.answer('Выберите язык / Choose language:', reply_markup=kb)

    texts = TEXTS[lang]
    await message.answer(texts['greeting'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
    ])
    await message.answer(texts['welcome'], reply_markup=kb)

@router.callback_query(F.data.startswith('lang_'))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split('_')[1]
    await set_lang(callback.from_user.id, lang)
    await callback.message.delete()
    await start(callback.message)

# ──────────────────────── ВЫБОР КАНАЛА И СРОКА ─────────────────
@router.callback_query(F.data.startswith('channel_'))
async def choose_duration(callback: CallbackQuery):
    channel, lang = callback.data.split('_')[1], callback.data.split('_')[2]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1 неделя' if lang=='ru' else '1 week', callback_data=f'duration_{channel}_week_{lang}')],
        [InlineKeyboardButton(text='1 месяц' if lang=='ru' else '1 month', callback_data=f'duration_{channel}_month_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_main_{lang}')],
    ])
    await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)

@router.callback_query(F.data.startswith('duration_'))
async def choose_payment_method(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[1], parts[2], parts[3]
    texts = TEXTS[lang]
    price = PRICES[channel][duration]
    stars = usd_to_stars(price)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'channel_{channel}_{lang}')],
    ])
    await callback.message.edit_text(texts['price'].format(price=price, stars=stars), reply_markup=kb)

# ──────────────────────── ОПЛАТА STARS ───────────────────────
@router.callback_query(F.data.startswith('pay_stars_'))
async def send_invoice(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)

    title = 'Private + VIP' if channel == 'both' else ('Private' if channel == 'private' else 'VIP')
    title += ' DarjaS'

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description='Доступ к приватному контенту',
        payload=f'{callback.from_user.id}:{channel}:{duration}:{lang}',
        provider_token='',
        currency='XTR',
        prices=[LabeledPrice(label='Подписка', amount=stars)]
    )

@router.pre_checkout_query()
async def precheckout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@router.message(F.successful_payment)
async def stars_paid(message: Message):
    user_id, channel, duration, lang = message.successful_payment.invoice_payload.split(':')
    user_id = int(user_id)
    texts = TEXTS[lang]
    channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else \
               [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID]

    links = []
    for ch_id in channels:
        link = await create_invite(user_id, ch_id)
        if link: links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL, ?)', (user_id, str(ch_id), duration))
    conn.commit()

    await message.answer(texts['access_granted'].format(link='\n'.join(links)))
    await bot.send_message(ADMIN_ID, f'Stars оплата: {user_id} → {channel} {duration}')

# ──────────────────────── КРИПТО-ОПЛАТА ───────────────────────
@router.callback_query(F.data.startswith('pay_crypto_'))
async def crypto_start(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='Litecoin (LTC)', callback_data=f'crypto_ltc_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=TEXTS[lang]['back'], callback_data=f'duration_{channel}_{duration}_{lang}')],
    ])
    await callback.message.edit_text(TEXTS[lang]['crypto_choice'], reply_markup=kb)

@router.callback_query(F.data.startswith('crypto_'))
async def crypto_address(callback: CallbackQuery):
    parts = callback.data.split('_')
    crypto = parts[1]
    channel = parts[2]
    duration = parts[3]
    lang = parts[4]
    amount = PRICES[channel][duration]
    address = USDT_TRC20 if crypto == 'usdt' else LTC_ADDRESS
    network = 'TRC20' if crypto == 'usdt' else 'LTC'

    cursor.execute('INSERT OR REPLACE INTO crypto_pending VALUES (?, ?, ?, ?, ?)',
                   (callback.from_user.id, channel, duration, crypto, amount))
    conn.commit()

    addr_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Скопировать адрес', callback_data='copy')]])
    await callback.message.answer(TEXTS[lang]['address_msg'].format(address=address, network=network, amount=amount), reply_markup=addr_kb)
    await callback.message.answer(TEXTS[lang]['proof_msg'])

@router.callback_query(F.data == 'copy')
async def copy(callback: CallbackQuery):
    await callback.answer('Адрес скопирован в буфер!', show_alert=True)

@router.message(F.photo)
async def crypto_proof(message: Message):
    cursor.execute('SELECT 1 FROM crypto_pending WHERE user_id = ?', (message.from_user.id,))
    if not cursor.fetchone():
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Подтвердить оплату', callback_data=f'confirm_{message.from_user.id}')],
        [InlineKeyboardButton(text='Отклонить', callback_data=f'reject_{message.from_user.id}')],
    ])
    await bot.send_photo(ADMIN_USERNAME, message.photo[-1].file_id,
                         caption=f'Крипто-чек от @{message.from_user.username or "NoUsername"} ({message.from_user.id})\n{message.from_user.full_name}',
                         reply_markup=kb)
    await message.answer(TEXTS[get_lang(message.from_user.id)]['check_received'])

@router.callback_query(F.data.startswith('confirm_'))
async def confirm_crypto(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    row = cursor.execute('SELECT channel, duration FROM crypto_pending WHERE user_id = ?', (user_id,)).fetchone()
    if not row: return await callback.answer('Уже обработано')

    channel, duration = row
    lang = get_lang(user_id)
    channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else \
               [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID]

    links = []
    for ch_id in channels:
        link = await create_invite(user_id, ch_id)
        if link: links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL, ?)', (user_id, str(ch_id), duration))
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

    await bot.send_message(user_id, TEXTS[lang]['access_granted'].format(link='\n'.join(links)))
    await callback.message.edit_caption(caption=callback.message.caption + '\n\nПодтверждено')
    await callback.answer()

@router.callback_query(F.data.startswith('reject_'))
async def reject_crypto(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    await bot.send_message(user_id, 'Оплата не подтверждена. Проверьте сумму и адрес.')
    await callback.message.edit_caption(caption=callback.message.caption + '\n\nОтклонено')
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

# ──────────────────────── JOIN И ВЫКИДЫВАНИЕ ─────────────────
@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=ChatMemberStatus.MEMBER))
async def user_joined(update: ChatMemberUpdated):
    user_id = update.from_user.id
    channel_id = str(update.chat.id)
    row = cursor.execute('SELECT duration FROM subs WHERE user_id = ? AND channel = ? AND end_date IS NULL', (user_id, channel_id)).fetchone()
    if row:
        days = await get_days(row[0])
        end_date = datetime.datetime.now() + datetime.timedelta(days=days)
        cursor.execute('UPDATE subs SET end_date = ? WHERE user_id = ? AND channel = ?', (end_date.isoformat(), user_id, channel_id))
        conn.commit()
        await bot.send_message(user_id, TEXTS[get_lang(user_id)]['subscription_started'].format(date=end_date.strftime('%d.%m.%Y')))

async def check_expirations():
    now = datetime.datetime.now().isoformat()
    expired = cursor.execute('SELECT user_id, channel FROM subs WHERE end_date < ? AND end_date IS NOT NULL', (now,)).fetchall()
    for user_id, ch_id in expired:
        await kick_user(user_id, int(ch_id))
        cursor.execute('DELETE FROM subs WHERE user_id = ? AND channel = ?', (user_id, ch_id))
    conn.commit()

async def on_startup(bot: Bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expirations, CronTrigger(hour=0, minute=10))
    scheduler.start()
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)

if __name__ == '__main__':
    main()
