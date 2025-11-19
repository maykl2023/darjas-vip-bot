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
        'crypto_info': 'Отправьте {price}$ эквивалент на {address} ({crypto}), затем пришлите фото квитанции сюда.',
        'access_granted': 'Доступ предоставлен до {date}.',
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
        'crypto_info': 'Send {price}$ equivalent to {address} ({crypto}), then send photo of the receipt here.',
        'access_granted': 'Access granted until {date}.',
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
conn.commit()

# Bot и Dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

def get_lang(user_id):
    cursor.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None

async def set_lang(user_id, lang):
    cursor.execute('INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)', (user_id, lang))
    conn.commit()

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
    user_id = message.from_user.id
    await message.reply(TEXTS['ru']['delay_warning'] + '\n' + TEXTS['en']['delay_warning'])
    lang = get_lang(user_id)
    if lang is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='English', callback_data='lang_en')],
            [InlineKeyboardButton(text='Russian', callback_data='lang_ru')]
        ])
        await message.reply('Language:', reply_markup=kb)
    else:
        texts = TEXTS[lang]
        await message.reply(texts['greeting'])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
            [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
            [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
            [InlineKeyboardButton(text=texts['test_button'], callback_data=f'channel_test_{lang}')]
        ])
        await message.reply(texts['welcome'], reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith('lang_'))
async def choose_lang(callback: CallbackQuery):
    lang = callback.data.split('_')[1]
    await set_lang(callback.from_user.id, lang)
    texts = TEXTS[lang]
    await callback.message.reply(texts['greeting'])  # Отправляем приветствие после выбора
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
        [InlineKeyboardButton(text=texts['test_button'], callback_data=f'channel_test_{lang}')]
    ])
    await callback.message.reply(texts['welcome'], reply_markup=kb)
    await callback.message.delete()  # Удаляем сообщение с выбором языка
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('channel_'))
async def choose_duration(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel = parts[1]
    lang = parts[2]
    texts = TEXTS[lang]
    if channel == 'test':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='2 недели' if lang == 'ru' else '2 weeks', callback_data=f'duration_test_2weeks_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_channels_{lang}')]
        ])
        await callback.message.edit_text(texts['choose_duration_test'], reply_markup=kb)
    else:
        week_text = '1 неделя' if lang == 'ru' else '1 week'
        month_text = '1 месяц' if lang == 'ru' else '1 month'
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=week_text, callback_data=f'duration_{channel}_week_{lang}')],
            [InlineKeyboardButton(text=month_text, callback_data=f'duration_{channel}_month_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_channels_{lang}')]
        ])
        await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('duration_'))
async def choose_payment(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[1], parts[2], parts[3]
    texts = TEXTS[lang]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    if channel == 'test':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_duration_{channel}_{lang}')]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_duration_{channel}_{lang}')]
        ])
    await callback.message.edit_text(texts['price'].format(price=price_usd, stars=stars), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('back_to_duration_'))
async def back_to_duration(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel = parts[3]
    lang = parts[4]
    texts = TEXTS[lang]
    if channel == 'test':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='2 недели' if lang == 'ru' else '2 weeks', callback_data=f'duration_test_2weeks_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_channels_{lang}')]
        ])
        await callback.message.edit_text(texts['choose_duration_test'], reply_markup=kb)
    else:
        week_text = '1 неделя' if lang == 'ru' else '1 week'
        month_text = '1 месяц' if lang == 'ru' else '1 month'
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=week_text, callback_data=f'duration_{channel}_week_{lang}')],
            [InlineKeyboardButton(text=month_text, callback_data=f'duration_{channel}_month_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_channels_{lang}')]
        ])
        await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('back_to_channels_'))
async def back_to_channels(callback: CallbackQuery):
    lang = callback.data.split('_')[3]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
        [InlineKeyboardButton(text=texts['test_button'], callback_data=f'channel_test_{lang}')]
    ])
    await callback.message.edit_text(texts['welcome'], reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('pay_stars_'))
