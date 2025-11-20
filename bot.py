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
ADMIN_ID = 7761264987  # Твой ID для квитанций

PRIVATE_CHANNEL_ID = -1003390307296
VIP_CHANNEL_ID = -1003490943132

# Крипто-кошельки
CRYPTO_WALLETS = {
    'usdt': {'address': 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK', 'network': 'TRC20'},
    'ltc': {'address': 'LKVnoZeGr3hg2BYxwDxYbuEb7EiKrScHVz', 'network': 'LTC'},
    'ton': {'address': 'UQBagTGNqS-9-DOudj7oHblM4Nhl2EeJdLTvrKzsfKHDTC5q', 'network': 'TON'},
    'sol': {'address': '5vCxpDJS6BaHuoyP3Yqixwr75KtJike9gjc95VsZ5UxT', 'network': 'SOLANA'},
    'trx': {'address': 'TQZnT946myLGyHEvvcNZiGN1b18An9yFhK', 'network': 'TRC20'},
    'doge': {'address': 'DN3ASEyxJL6uNcTA2XR5esyva5mwQRwCDA', 'network': 'DOGE'},
    'bch': {'address': '15TSCoqjPm5ypf7HuyvEoZhmW1MwCb73oS', 'network': 'BCH'}
}

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
        'language_choice': 'Выберите язык:',
        'greeting': 'Детка я рада тебя видеть😘\nТебя ожидает невероятное путешествие💋🔞',
        'welcome': 'Выберите подписку:',
        'choose_duration': 'Выберите срок для {channel}:',
        'price': 'Цена: {price}$ ({stars} Stars)',
        'pay_stars': 'Оплатить Stars',
        'pay_crypto': 'Оплатить криптой',
        'crypto_choice': 'Выберите криптовалюту:',
        'address_msg': '<b>Отправьте ровно {amount}$</b>\n\nАдрес:\n<code>{address}</code>\nСеть: <b>{network}</b>\n\nНажмите на адрес — он скопируется',
        'proof_msg': 'Пришлите сюда фото/скриншот перевода ↓\nЯ проверю и выдам доступ за 1–3 минуты',
        'access_granted': 'Ссылка для вступления:\n{link}\n\nСрок начнётся после вступления в канал',
        'subscription_started': 'Подписка активирована!\nЗаканчивается: <b>{date}</b>',
        'back': 'Назад',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'both_button': 'Private+VIP (скидка)',
        'check_received': 'Чек получен! Ожидайте — проверяю (1–3 мин)',
        'payment_confirmed': 'Оплата подтверждена! Выдаю доступ'
    },
    'en': {
        'language_choice': 'Choose language:',
        'greeting': 'Baby, I\'m glad to see you😘\nYou are in for an incredible journey💋🔞',
        'welcome': 'Choose subscription:',
        'choose_duration': 'Choose duration for {channel}:',
        'price': 'Price: {price}$ ({stars} Stars)',
        'pay_stars': 'Pay with Stars',
        'pay_crypto': 'Pay with crypto',
        'crypto_choice': 'Choose cryptocurrency:',
        'address_msg': '<b>Send exactly {amount}$</b>\n\nAddress:\n<code>{address}</code>\nNetwork: <b>{network}</b>\n\nTap the address to copy',
        'proof_msg': 'Send a photo/screenshot of the transfer here ↓\nI will check and give access in 1–3 minutes',
        'access_granted': 'Join link:\n{link}\n\nSubscription starts after joining the channel',
        'subscription_started': 'Subscription activated!\nEnds on: <b>{date}</b>',
        'back': 'Back',
        'private_button': 'Private DarjaS',
        'vip_button': 'VIP DarjaS',
        'both_button': 'Private+VIP (discount)',
        'check_received': 'Check received! Waiting — checking (1–3 min)',
        'payment_confirmed': 'Payment confirmed! Giving access'
    }
}

