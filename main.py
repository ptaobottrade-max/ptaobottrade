import os
import sqlite3
import yfinance as yf
from datetime import datetime, timedelta
from telegram.ext import ConversationHandler


from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
# แก้ ChatId
ADMIN_IDS = [7753207716,7916012945]
DB_NAME = os.getenv("DB_PATH", "members.db")

FREE_LIMIT = 2
PREMIUM_PRICE = "68 บาท"
RENEW_DAYS = 1


# ================= DB =================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS members(
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        expire_date TEXT,
        language TEXT DEFAULT 'th'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS usage(
        user_id INTEGER,
        date TEXT,
        count INTEGER,
        PRIMARY KEY(user_id, date)
    )
    """)

    conn.commit()
    conn.close()

# ================= MEMBER =================
def update_username(user_id, username):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    INSERT INTO members(user_id,username)
    VALUES(?,?)
    ON CONFLICT(user_id) DO UPDATE SET username=?
    """,(user_id,username,username))

    conn.commit()
    conn.close()

def add_member(user_id):
    expire = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    UPDATE members
    SET expire_date = ?
    WHERE user_id = ?
    """,(expire,user_id))

    conn.commit()
    conn.close()

def renew_member(user_id, days):

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT expire_date FROM members WHERE user_id=?", (user_id,))
    r = c.fetchone()

    if r and r[0]:
        base_date = datetime.strptime(r[0], "%Y-%m-%d")

        # ถ้ายังไม่หมดอายุ → ต่อจากวันหมดอายุ
        if base_date > datetime.now():
            new_expire = base_date + timedelta(days=days)
        else:
            # ถ้าหมดแล้ว → ต่อจากวันนี้
            new_expire = datetime.now() + timedelta(days=days)

    else:
        new_expire = datetime.now() + timedelta(days=days)

    c.execute("""
    INSERT INTO members(user_id, expire_date)
    VALUES(?,?)
    ON CONFLICT(user_id)
    DO UPDATE SET expire_date=excluded.expire_date
    """,(user_id,new_expire.strftime("%Y-%m-%d")))

    conn.commit()
    conn.close()

    return new_expire.strftime("%Y-%m-%d")



def remove_member(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("DELETE FROM members WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM usage WHERE user_id=?", (user_id,))

    conn.commit()
    conn.close()


def is_premium(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT expire_date FROM members WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()

    if not r or not r[0]:
        return False

    try:
        return datetime.now() <= datetime.strptime(r[0], "%Y-%m-%d")
    except:
        return False


# ================= LANGUAGE =================
def set_language(user_id, lang):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    INSERT INTO members(user_id,language)
    VALUES(?,?)
    ON CONFLICT(user_id) DO UPDATE SET language=?
    """,(user_id,lang,lang))

    conn.commit()
    conn.close()

