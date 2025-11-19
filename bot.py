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
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, CallbackQuery
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import requests
from pytoniq import LiteClient

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Токен и настройки
TOKEN = '8409972026:AAH4xZ99d-Zx2e0eIwm6PVVd5XCM23cFRfY'  # Твой токен
ADMIN_ID = 7761264987  # Твой ID
PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132
USDT_ADDRESS = 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK'
LTC_ADDRESS = 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz'
TON_ADDRESS = 'UQAUkv5UACvJoDPz2YhUkItK8Kuy9UB1OnHHDsLdlSkKJUl-'  # Твой TON адрес

# Webhook настройки
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(getenv("PORT", 8080))
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = "my-secret"
BASE_WEBHOOK_URL = "https://darjas-vip-bot.onrender.com"

# Курс для Stars
STAR_RATE = 0.025
def usd_to_stars(usd):
    return int(usd / STAR_RATE)

# Динамический курс TON/USD
def get_ton_usd_price():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd')
        return response.json()['the-open-network']['usd']
    except Exception as e:
        logging.error(f"TON price error: {e}")
        return 5.0  # Фоллбек

def usd_to_ton(usd):
    ton_price = get_ton_usd_price()
    return usd / ton_price

# Цены
PRICES = {
    'private': {'week': 6, 'month': 18},
    'vip': {'week': 12, 'month': 36},
    'both': {'week': 16, 'month': 43},
    'test': {'2weeks': 0.025}
}

# Тексты
TEXTS = {
    'ru': {
        'greeting': 'Детка я рада тебя видеть😘\nТебя ожидает невероятное путешествие💋🔞',
        'welcome': 'Выберите подписку:',
        'choose_duration': 'Выберите срок для {channel}:',
        'choose_duration_test': 'Тестовая подписка:',
        'price': 'Цена: {price}$ ({stars} Stars) или крипта.',
        'pay_stars': 'Оплатить Stars',
        'pay_crypto': 'Оплатить криптой',
        'pay_ton': 'Оплатить TON',
        'ton_info': 'Отправьте {ton_amount:.4f} TON на {address} с memo: {memo}. Ждите подтверждения (до 1 мин).',
        'crypto_info': 'Отправьте {price}$ эквивалент на {address} ({crypto}), затем пришлите фото квитанции сюда.',
        'access_granted': 'Ссылка для вступления: {link}. Срок начнётся после вступления (до {date} после join).',
        'error': 'Ошибка: {msg}',
        'terms': 'Условия: Подписка на приватные каналы. Нет возвратов.',
        'support': 'Поддержка: @maykll23',
        'back': 'Назад',
        'both_button': 'Private+VIP (скидка 10-20%)',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'test_button': 'Тест (2 недели за 1 Star)',
        'choose_crypto': 'Выберите крипту:',
        'send_proof': 'Пришлите фото квитанции сюда.',
        'delay_warning': 'Возможна задержка ответа от бота до 2 минут в связи с большим количеством операций'
    },
    'en': {
        'greeting': 'Baby, I\'m glad to see you😘\nYou are in for an incredible journey💋🔞',
        'welcome': 'Choose subscription:',
        'choose_duration': 'Choose duration for {channel}:',
        'choose_duration_test': 'Test subscription:',
        'price': 'Price: {price}$ ({stars} Stars) or crypto.',
        'pay_stars': 'Pay with Stars',
        'pay_crypto': 'Pay with crypto',
        'pay_ton': 'Pay with TON',
        'ton_info': 'Send {ton_amount:.4f} TON to {address} with memo: {memo}. Wait for confirmation (up to 1 min).',
        'crypto_info': 'Send {price}$ equivalent to {address} ({crypto}), then send photo of the receipt here.',
        'access_granted': 'Join link: {link}. Subscription starts after joining (until {date} after join).',
        'error': 'Error: {msg}',
        'terms': 'Terms: Subscription to private channels. No refunds.',
        'support': 'Support: @maykll23',
        'back': 'Back',
        'both_button': 'Private+VIP (10-20% off)',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'test_button': 'Test (2 weeks for 1 Star)',
        'choose_crypto': 'Choose crypto:',
        'send_proof': 'Send photo of the receipt here.',
        'delay_warning': 'Possible delay in bot response up to 2 minutes due to high volume of operations'
    }
}