# ──────────────────────── БАЗА ДАННЫХ ─────────────────────
conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS subs 
                  (user_id INTEGER, channel TEXT, end_date TEXT, duration TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                  (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru')''')
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
    return r[0] if r else None

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
        return 'Ошибка генерации ссылки'

async def kick_user(user_id, channel_id):
    try:
        await bot.ban_chat_member(channel_id, user_id)
    except: pass

# ──────────────────────── СТАРТ И ЯЗЫК ───────────────────────
@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    lang = get_lang(user_id)
    if lang is None:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Русский', callback_data='lang_ru')],
            [InlineKeyboardButton(text='English', callback_data='lang_en')],
        ])
        await message.answer('Выберите язык / Choose language:', reply_markup=kb)
        return

    texts = TEXTS[lang]
    await message.answer(texts['greeting'])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
    ])
    await message.answer(texts['welcome'], reply_markup=kb)

@router.callback_query(F.data.startswith('lang_'))
async def choose_lang(callback: CallbackQuery):
    lang = callback.data.split('_')[1]
    await set_lang(callback.from_user.id, lang)
    await callback.message.delete()
    await start(callback.message)

# ──────────────────────── ВЫБОР КАНАЛА/СРОКА ─────────────────
@router.callback_query(F.data.startswith('channel_'))
async def choose_duration(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, lang = parts[1], parts[2]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1 неделя' if lang=='ru' else '1 week', callback_data=f'duration_{channel}_week_{lang}')],
        [InlineKeyboardButton(text='1 месяц' if lang=='ru' else '1 month', callback_data=f'duration_{channel}_month_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'back_main_{lang}')],
    ])
    await callback.message.edit_text(texts['choose_duration'].format(channel=channel.capitalize()), reply_markup=kb)

@router.callback_query(F.data.startswith('back_main_'))
async def back_main(callback: CallbackQuery):
    lang = callback.data.split('_')[2]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts['private_button'], callback_data=f'channel_private_{lang}')],
        [InlineKeyboardButton(text=texts['vip_button'], callback_data=f'channel_vip_{lang}')],
        [InlineKeyboardButton(text=texts['both_button'], callback_data=f'channel_both_{lang}')],
    ])
    await callback.message.edit_text(texts['welcome'], reply_markup=kb)

@router.callback_query(F.data.startswith('duration_'))
async def choose_payment(callback: CallbackQuery):
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

# ──────────────────────── STARS ─────────────────────
@router.callback_query(F.data.startswith('pay_stars_'))
async def send_invoice(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    price = PRICES[channel][duration]
    stars = usd_to_stars(price)

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

# ──────────────────────── КРИПТО ─────────────────────
@router.callback_query(F.data.startswith('pay_crypto_'))
async def crypto_choice(callback: CallbackQuery):
    parts = callback.data.split('_')
    channel, duration, lang = parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='USDT TRC20', callback_data=f'crypto_usdt_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='LTC', callback_data=f'crypto_ltc_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='TON', callback_data=f'crypto_ton_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='SOLANA SOL', callback_data=f'crypto_sol_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='TRX TRON (TRC20)', callback_data=f'crypto_trx_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='DOGE', callback_data=f'crypto_doge_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text='BITCOIN CASH (BCH)', callback_data=f'crypto_bch_{channel}_{duration}_{lang}')],
        [InlineKeyboardButton(text=texts['back'], callback_data=f'duration_{channel}_{duration}_{lang}')],
    ])
    await callback.message.edit_text(texts['crypto_choice'], reply_markup=kb)

@router.callback_query(F.data.startswith('crypto_'))
async def show_crypto_address(callback: CallbackQuery):
    parts = callback.data.split('_')
    crypto, channel, duration, lang = parts[1], parts[2], parts[3], parts[4]
    texts = TEXTS[lang]
    amount = PRICES[channel][duration]
    wallet = CRYPTO_WALLETS[crypto]
    address = wallet['address']
    network = wallet['network']

    cursor.execute('INSERT OR REPLACE INTO crypto_pending VALUES (?, ?, ?, ?, ?)',
                   (callback.from_user.id, channel, duration, crypto, amount))
    conn.commit()

    await callback.message.answer(texts['address_msg'].format(amount=amount, address=address, network=network))
    await callback.message.answer(texts['proof_msg'])

