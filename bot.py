import asyncio
import logging
import sqlite3
import datetime
import sys
from os import getenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Токен и настройки
TOKEN = '8409972026:AAH4xZ99d-Zx2e0eIwm6PVVd5XCM23cFRfY'  # Твой токен
ADMIN_ID = 7761264987  # Твой ID
PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132
USDT_ADDRESS = 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK'
LTC_ADDRESS = 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz'

# Webhook настройки
WEB_SERVER_HOST = "0.0.0.0"  # Для Render
WEB_SERVER_PORT = int(getenv("PORT", 8080))  # Render использует $PORT
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret"  # Опционально, для безопасности
BASE_WEBHOOK_URL = "https://darjas-vip-bot.onrender.com"  # Твой Render URL

# Курс для Stars
STAR_RATE = 0.025
def usd_to_stars(usd):
    return int(usd / STAR_RATE)

# Цены
PRICES = {
    'private': {'week': 6, 'month': 18},
    'vip': {'week': 12, 'month': 36},
    'both': {'week': 16, 'month': 43}
}

# Тексты
TEXTS = {
    'ru': {
        'welcome': 'Добро пожаловать! Выберите подписку:',
        'choose_channel': 'Выберите канал:',
        'choose_duration': 'Выберите срок для {channel}:',
        'price': 'Цена: {price}$ ({stars} Stars) или крипта.',
        'pay_stars': 'Оплатить Stars',
        'pay_crypto': 'Оплатить криптой',
        'crypto_info': 'Отправьте {price}$ эквивалент на {address} ({crypto}), затем пришлите proof здесь.',
        'access_granted': 'Доступ предоставлен до {date}.',
        'error': 'Ошибка: {msg}',
        'terms': 'Условия: Подписка на приватные каналы. Нет возвратов.',
        'support': 'Поддержка: @maykll23'
    },
    'en': {
        'welcome': 'Welcome! Choose subscription:',
        'choose_channel': 'Choose channel:',
        'choose_duration': 'Choose duration for {channel}:',
        'price': 'Price: {price}$ ({stars} Stars) or crypto.',
        'pay_stars': 'Pay with Stars',
        'pay_crypto': 'Pay with crypto',
        'crypto_info': 'Send {price}$ equivalent to {address} ({crypto}), then send proof here.',
        'access_granted': 'Access granted until {date}.',
        'error': 'Error: {msg}',
        'terms': 'Terms: Subscription to private channels. No refunds.',
        'support': 'Support: @maykll23'
    }
}

