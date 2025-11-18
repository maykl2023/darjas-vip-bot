from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook import SimpleRequestHandler
from datetime import datetime, timedelta
import os
import logging
import asyncio
import uvicorn

TOKEN = os.getenv("BOT_TOKEN")
RENDER_SERVICE_NAME = os.getenv("RENDER_SERVICE_NAME", "darjas-vip-bot")  # Твой сервис в Render
WEBHOOK_PATH = f"/bot{TOKEN}"
WEBHOOK_URL = f"https://{RENDER_SERVICE_NAME}.onrender.com{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()

PRIVATE_ID = int(os.getenv("PRIVATE_ID"))
VIP_ID = int(os.getenv("VIP_ID"))

PRICES = {
    "private_week": 600,   # 6$
    "private_month": 1800, # 18$
    "vip_week": 1200,      # 12$
    "vip_month": 3600,     # 36$
    "both_week": 1620,     # 10% скидка
    "both_month": 4320     # 20% скидка
}

async def create_link(channel_id, days):
    expire = int((datetime.utcnow() + timedelta(days=days)).timestamp())
    link = await bot.create_chat_invite_link(
        chat_id=channel_id,
        member_limit=1,
        expire_date=expire
    )
    return link.invite_link

async def check_access(user_id):
    p = "❌ Private DarjaS"
    v = "❌ VIP DarjaS"
    try:
        m = await bot.get_chat_member(PRIVATE_ID, user_id)
        if m.status in ["member", "administrator", "creator"]:
            p = "✅ Private DarjaS"
    except: pass
    try:
        m = await bot.get_chat_member(VIP_ID, user_id)
        if m.status in ["member", "administrator", "creator"]:
            v = "✅ VIP DarjaS"
    except: pass
    return p, v

@router.message(Command("start"))
async def start(m: types.Message):
    p, v = await check_access(m.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r"Private DarjaS — 6\( /нед • 18 \)/мес", callback_data="p")],
        [InlineKeyboardButton(text=r"VIP DarjaS — 12\( /нед • 36 \)/мес", callback_data="v")],
        [InlineKeyboardButton(text=r"Оба канала — скидка 10–20%", callback_data="b")],
        [InlineKeyboardButton(text="Проверить / Продлить", callback_data="check")],
    ])
    await m.answer(
        f"<b>Привет, детка 😘</b>\n\n"
        f"Твой доступ:\n{p}\n{v}\n\n"
        f"Выбери подписку:",
        reply_markup=kb
    )

@router.callback_query(F.data == "check")
async def check(call: types.CallbackQuery):
    p, v = await check_access(call.from_user.id)
    await call.message.edit_text(
        f"<b>Твой доступ:</b>\n\n{p}\n{v}\n\n"
        f"Хочешь продлить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к тарифам", callback_data="back")]
        ])
    )

@router.callback_query(F.data == "back")
async def back(call: types.CallbackQuery):
    await start(call.message)

@router.callback_query(F.data.in_({"p", "v", "b"}))
async def choose_type(call: types.CallbackQuery):
    t = call.data
    if t == "p":
        kb = [[InlineKeyboardButton(text=r"Неделя — 600 ⭐", callback_data="pay_private_week")],
              [InlineKeyboardButton(text=r"Месяц — 1800 ⭐", callback_data="pay_private_month")]]
    elif t == "v":
        kb = [[InlineKeyboardButton(text=r"Неделя — 1200 ⭐", callback_data="pay_vip_week")],
              [InlineKeyboardButton(text=r"Месяц — 3600 ⭐", callback_data="pay_vip_month")]]
    else:
        kb = [[InlineKeyboardButton(text=r"Неделя обоих — 1620 ⭐ (−10%)", callback_data="pay_both_week")],
              [InlineKeyboardButton(text=r"Месяц обоих — 4320 ⭐ (−20%)", callback_data="pay_both_month")]]
    kb.append([InlineKeyboardButton(text="« Назад", callback_data="back")])
    await call.message.edit_text("Выбери срок:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("pay_"))
async def pay(call: types.CallbackQuery):
    payload = call.data[4:]
    price = PRICES[payload]
    title = "Доступ DarjaS"
    if "both" in payload:
        title = "Оба канала DarjaS"
    elif "vip" in payload:
        title = "VIP DarjaS"
    else:
        title = "Private DarjaS"
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=title,
        description="Одноразовая ссылка • сгорает после входа и по сроку",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=price)],
    )

@router.pre_checkout_query()
async def pre(q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)

@router.message(F.successful_payment)
async def success(m: types.Message):
    p = m.successful_payment.invoice_payload
    links = []
    days = 7 if "week" in p else 30
    if "private" in p or "both" in p:
        link = await create_link(PRIVATE_ID, days)
        links.append(f"<b>Private DarjaS</b>\n{link}")
    if "vip" in p or "both" in p:
        link = await create_link(VIP_ID, days)
        links.append(f"<b>VIP DarjaS</b>\n{link}")
    await m.answer(
        f"<b>Оплата прошла! Спасибо, детка 🔥</b>\n\n"
        f"Привет детка, я тебе очень рада 😘\n\n"
        f"Твои личные ссылки:\n\n" + "\n\n".join(links) +
        f"\n\nСсылки одноразовые и сгорят {'через 7 дней' if 'week' in p else 'через 30 дней'}.",
        disable_web_page_preview=True
    )

dp.include_router(router)

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    await handler.feed_update(request)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