def get_language(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT language FROM members WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()

    return r[0] if r else "th"

# ================= USAGE =================
def check_usage(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT count FROM usage WHERE user_id=? AND date=?", (user_id, today))
    r = c.fetchone()

    if not r:
        c.execute("INSERT INTO usage VALUES(?,?,0)", (user_id, today))
        conn.commit()
        conn.close()
        return 0

    conn.close()
    return r[0]

def increase_usage(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    INSERT INTO usage VALUES(?,?,1)
    ON CONFLICT(user_id,date)
    DO UPDATE SET count=count+1
    """,(user_id,today))

    conn.commit()
    conn.close()

# ================= STOCK =================
def analyze_stock(symbol):

    stock = yf.Ticker(symbol)

    # ⭐ ใช้ 1D TF
    df = stock.history(period="2y", interval="1d")

    if df.empty:
        return None

    close = df["Close"]

    price = round(close.iloc[-1],2)

    # ===== EMA =====
    ema20 = close.ewm(span=20).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    ema100 = close.ewm(span=100).mean().iloc[-1]
    ema200 = close.ewm(span=200).mean().iloc[-1]
    ema400 = close.ewm(span=400).mean().iloc[-1]

    # ===== Momentum =====
    momentum = close.pct_change().tail(5).mean()

    # ===== RSI =====
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # ===== MACD =====
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26

    # ===== Bollinger =====
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + (bb_std * 2)
    bb_lower = bb_mid - (bb_std * 2)

    high52 = df["High"].max()
    low52 = df["Low"].min()

    swing20 = df["High"].rolling(20).max().iloc[-1]

    # ===== Resistance Candidates =====
    candidates = [
        swing20,
        bb_upper.iloc[-1],
        ema50 * 1.02,     # buffer กัน false break
    ]
    
    # ⭐ เอาเฉพาะที่อยู่เหนือราคา
    above_price = [r for r in candidates if r > price]
    
    # ⭐ เลือกอันที่ใกล้ราคาที่สุด
    if above_price:
        resistance = min(above_price)
    else:
        # fallback ถ้าไม่มีเลย
        resistance = max(candidates)
    
    resistance = round(resistance, 2)


    return {
        "price":price,
        "momentum":momentum,
        "rsi":rsi.iloc[-1],
        "macd":macd.iloc[-1],
        "vol":close.pct_change().std()*100,
        "avg5":close.tail(5).mean(),
        "high52":high52,
        "low52":low52,
        "ema20":ema20,
        "ema50":ema50,
        "ema100":ema100,
        "ema200":ema200,
        "ema400":ema400,
        "resistance": resistance,
        "bb_upper": bb_upper.iloc[-1],
        "bb_mid": bb_mid.iloc[-1],
        "bb_lower": bb_lower.iloc[-1]
    }



# ================= TEXT =================
def premium_text(symbol,d,lang):

    momentum_icon = "🟢" if d["momentum"] > 0 else "🔴"
    rsi_icon = "🟢" if d["rsi"] < 30 else "🔴" if d["rsi"] > 70 else "🟡"
    macd_icon = "🟢" if d["macd"] > 0 else "🔴"

    below_ema200 = d["price"] < d["ema200"]

    # ================= TH =================
    if lang == "th":

        ema2050 = "🟢 ขาขึ้น" if d["ema20"] > d["ema50"] else "🔴 ขาลง"
        ema50200 = "🟢 ขาขึ้น" if d["ema50"] > d["ema200"] else "🔴 ขาลง"

        if below_ema200:
            support_text = "\n⚠️ ราคาอยู่ต่ำกว่า EMA200\n📞 แนะนำติดต่อพี่เต่า"
        else:
            support_note = ""
            if d["price"] < d["ema50"]:
                support_note = "\n(หากราคาปัจจุบัน ต่ำกว่า แนวรับที่ 1 ควรรอแนวรับที่ 2-3)"

            support_text = f"""
        🛟 แนวรับ 1 : {round(d['ema50'],2)}
        🛟 แนวรับ 2 : {round(d['ema100'],2)}
        🛟 แนวรับ 3 : {round(d['ema200'],2)}
        🛟 StopLoss : {round(d['ema400'],2)}
            {support_note}
            """

        return f"""
📊 หุ้น: {symbol}

💰 ราคา: {d['price']}
⚡ {momentum_icon} โมเมนตัม
📉 RSI: {rsi_icon} {round(d['rsi'],2)}
📊 MACD: {macd_icon}
🌪 ความผันผวน: {round(d['vol'],2)}%

📅 ราคาเฉลี่ย 5 สัปดาห์: {round(d['avg5'],2)}

📈 52W High: {round(d['high52'],2)}
📉 52W Low: {round(d['low52'],2)}

📊 EMA20/50: {ema2050}
📊 EMA50/200: {ema50200}

🚧 แนวต้าน : {round(d['resistance'],2)}

{support_text}

⚠️ ข้อมูลเพื่อประกอบการตัดสินใจเท่านั้น
"""

    # ================= EN =================
    else:

        ema2050 = "🟢 Bullish" if d["ema20"] > d["ema50"] else "🔴 Bearish"
        ema50200 = "🟢 Bullish" if d["ema50"] > d["ema200"] else "🔴 Bearish"

        if below_ema200:
            support_text = "\n⚠️ Price is below EMA200\n📞 Suggest contacting P'Tao"
        else:
            support_text = f"""
🛟 Support 1 : {round(d['ema50'],2)}
🛟 Support 2 : {round(d['ema100'],2)}
🛟 Support 3 : {round(d['ema200'],2)}
🛟 StopLoss : {round(d['ema400'],2)}
"""

        return f"""
📊 Stock: {symbol}

💰 Price: {d['price']}
⚡ Momentum: {momentum_icon}
📉 RSI: {rsi_icon} {round(d['rsi'],2)}
📊 MACD: {macd_icon}
🌪 Volatility: {round(d['vol'],2)}%

📅 5 Week Avg: {round(d['avg5'],2)}

📈 52W High: {round(d['high52'],2)}
📉 52W Low: {round(d['low52'],2)}

📊 EMA20/50: {ema2050}
📊 EMA50/200: {ema50200}

🚧 Resistance : {round(d['resistance'],2)}

{support_text}

⚠️ For information only. Not financial advice.
"""


def free_text(symbol,d,lang):

    momentum_icon = "🟢" if d["momentum"] > 0 else "🔴"
    rsi_icon = "🟢" if d["rsi"] < 30 else "🔴" if d["rsi"] > 70 else "🟡"
    macd_icon = "🟢" if d["macd"] > 0 else "🔴"

    if lang == "th":
        return f"""
📊 หุ้น: {symbol}

⚡ โมเมนตัม: {momentum_icon}
📉 RSI: {rsi_icon} {round(d['rsi'],2)}
📊 MACD: {macd_icon}
🌪 ความผันผวน: {round(d['vol'],2)}%

📅 ราคาเฉลี่ย 5 วัน: {round(d['avg5'],2)}

🚧 แนวต้าน : {round(d['resistance'],2)}
🛟 แนวรับ : {round(d['ema50'],2)}

⚠️ ข้อมูลเพื่อเป็นข้อมูล ไม่ใช่คำแนะนำการลงทุน

⭐ อัปเกรดเดือนละ {PREMIUM_PRICE}
พิมพ์ /payment เพื่อสมัคร Premium
"""

    else:
        return f"""
📊 Stock: {symbol}

⚡ Momentum: {momentum_icon}
📉 RSI: {rsi_icon} {round(d['rsi'],2)}
📊 MACD: {macd_icon}
🌪 Volatility: {round(d['vol'],2)}%

📅 5 Day Avg: {round(d['avg5'],2)}

📊 Bollinger(20)
Upper: {round(d['bb_upper'],2)}
Middle: {round(d['bb_mid'],2)}
Lower: {round(d['bb_lower'],2)}

⚠️ For information only. Not financial advice.

⭐ Upgrade {PREMIUM_PRICE} / month
Type /payment to upgrade
"""


# ================= COMMAND =================
async def start(update,context):
    user = update.effective_user
    update_username(user.id, user.username or user.first_name)

    await update.message.reply_text(
"""🤖 Stock Bot

/start - เริ่มต้น
/payment - สมัคร Premium
/thai - ภาษาไทย
/eng - English
/help - วิธีใช้งาน
"""
)
async def renew_cmd(update, context):

    if update.effective_user.id not in ADMIN_IDS:
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /renew <chatid> <days>")
        return

    try:
        uid = int(context.args[0])
        days = int(context.args[1])

        if days <= 0 or days > 3650:
            await update.message.reply_text("❌ จำนวนวันไม่ถูกต้อง")
            return

        new_expire = renew_member(uid, days)

        await update.message.reply_text(
            f"✅ Renew แล้ว\nUser: {uid}\nเพิ่ม: {days} วัน\nExpire ใหม่: {new_expire}"
        )

        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"🎉 Premium ถูกต่ออายุอีก {days} วัน\nExpire: {new_expire}"
            )
        except:
            pass

    except:
        await update.message.reply_text("❌ Invalid format")

async def help_cmd(update,context):
    await update.message.reply_text(
"""📖 วิธีใช้งาน

พิมพ์ชื่อหุ้น เช่น
AAPL
TSLA
NVDA

Free ใช้ได้วันละ 2 ครั้ง
Premium ใช้ได้ไม่จำกัด
"""
)

async def payment(update,context):
    await update.message.reply_text(
"""💳 โปรดชำระเงิน 68 บาท ไปที่บัญชี

นาย ธงชัย ประเสริฐสัง
ธนาคารทีเอ็มบีธนชาติ (TTB)
เลขบัญชี 6532343883

* หลังโอนเงินแล้ว โปรดทำตามขั้นตอนดังนี้
* ส่งรูปภาพสลิปให้กับ bot
* พิมพ์ /paid ชื่อจริงของผู้โอนเงินส่งใน bot
* เช่น /paid Thongchai หรือ /paid ธงชัย
* ถ้าพิมพ์ชื่อเล่นหรือชื่ออื่น ระบบจะตรวจสอบไม่ได้
* ต้องเว้นวรรคหลัง /paid 1 ครั้งก่อนพิมพ์ชื่อ
* ถ้าไม่กด /paid ชื่อผู้ชำระเงิน ระบบจะไม่อัพเกรด
* หากใช้งานไม่ได้ ส่งสลิปแจ้งที่เพจ พี่เต่า investment
* โอนหลัง 22.00 น. ระบบจะอัพเกรดวันถัดไป
* ระบบจะตรวจสอบการโอนเงินภายใน 12 ชั่วโมง
"""
    )

async def thai(update,context):
    set_language(update.effective_user.id,"th")
    await update.message.reply_text("✅ เปลี่ยนเป็นภาษาไทย")

async def eng(update,context):
    set_language(update.effective_user.id,"en")
    await update.message.reply_text("✅ Switched to English")

async def dashboard(update,context):

    if update.effective_user.id not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    c.execute("""
    SELECT user_id, username, expire_date
    FROM members
    WHERE expire_date IS NOT NULL
    AND expire_date >= ?
    """, (today,))

    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No members")
        return

    CHUNK = 20

    for i in range(0, len(rows), CHUNK):

        batch = rows[i:i+CHUNK]

        text = f"📊 MEMBER DASHBOARD ({i+1}-{i+len(batch)})\n"

        for uid,u,exp in batch:

            u = u or "NoName"

            if not exp:
                status="Free"
                remain="-"
            else:
                expire_date = datetime.strptime(exp,"%Y-%m-%d").date()
                remain=(expire_date-datetime.now().date()).days
                status="Active" if remain>=0 else "Expired"

            text += f"""
👤 {u}
ChatID: {uid}
Expire: {exp}
Remain: {remain}
Status: {status}
"""

        await update.message.reply_text(text)

# ================= SLIP =================
async def receive_slip(update, context):

    user = update.effective_user
    username = user.username or user.first_name

    photo = update.message.photo[-1].file_id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
        ]
    ])

    for admin in ADMIN_IDS:
        await context.bot.send_photo(
            chat_id=admin,
            photo=photo,
            caption=f"📥 Slip from {username}\nID: {user.id}",
            reply_markup=keyboard
        )

    await update.message.reply_text("✅ ส่งสลิปแล้ว รอระบบตรวจสอบ")

async def admin_callback(update, context):

    query = update.callback_query
    await query.answer()

    action, user_id = query.data.split("_")
    user_id = int(user_id)

    if action == "approve":
        add_member(user_id)

        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Premium เปิดแล้ว"
        )

        await query.edit_message_caption("✅ Approved")

    elif action == "reject":

        await context.bot.send_message(
            chat_id=user_id,
            text="❌ สลิปไม่ถูกต้อง"
        )

        await query.edit_message_caption("❌ Rejected")

# ================= SEARCH =================
async def stock_search(update,context):

    user_id = update.effective_user.id
    update_username(user_id, update.effective_user.username or update.effective_user.first_name)

    lang = get_language(user_id)   # ⭐ สำคัญ

    text = update.message.text.upper().strip()

    if not text.isalpha():
        return

    data = analyze_stock(text)
    if not data:
        await update.message.reply_text("No data")
        return

    premium = is_premium(user_id)

    if not premium:
        try:
    
            used = check_usage(user_id)
    
            if used >= FREE_LIMIT:
    
                if lang == "th":
                    limit_msg = """🚫 คุณใช้โควตาวันนี้ครบแล้ว
    
    แพ็กเกจ Free สามารถใช้งานได้ตามจำนวนที่กำหนดต่อวัน
    หากต้องการใช้งานต่อแบบไม่จำกัด แนะนำอัปเกรดเป็น Premium ✨
    
    📌 สิทธิ์ Premium:
    • ใช้งานได้มากขึ้น / ไม่จำกัดตามแพ็กเกจ
    • เข้าถึงฟีเจอร์พิเศษ
    • ใช้งานได้เร็วและเสถียรกว่า
    
    💎 สนใจสมัคร Premium พิมพ์ /payment
    """
    
                else:  # EN default
                    limit_msg = """🚫 You have reached today’s usage limit.
    
    The Free plan allows limited daily usage.
    To continue using without limits, upgrade to Premium ✨
    
    📌 Premium Benefits:
    • Higher / Unlimited usage (depending on package)
    • Access to exclusive features
    • Faster and more stable performance
    
    💎 To upgrade to Premium type /payment
    """
    
                await update.message.reply_text(limit_msg)
                return
    
            increase_usage(user_id)
    
            msg = free_text(text, data, lang)
            await update.message.reply_text(msg)
    
        except Exception as e:
            print("FREE ERROR:", e)
            await update.message.reply_text("SYSTEM ERROR")
    
    else:
        msg = premium_text(text, data, lang)
        await update.message.reply_text(msg)


async def remove_cmd(update, context):

    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove <chatid>")
        return

    try:
        uid = int(context.args[0])
        remove_member(uid)
        await update.message.reply_text(f"✅ Removed user {uid}")
    except:
        await update.message.reply_text("❌ Invalid chatid")


# ================= MAIN =================
def main():

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("payment", payment))
    app.add_handler(CommandHandler("thai", thai))
    app.add_handler(CommandHandler("eng", eng))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("remove", remove_cmd))

    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.PHOTO, receive_slip))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, stock_search))

    app.add_handler(CommandHandler("renew", renew_cmd))

    print("RUNNING")
    app.run_polling()

if __name__=="__main__":
    main()







