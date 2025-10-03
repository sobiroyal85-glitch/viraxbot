import telebot
import sqlite3
import requests
import time
import threading
from flask import Flask, request
from telebot import types
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
import io
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib import dates as mdates
from matplotlib import ticker
from mplfinance.original_flavor import candlestick_ohlc
import os
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
import json
import jdatetime
from hijri_converter import Gregorian
from flask import Flask, send_file
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ------------------ تنظیمات ربات ------------------ #
BOT_TOKEN = "7721189428:AAF0jNEXaJ3Ra9dhSrogu6QthQBwqZYe9oU"
CHANNEL_ID = "@VIRAXcpl"
ADMIN_ID = 2054901055


# ------------------ تعریف ادمین‌ها ------------------ #
ADMINS = [2054901055, 7772858062]
bot = telebot.TeleBot(BOT_TOKEN)
SUPPORT_ADMIN_ID = 2054901055

pending_support = set()     # کاربران در حالت پشتیبانی
admin_reply_to = {}         # ادمینی که قصد پاسخ دادن دارد

broadcast_waiting_for_text = False
broadcast_admin_id = None


# ------------------ تعریف دستورات ------------------ #
def set_commands():
    commands = [
        types.BotCommand("start", "شروع / بازگشت به منوی اصلی"),
        types.BotCommand("menu", "نمایش منوی اصلی"),
        types.BotCommand("help", "راهنما و توضیحات"),
        types.BotCommand("vip", "بخش VIP"),
        types.BotCommand("price", "📈 دریافت قیمت لحظه‌ای"),       # دستور برای دریافت قیمت
        types.BotCommand("calculator", "🧮 محاسبه نرخ"),          # دستور برای محاسبه نرخ
        types.BotCommand("calendar", "📅 تقویم"),                  # دستور تقویم
        types.BotCommand("addgroup", "➕ افزودن به گروه"),          # دستور افزودن ربات به گروه
        types.BotCommand("profile", "👤 نمایش پروفایل / حساب کاربری")  # دستور پروفایل
    ]
    bot.set_my_commands(commands)


MAIN_CHANNEL_ID = "@VIRAXcpl"  
# ------------------ چک عضویت در کانال ------------------ #
def is_user_joined(user_id):
    try:
        member = bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception:
        return False

# ------------------ Decorator برای چک عضویت ------------------ #
def require_join(func):
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if not is_user_joined(user_id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            btn_join = types.InlineKeyboardButton("📢 عضویت در کانال", url="https://t.me/VIRAXcpl")
            btn_done = types.InlineKeyboardButton("✅ عضو شدم", callback_data="joined_channel")
            markup.add(btn_join, btn_done)

            bot.send_message(
                user_id,
                "✨ لطفاً ابتدا در کانال رسمی ما عضو شوید تا از خدمات ربات استفاده کنید.",
                reply_markup=markup
            )

            # حذف پیام کاربر بعد از ارسال پیام ربات
            try:
                bot.delete_message(user_id, message.message_id)
            except:
                pass
                
            return  # ادامه دستور اجرا نمی‌شود
        return func(message, *args, **kwargs)
    return wrapper
    
# ------------------ دیتابیس ------------------ #
def init_db():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        join_date TEXT,
        is_admin INTEGER DEFAULT 0,
        is_vip INTEGER DEFAULT 0,
        request_count INTEGER DEFAULT 0,
        favorite_currencies TEXT DEFAULT ''
    )
    """)
    conn.commit()
    conn.close()

# ذخیره یا بروزرسانی کاربر
def save_user(user_id, username="", first_name=""):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()

    join_date = datetime.now().strftime("%Y-%m-%d")  # تاریخ امروز

    # اگر کاربر ادمین باشد مقدار is_admin را برابر 1 قرار می‌دهیم
    is_admin = 1 if user_id in ADMINS else 0

    cursor.execute("""
        INSERT OR IGNORE INTO users (id, username, first_name, join_date, is_admin)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, first_name, join_date, is_admin))

    # بروزرسانی نام و ادمین بودن
    cursor.execute("""
        UPDATE users SET username=?, first_name=?, is_admin=? WHERE id=?
    """, (username, first_name, is_admin, user_id))

    conn.commit()
    conn.close()


# افزایش تعداد درخواست کاربر
def increment_request_count(user_id):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET request_count = request_count + 1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

# گرفتن اطلاعات کاربر
def get_user(user_id):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, first_name, join_date, is_admin, is_vip, request_count, favorite_currencies
        FROM users WHERE id=?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "username": row[1] or "",
            "first_name": row[2] or "",
            "join_date": row[3] or "",
            "is_admin": row[4],
            "is_vip": row[5],
            "request_count": row[6],
            "favorite_currencies": row[7].split(",") if row[7] else []
        }
    return None

# محاسبه رتبه کاربر
def get_user_rank(user_id):
    user = get_user(user_id)
    if not user:
        return 0
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*)+1 FROM users WHERE request_count > ?", (user["request_count"],))
    rank = cursor.fetchone()[0]
    conn.close()
    return rank

# دریافت لیست تمام کاربران همراه با وضعیت ادمین بودن
def get_all_users_with_admin():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, first_name, is_admin FROM users")
    users = cursor.fetchall()
    conn.close()
    return users

        
# ------------------ ارزهای پشتیبانی شده ------------------ #
supported_cryptos = [
    "بیت کوین", "اتریوم", "تتر", "ریپل", "کاردانو",
    "سولانا", "دوج کوین", "شیبا", "پولکادات", "ترون", "لایت کوین",
    "دلار", "یورو", "طلای ۱۸ عیار", "سکه"
]

API_URL = "https://api.majidapi.ir/price/bitpin?token=qygetwhfbqnvnds:rXA3mgupmVI1XFqhqWQ0"
GOLD_API_URL = "https://api.majidapi.ir/price/gold?token=qygetwhfbqnvnds:rXA3mgupmVI1XFqhqWQ0"
API_URL_FOREX = "https://api.majidapi.ir/price/bonbast?token=qygetwhfbqnvnds:rXA3mgupmVI1XFqhqWQ0"
API_URL_COINS = "https://api.majidapi.ir/price/bonbast?token=qygetwhfbqnvnds:rXA3mgupmVI1XFqhqWQ0"

# ------------------ کش قیمت‌ها ------------------ #
crypto_candles = {}
crypto_cache = []
gold_cache = []
forex_cache = []  
coins_cache = []
last_update = 0  # زمان آخرین آپدیت موفق

def fetch_candles(symbol):
    try:
        # حالت اول: tBTCUSD
        url1 = f"https://api-pub.bitfinex.com/v2/candles/trade:1h:t{symbol}USD/hist"
        res = requests.get(url1, timeout=30).json()

        # اگر درست نبود → حالت دوم: tBTC:USD
        if not isinstance(res, list) or len(res) == 0:
            url2 = f"https://api-pub.bitfinex.com/v2/candles/trade:1h:t{symbol}:USD/hist"
            res = requests.get(url2, timeout=30).json()

        # اگر همچنان لیست معتبر نبود → بیخیال
        if not isinstance(res, list) or len(res) == 0 or not isinstance(res[0], list):
            return None

        candles_list = []
        for c in res[:5]:
            if len(c) < 6:
                continue
            candles_list.append({
                "timestamp": c[0],
                "open": c[1],
                "close": c[2],
                "high": c[3],
                "low": c[4],
                "volume": c[5]
            })

        return candles_list if candles_list else None

    except Exception as e:
        print(f"⚠️ خطا در گرفتن کندل {symbol}: {e}")
        return None