@router.message(F.photo)
async def receive_proof(message: Message):
    cursor.execute('SELECT 1 FROM crypto_pending WHERE user_id = ?', (message.from_user.id,))
    if not cursor.fetchone(): return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Выдать доступ', callback_data=f'confirm_{message.from_user.id}')],
        [InlineKeyboardButton(text='Отклонить', callback_data=f'reject_{message.from_user.id}')],
    ])

    await bot.send_photo(
        ADMIN_ID,
        message.photo[-1].file_id,
        caption=f'Крипто-чек от {message.from_user.full_name}\nID: {message.from_user.id}\n@{message.from_user.username or "—"}',
        reply_markup=kb
    )
    lang = get_lang(message.from_user.id)
    texts = TEXTS[lang or 'ru']  # Fallback to 'ru' if lang is None
    await message.answer(texts['check_received'])

# ──────────────────────── ПОДТВЕРЖДЕНИЕ ─────────────────────
@router.callback_query(F.data.startswith('confirm_'))
async def confirm_crypto(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    row = cursor.execute('SELECT channel, duration FROM crypto_pending WHERE user_id = ?', (user_id,)).fetchone()
    if not row:
        return await callback.answer('Уже обработано')

    channel, duration = row
    lang = get_lang(user_id)
    texts = TEXTS[lang]
    channels = [PRIVATE_CHANNEL_ID, VIP_CHANNEL_ID] if channel == 'both' else \
               [PRIVATE_CHANNEL_ID] if channel == 'private' else [VIP_CHANNEL_ID]

    links = []
    for ch_id in channels:
        link = await create_invite(user_id, ch_id)
        if link: links.append(link)
        cursor.execute('INSERT OR REPLACE INTO subs VALUES (?, ?, NULL, ?)', (user_id, str(ch_id), duration))
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

    await bot.send_message(user_id, texts['access_granted'].format(link='\n'.join(links)))
    await callback.message.edit_caption(caption=callback.message.caption + '\n\nПодтверждено')
    await callback.answer(texts['payment_confirmed'])

@router.callback_query(F.data.startswith('reject_'))
async def reject_crypto(callback: CallbackQuery):
    user_id = int(callback.data.split('_')[1])
    lang = get_lang(user_id)
    texts = TEXTS[lang or 'ru']  # Fallback to 'ru' if lang is None
    await bot.send_message(user_id, 'Оплата не подтверждена. Проверьте сумму и адрес.' if lang == 'ru' else 'Payment not confirmed. Check the amount and address.')
    await callback.message.edit_caption(caption=callback.message.caption + '\n\nОтклонено')
    cursor.execute('DELETE FROM crypto_pending WHERE user_id = ?', (user_id,))
    conn.commit()

# ──────────────────────── JOIN И КИК ─────────────────────
@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=ChatMemberStatus.MEMBER))
async def on_join(update: ChatMemberUpdated):
    user_id = update.from_user.id
    channel_id = str(update.chat.id)
    row = cursor.execute('SELECT duration FROM subs WHERE user_id = ? AND channel = ? AND end_date IS NULL', (user_id, channel_id)).fetchone()
    if row:
        days = await get_days(row[0])
        end_date = datetime.datetime.now() + datetime.timedelta(days=days)
        cursor.execute('UPDATE subs SET end_date = ? WHERE user_id = ? AND channel = ?', (end_date.isoformat(), user_id, channel_id))
        conn.commit()
        texts = TEXTS[get_lang(user_id)]
        await bot.send_message(user_id, texts['subscription_started'].format(date=end_date.strftime('%d.%m.%Y')))

async def check_expirations():
    now = datetime.datetime.now().isoformat()
    expired = cursor.execute('SELECT user_id, channel FROM subs WHERE end_date < ? AND end_date IS NOT NULL', (now,)).fetchall()
    for uid, ch in expired:
        await kick_user(int(uid), int(ch))
        cursor.execute('DELETE FROM subs WHERE user_id = ? AND channel = ?', (uid, ch))
    conn.commit()

async def on_startup(bot: Bot):
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