# DB
conn = sqlite3.connect('subscriptions.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS subs 
                  (user_id INTEGER, channel TEXT, end_date TEXT)''')
conn.commit()

# Bot и Dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

def get_lang(user_lang):
    return 'ru' if user_lang and user_lang.startswith('ru') else 'en'

async def add_to_channel(user_id, channel_id):
    try:
        await bot.unban_chat_member(channel_id, user_id, only_if_banned=True)
        await bot.add_chat_member(channel_id, user_id)
    except Exception as e:
        logging.error(f'Add error: {e}')
        await bot.send_message(ADMIN_ID, f'Error adding user {user_id} to channel {channel_id}: {e}')

async def remove_from_channel(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except Exception as e:
        logging.error(f'Remove error: {e}')
        await bot.send_message(ADMIN_ID, f'Error removing user {user_id} from channel {channel_id}: {e}')

@router.message(CommandStart())
async def start(message: Message):
    lang = get_lang(message.from_user.language_code)
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Private DarjaS', callback_data='channel_private')],
        [InlineKeyboardButton(text='VIP DarjaS', callback_data='channel_vip')],
        [InlineKeyboardButton(text='Both', callback_data='channel_both')]
    ])
    await message.reply(texts['welcome'], reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('channel_'))
async def choose_duration(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    channel = callback.data.split('_')[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1 week', callback_data=f'duration_{channel}_week')],
        [InlineKeyboardButton(text='1 month', callback_data=f'duration_{channel}_month')]
    ])
    await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('duration_'))
async def choose_payment(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[1], parts[2]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}')],
        [InlineKeyboardButton(text=texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}')]
    ])
    await callback.message.edit_text(texts['price'].format(price=price_usd, stars=stars), reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('pay_stars_'))
async def pay_stars(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    prices = [LabeledPrice(label='Subscription', amount=stars)]
    if channel == 'both':
        title = 'Subscription to Both Channels'
        desc = 'Access to Private and VIP DarjaS'
        channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    elif channel == 'private':
        title = 'Subscription to Private DarjaS'
        desc = 'Access to Private channel'
        channels = [PRIVATE_CHANNEL_ID]
    else:
        title = 'Subscription to VIP DarjaS'
        desc = 'Access to VIP channel'
        channels = [VIP_CHANNEL_ID]
    payload = f'{callback.from_user.id}:{channel}:{duration}'
    try:
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=title,
            description=desc,
            payload=payload,
            provider_token='',
            currency='XTR',
            prices=prices
        )
    except Exception as e:
        await callback.answer(texts['error'].format(msg=str(e)))
        await bot.send_message(ADMIN_ID, f'Payment error for user {callback.from_user.id}: {e}')
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@router.message(lambda m: m.successful_payment)
async def successful_payment(message: Message):
    lang = get_lang(message.from_user.language_code)
    texts = TEXTS[lang]
    payload = message.successful_payment.invoice_payload
    user_id, channel, duration = payload.split(':')
    user_id = int(user_id)
    days = 7 if duration == 'week' else 30
    end_date = datetime.datetime.now() + datetime.timedelta(days=days)
    channels = [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID] if channel == 'vip' else [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    for ch_id in channels:
        await add_to_channel(user_id, ch_id)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, ?)', (user_id, str(ch_id), end_date.isoformat()))
    conn.commit()
    await message.reply(texts['access_granted'].format(date=end_date.strftime('%Y-%m-%d')))
    await bot.send_message(ADMIN_ID, f'Successful payment: User {user_id}, {channel} {duration}')

@router.callback_query(lambda c: c.data.startswith('pay_crypto_'))
async def pay_crypto(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}')]
    ])
    await callback.message.edit_text('Choose crypto:', reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('crypto_'))
async def send_crypto_info(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    crypto, channel, duration = parts[1], parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    address = USDT_ADDRESS if crypto == 'usdt' else LTC_ADDRESS
    await callback.message.edit_text(texts['crypto_info'].format(price=price_usd, address=address, crypto=crypto.upper()))
    await callback.answer('Send proof as message or photo.')

@router.message()
async def handle_proof(message: Message):
    if message.reply_to_message: return
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f'Proof from {message.from_user.id}. Use /approve {message.from_user.id} channel duration (e.g. private week)')

@router.message(Command('approve'))
async def approve(message: Message):
    if message.chat.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 4: return await message.reply('Usage: /approve user_id channel duration')
    user_id = int(parts[1])
    channel = parts[2]
    duration = parts[3]
    days = 7 if duration == 'week' else 30
    end_date = datetime.datetime.now() + datetime.timedelta(days=days)
    channels = [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID] if channel == 'vip' else [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    for ch_id in channels:
        await add_to_channel(user_id, ch_id)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, ?)', (user_id, str(ch_id), end_date.isoformat()))
    conn.commit()
    user = await bot.get_chat(user_id)
    lang = get_lang(user.language_code)
    texts = TEXTS[lang]
    await bot.send_message(user_id, texts['access_granted'].format(date=end_date.strftime('%Y-%m-%d')))
    await message.reply('Approved.')

@router.message(Command('terms'))
async def terms(message: Message):
    lang = get_lang(message.from_user.language_code)
    await message.reply(TEXTS[lang]['terms'])

@router.message(Command('support'))
async def support(message: Message):
    lang = get_lang(message.from_user.language_code)
    await message.reply(TEXTS[lang]['support'])

async def check_expirations():
    now = datetime.datetime.now().isoformat()
    cursor.execute('SELECT * FROM subs WHERE end_date < ?', (now,))
    expired = cursor.fetchall()
    for user_id, ch_id, _ in expired:
        await remove_from_channel(int(user_id), int(ch_id))
        cursor.execute('DELETE FROM subs WHERE user_id=? AND channel=?', (user_id, ch_id))
    conn.commit()
    if expired:
        await bot.send_message(ADMIN_ID, f'Expired {len(expired)} subs.')

async def on_startup(bot: Bot) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expirations, CronTrigger(hour=0, minute=0))
    scheduler.start()
    await bot.set_webhook(f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET)

def main() -> None:
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)

if __name__ == "__main__":
    main()