def update_cache():
    """
    آپدیت کش کریپتو، طلا و فارکس و ذخیره قیمت‌ها برای استفاده بعدی
    """
    global crypto_cache, gold_cache, forex_cache, coins_cache, last_update, crypto_candles
    try:
        # ---------- گرفتن لیست کریپتو ---------- #
        crypto_res = requests.get(API_URL, timeout=60).json()
        if isinstance(crypto_res, dict) and "result" in crypto_res:
            new_crypto = []
            for item in crypto_res["result"]:
                code = item.get("code", "")
                if "_USDT" in code:
                    code_clean = code.replace("_USDT", "")
                    try:
                        price = float(item.get("price", 0))
                    except:
                        price = 0
                    new_crypto.append({
                        "code": code_clean,
                        "price": price
                    })
            if new_crypto:
                crypto_cache = new_crypto
                for item in crypto_cache:
                    symbol = item["code"]
                    candles = fetch_candles(symbol)
                    if candles:
                        crypto_candles[symbol] = candles

        # ---------- گرفتن لیست طلا ---------- #
        gold_res = requests.get(GOLD_API_URL, timeout=60).json()
        if isinstance(gold_res, dict) and "result" in gold_res:
            new_gold_raw = gold_res["result"].get("tala", [])
            new_gold = []
            for item in new_gold_raw:
                title = item.get("title", "")
                price_raw = str(item.get("price", "0")).replace(",", "")  # حذف ویرگول‌ها
                try:
                    price = int(price_raw)  # تبدیل به عدد
                except:
                    price = 0
                new_gold.append({
                    "title": title,
                    "price": price
                })
            if new_gold:
                gold_cache = new_gold

        # ---------- گرفتن لیست فارکس ---------- #
        forex_res = requests.get(API_URL_FOREX, timeout=60).json()

        if isinstance(forex_res, dict) and "result" in forex_res and "currencies" in forex_res["result"]:
            new_forex = []
            for item in forex_res["result"]["currencies"]:
                code = item.get("code", "").strip()  # فقط کد
                try:
                    sell_price = int(str(item.get("sell", "0")).replace(",", ""))
                except:
                    sell_price = 0
                if code and sell_price > 0:  # فقط موارد معتبر
                    new_forex.append({
                        "code": code,   # برای کیبورد
                        "sell": sell_price  # برای قیمت
                    })
            forex_cache = new_forex

        # ---------- گرفتن لیست سکه ---------- #
        coins_res = requests.get(API_URL_COINS, timeout=60).json()
        if isinstance(coins_res, dict) and "result" in coins_res and "coins" in coins_res["result"]:
            new_coins = []
            for item in coins_res["result"]["coins"]:
                coin_name = item.get("coin", "").strip()
                try:
                    sell_price = int(str(item.get("sell", "0")).replace(",", ""))
                except:
                    sell_price = 0
                if coin_name and sell_price > 0:
                    new_coins.append({
                        "coin": coin_name,
                        "sell": sell_price
                    })
            if new_coins:
                coins_cache = new_coins


        # ---------- آپدیت زمان ---------- #
        if crypto_cache or gold_cache or forex_cache:  
            last_update = time.time()
            print("✅ کش و قیمت‌ها آپدیت شد:", time.ctime(last_update))
        else:
            print("⚠️ کش خالی موند (دیتا معتبر نبود)")

    except Exception as e:
        print("❌ خطا در آپدیت کش:", e)

print("[CANDLE TEST BTC]:", crypto_candles.get("BTC"))



# ---------- توابع دسترسی به کش ---------- #
def get_all_crypto_cached():
    return crypto_cache

def get_all_gold_cached():
    return gold_cache

def get_all_forex_cached():  
    return forex_cache

def get_all_coins_cached():
    return coins_cache

def time_since_update():
    """
    محاسبه زمان آخرین آپدیت به صورت خوانا
    """
    if not last_update:
        return "نامشخص"
    diff = int(time.time() - last_update)
    if diff < 60:
        return f"{diff} ثانیه پیش"
    elif diff < 3600:
        return f"{diff // 60} دقیقه پیش"
    else:
        return f"{diff // 3600} ساعت پیش"


# ------------------ ترد آپدیت کش ------------------ #
def auto_update_cache():
    while True:
        update_cache()
        time.sleep(60)  

threading.Thread(target=auto_update_cache, daemon=True).start()

# ---------- تابع گرفتن قیمت از کش ---------- #
def get_crypto_usd_price(symbol):
    crypto_item = next((i for i in crypto_cache if i["code"] == symbol), None)
    if crypto_item:
        return crypto_item["price"]
    return None

# ------------------ منو ------------------ #
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_price = types.KeyboardButton("📈 دریافت قیمت لحظه‌ای")
    btn_calc = types.KeyboardButton("💱 محاسبه نرخ ارز")
    btn_vip = types.KeyboardButton("👑 VIP")
    btn_profile = types.KeyboardButton("👤 پروفایل")  
    btn_contact = types.KeyboardButton("📞 تماس با ما")

    markup.add(btn_price, btn_calc, btn_vip, btn_profile, btn_contact)
    return markup