async def pay_stars(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    prices = [LabeledPrice(label='Subscription', amount=stars)]
    if channel == 'both':
        title = 'Подписка на оба канала' if lang == 'ru' else 'Subscription to Both Channels'
        desc = 'Доступ к Private и VIP DarjaS' if lang == 'ru' else 'Access to Private and VIP DarjaS'
        channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    elif channel == 'private':
        title = 'Подписка на Private DarjaS' if lang == 'ru' else 'Subscription to Private DarjaS'
        desc = 'Доступ к Private каналу' if lang == 'ru' else 'Access to Private channel'
        channels = [PRIVATE_CHANNEL_ID]
    elif channel == 'vip':
        title = 'Подписка на VIP DarjaS' if lang == 'ru' else 'Subscription to VIP DarjaS'
        desc = 'Доступ к VIP каналу' if lang == 'ru' else 'Access to VIP channel'
        channels = [VIP_CHANNEL_ID]
    else:  # test
        title = 'Тестовая подписка' if lang == 'ru' else 'Test Subscription'
        desc = 'Тестовый доступ к Private на 2 недели' if lang == 'ru' else 'Test access to Private for 2 weeks'
        channels = [PRIVATE_CHANNEL_ID]
    payload = f'{callback.from_user.id}:{channel}:{duration}:{lang}'
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
    payload = message.successful_payment.invoice_payload
    user_id, channel, duration, lang = payload.split(':')
    user_id = int(user_id)
    texts = TEXTS[lang]
    if duration == '2weeks':
        days = 14
    else:
        days = 7 if duration == 'week' else 30
    end_date = datetime.datetime.now() + datetime.timedelta(days=days)
    if channel == 'test':
        ch_ids = [PRIVATE_CHANNEL_ID]
    elif channel == 'private':
        ch_ids = [PRIVATE_CHANNEL_ID]
    elif channel == 'vip':
        ch_ids = [VIP_CHANNEL_ID]
    else:  # both
        ch_ids = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    for ch_id in ch_ids:
        await add_to_channel(user_id, ch_id)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, ?)', (user_id, str(ch_id), end_date.isoformat()))
    conn.commit()
    await message.reply(texts['access_granted'].format(date=end_date.strftime('%Y-%m-%d')))
    await bot.send_message(ADMIN_ID, f'Successful payment: User {user_id}, {channel} {duration}')

@router.callback_query(lambda c: c.data.startswith('pay_crypto_'))
async def pay_crypto(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_payment_{channel}_{duration}_{lang}')]
    ])
    await callback.message.edit_text(texts['choose_crypto'], reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('back_to_payment_'))
async def back_to_payment(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[3], parts[4], parts[5]
    texts = TEXTS[lang]
    price_usd = PRICES[channel][duration]
    stars = usd_to_stars(price_usd)
    if channel == 'test':
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_duration_{channel}_{lang}')]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts['pay_stars'], callback_data=f'pay_stars_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['pay_crypto'], callback_data=f'pay_crypto_{channel}_{duration}_{lang}')],
            [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_duration_{channel}_{lang}')]
        ])
    await callback.message.edit_text(texts['price'].format(price=price_usd, stars=stars), reply_markup=kb)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith('crypto_'))
async def send_crypto_info(callback: CallbackQuery):
    parts = callback.data.split('_')
    crypto, channel, duration, lang = parts[1], parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    price_usd = PRICES[channel][duration]
    address = USDT_ADDRESS if crypto == 'usdt' else LTC_ADDRESS
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_crypto_{channel}_{duration}_{lang}')]
    ])
    await callback.message.edit_text(texts['crypto_info'].format(price=price_usd, address=address, crypto=crypto.upper()), reply_markup=kb)
    await callback.answer(texts['send_proof'])

@router.callback_query(lambda c: c.data.startswith('back_to_crypto_'))
async def back_to_crypto(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[3], parts[4], parts[5]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_to_payment_{channel}_{duration}_{lang}')]
    ])
    await callback.message.edit_text(texts['choose_crypto'], reply_markup=kb)
    await callback.answer()

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
    if duration == '2weeks':
        days = 14
    else:
        days = 7 if duration == 'week' else 30
    end_date = datetime.datetime.now() + datetime.timedelta(days=days)
    if channel == 'test':
        ch_ids = [PRIVATE_CHANNEL_ID]
    elif channel == 'private':
        ch_ids = [PRIVATE_CHANNEL_ID]
    elif channel == 'vip':
        ch_ids = [VIP_CHANNEL_ID]
    else:  # both
        ch_ids = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID]
    for ch_id in ch_ids:
        await add_to_channel(user_id, ch_id)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, ?)', (user_id, str(ch_id), end_date.isoformat()))
    conn.commit()
    lang = get_lang(user_id)
    texts = TEXTS[lang]
    await bot.send_message(user_id, texts['access_granted'].format(date=end_date.strftime('%Y-%m-%d')))
    await message.reply('Approved.')

@router.message(Command('terms'))
async def terms(message: Message):
    lang = get_lang(message.from_user.id)
    await message.reply(TEXTS[lang]['terms'])

@router.message(Command('support'))
async def support(message: Message):
    lang = get_lang(message.from_user.id)
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
