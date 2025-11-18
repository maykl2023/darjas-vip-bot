import asyncio
import logging
import sqlite3
import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = '8409972026:AAH4xZ99d-Zx2e0eIwm6PVVd5XCM23cFRfY'  # Ваш токен
ADMIN_ID = 123456789  # Замените на ваш Telegram ID (не @maykll23, а число)
PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132
USDT_ADDRESS = 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK'  # USDT TRC20
LTC_ADDRESS = 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz'  # LTC

# Курс для Stars (примерно 0.025 USD/Star для пользователя)
STAR_RATE = 0.025
def usd_to_stars(usd):
    return int(usd / STAR_RATE)

# Цены в USD, округленные
PRICES = {
    'private': {'week': 6, 'month': 18},
    'vip': {'week': 12, 'month': 36},
    'both': {'week': 16, 'month': 43}  # После скидки и округления
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

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

def get_lang(user_lang):
    return 'ru' if user_lang.startswith('ru') else 'en'

async def add_to_channel(user_id, channel_id):
    try:
        await bot.unban_chat_member(channel_id, user_id, only_if_banned=True)
        await bot.export_chat_invite_link(channel_id)  # Для генерации, но используем add
        await bot.add_chat_member(channel_id, user_id)
    except Exception as e:
        logging.error(f'Add error: {e}')

async def remove_from_channel(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except Exception as e:
        logging.error(f'Remove error: {e}')

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    lang = get_lang(message.from_user.language_code)
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('Private DarjaS', callback_data='channel_private'))
    kb.add(InlineKeyboardButton('VIP DarjaS', callback_data='channel_vip'))
    kb.add(InlineKeyboardButton('Both', callback_data='channel_both'))
    await message.reply(texts['welcome'], reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('channel_'))
async def choose_duration(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    channel = callback.data.split('_')[1]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('1 week', callback_data=f'duration_{channel}_week'))
    kb.add(InlineKeyboardButton('1 month', callback_data=f'duration_{channel}_month'))
    await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('duration_'))
async def choose_payment(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[1], parts[2]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}'))
    kb.add(InlineKeyboardButton(texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}'))
    await callback.message.edit_text(texts['price'].format(price=price_usd, stars=stars), reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('pay_stars_'))
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
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=desc,
        payload=payload,
        provider_token='',  # Пустой для Stars
        currency='XTR',
        prices=prices,
        start_parameter='sub'
    )
    await callback.answer()

@dp.pre_checkout_query_handler()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
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

@dp.callback_query_handler(lambda c: c.data.startswith('pay_crypto_'))
async def pay_crypto(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}'))
    kb.add(InlineKeyboardButton('LTC', callback_data=f'crypto_ltc_{channel}_{duration}'))
    await callback.message.edit_text('Choose crypto:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('crypto_'))
async def send_crypto_info(callback: types.CallbackQuery):
    lang = get_lang(callback.from_user.language_code)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    crypto, channel, duration = parts[1], parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    address = USDT_ADDRESS if crypto == 'usdt' else LTC_ADDRESS
    await callback.message.edit_text(texts['crypto_info'].format(price=price_usd, address=address, crypto=crypto.upper()))
    # Теперь пользователь присылает proof, бот пересылает админу
    await callback.answer('Send proof as message or photo.')

@dp.message_handler(content_types=['text', 'photo'])
async def handle_proof(message: types.Message):
    if message.reply_to_message: return  # Игнор если не proof
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f'Proof from {message.from_user.id}. Use /approve {message.from_user.id} channel duration (e.g. private week)')

@dp.message_handler(commands=['approve'], chat_id=ADMIN_ID)
async def approve(message: types.Message):
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
    lang = get_lang((await bot.get_chat(user_id)).language_code)  # Примерно
    texts = TEXTS[lang or 'en']
    await bot.send_message(user_id, texts['access_granted'].format(date=end_date.strftime('%Y-%m-%d')))
    await message.reply('Approved.')

@dp.message_handler(commands=['terms'])
async def terms(message: types.Message):
    lang = get_lang(message.from_user.language_code)
    await message.reply(TEXTS[lang]['terms'])

@dp.message_handler(commands=['support'])
async def support(message: types.Message):
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

async def on_startup(dp):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expirations, CronTrigger(hour=0, minute=0))  # Ежедневно в 00:00
    scheduler.start()
    # Set webhook
    webhook_url = 'https://your-app.onrender.com/webhook'  # Замените на ваш Render URL
    await bot.set_webhook(webhook_url)

if __name__ == '__main__':
    executor.start_webhook(dp, webhook_path='/webhook', on_startup=on_startup, skip_updates=True, host='0.0.0.0', port=8080)