@bot.message_handler(commands=["start"])
def start_handler(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""

    # ذخیره کاربر در دیتابیس
    save_user(
    user_id=message.from_user.id,
    username=message.from_user.username or "",
    first_name=message.from_user.first_name or ""
    )

    
    # ----------------- چک عضویت ----------------- #
    if not is_user_joined(user_id):
        markup = types.InlineKeyboardMarkup(row_width=1)
        btn_join = types.InlineKeyboardButton(
            text="📢 عضویت در کانال اصلی",
            url="https://t.me/VIRAXcpl"
        )
        btn_done = types.InlineKeyboardButton(
            text="✅ عضو شدم",
            callback_data="joined_channel"
        )
        markup.add(btn_join, btn_done)

        msg = bot.send_message(
            user_id,
            "✨ لطفاً ابتدا در کانال رسمی ما عضو شوید تا از خدمات ربات استفاده کنید.",
            reply_markup=markup
        )

        try:
            bot.delete_message(user_id, message.message_id)
        except:
            pass
            
        return

    # ---------- متن خوش آمدگویی رسمی ----------
    first_name = message.from_user.first_name or ""
    welcome_text = (
        f"👋 سلام {first_name}! به دنیای ویراکس خوش آمدید!\n"
        "─·─·─·─·─·─·─·─·\n"
        "💎 قیمت لحظه‌ای: ارزهای کریپتو 🚀، دلار 💵، طلا \n"
        "⚡ محاسبه سریع: نرخ تبدیل ارز و طلا بدون دردسر \n"
        "📰 بروزرسانی VIP: آخرین اخبار و اطلاعیه‌ها 🎯\n"
        "─·─·─·─·─·─·─·─·\n"
        "💬 پشتیبانی 24 ساعته: @ViraxAd 🧑‍💻\n"
        "📢 کانال رسمی: @VIRAXcpl 🔔\n\n"
        "✨ برای شروع سریع، از دکمه‌های پایین استفاده کنید!"
    )

    # ---------- ایجاد Inline Keyboard ----------
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_channel = types.InlineKeyboardButton("📢 کانال رسمی", url="https://t.me/VIRAXcpl")
    btn_support = types.InlineKeyboardButton("💬 ارتباط با پشتیبانی", url="https://t.me/ViraxAd")
    btn_price = types.InlineKeyboardButton("📈 دریافت قیمت لحظه‌ای", callback_data="get_price")
    btn_calc = types.InlineKeyboardButton("💱 محاسبه نرخ ارز", callback_data="calc_rate")
    btn_vip = types.InlineKeyboardButton("👑 VIP", callback_data="vip_section")
    btn_profile = types.InlineKeyboardButton("👤 پروفایل", callback_data="profile")
    markup.add(btn_channel, btn_support, btn_price, btn_calc, btn_vip, btn_profile)

    # ---------- ارسال پیام ----------
    bot.send_message(user_id, welcome_text, reply_markup=markup)

# ------------------ دستورات ------------------ #
@bot.message_handler(commands=["help"])
@require_join
def help_handler(message):
    help_text = (
        "🆘 راهنمای استفاده از ربات ویراکس:\n\n"
        "1️⃣ /start - شروع و ورود به منوی اصلی ربات\n"
        "2️⃣ /menu - نمایش منوی اصلی\n"
        "3️⃣ /help - این راهنما\n"
        "4️⃣ /vip - بخش VIP\n"
        "5️⃣ /price - 📈 دریافت قیمت لحظه‌ای\n"
        "6️⃣ /calculator - 🧮 محاسبه نرخ\n"
        "7️⃣ /calendar - 📅 تقویم\n"
        "8️⃣ /addgroup - ➕ افزودن ربات به گروه\n\n"
        "💬 برای ارتباط با پشتیبانی: @ViraxAd\n"
        "📢 کانال رسمی: @VIRAXcpl"
    )
    bot.send_message(message.chat.id, help_text)

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

@bot.message_handler(commands=["menu"])
@require_join
def menu_handler(message):
    bot.send_message(
        message.chat.id,
        "📋 منوی اصلی ربات ویراکس:\n"
        "از گزینه‌های زیر استفاده کنید:",
        reply_markup=main_menu()
    )

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

@bot.message_handler(commands=["price"])
@require_join
def price_handler(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_crypto = types.KeyboardButton("💎 کریپتو")
    btn_forex = types.KeyboardButton("💱 فارکس (دلار و…)")
    btn_gold_coin = types.KeyboardButton("💰 طلا")
    btn_coin = types.KeyboardButton("🪙 سکه")
    btn_back = types.KeyboardButton("🔙 بازگشت")
    markup.add(btn_crypto, btn_forex, btn_gold_coin, btn_coin, btn_back)

    bot.send_message(
        chat_id,
        "💹 لطفاً دسته مورد نظر خود را انتخاب کنید:",
        reply_markup=markup
    )

    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

@bot.message_handler(commands=["calculator"])
@require_join
def calculator_handler(message):
    bot.send_message(
        message.chat.id,
        "🧮 در حال بروز رسانی ابزار محاسبه نرخ…"
    )

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass


@bot.message_handler(commands=["calendar"])
@require_join
def calendar_handler(message):
    send_calendar(message.chat.id)

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass

@bot.message_handler(commands=["addgroup"])
@require_join
def addgroup_handler(message):
    chat_id = message.chat.id

    # ساخت دکمه شیشه‌ای با لینک افزودن به گروه
    markup = types.InlineKeyboardMarkup()
    btn_add_group = types.InlineKeyboardButton(
        "➕ افزودن ربات به گروه",
        url="https://t.me/ViraxPriceBot?startgroup=true"
    )
    markup.add(btn_add_group)

    # ارسال پیام همراه با دکمه
    bot.send_message(
        chat_id,
        "برای افزودن ربات به یک گروه، روی دکمه زیر کلیک کنید:",
        reply_markup=markup
    )

    # حذف پیام دستور کاربر
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

# ------------------ نمایش کاربران برای ادمین ------------------ #
@bot.message_handler(commands=["users"])
def show_users(message):
    user_id = message.from_user.id

    if user_id not in ADMINS:  # ✅ مطمئن شو لیست ADMINS درست تعریف شده
        bot.send_message(user_id, "❌ شما دسترسی به این بخش را ندارید.")
        return

    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, first_name, is_admin FROM users")
    users = cursor.fetchall()
    conn.close()

    if not users:
        bot.send_message(user_id, "❌ هیچ کاربری در دیتابیس موجود نیست.")
        return

    total_users = len(users)
    text = f"👥 تعداد کل کاربران ربات: {total_users} نفر\n\n📋 لیست کاربران:\n\n"

    for uid, username, first_name, is_admin in users:
        username_display = f"@{username}" if username else "ندارد"
        name_display = first_name if first_name else "بدون‌نام"

        # ✅ اینجا با int تبدیل می‌کنیم که مشکل رشته/عدد نباشه
        role = "👑 ادمین" if int(is_admin) == 1 else "👤 کاربر عادی"

        text += f"• {uid} | {name_display} | {username_display} | {role}\n"

    bot.send_message(user_id, text)


# ------------------ ارسال پیام با افزایش درخواست ------------------ #
def send_message_with_request(user_id, text, reply_markup=None, parse_mode="HTML"):
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET request_count = request_count + 1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return bot.send_message(user_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ------------------ هندلر ارسال پروفایل ------------------ #
def send_profile(user_id, message=None):
    # اگر پیام اصلی وجود داشت → حذفش کن و اطلاعاتش رو ذخیره کن
    if message:
        try:
            bot.delete_message(chat_id=user_id, message_id=message.message_id)
        except:
            pass

    # گرفتن اطلاعات کاربر برای ذخیره
    if message:  # اگر از message_handler اومده
        username = message.from_user.username
        first_name = message.from_user.first_name
    else:  # اگر از callback_query اومده
        chat = bot.get_chat(user_id)
        username = chat.username
        first_name = chat.first_name

    # ذخیره نام و یوزرنیم
    save_user(user_id, username=username, first_name=first_name)

    # گرفتن اطلاعات کاربر از دیتابیس
    user = get_user(user_id)
    if not user:
        send_message_with_request(user_id, "❌ اطلاعات کاربری یافت نشد.")
        return

    # تبدیل تاریخ عضویت به شمسی
    try:
        j_join = jdatetime.datetime.fromgregorian(datetime=datetime.strptime(user["join_date"], "%Y-%m-%d"))
        join_date_shamsi = j_join.strftime("%Y/%m/%d")
    except:
        join_date_shamsi = user["join_date"]

    # محاسبه رتبه کاربر
    rank = get_user_rank(user_id)

    # متن پروفایل
    profile_text = (
        f"👤 پروفایل شما:\n\n"
        f"📛 نام: {user['first_name']}\n"
        f"🔗 یوزرنیم: @{user['username']}\n"
        f"📅 تاریخ عضویت: {join_date_shamsi}\n"
        f"📊 تعداد درخواست‌ها: {user['request_count']}\n"
        f"⭐ رتبه کاربر: #{rank}\n"
        f"💎 وضعیت VIP: {'✅' if user['is_vip'] else '❌'}\n"
        f"💱 ارزهای مورد علاقه: {', '.join(user['favorite_currencies']) if user['favorite_currencies'] else 'ندارد'}\n\n"
        "💬 برای ارسال بازخورد، لطفاً از دکمه‌های پایین استفاده کنید."
    )

    # ---------- دکمه‌های شیشه‌ای پروفایل ----------
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_edit_fav = types.InlineKeyboardButton("✏️ تنظیم ارزهای مورد علاقه", callback_data="edit_favorites")
    btn_send_feedback = types.InlineKeyboardButton("💬 ارسال بازخورد", callback_data="send_feedback")
    btn_back = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")
    markup.add(btn_edit_fav, btn_send_feedback, btn_back)

    # ارسال پیام پروفایل
    send_message_with_request(user_id, profile_text, reply_markup=markup)


# ------------------ هندلر پروفایل ------------------ #
@bot.message_handler(commands=["profile"])
@require_join
def profile_handler(message):
    send_profile(message.from_user.id, message)  # با message

    # ------------------ هندلر پیام پروفایل ------------------ #
@bot.callback_query_handler(func=lambda call: call.data in ["edit_favorites", "send_feedback", "back_to_menu"])
def profile_buttons_handler(call):
    user_id = call.from_user.id

    if call.data == "edit_favorites":
        msg = bot.send_message(user_id, "💱 لطفاً ارزهای مورد علاقه خود را با کاما وارد کنید، مثال: BTC,ETH,USDT")
        bot.register_next_step_handler(msg, save_favorite_currencies)

    elif call.data == "send_feedback":
        msg = bot.send_message(user_id, "💬 لطفاً پیام خود را برای پشتیبانی ارسال کنید:")
        bot.register_next_step_handler(msg, send_feedback)

    elif call.data == "back_to_menu":
        bot.send_message(user_id, "🔙 به منوی اصلی بازگشتید:", reply_markup=main_menu())

    # ------------------ هندلر ارز موردعلاقه ------------------ #
def save_favorite_currencies(message):
    user_id = message.chat.id
    
    # حذف پیام کاربر
    try:
        bot.delete_message(chat_id=user_id, message_id=message.message_id)
    except:
        pass

    favs = message.text.strip()
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET favorite_currencies=? WHERE id=?", (favs, user_id))
    conn.commit()
    conn.close()

    send_message_with_request(user_id, f"✅ ارزهای مورد علاقه شما ذخیره شد: {favs}")

def send_feedback(message):
    user_id = message.chat.id

    feedback_text = message.text.strip()
    SUPPORT_ID = 2054901055  # آیدی پشتیبانی
    send_message_with_request(SUPPORT_ID, f"💬 بازخورد از @{message.from_user.username}:\n\n{feedback_text}")
    send_message_with_request(user_id, "✅ بازخورد شما با موفقیت ارسال شد. ممنون از همکاری شما!")


# ---------- هندلر Callback برای دکمه‌های Inline ----------#
@bot.callback_query_handler(func=lambda call: True)
def handle_inline_buttons(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    if call.data == "joined_channel":
        if is_user_joined(user_id):
            # اگر عضو هست → ادیت پیام قبلی یا پاک و ارسال پیام جدید
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="✅ عضویت شما تایید شد!\n\nبرای استفاده از ربات روی /start بزنید."
                )
                bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    reply_markup=None
                )
            except Exception:
                # اگر ادیت نشد، هیچ کاری انجام نمی‌ده
                pass
            bot.answer_callback_query(
                call.id,
                text="✅ عضویت شما تایید شد!",
                show_alert=False
            )
        else:
            # اگر عضو نیست → فقط پیام کوچک بالای صفحه (Toast) بده
            bot.answer_callback_query(
                call.id,
                text="❌ هنوز عضو کانال نیستید!",
                show_alert=False
            )
        return  # کال‌بک پردازش شد

    # ---------- دریافت قیمت لحظه‌ای ----------
    if call.data == "get_price":
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        btn_crypto = types.KeyboardButton("💎 کریپتو")
        btn_forex = types.KeyboardButton("💱 فارکس (دلار و…)")
        btn_gold_coin = types.KeyboardButton("💰 طلا")
        btn_coin = types.KeyboardButton("🪙 سکه")
        btn_back = types.KeyboardButton("🔙 بازگشت")
        markup.add(btn_crypto, btn_forex, btn_gold_coin, btn_coin, btn_back)

        send_message_with_request(
            chat_id,
            "💹 لطفاً دسته مورد نظر خود را انتخاب کنید:",
            reply_markup=markup
        )
        

    # ---------- محاسبه نرخ (نوتیف کوتاه) ----------
    elif call.data == "calc_rate":
        bot.answer_callback_query(
            call.id,
            text="💵 بخش محاسبه نرخ در حال بروزرسانی است...",
            show_alert=False
        )

    elif call.data == "vip_section":
        bot.send_message(
            chat_id,
            "👑 بخش VIP در حال آماده‌سازی است و به زودی با امکانات ویژه برای کاربران فعال خواهد شد.\n"
            "🔥 برای دسترسی به امکانات VIP، کانال رسمی ما را دنبال کنید:\n"
            "@VIRAXcpl"
        )

    elif call.data == "profile":
        send_profile(user_id)


    # جواب به callback برای جلوگیری از لود نامحدود دکمه‌ها
    bot.answer_callback_query(call.id)


# ------------------ هندلر پروفایل برای Callback ------------------ #
def profile_handler_callback(chat_id, user_id):
    user = get_user(user_id)
    if not user:
        send_message_with_request(user_id, "❌ اطلاعات کاربری یافت نشد.")
        return

    first_name = user["first_name"] or "نامشخص"
    username = user["username"] or ""
    join_date = user["join_date"] or ""
    request_count = user["request_count"] or 0
    favorite_currencies = ", ".join(user["favorite_currencies"]) if user["favorite_currencies"] else "ندارد"
    is_vip = user["is_vip"]

    try:
        j_join = jdatetime.datetime.fromgregorian(datetime=datetime.strptime(join_date, "%Y-%m-%d"))
        join_date_shamsi = j_join.strftime("%Y/%m/%d")
    except:
        join_date_shamsi = join_date or "نامشخص"

    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*)+1 FROM users WHERE request_count > ?", (request_count,))
    rank = cursor.fetchone()[0]
    conn.close()

    vip_status = "✅ VIP" if is_vip else "❌ معمولی"

    profile_text = (
        f"👤 پروفایل شما:\n\n"
        f"📛 نام: {first_name}\n"
        f"🔗 یوزرنیم: @{username}\n"
        f"📅 تاریخ عضویت: {join_date_shamsi}\n"
        f"📊 تعداد درخواست‌ها: {request_count}\n"
        f"⭐ رتبه کاربر: #{rank}\n"
        f"💎 وضعیت VIP: {vip_status}\n"
        f"💱 ارزهای مورد علاقه: {favorite_currencies}\n\n"
        "💬 برای ارسال بازخورد، لطفاً از دکمه‌های پایین استفاده کنید."
    )

    # دکمه‌های شیشه‌ای پروفایل
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_edit_fav = types.InlineKeyboardButton("✏️ تنظیم ارزهای مورد علاقه", callback_data="edit_favorites")
    btn_send_feedback = types.InlineKeyboardButton("💬 ارسال بازخورد", callback_data="send_feedback")
    btn_back = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")
    markup.add(btn_edit_fav, btn_send_feedback, btn_back)

    send_message_with_request(user_id, profile_text, reply_markup=markup)
    
# ------------------ تقویم ------------------ #
def send_calendar(chat_id):
    # منطقه زمانی تهران
    tz = pytz.timezone("Asia/Tehran")
    now = datetime.now(tz)

    # تاریخ شمسی
    j_now = jdatetime.datetime.fromgregorian(datetime=now)
    shamsi_date = j_now.strftime("%Y/%m/%d")
    shamsi_day_en = j_now.strftime("%A")  # اسم روز شمسی انگلیسی

    # تبدیل روزهای شمسی به فارسی
    shamsi_days_fa = {
        "Saturday": "شنبه",
        "Sunday": "یک‌شنبه",
        "Monday": "دو‌شنبه",
        "Tuesday": "سه‌شنبه",
        "Wednesday": "چهار‌شنبه",
        "Thursday": "پنج‌شنبه",
        "Friday": "جمعه"
    }
    shamsi_day = shamsi_days_fa.get(shamsi_day_en, shamsi_day_en)

    # تاریخ میلادی
    miladi_date = now.strftime("%Y/%m/%d")
    miladi_day = now.strftime("%A")

    # تاریخ هجری قمری
    hijri = Gregorian(now.year, now.month, now.day).to_hijri()
    hijri_date = f"{hijri.year}/{hijri.month}/{hijri.day}"

    # ساعت دقیق ایران
    time_now = now.strftime("%H:%M:%S")

    # متن خروجی
    text = (
        "📆 تقویم و تاریخ امروز\n"
        f"📅 تاریخ شمسی: {shamsi_date} ({shamsi_day})\n"
        f"📅 تاریخ میلادی: {miladi_date} ({miladi_day})\n"
        f"📅 تاریخ هجری قمری: {hijri_date}\n"
        f"⏰ ساعت تهران: {time_now}"
    )

    bot.send_message(chat_id, text)

# ------------------ تاریخ ------------------ #
def get_datetime_info():
    tz = pytz.timezone("Asia/Tehran")
    now = datetime.now(tz)
    time_now = now.strftime("%H:%M:%S")

    j_now = jdatetime.datetime.fromgregorian(datetime=now)
    shamsi_date = j_now.strftime("%Y/%m/%d")

    weekdays_fa = {
        "Saturday": "شنبه",
        "Sunday": "یکشنبه",
        "Monday": "دوشنبه",
        "Tuesday": "سه‌شنبه",
        "Wednesday": "چهارشنبه",
        "Thursday": "پنجشنبه",
        "Friday": "جمعه"
    }
    day_fa = weekdays_fa[now.strftime("%A")]

    return f"📅 {day_fa} {shamsi_date} | 🕒 {time_now}"

    # ------------------ دکمه تماس ------------------ #
def contact_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_channel = types.KeyboardButton("📢 کانال رسمی")
    btn_support = types.KeyboardButton("💬 ارتباط با پشتیبانی")
    btn_back = types.KeyboardButton("🔙 بازگشت به منو")

    markup.add(btn_channel, btn_support, btn_back)
    return markup



pending_support = set()
admin_reply_to = {}  # {admin_id: user_id}
# ====================== شروع پشتیبانی ====================== #
@bot.message_handler(func=lambda m: m.text == "💬 ارتباط با پشتیبانی")
def start_support(message):
    chat_id = message.chat.id
    if chat_id in pending_support:
        bot.send_message(chat_id, "💬 شما در حال حاضر در حالت چت پشتیبانی هستید.")
        return

    pending_support.add(chat_id)
    bot.send_message(
        chat_id,
        "💬 لطفاً پیام خود را برای پشتیبانی ارسال کنید.\n❌ برای لغو، کلمه 'لغو' را ارسال کنید."
    )

# ====================== پیام کاربر ====================== #
@bot.message_handler(func=lambda m: m.chat.id in pending_support)
def handle_support_message(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.lower() == "لغو":
        pending_support.remove(chat_id)
        bot.send_message(chat_id, "❌ ارسال پیام لغو شد.", reply_markup=main_menu())
        return

    # دکمه برای پاسخ ادمین
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✉️ پاسخ به کاربر", callback_data=f"reply_{chat_id}"))

    bot.send_message(
        SUPPORT_ADMIN_ID,
        f"📩 پیام جدید از کاربر:\n"
        f"👤 نام: {message.from_user.first_name or 'ندارد'}\n"
        f"🔗 یوزرنیم: @{message.from_user.username or 'ندارد'}\n"
        f"🆔 آیدی: {chat_id}\n\n"
        f"💬 پیام:\n{text}",
        reply_markup=markup
    )

    bot.send_message(chat_id, "✅ پیام شما برای پشتیبانی ارسال شد. منتظر پاسخ باشید.")
    pending_support.discard(chat_id)
    bot.send_message(chat_id, "🔙 به منوی اصلی بازگشتید.", reply_markup=main_menu())

# =================== دکمه ادمین =================== #
@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def handle_reply_button(call):
    if call.from_user.id != SUPPORT_ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ شما اجازه استفاده از این دکمه را ندارید.", show_alert=True)
        return

    user_id = int(call.data.split("_")[1])
    admin_reply_to[call.from_user.id] = user_id

    bot.send_message(call.from_user.id,
                     f"✍️ شما در حالت پاسخ‌دهی به کاربر {user_id} هستید.\n"
                     "💬 هر پیامی که ارسال کنید، مستقیماً برای کاربر ارسال خواهد شد.\n"
                     "❌ برای لغو، کلمه 'لغو' را ارسال کنید.")

# =================== هندلر پیام ادمین =================== #
@bot.message_handler(func=lambda m: m.from_user.id in admin_reply_to)
def handle_admin_message(message):
    admin_id = message.from_user.id
    text = message.text.strip()

    if text.lower() == "لغو":
        admin_reply_to.pop(admin_id)
        bot.send_message(admin_id, "❌ پاسخ‌دهی لغو شد.", reply_markup=main_menu())
        return

    user_id = admin_reply_to[admin_id]
    bot.send_message(user_id, f"📬 پاسخ پشتیبانی:\n\n{text}")
    bot.send_message(admin_id, f"✅ پاسخ شما با موفقیت برای کاربر {user_id} ارسال شد.")

    # بعد از ارسال، ادمین از حالت پاسخ‌دهی خارج شود
    admin_reply_to.pop(admin_id)
    
    # ------------------ هندلر دکمه منو ------------------ #
@bot.message_handler(func=lambda message: message.text in [
    "📞 تماس با ما",
    "📢 کانال رسمی",
    "💬 ارتباط با پشتیبانی",
    "📈 دریافت قیمت لحظه‌ای",
    "💱 محاسبه نرخ ارز",
    "👑 VIP",
    "👤 پروفایل",
    "🔙 بازگشت به منو"
])
@require_join
def handle_menu(message):
    text = message.text
    chat_id = message.chat.id
    
    # ---------- بررسی بازگشت به منو ----------
    if text == "🔙 بازگشت به منو":
        if chat_id in pending_support:
            pending_support.remove(chat_id)  # خارج کردن کاربر از حالت پشتیبانی
        bot.send_message(chat_id, "🔙 بازگشت به منوی اصلی", reply_markup=main_menu())
        return  # اجرای هیچ بخش دیگه

    # ---------- اگر کاربر در حالت پشتیبانی است ----------
    if chat_id in pending_support:
        # پیام عادی برای پشتیبانی ارسال میشه
        return

        
    user_message_id = message.message_id

    # --- تماس با ما: باز کردن زیرمنو ---
    if text == "📞 تماس با ما":
        bot.send_message(chat_id, "📌 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=contact_menu())

    # --- کانال رسمی ---
    elif text == "📢 کانال رسمی":
        send_message_with_request(
            chat_id,
            "📢 کانال رسمی ویراکس، منبع آخرین اخبار و آپدیت‌های ربات:\n"
            "@VIRAXcpl\n\n"
            "برای مشاهده محتوا و دریافت اطلاع‌رسانی‌ها روی لینک کانال کلیک کنید."
        )

    # --- ارتباط با پشتیبانی ---
    elif text == "💬 ارتباط با پشتیبانی":
        if chat_id not in pending_support:
            pending_support.add(chat_id)
        bot.send_message(
            chat_id,
            "📝 لطفاً پیام خود را برای پشتیبانی ارسال کنید:\n"
            "➤ هر پیامی که ارسال کنید برای تیم پشتیبانی فرستاده می‌شود.\n"
            "❌ برای لغو، کلمه 'لغو' را بفرستید."
        )

    elif text == "📈 دریافت قیمت لحظه‌ای":
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)

        btn_crypto = types.KeyboardButton("💎 کریپتو")
        btn_forex = types.KeyboardButton("💱 فارکس (دلار و…)")
        btn_gold_coin = types.KeyboardButton("💰 طلا")
        btn_coin = types.KeyboardButton("🪙 سکه")
        btn_back = types.KeyboardButton("🔙 بازگشت")

        markup.add(btn_crypto, btn_forex, btn_gold_coin, btn_coin, btn_back)

        send_message_with_request(
            message.chat.id,
            "💹 لطفاً دسته مورد نظر خود را انتخاب کنید:",
            reply_markup=markup
        )
 
    elif text == "💱 محاسبه نرخ ارز":
        send_message_with_request(
            message.chat.id,
            "💵 با استفاده از این بخش می‌توانید مقدار مشخصی از هر ارز یا طلا را به معادل تومان و دلار تبدیل کنید.\n"
            "فرمت ورودی:\n"
            "• مقدار و نام ارز را وارد کنید، مثال:\n"
            "  - '۱۰ دلار'\n"
            "  - '۲ بیت کوین'\n"
            "• پس از ارسال، ربات محاسبه و نتیجه را همراه با قیمت لحظه‌ای نمایش خواهد داد."
        )

    elif text == "👑 VIP":
        send_message_with_request(
            message.chat.id,
            "👑 بخش VIP در حال آماده‌سازی است و به زودی با امکانات ویژه برای کاربران فعال خواهد شد.\n"
            "🔥 برای دسترسی به امکانات VIP، کانال رسمی ما را دنبال کنید:\n"
            "@VIRAXcpl"
        )

    elif text == "👤 پروفایل":
        send_profile(message.from_user.id)  # بدون message


# ------------------ هندلر بخش قیمت لحظه‌ای ------------------ #
@bot.message_handler(func=lambda message: message.text in ["💱 فارکس (دلار و…)", "💎 کریپتو", "💰 طلا", "🪙 سکه", "🔙 بازگشت"])
@require_join
def handle_price_categories(message):
    chat_id = message.chat.id
    text = message.text
    user_message_id = message.message_id

    if text == "🔙 بازگشت":
        # بازگشت به منوی اصلی
        bot.send_message(chat_id, "🔙 به منوی اصلی بازگشتید:", reply_markup=main_menu())
        return

    elif text == "💎 کریپتو":
        if not crypto_cache:
            bot.send_message(message.chat.id, "❌ لیست کریپتو در دسترس نیست.")
            return
        # دکمه بازگشت اول اضافه می‌شود
        buttons = [types.KeyboardButton("🔙 بازگشت")]
        # بعد همه ارزها از کش اضافه می‌شوند
        buttons += [types.KeyboardButton(i["code"]) for i in crypto_cache]
    
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        markup.add(*buttons)
        send_message_with_request(message.chat.id, "💹 لطفاً ارز مورد نظر را انتخاب کنید:", reply_markup=markup)
        return

    elif text == "💱 فارکس (دلار و…)":
        # اطمینان از اینکه کش موجود و غیر خالی است
        if not forex_cache or not isinstance(forex_cache, list):
            send_message_with_request(message.chat.id, "❌ لیست فارکس در دسترس نیست.")
            return

        # دکمه بازگشت اول اضافه می‌شود
        buttons = [types.KeyboardButton("🔙 بازگشت")]

        # فقط از code دکمه بساز، اگر وجود داشته باشد
        for item in forex_cache:
            code = item.get("code", "").strip()
            if code:
                buttons.append(types.KeyboardButton(code))

        if len(buttons) == 1:  # یعنی فقط دکمه بازگشت هست
            send_message_with_request(message.chat.id, "❌ لیست فارکس در دسترس نیست.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        markup.add(*buttons)
        send_message_with_request(message.chat.id, "💹 لطفاً ارز مورد نظر را انتخاب کنید:", reply_markup=markup)
        return

    elif text == "💰 طلا":
        if not gold_cache:
            send_message_with_request(message.chat.id, "❌ لیست طلا در دسترس نیست.")
            return
    
        buttons = [types.KeyboardButton("🔙 بازگشت")]
        buttons += [types.KeyboardButton(i["title"]) for i in gold_cache]
    
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(*buttons)
        send_message_with_request(message.chat.id, "💹 لطفاً نوع طلای مورد نظر را انتخاب کنید:", reply_markup=markup)
        return

    elif text == "🪙 سکه":
        # اطمینان از اینکه کش موجود و غیر خالی است
        if not coins_cache or not isinstance(coins_cache, list):
            bot.send_message(message.chat.id, "❌ لیست سکه در دسترس نیست.")
            return

        # دکمه بازگشت اول اضافه می‌شود
        buttons = [types.KeyboardButton("🔙 بازگشت")]

        # فقط از نام سکه‌ها دکمه بساز، اگر وجود داشته باشد
        for item in coins_cache:
            coin_name = item.get("coin", "").strip()
            if coin_name:
                buttons.append(types.KeyboardButton(coin_name))

        if len(buttons) == 1:  # یعنی فقط دکمه بازگشت هست
            bot.send_message(message.chat.id, "❌ لیست سکه در دسترس نیست.")
            return

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(*buttons)
        bot.send_message(message.chat.id, "🪙 لطفاً نوع سکه مورد نظر را انتخاب کنید:", reply_markup=markup)
        return

    # ---------- حذف پیام کاربر پس از پاسخ ----------
    try:
        bot.delete_message(chat_id, user_message_id)
    except:
        pass


        
# ------------------   کندل ساخت تصویر ------------------ #
def plot_candles_on_bg(symbol, candles, bg_path="p_back.png", save_path="output.png"):
    # candles: خروجی fetch_candles
    # فرمت‌دهی دیتای کندل
    ohlc = []
    for c in candles:
        ts = c["timestamp"] / 1000  # تبدیل ms به s
        ohlc.append([
            mdates.date2num(datetime.utcfromtimestamp(ts)),
            c["open"],
            c["high"],
            c["low"],
            c["close"]
        ])

    fig, ax = plt.subplots(figsize=(4.2, 2.3), dpi=100)  # سایز متناسب با مستطیل
    candlestick_ohlc(ax, ohlc, width=0.0005, colorup="green", colordown="red", alpha=1.0)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(ticker.MaxNLocator(4))
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    plt.axis("off")

    # ذخیره کندل به صورت تصویر موقت
    plt.savefig("candles_tmp.png", bbox_inches="tight", pad_inches=0, transparent=True)
    plt.close(fig)

    # الحاق به بکگراند
    bg = Image.open(bg_path).convert("RGBA")
    candle_img = Image.open("candles_tmp.png").convert("RGBA")

    # تغییر سایز و جایگذاری
    candle_img = candle_img.resize((420, 230))
    bg.paste(candle_img, (60, 500), candle_img)

    bg.save(save_path)
    print(f"[✅] تصویر ذخیره شد: {save_path}")

candles = fetch_candles("BTC")  # مثلا کندل بیتکوین
plot_candles_on_bg("BTC", candles, bg_path="p_back.png", save_path="btc_output.png")

        
# ------------------ ساخت تصویر ------------------ #

def generate_crypto_image(symbol, price_usd, price_irt, time_str,
                          logo_path="logo.png", telegram_logo_path="telegram_logo.png",
                          font_path="arial unicode ms.ttf",
                          width=1200, height=600):
    """
    ساخت تصویر ارز دیجیتال با بک‌گراند گرادینت، متن و لوگو
    
    symbol: نام ارز
    price_usd: قیمت دلاری
    price_irt: قیمت تومان
    time_str: زمان
    logo_path: مسیر لوگوی اصلی
    telegram_logo_path: مسیر لوگوی تلگرام
    font_path: مسیر فونت دلخواه
    width, height: اندازه تصویر خروجی
    """

    # ---------- گرادینت پس‌زمینه ----------
    gradient = np.linspace(0, 1, width)
    gradient = np.tile(gradient, (height, 1))
    color_left = np.array([5, 50, 30])    # سبز تیره خیلی ملایم
    color_right = np.array([90, 10, 10])   # قرمز تیره
    gradient_rgb = color_left + (color_right - color_left) * gradient[:, :, None]
    bg_image = Image.fromarray(gradient_rgb.astype(np.uint8))

    # ---------- نویز خیلی ملایم ----------
    noise = (np.random.rand(height, width, 3) * 20).astype(np.uint8)
    noise_image = Image.fromarray(noise)
    bg_image = Image.blend(bg_image, noise_image, alpha=0.04)

    draw = ImageDraw.Draw(bg_image)

    # ---------- فونت ----------
    try:
        if font_path and os.path.exists(font_path):
            font_title = ImageFont.truetype(font_path, 100)
            font_price = ImageFont.truetype(font_path, 64)
            font_time = ImageFont.truetype(font_path, 36)
            font_telegram = ImageFont.truetype(font_path, 42)
        else:
            font_title = font_price = font_time = font_telegram = ImageFont.load_default()
    except:
        font_title = font_price = font_time = font_telegram = ImageFont.load_default()

    # ---------- تابع متن با حاشیه مشکی ----------
    def draw_text_with_outline(x, y, text, font, fill, outline_color=(0,0,0), outline_width=3):
        for dx in range(-outline_width, outline_width+1):
            for dy in range(-outline_width, outline_width+1):
                if dx != 0 or dy != 0:
                    draw.text((x+dx, y+dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill)

    # ---------- رنگ‌های متالیک ----------
    metallic_silver = (200, 200, 200)
    metallic_gold = (212, 175, 55)
    metallic_green = (0, 180, 120)
                              
    # ---------- متن‌ها ----------
    draw.text((80, 105), symbol.upper(), fill=(255,255,255), font=font_title)
    draw.text((50, 250), f"${price_usd:,.2f} USD", fill=(0,255,128), font=font_price)
    draw.text((50, 350), f"{price_irt:,} IRT", fill=(255,230,0), font=font_price)
    draw.text((50, 450), time_str, fill=(255,255,255), font=font_time)

    # ---------- پیش‌تعیین سایز لوگوی اصلی به‌صورت نسبی (همیشه تعریف می‌شود) ----------
    logo_w_default = int(width * 0.22)
    logo_h_default = int(logo_w_default * 0.6)

    logo_x = int(width * 0.65)
    logo_y = int(height * 0.08)

    # ---------- لوگوی اصلی ----------
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            # اندازه براساس نسبت واقعی لوگو
            logo_w = int(width * 0.4)
            logo_h = int(logo_w * logo.height / logo.width)
            logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
            # محل قرارگیری (سمت راست بالا)
            logo_x = width - logo_w - int(width * 0.05)
            logo_y = int(height * 0.08)
            bg_image.paste(logo, (logo_x, logo_y), logo)
        except Exception as e:
            print("خطا در افزودن لوگوی اصلی:", e)
            # در صورت خطا از اندازه پیش‌فرض استفاده کن
            logo_w, logo_h = logo_w_default, logo_h_default
    else:
        # اگر لوگو نیست، از اندازه پیش‌فرض استفاده کن تا تلگرام زیر آن درست قرار بگیرد
        logo_w, logo_h = logo_w_default, logo_h_default
        logo_x = width - logo_w - int(width * 0.05)
        logo_y = int(height * 0.08)

    # ---------- تابع کمکی برای اندازه متن (سازگار با ورژن‌های Pillow مختلف) ----------
    def measure_text(draw_obj, text, font):
        # روش 1: draw.textsize
        try:
            return draw_obj.textsize(text, font=font)
        except Exception:
            pass
        # روش 2: draw.textbbox
        try:
            bbox = draw_obj.textbbox((0,0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            pass
        # روش 3: font.getsize
        try:
            return font.getsize(text)
        except Exception:
            pass
        # fallback تقریبی
        approx_w = int(len(text) * (getattr(font, "size", 12) * 0.6))
        approx_h = getattr(font, "size", 12)
        return (approx_w, approx_h)

    # ---------- لوگوی تلگرام + آیدی (زیر لوگوی اصلی، وسط‌چین) ----------
    if telegram_logo_path and os.path.exists(telegram_logo_path):
        try:
            tg = Image.open(telegram_logo_path).convert("RGBA")
            # سایز تلگرام کوچک‌تر نسبت به لوگوی اصلی
            tg_size = max(24, int(logo_w * 0.11))  # حداقل 24px
            tg = tg.resize((tg_size, tg_size), Image.LANCZOS)

            tg_handle = "@VIRAXcpl"
            text_w, text_h = measure_text(draw, tg_handle, font_telegram)

            gap = 6  # فاصله بین لوگوی تلگرام و متن

            group_w = tg_size + gap + text_w
            group_h = max(tg_size, text_h)

            # گروه تلگرام دقیقا زیر لوگوی اصلی با 5px فاصله
            group_x = logo_x + (logo_w - group_w) // 2
            group_y = logo_y + logo_h -170  

            tg_x = group_x
            tg_y = group_y + (group_h - tg_size) // 2
            text_x = tg_x + tg_size + gap
            text_y = group_y + (group_h - text_h) // 2 - 12 

            # paste و نوشتن
            bg_image.paste(tg, (int(tg_x), int(tg_y)), tg)
            draw.text((int(text_x), int(text_y)), tg_handle, fill=(255,255,255), font=font_telegram)
        except Exception as e:
            print("خطا در افزودن لوگوی تلگرام:", e)
            
    # ---------- ذخیره در بافر ----------
    buf = io.BytesIO()
    bg_image.save(buf, format='PNG')
    buf.seek(0)
    return buf

# ------------------ وضعیت انتظار برای پیام همگانی ------------------ #
broadcast_waiting_for_text = False  # حالت پیش‌فرض غیرفعال
broadcast_admin_id = None  # ذخیره آیدی ادمینی که دستور داد

# ------------------ دستور /broadcast ------------------ #
@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    global broadcast_waiting_for_text, broadcast_admin_id

    if message.from_user.id not in ADMINS:
        bot.send_message(message.chat.id, "❌ شما دسترسی به این بخش را ندارید.")
        return

    broadcast_waiting_for_text = True
    broadcast_admin_id = message.from_user.id
    bot.send_message(message.chat.id, "✏️ لطفاً متن پیام همگانی را ارسال کنید:")
        
# ------------------ هندلر اصلی پیام‌ها ------------------ #
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    global broadcast_waiting_for_text, broadcast_admin_id
    try:
        user_id = message.from_user.id
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or ""

        # ثبت کاربر
        save_user(user_id, username=username, first_name=first_name)

        text = message.text.strip()

        # ---------- حالت پیام همگانی ----------
        if broadcast_waiting_for_text and user_id == broadcast_admin_id:
            if not text:
                bot.send_message(user_id, "❌ متن پیام خالی است. لطفاً دوباره وارد کنید.")
                return

            users = get_all_users_with_admin()  # همه کاربران
            sent_count = 0
            for uid, username, first_name, is_admin in users:
                try:
                    bot.send_message(uid, text)
                    sent_count += 1
                except:
                    pass

            try:
                bot.send_message(CHANNEL_ID, text)
            except:
                pass

            bot.send_message(user_id, f"✅ پیام به {sent_count} کاربر و کانال ارسال شد.")
            broadcast_waiting_for_text = False
            broadcast_admin_id = None
            return  # بسیار مهم: بعد از پیام همگانی هیچ شرط دیگری اجرا نشود

        # --------- دکمه بازگشت ----------#
        if text == "🔙 بازگشت":
            bot.send_message(
                message.chat.id,
                "🔙 به منوی اصلی بازگشتید:",
                reply_markup=main_menu()
            )
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            return

        # ---------- پاسخ به کریپتو ----------#
        crypto_codes = [i["code"] for i in crypto_cache]
        if text in crypto_codes:
            crypto_item = next((i for i in crypto_cache if i["code"] == text), None)
            if crypto_item:
                price = crypto_item["price"]
                send_message_with_request(
                    message.chat.id,
                    f"💎 قیمت {text}: {price:,} تومان\n⏱ آخرین بروزرسانی: {time_since_update()}\n{get_datetime_info()}"
                )
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            return

        # ---------- پاسخ به طلا ----------#
        gold_item = next((i for i in gold_cache if i["title"] == text), None)
        if gold_item:
            try:
                price_toman = int(str(gold_item["price"]).replace(",", "").replace("٬", "")) // 10
            except:
                price_toman = 0
            send_message_with_request(
                message.chat.id,
                f"💰 قیمت {text}: {price_toman:,} تومان\n⏱ آخرین بروزرسانی: {time_since_update()}\n{get_datetime_info()}"
            )
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass            
            return

        # ---------- پاسخ به فارکس ----------#
        if not forex_cache or not isinstance(forex_cache, list):
            bot.send_message(message.chat.id, "❌ لیست فارکس در دسترس نیست.")
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            return

        try:
            forex_item = next(
                (i for i in forex_cache if i.get("code") == text or i.get("currency") == text),
                None
            )

            if forex_item:
                try:
                    price_toman = int(str(forex_item.get("sell", 0)).replace(",", ""))
                except ValueError:
                    price_toman = 0

                if price_toman > 0:
                    send_message_with_request(
                        message.chat.id,
                        f"💵 قیمت {forex_item.get('code', text)}: {price_toman:,} تومان\n⏱ آخرین بروزرسانی: {time_since_update()}\n{get_datetime_info()}"
                    )
                else:
                    bot.send_message(message.chat.id, f"❌ قیمت {text} در دسترس نیست.")

            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass

        except Exception as e:
            print(f"خطا در هندل پیام‌ها: {e}")

        # ---------- پاسخ به سکه ----------#
        if not coins_cache or not isinstance(coins_cache, list):
            bot.send_message(message.chat.id, "❌ لیست سکه در دسترس نیست.")
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            return

        try:
            coin_item = next((i for i in coins_cache if i.get("coin") == text), None)

            if coin_item:
                try:
                    price_toman = int(str(coin_item.get("sell", 0)).replace(",", ""))
                except ValueError:
                    price_toman = 0

                if price_toman > 0:
                    send_message_with_request(
                        message.chat.id,
                        f"🪙 قیمت {coin_item.get('coin', text)}: {price_toman:,} تومان\n⏱ آخرین بروزرسانی: {time_since_update()}\n{get_datetime_info()}"
                    )
                else:
                    bot.send_message(message.chat.id, f"❌ قیمت {text} در دسترس نیست.")

            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
                

        except Exception as e:
            print(f"خطا در هندل پیام‌ها: {e}")


        # ---------- انتخاب ارز یا واحد پول ----------#
        mapping = {
            "بیت کوین": "BTC", "btc": "BTC", "bitcoin": "BTC",
            "اتریوم": "ETH", "eth": "ETH", "ethereum": "ETH",
            "تتر": "USDT", "usdt": "USDT",
            "ریپل": "XRP", "xrp": "XRP",
            "کاردانو": "ADA", "ada": "ADA",
            "سولانا": "SOL", "sol": "SOL",
            "دوج کوین": "DOGE", "doge": "DOGE",
            "شیبا": "SHIB", "shib": "SHIB",
            "پولکادات": "DOT", "dot": "DOT",
            "ترون": "TRX", "trx": "TRX",
            "لایت کوین": "LTC", "ltc": "LTC",
            "دلار": "USD", "usd": "USD",
            "یورو": "EUR", "eur": "EUR", "euro": "EUR",
            "طلا": "GOLD", "طلای 18": "GOLD",
        }
                # حذف پیام کاربر برای هر حالت که به اینجا رسید
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

    except Exception as e:
        print(f"خطا در هندل پیام‌ها (کلی): {e}")

# ---------- helpers برای کش و فراخوانی امن ----------
CACHE_PATH = "data/price_cache.json"
os.makedirs("data", exist_ok=True)

def load_price_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_price_cache(cache):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print("خطا در ذخیره کش قیمت:", e)

def safe_fetch_price(name, fetch_func, *args, attempts=3, delay=1):
    """
    تلاش برای گرفتن قیمت با چند Retry.
    اگر موفق شد مقدار جدید را در کش ذخیره میکند و برمیگرداند.
    اگر ناموفق شد مقدار قبلی از کش را برمیگرداند (یا None اگر موجود نباشد).
    """
    cache = load_price_cache()
    for i in range(attempts):
        try:
            val = fetch_func(*args)
            if val is not None:
                # اطمینان از اینکه عدد ذخیره می‌شود (int/float)
                try:
                    # اگر str با کاما بود پاک کنیم و به عدد تبدیل کنیم
                    if isinstance(val, str):
                        v = float(val.replace(",", ""))
                    else:
                        v = val
                    cache[name] = v
                    save_price_cache(cache)
                    return v
                except:
                    # اگر تبدیل ناموفق بود، باز هم کش نکن و None برگردان
                    cache[name] = val
                    save_price_cache(cache)
                    return val
        except Exception as e:
            print(f"خطا در دریافت {name} (attempt {i+1}): {e}")
        time.sleep(delay)

    # اگر همه تلاش‌ها شکست خورد، مقدار از کش رو برگردون
    return cache.get(name)

def fmt_num(value, decimals=0):
    """فرمت با جداکننده هزارگان یا برگرداندن None -> 'نامشخص'"""
    if value is None:
        return None
    try:
        if decimals > 0:
            return f"{float(value):,.{decimals}f}"
        return f"{int(round(float(value))):,}"
    except Exception:
        try:
            return str(value)
        except:
            return None

def make_pair_line(label, usd_val, ird_val):
    """ساخت یک خط برای ارز با دو طرف USD و IRR (toman)"""
    left = f"{fmt_num(usd_val, 2)} دلار" if usd_val is not None else ""
    right = f"{fmt_num(ird_val)} تومان" if ird_val is not None else ""
    if left and right:
        return f"{label}: {left} | {right}"
    if left:
        return f"{label}: {left}"
    if right:
        return f"{label}: {right}"
    return f"{label}: نامشخص"



# ------------------ تست اختصاصی برای reply_ ------------------ #
@bot.callback_query_handler(func=lambda call: True)
def catch_all_callbacks(call):
    print("CALLBACK RECEIVED:", call.data)
    bot.answer_callback_query(call.id, "کلیک شد!")
    
# ------------------ Flask + Webhook ------------------ #
app = Flask(__name__)

@app.route("/" + BOT_TOKEN, methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")

    # فیکس باگ chat_boost بدون فیلد source
    import json
    update_data = json.loads(json_str)

    if "chat_boost" in update_data and isinstance(update_data["chat_boost"], dict):
        if "source" not in update_data["chat_boost"]:
            del update_data["chat_boost"]

    update = telebot.types.Update.de_json(update_data)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "VIRAX bot is running", 200

@app.route("/btc.png")
def get_btc():
    return send_file("btc_output.png", mimetype="image/png")

if __name__ == "__main__":
    init_db()
    set_commands()

    bot.remove_webhook()
    bot.set_webhook(url="https://viraxbot-production.up.railway.app/" + BOT_TOKEN)
    app.run(host="0.0.0.0", port=8090)