# DB
conn = sqlite3.connect('subscriptions.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS subs 
                  (user_id INTEGER, channel TEXT, end_date TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                  (user_id INTEGER PRIMARY KEY, lang TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS pending_payments 
                  (user_id INTEGER, channel TEXT, duration TEXT, amount FLOAT, memo TEXT)''')
conn.commit()

# Bot и Dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# TON Client без ключа
ton_client = LiteClient.from_mainnet_config(ls_i=2, trust_level=2)  # ls_i for liteserver index, trust_level for security

def get_lang(user_id):
    cursor.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 'en'

async def set_lang(user_id, lang):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)', (user_id, lang))
    conn.commit()

async def get_days_from_duration(duration):
    if duration == '2weeks':
        return 14
    return 7 if duration == 'week' else 30

async def add_to_channel(user_id, channel_id):
    try:
        await bot.unban_chat_member(channel_id, user_id, only_if_banned=True)
        invite = await bot.create_chat_invite_link(channel_id, member_limit=1)
        return invite.invite_link
    except Exception as e:
        logging.error(f'Add error: {e}')
        await bot.send_message(ADMIN_ID, f'Error granting access to user {user_id} in channel {channel_id}: {e}')
        return None

async def remove_from_channel(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except Exception as e:
        logging.error(f'Remove error: {e}')
        await bot.send_message(ADMIN_ID, f'Error removing user {user_id} from channel {channel_id}: {e}')

@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    await message.reply(TEXTS['ru']['delay_warning'] + '\n' + TEXTS['en']['delay_warning'])
    lang = get_lang(user_id)
    if lang is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='English', callback_data='lang_en')],
            [InlineKeyboardButton(text='Russian', callback_data='lang_ru')]
        ])
        await message.reply('Choose language:', reply_markup=kb)
    else:
        texts = TEXTS[lang]
        await message.reply(texts['greeting'])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['private_button'], callback_data='channel_private')],
            [InlineKeyboardButton(text=texts['vip_button'], callback_data='channel_vip')],
            [InlineKeyboardButton(text=texts['both_button'], callback_data='channel_both')],
            [InlineKeyboardButton(text=texts['test_button'], callback_data='channel_test')]
        ])
        await message.reply(texts['welcome'], reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('lang_'))
async def choose_lang(callback: CallbackQuery):
    lang = callback.data.split('_')[1]
    await set_lang(callback.from_user.id, lang)
    texts = TEXTS[lang]
    await callback.message.reply(texts['greeting'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data='channel_private')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data='channel_vip')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data='channel_both')],
        [InlineKeyboardButton(text=texts['test_button'], callback_data='channel_test')]
    ])
    await callback.message.reply(texts['welcome'], reply_markup=kb)
    await callback.message.delete()
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('channel_'))
async def choose_duration(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    channel = callback.data.split('_')[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1 week', callback_data=f'duration_{channel}_week')],
        [InlineKeyboardButton(text='1 month', callback_data=f'duration_{channel}_month')],
        [InlineKeyboardButton(text=texts['back'], callback_data='back_start')]
    ])
    if channel == 'test':
        kb.inline_keyboard[0][0].text = '2 weeks'
        kb.inline_keyboard[0][0].callback_data = f'duration_test_2weeks'
        kb.inline_keyboard.pop(1)  # Убрать month для test
    await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('duration_'))
async def choose_payment(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[1], parts[2]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}')],
        [InlineKeyboardButton(text=texts['pay_ton'], callback_data=f'pay_ton_{channel}_{duration}')],
        [InlineKeyboardButton(text=texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_channel_{channel}')]
    ])
    await callback.message.edit_text(texts['price'].format(price=price_usd, stars=stars), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('back_'))
async def back_handler(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    if parts[1] == 'start':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['private_button'], callback_data='channel_private')],
            [InlineKeyboardButton(text=texts['vip_button'], callback_data='channel_vip')],
            [InlineKeyboardButton(text=texts['both_button'], callback_data='channel_both')],
            [InlineKeyboardButton(text=texts['test_button'], callback_data='channel_test')]
        ])
        await callback.message.edit_text(texts['welcome'], reply_markup=kb)
    elif parts[1] == 'channel':
        channel = parts[2]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='1 week', callback_data=f'duration_{channel}_week')],
            [InlineKeyboardButton(text='1 month', callback_data=f'duration_{channel}_month')],
            [InlineKeyboardButton(text=texts['back'], callback_data='back_start')]
        ])
        await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('pay_stars_'))
async def pay_stars(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    prices = [LabeledPrice(label='Subscription', amount=stars)]
    if channel == 'both':
        title = 'Subscription to Both Channels'
        desc = 'Access to Private and VIP DarjaS'
    elif channel == 'private':
        title = 'Subscription to Private DarjaS'
        desc = 'Access to Private channel'
    elif channel == 'vip':
        title = 'Subscription to VIP DarjaS'
        desc = 'Access to VIP channel'
    else:
        title = 'Test Subscription'
        desc = 'Test access for 2 weeks'
    payload = f'{callback.from_user.id}:{channel}:{duration}'
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=desc,
        payload=payload,
        provider_token='',
        currency='XTR',
        prices=prices
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@router.message(lambda m: m.successful_payment)
async def successful_payment(message: Message):
    lang = get_lang(message.from_user.id)
    texts = TEXTS[lang]
    payload = message.successful_payment.invoice_payload
    user_id, channel, duration = payload.split(':')
    user_id = int(user_id)
    days = await get_days_from_duration(duration)
    channels = [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID] if channel == 'vip' else [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else [PRIVATE_CHANNEL_ID]
    links = []
    for ch_id in channels:
        link = await add_to_channel(user_id, ch_id)
        if link:
            links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL)', (user_id, str(ch_id)))
    conn.commit()
    link_text = '\n'.join(links)
    await message.reply(texts['access_granted'].format(link=link_text, date='[date after join]'))
    await bot.send_message(ADMIN_ID, f'Successful payment: User {user_id}, {channel} {duration}')

@router.callback_query(lambda c: c.data.startswith('pay_ton_'))
async def pay_ton(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    ton_amount = usd_to_ton(price_usd)
    memo = f'{callback.from_user.id}:{channel}:{duration}'
    cursor.execute('INSERT INTO pending_payments VALUES (?, ?, ?, ?, ?)', (callback.from_user.id, channel, duration, ton_amount, memo))
    conn.commit()
    await callback.message.edit_text(texts['ton_info'].format(ton_amount=ton_amount, address=TON_ADDRESS, memo=memo))
    await callback.answer()

async def check_ton_payments():
    cursor.execute('SELECT * FROM pending_payments')
    pending = cursor.fetchall()
    for p in pending:
        user_id, channel, duration, amount, memo = p
        try:
            transactions = await ton_client.get_account_transactions(TON_ADDRESS, count=20)
            for tx in transactions:
                if tx.in_msg and tx.in_msg.msg_data.text == memo and tx.in_msg.value / 10**9 >= amount:
                    cursor.execute('DELETE FROM pending_payments WHERE user_id=? AND memo=?', (user_id, memo))
                    conn.commit()
                    days = await get_days_from_duration(duration)
                    channels = [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID] if channel == 'vip' else [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else [PRIVATE_CHANNEL_ID]
                    links = []
                    for ch_id in channels:
                        link = await add_to_channel(user_id, ch_id)
                        if link:
                            links.append(link)
                        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL)', (user_id, str(ch_id)))
                    conn.commit()
                    texts = TEXTS[get_lang(user_id)]
                    link_text = '\n'.join(links)
                    await bot.send_message(user_id, texts['access_granted'].format(link=link_text, date='[date after join]'))
                    await bot.send_message(ADMIN_ID, f'TON payment confirmed: User {user_id}, {channel} {duration}')
                    break
        except Exception as e:
            logging.error(f'TON check error: {e}')

@router.callback_query(lambda c: c.data.startswith('pay_crypto_'))
async def pay_crypto(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    channel, duration = parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_duration_{channel}')],
    ])
    await callback.message.edit_text(texts['choose_crypto'], reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('crypto_'))
async def send_crypto_info(callback: CallbackQuery):
    lang = get_lang(callback.from_user.id)
    texts = TEXTS[lang]
    parts = callback.data.split('_')
    crypto, channel, duration = parts[1], parts[2], parts[3]
    price_usd = PRICES[channel][duration]
    address = USDT_ADDRESS if crypto == 'usdt' else LTC_ADDRESS
    await callback.message.edit_text(texts['crypto_info'].format(price=price_usd, address=address, crypto=crypto.upper()))
    await callback.answer(texts['send_proof'])

@router.message(content_types=['text', 'photo'])
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
    lang = get_lang(user_id)
    texts = TEXTS[lang]
    channels = [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID] if channel == 'vip' else [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else [PRIVATE_CHANNEL_ID]
    links = []
    for ch_id in channels:
        link = await add_to_channel(user_id, ch_id)
        if link:
            links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL)', (user_id, str(ch_id)))
    conn.commit()
    link_text = '\n'.join(links)
    await bot.send_message(user_id, texts['access_granted'].format(link=link_text, date='[date after join]'))
    await message.reply('Approved.')

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(update: ChatMemberUpdated):
    channel_id = update.chat.id
    user_id = update.from_user.id
    cursor.execute('SELECT * FROM subs WHERE user_id = ? AND channel = ? AND end_date IS NULL', (user_id, str(channel_id)))
    if cursor.fetchone():
        # Assume 30 days, or store duration in DB
        end_date = datetime.datetime.now() + datetime.timedelta(days=30)
        cursor.execute('UPDATE subs SET end_date = ? WHERE user_id = ? AND channel = ?', (end_date.isoformat(), user_id, str(channel_id)))
        conn.commit()
        lang = get_lang(user_id)
        texts = TEXTS[lang]
        await bot.send_message(user_id, f'Subscription started! Ends on {end_date.strftime("%Y-%m-%d")}')

async def check_expirations():
    now = datetime.datetime.now().isoformat()
    cursor.execute('SELECT * FROM subs WHERE end_date < ? AND end_date IS NOT NULL', (now,))
    expired = cursor.fetchall()
    for user_id, ch_id, _ in expired:
        await remove_from_channel(int(user_id), int(ch_id))
        cursor.execute('DELETE FROM subs WHERE user_id=? AND channel=?', (user_id, ch_id))
    conn.commit()
    if expired:
        await bot.send_message(ADMIN_ID, f'Expired {len(expired)} subs.')

async def on_startup(bot: Bot) -> None:
    await ton_client.connect()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expirations, CronTrigger(hour=0, minute=0))
    scheduler.add_job(check_ton_payments, IntervalTrigger(seconds=60))
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
