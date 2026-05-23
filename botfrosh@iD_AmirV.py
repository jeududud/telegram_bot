import asyncio
import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime

import jdatetime


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
EN_FROM_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa_digits(s) -> str:
    return str(s).translate(PERSIAN_DIGITS)


def fa_to_en_digits(s) -> str:
    return str(s).translate(EN_FROM_FA_DIGITS)


def jalali_date(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return fa_digits(j.strftime("%Y/%m/%d"))


def jalali_datetime(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return fa_digits(j.strftime("%Y/%m/%d %H:%M:%S"))

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from typing import Any, Awaitable, Callable, Dict

# ===== رنگ دکمه‌های شیشه‌ای =====
try:
    from aiogram.enums import ButtonStyle  # aiogram >= 3.27  # type: ignore
    _HAS_STYLE = True
except ImportError:
    class ButtonStyle:  # type: ignore
        PRIMARY = "primary"
        DANGER  = "danger"
        SUCCESS = "success"
    _HAS_STYLE = False

    # patch: اگر aiogram از style پشتیبانی نمی‌کند، پارامتر را حذف کن
    _orig_ikb = InlineKeyboardButton.__init__
    def _safe_ikb(self, **kw):
        kw.pop("style", None)
        _orig_ikb(self, **kw)
    InlineKeyboardButton.__init__ = _safe_ikb  # type: ignore

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== تنظیمات ثابت ====================
BOT_TOKEN = "8631257051:AAGdcIxXT6iB9LQBblxfe8SaNtBEKbP3-fc"
SUPER_ADMIN_IDS = [8478999016, 6925196927]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bot24.db")
SETTINGS_FILE = os.path.join(BASE_DIR, "bot_settings.json")

DEFAULT_SUPPORT_ID = "@v2ray_404"
DEFAULT_CHANNELS = ["@v2ray_404"]

# قیمت پیش‌فرض (تومان × ۱۰۰۰ یعنی هزار تومان نمایش داده می‌شود)
DEFAULT_PRICES = {
    "1": 450_000,
    "2": 900_000,
    "3": 1_350_000,
    "5": 2_250_000,
    "10": 4_200_000,
}
PRODUCT_LABEL = {
    "1":  "۱ گیگ",
    "2":  "۲ گیگ",
    "3":  "۳ گیگ",
    "5":  "۵ گیگ",
    "6":  "۶ گیگ",
    "7":  "۷ گیگ",
    "8":  "۸ گیگ",
    "9":  "۹ گیگ",
    "10": "۱۰ گیگ",
}

# لیست محصولات پیش‌فرض (ترتیب نمایش از همین لیست)
DEFAULT_PRODUCTS = [
    {"key": "1",  "label": "۱ گیگ",  "price": 450_000},
    {"key": "2",  "label": "۲ گیگ",  "price": 900_000},
    {"key": "3",  "label": "۳ گیگ",  "price": 1_350_000},
    {"key": "5",  "label": "۵ گیگ",  "price": 2_250_000},
    {"key": "6",  "label": "۶ گیگ",  "price": 2_700_000},
    {"key": "7",  "label": "۷ گیگ",  "price": 3_150_000},
    {"key": "8",  "label": "۸ گیگ",  "price": 3_600_000},
    {"key": "9",  "label": "۹ گیگ",  "price": 3_800_000},
    {"key": "10", "label": "۱۰ گیگ", "price": 4_200_000},
]

DEFAULT_BUTTON_COLORS = {
    "main_buy": "primary",
    "main_freeconf": "success",
    "main_my": "success",
    "main_account": "primary",
    "main_invite": "success",
    "main_support": "default",
    "main_admin": "danger",
    "pay_card": "primary",
    "pay_discount": "success",
    "back": "default",
}

DEFAULT_BUTTON_LABELS = {
    "main_buy": "🛒 خرید سرویس جدید",
    "main_freeconf": "🎁 کانفیگ رایگان",
    "main_my": "📦 سرویس‌های من",
    "main_account": "👤 حساب کاربری",
    "main_invite": "🤝 دعوت دوستان",
    "main_support": "📞 ارتباط با پشتیبانی",
    "main_admin": "🛠 پنل مدیریت",
    "pay_card": "💳 کارت به کارت",
    "pay_discount": "🎁 اعمال کد تخفیف",
    "back": "🔙 بازگشت",
}

# نگاشت زنده — از SETTINGS["button_labels"] خوانده می‌شود
BUTTON_LABELS = dict(DEFAULT_BUTTON_LABELS)

BUTTON_NAMES_FA = {
    "main_buy": "دکمه خرید سرویس",
    "main_freeconf": "دکمه کانفیگ رایگان",
    "main_my": "دکمه سرویس‌های من",
    "main_account": "دکمه حساب کاربری",
    "main_invite": "دکمه دعوت دوستان",
    "main_support": "دکمه پشتیبانی",
    "main_admin": "دکمه پنل مدیریت",
    "pay_card": "دکمه کارت به کارت",
    "pay_discount": "دکمه اعمال تخفیف",
    "back": "دکمه بازگشت",
}

# ===== متن‌های قابل ویرایش =====
DEFAULT_TEXTS = {
    "welcome": (
        "✨ به فروشگاه VPN ما خوش آمدید!\n\n"
        "🛡 ارائه انواع سرویس‌های VPN با کیفیت عالی\n"
        "✅ تضمین امنیت ارتباطات شما\n"
        "📞 پشتیبانی حرفه‌ای ۲۴ ساعته\n\n"
        "از منوی زیر بخش مورد نظر خود را انتخاب کنید."
    ),
    "sales_off": "🚫 فروش بسته است.\n\nلطفاً بعداً مراجعه کنید.",
    "bot_off_alert": "🛠 ربات در حال بروزرسانی است.\nلطفاً کمی بعد دوباره تلاش کنید.",
    "join_required": "❌ برای استفاده از ربات لازم است در کانال زیر عضو شوید:",
    "not_joined": "❌ هنوز عضو نشده‌اید!",
    "banned": "⛔️ حساب شما مسدود شده است.",
}

TEXT_NAMES_FA = {
    "welcome": "متن خوش‌آمد",
    "sales_off": "متن «فروش بسته است»",
    "bot_off_alert": "متن «ربات در حال بروزرسانی»",
    "join_required": "متن «الزام عضویت در کانال»",
    "not_joined": "متن «هنوز عضو نشده‌اید»",
    "banned": "متن «حساب مسدود است»",
}

# ===== اموجی پریمیوم تلگرام (فقط داخل متن HTML قابل استفاده، روی دکمه‌ها نه) =====
PREMIUM_EMOJIS = {
    "fire":   "5377498341074542751",
    "heart":  "5404870433939922908",
    "rocket": "5276424673834317384",
    "star":   "5370870893004203987",
    "check":  "5443038326535759217",
    "crown":  "5188377234767305988",
    "lock":   "5188279383087325151",
    "money":  "5197070321321989384",
    "gift":   "5188331717857411845",
    "phone":  "5471978007890188532",
}

def pe(name_or_id: str, fallback: str) -> str:
    """ساخت تگ اموجی پریمیوم برای متن HTML.
    اگر نام شناخته‌شده‌ای از PREMIUM_EMOJIS باشد آی‌دی‌اش را برمی‌دارد، وگرنه خود ورودی را آی‌دی فرض می‌کند.
    """
    eid = PREMIUM_EMOJIS.get(name_or_id, name_or_id)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


# ===== مجوزهای ادمین جانبی =====
ALL_PERMS = [
    "stats", "users", "broadcast", "channels", "support_id",
    "products", "prices", "card", "discount", "giftcfg",
    "approve_receipts", "ban", "texts", "buttons", "colors",
    "toggle_sales", "toggle_bot", "coins",
]

PERM_NAMES_FA = {
    "stats":            "📊 آمار ربات",
    "users":            "👥 لیست کاربران",
    "broadcast":        "📢 پیام همگانی",
    "channels":         "📡 مدیریت چنل‌ها",
    "support_id":       "🛟 تنظیم پشتیبانی",
    "products":         "💵 مدیریت محصولات/قیمت‌ها",
    "prices":           "💰 تغییر قیمت محصولات",
    "card":             "💳 تنظیم کارت",
    "discount":         "🎁 ساخت کد تخفیف",
    "giftcfg":          "🎁 مدیریت کانفیگ هدیه",
    "approve_receipts": "✅ تایید رسیدها",
    "ban":              "🚫 بن/آنبن کاربران",
    "texts":            "✏️ مدیریت متن‌ها",
    "buttons":          "🔘 مدیریت دکمه‌ها",
    "colors":           "🎨 تنظیم رنگ دکمه‌ها",
    "toggle_sales":     "🟢 خاموش/روشن فروش",
    "toggle_bot":       "🔴 خاموش/روشن ربات",
    "coins":            "🪙 مدیریت سکه‌ها",
}

# ==================== ذخیره تنظیمات ====================
def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("support_id", DEFAULT_SUPPORT_ID)
    data.setdefault("channels", DEFAULT_CHANNELS.copy())
    data.setdefault("prices", DEFAULT_PRICES.copy())
    data.setdefault("colors", DEFAULT_BUTTON_COLORS.copy())
    data.setdefault("card_number", "")
    data.setdefault("card_holder", "")
    # تنظیمات جدید
    data.setdefault("sales_enabled", True)
    data.setdefault("bot_enabled", True)
    data.setdefault("products", [p.copy() for p in DEFAULT_PRODUCTS])
    data.setdefault("broadcast_pins", [])
    # 🪙 سیستم سکه
    data.setdefault("free_config_coins", 5)   # تعداد سکه برای دریافت یک کانفیگ رایگان
    data.setdefault("coins_per_referral", 1)  # تعداد سکه به ازای هر دعوت موفق
    # متن‌ها و برچسب دکمه‌ها قابل ویرایش از پنل
    data.setdefault("texts", DEFAULT_TEXTS.copy())
    data.setdefault("button_labels", DEFAULT_BUTTON_LABELS.copy())
    # ادمین‌های جانبی با مجوز تفکیکی
    data.setdefault("sub_admins", [])  # [{user_id:int, perms:{perm:bool}}]
    # merge defaults
    for k, v in DEFAULT_PRICES.items():
        data["prices"].setdefault(k, v)
    for k, v in DEFAULT_BUTTON_COLORS.items():
        data["colors"].setdefault(k, v)
    for k, v in DEFAULT_TEXTS.items():
        data["texts"].setdefault(k, v)
    for k, v in DEFAULT_BUTTON_LABELS.items():
        data["button_labels"].setdefault(k, v)
    # سینک: اطمینان از وجود همه قیمت‌های محصولات داخل prices
    for p in data["products"]:
        data["prices"].setdefault(p["key"], p["price"])
    return data


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


SETTINGS = load_settings()

# سینک برچسب دکمه‌ها از تنظیمات (در زمان اجرا اپدیت می‌شود)
def sync_button_labels():
    BUTTON_LABELS.clear()
    BUTTON_LABELS.update(SETTINGS.get("button_labels") or DEFAULT_BUTTON_LABELS)

sync_button_labels()


def s_get(key, default=None):
    return SETTINGS.get(key, default)


def s_set(key, value):
    SETTINGS[key] = value
    save_settings(SETTINGS)


# ===== متن‌های قابل تنظیم =====
def get_text(key: str) -> str:
    return (SETTINGS.get("texts") or {}).get(key) or DEFAULT_TEXTS.get(key, "")


def set_text(key: str, value: str):
    SETTINGS.setdefault("texts", {})[key] = value
    save_settings(SETTINGS)


def get_button_label(key: str) -> str:
    return (SETTINGS.get("button_labels") or {}).get(key) or DEFAULT_BUTTON_LABELS.get(key, key)


def set_button_label(key: str, value: str):
    SETTINGS.setdefault("button_labels", {})[key] = value
    save_settings(SETTINGS)
    sync_button_labels()


# ===== ادمین‌های جانبی =====
def get_sub_admins() -> list:
    return SETTINGS.get("sub_admins") or []


def find_sub_admin(uid: int) -> dict | None:
    for sa in get_sub_admins():
        if int(sa.get("user_id", 0)) == int(uid):
            return sa
    return None


def add_sub_admin(uid: int, name: str = "", perms=None) -> bool:
    if find_sub_admin(uid):
        return False
    if perms is None:
        perms_dict = {p: True for p in ALL_PERMS}
    elif isinstance(perms, list):
        perms_dict = {p: True for p in ALL_PERMS}
    else:
        perms_dict = perms
    SETTINGS.setdefault("sub_admins", []).append({"user_id": int(uid), "name": name, "perms": perms_dict})
    save_settings(SETTINGS)
    return True


def remove_sub_admin(uid: int) -> bool:
    lst = get_sub_admins()
    new_lst = [sa for sa in lst if int(sa.get("user_id", 0)) != int(uid)]
    if len(new_lst) == len(lst):
        return False
    SETTINGS["sub_admins"] = new_lst
    save_settings(SETTINGS)
    return True


def toggle_sub_admin_perm(uid: int, perm: str) -> bool | None:
    sa = find_sub_admin(uid)
    if not sa:
        return None
    sa.setdefault("perms", {})
    cur = bool(sa["perms"].get(perm, False))
    sa["perms"][perm] = not cur
    save_settings(SETTINGS)
    return sa["perms"][perm]


# ==================== کمک‌های محصولات داینامیک ====================
def get_products() -> list:
    """لیست محصولات (ترتیبی)."""
    return SETTINGS.get("products") or []


def get_product(key: str) -> dict | None:
    for p in get_products():
        if p["key"] == key:
            return p
    return None


def get_product_label(key: str) -> str:
    if key == "free":
        return "🎁 کانفیگ رایگان"
    p = get_product(key)
    if p:
        return p["label"]
    return PRODUCT_LABEL.get(key, key)


def get_product_price(key: str) -> int:
    p = get_product(key)
    if p:
        return p["price"]
    return SETTINGS.get("prices", {}).get(key) or DEFAULT_PRICES.get(key, 0)


def add_product(label: str, price: int) -> str:
    """اضافه کردن محصول جدید با کلید یکتا. کلید را برمی‌گرداند."""
    products = get_products()
    used_keys = {p["key"] for p in products}
    # تولید کلید یکتا (شماره سریال)
    n = 1
    while str(n) in used_keys:
        n += 1
    key = str(n)
    products.append({"key": key, "label": label, "price": price})
    SETTINGS["products"] = products
    SETTINGS.setdefault("prices", {})[key] = price
    save_settings(SETTINGS)
    return key


def remove_product(key: str) -> bool:
    products = get_products()
    new_list = [p for p in products if p["key"] != key]
    if len(new_list) == len(products):
        return False
    SETTINGS["products"] = new_list
    if "prices" in SETTINGS and key in SETTINGS["prices"]:
        del SETTINGS["prices"][key]
    save_settings(SETTINGS)
    return True


def update_product_price(key: str, price: int) -> bool:
    products = get_products()
    found = False
    for p in products:
        if p["key"] == key:
            p["price"] = price
            found = True
            break
    if not found:
        return False
    SETTINGS["products"] = products
    SETTINGS.setdefault("prices", {})[key] = price
    save_settings(SETTINGS)
    return True


# ==================== رنگ دکمه‌ها ====================
_COLOR_MAP = {
    "primary": ButtonStyle.PRIMARY,
    "danger":  ButtonStyle.DANGER,
    "success": ButtonStyle.SUCCESS,
    "default": None,
}


def style_of(key: str):
    color = SETTINGS["colors"].get(key, DEFAULT_BUTTON_COLORS.get(key, "default"))
    return _COLOR_MAP.get(color, None)


def btn(text: str, key: str | None = None, **kwargs) -> InlineKeyboardButton:
    if key:
        return InlineKeyboardButton(text=text, style=style_of(key), **kwargs)
    return InlineKeyboardButton(text=text, **kwargs)


# ==================== دیتابیس ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        join_date TEXT,
        is_banned INTEGER DEFAULT 0,
        invited_by INTEGER,
        balance INTEGER DEFAULT 0,
        referral_discount_used INTEGER DEFAULT 0,
        referral_discount_available INTEGER DEFAULT 0
        )"""
    )
    for col, ddl in [
        ("balance", "ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0"),
        ("referral_discount_used", "ALTER TABLE users ADD COLUMN referral_discount_used INTEGER DEFAULT 0"),
        ("referral_discount_available", "ALTER TABLE users ADD COLUMN referral_discount_available INTEGER DEFAULT 0"),
        ("invite_credited", "ALTER TABLE users ADD COLUMN invite_credited INTEGER DEFAULT 0"),
        ("ref_configs_received", "ALTER TABLE users ADD COLUMN ref_configs_received INTEGER DEFAULT 0"),
        ("ref_configs_owed", "ALTER TABLE users ADD COLUMN ref_configs_owed INTEGER DEFAULT 0"),
        ("coins", "ALTER TABLE users ADD COLUMN coins INTEGER DEFAULT 0"),
    ]:
        try: c.execute(ddl)
        except: pass
    # جدول مخزن کانفیگ‌های هدیه‌ی رفرال
    c.execute(
        """CREATE TABLE IF NOT EXISTS referral_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_text TEXT NOT NULL,
        claimed_by INTEGER,
        claimed_at TEXT,
        created_at TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product TEXT,
        username TEXT,
        amount INTEGER,
        photo_id TEXT,
        status TEXT DEFAULT 'pending',
        config TEXT DEFAULT '',
        sub_link TEXT DEFAULT '',
        created_at TEXT
        )"""
    )
    for col, ddl in [
        ("config", "ALTER TABLE receipts ADD COLUMN config TEXT DEFAULT ''"),
        ("sub_link", "ALTER TABLE receipts ADD COLUMN sub_link TEXT DEFAULT ''"),
    ]:
        try: c.execute(ddl)
        except: pass
    c.execute(
        """CREATE TABLE IF NOT EXISTS discounts (
        code TEXT PRIMARY KEY,
        percent INTEGER,
        created_at TEXT
        )"""
    )
    # جدول pool کانفیگ‌ها به تفکیک محصول
    c.execute(
        """CREATE TABLE IF NOT EXISTS config_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_key TEXT NOT NULL,
        config_text TEXT NOT NULL,
        sub_link TEXT DEFAULT '',
        pool_type TEXT DEFAULT 'cfg',
        created_at TEXT,
        used INTEGER DEFAULT 0,
        used_for_receipt INTEGER DEFAULT 0
        )"""
    )
    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB_PATH)


def db_add_user(user_id, username, full_name, invited_by=None):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, join_date, invited_by) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, full_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), invited_by),
    )
    new = c.rowcount == 1
    conn.commit()
    conn.close()
    return new


def db_is_banned(user_id) -> bool:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return bool(r and r[0])


def db_set_ban(user_id, val: int):
    conn = db()
    c = conn.cursor()
    # اگر کاربر قبلاً نبوده، اول می‌سازیم
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
        (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (val, user_id))
    conn.commit()
    conn.close()


def db_stats():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM receipts")
    total_r = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM receipts WHERE status='approved'")
    approved = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM receipts WHERE status='pending'")
    pending = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM receipts WHERE status='approved'")
    revenue = c.fetchone()[0]
    today = date.today().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM users WHERE join_date LIKE ?", (today + "%",))
    new_today = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM discounts")
    discounts = c.fetchone()[0]
    conn.close()
    return {
        "total_users": total_users,
        "banned": banned,
        "total_receipts": total_r,
        "approved": approved,
        "pending": pending,
        "revenue": revenue,
        "new_today": new_today,
        "discounts": discounts,
    }


def db_create_receipt(user_id, product, username, amount, photo_id) -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO receipts (user_id, product, username, amount, photo_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, product, username, amount, photo_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def db_get_pending_receipts():
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, user_id, product, username, amount FROM receipts WHERE status='pending' ORDER BY id"
    )
    rows = c.fetchall()
    conn.close()
    return rows


def db_approve_receipt(rid):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE receipts SET status='approved' WHERE id = ?", (rid,))
    conn.commit()
    conn.close()


def db_get_user_receipts(user_id):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, product, username, amount, status, created_at FROM receipts WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def db_get_receipt(rid):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, user_id, product, username, amount, photo_id, status, config, sub_link, created_at FROM receipts WHERE id = ?",
        (rid,),
    )
    r = c.fetchone()
    conn.close()
    return r


def db_set_receipt_status(rid, status):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE receipts SET status = ? WHERE id = ?", (status, rid))
    conn.commit()
    conn.close()


def db_set_receipt_config(rid, config="", sub_link=""):
    conn = db()
    c = conn.cursor()
    fields, vals = [], []
    if config:
        fields.append("config = ?"); vals.append(config)
    if sub_link:
        fields.append("sub_link = ?"); vals.append(sub_link)
    if not fields:
        conn.close(); return
    vals.append(rid)
    c.execute(f"UPDATE receipts SET {', '.join(fields)} WHERE id = ?", tuple(vals))
    conn.commit()
    conn.close()


def db_get_user_delivered_services(user_id):
    """سرویس‌هایی که تایید شده‌اند (کانفیگ یا ساب دارند یا تایید شده‌اند)."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, product, username, config, sub_link FROM receipts "
        "WHERE user_id = ? AND status='approved' ORDER BY id DESC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def db_get_user_info(user_id):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT balance, join_date FROM users WHERE user_id = ?",
        (user_id,),
    )
    r = c.fetchone()
    c.execute(
        "SELECT COUNT(*) FROM receipts WHERE user_id = ? AND status='approved'",
        (user_id,),
    )
    services = c.fetchone()[0]
    conn.close()
    if not r:
        return {"balance": 0, "join_date": None, "services": 0}
    return {"balance": r[0] or 0, "join_date": r[1], "services": services}


def db_get_users_page(page: int, per_page: int = 10, banned_only: bool = False):
    """صفحه‌بندی کاربران. برمی‌گرداند: (rows, total_count).

    هر row: (user_id, username, full_name, balance, is_banned, join_date, coins, refs_count)
    """
    conn = db()
    c = conn.cursor()
    where = "WHERE is_banned = 1" if banned_only else ""
    c.execute(f"SELECT COUNT(*) FROM users {where}")
    total = c.fetchone()[0]
    offset = page * per_page
    c.execute(
        f"SELECT u.user_id, u.username, u.full_name, u.balance, u.is_banned, u.join_date, "
        f"COALESCE(u.coins,0) AS coins, "
        f"(SELECT COUNT(*) FROM users x WHERE x.invited_by = u.user_id AND x.invite_credited = 1) AS refs "
        f"FROM users u {where} ORDER BY u.rowid DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    rows = c.fetchall()
    conn.close()
    return rows, total


def db_get_user_full(user_id):
    """اطلاعات کامل یک کاربر."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, full_name, balance, is_banned, join_date, "
        "invited_by, invite_credited, ref_configs_received, ref_configs_owed, "
        "COALESCE(coins,0) "
        "FROM users WHERE user_id = ?",
        (user_id,),
    )
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "user_id": r[0],
        "username": r[1],
        "full_name": r[2],
        "balance": r[3] or 0,
        "is_banned": bool(r[4]),
        "join_date": r[5],
        "invited_by": r[6],
        "invite_credited": r[7] or 0,
        "ref_configs_received": r[8] or 0,
        "ref_configs_owed": r[9] or 0,
        "coins": r[10] or 0,
    }


def db_add_to_pool(product_key: str, config_text: str, sub_link: str = "", pool_type: str = "cfg") -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO config_pool (product_key, config_text, sub_link, pool_type, created_at) VALUES (?, ?, ?, ?, ?)",
        (product_key, config_text, sub_link, pool_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def db_pop_from_pool(product_key: str):
    """یک کانفیگ آزاد از pool می‌گیرد. None اگر خالی باشد."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, config_text, sub_link, pool_type FROM config_pool WHERE product_key=? AND used=0 ORDER BY id LIMIT 1",
        (product_key,),
    )
    r = c.fetchone()
    if not r:
        conn.close()
        return None
    cid, cfg, sub, ptype = r
    c.execute("UPDATE config_pool SET used=1 WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return {"id": cid, "config": cfg, "sub_link": sub, "type": ptype}


def db_count_pool(product_key: str) -> int:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM config_pool WHERE product_key=? AND used=0", (product_key,))
    n = c.fetchone()[0]
    conn.close()
    return n


def db_pool_summary() -> dict:
    """خلاصه pool به تفکیک محصول."""
    conn = db()
    c = conn.cursor()
    c.execute("SELECT product_key, COUNT(*) FROM config_pool WHERE used=0 GROUP BY product_key")
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def db_get_buyers_page(page: int, per_page: int = 10):
    """کاربرانی که حداقل یک خرید تاییدشده دارند."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(DISTINCT user_id) FROM receipts WHERE status='approved'"
    )
    total = c.fetchone()[0]
    offset = page * per_page
    c.execute(
        "SELECT u.user_id, u.username, u.full_name, "
        "(SELECT COUNT(*) FROM receipts r WHERE r.user_id=u.user_id AND r.status='approved') AS buy_count "
        "FROM users u WHERE EXISTS (SELECT 1 FROM receipts r WHERE r.user_id=u.user_id AND r.status='approved') "
        "ORDER BY buy_count DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    rows = c.fetchall()
    conn.close()
    return rows, total


def db_get_user_purchase_stats(user_id: int) -> tuple:
    """آمار خریدهای کاربر: (تعداد خرید, مجموع پرداختی, مجموع گیگ)."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM receipts WHERE user_id = ? AND status='approved'",
        (user_id,),
    )
    r = c.fetchone()
    count, total_paid = (r[0] or 0), (r[1] or 0)
    c.execute(
        "SELECT product FROM receipts WHERE user_id = ? AND status='approved'",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    total_gb = 0.0
    for (product,) in rows:
        try:
            total_gb += float(product)
        except Exception:
            pass
    return count, total_paid, total_gb


def db_get_user_sub_links(user_id: int) -> list:
    """لینک‌های اشتراک تاییدشده یک کاربر."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, product, sub_link, config FROM receipts "
        "WHERE user_id = ? AND status='approved' AND (sub_link != '' OR config != '') ORDER BY id DESC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def db_add_balance(user_id: int, amount: int):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
        (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.execute("UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


# ==================== 🪙 سیستم سکه ====================
def db_get_coins(user_id: int) -> int:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(coins,0) FROM users WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return int(r[0]) if r else 0


def db_add_coins(user_id: int, amount: int) -> int:
    """امن: اگر کاربر وجود نداشته باشد ساخته می‌شود. کف صفر تضمین می‌شود.
    خروجی: موجودی جدید."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
        (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.execute(
        "UPDATE users SET coins = MAX(0, COALESCE(coins,0) + ?) WHERE user_id = ?",
        (amount, user_id),
    )
    c.execute("SELECT COALESCE(coins,0) FROM users WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.commit()
    conn.close()
    return int(r[0]) if r else 0


def db_set_coins(user_id: int, amount: int) -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
        (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.execute("UPDATE users SET coins = ? WHERE user_id = ?", (max(0, amount), user_id))
    conn.commit()
    conn.close()
    return max(0, amount)


def db_clear_all_coins() -> int:
    """صفر کردن همگانی سکه‌ها. خروجی: تعداد ردیف‌های متاثر."""
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET coins = 0 WHERE COALESCE(coins,0) > 0")
    n = c.rowcount
    conn.commit()
    conn.close()
    return n


def db_transfer_coins(from_uid: int, to_uid: int, amount: int) -> tuple[bool, str]:
    """انتقال سکه با کسر از مبدا. خروجی: (موفق؟, پیام)."""
    if amount <= 0:
        return False, "مبلغ نامعتبر است."
    if from_uid == to_uid:
        return False, "مبدا و مقصد نمی‌توانند یکی باشند."
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(coins,0) FROM users WHERE user_id = ?", (from_uid,))
    rf = c.fetchone()
    if not rf:
        conn.close(); return False, "کاربر مبدا یافت نشد."
    if int(rf[0]) < amount:
        conn.close(); return False, f"موجودی سکه کاربر مبدا کافی نیست (موجودی: {int(rf[0])})."
    # اگر مقصد نباشد، می‌سازیم
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
        (to_uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.execute("UPDATE users SET coins = COALESCE(coins,0) - ? WHERE user_id = ?", (amount, from_uid))
    c.execute("UPDATE users SET coins = COALESCE(coins,0) + ? WHERE user_id = ?", (amount, to_uid))
    conn.commit()
    conn.close()
    return True, "ok"


def db_create_free_config_receipt(user_id: int, cfg: str) -> int:
    """ثبت یک رسید تاییدشده برای کانفیگ رایگان تا در بخش «سرویس‌های من» نمایش داده شود."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO receipts (user_id, product, username, amount, photo_id, status, config, sub_link, created_at) "
        "VALUES (?, 'free', 'کانفیگ رایگان', 0, '', 'approved', ?, '', ?)",
        (user_id, cfg, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def db_count_referrals(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE invited_by = ?", (user_id,))
    n = c.fetchone()[0]
    conn.close()
    return n


def db_get_referral_discount(user_id):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT referral_discount_available, referral_discount_used FROM users WHERE user_id = ?",
        (user_id,),
    )
    r = c.fetchone()
    conn.close()
    if not r:
        return 0, 0
    return (r[0] or 0), (r[1] or 0)


def db_grant_referral_discount(user_id):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET referral_discount_available = COALESCE(referral_discount_available,0) + 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def db_consume_referral_discount(user_id):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET referral_discount_available = MAX(0, COALESCE(referral_discount_available,0) - 1), "
        "referral_discount_used = COALESCE(referral_discount_used,0) + 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ===== رفرال جدید: اعتبار + مخزن کانفیگ =====
def db_get_invited_by(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT invited_by, invite_credited FROM users WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r  # (invited_by, invite_credited) or None


def db_mark_invite_credited(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE users SET invite_credited = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def db_count_credited_referrals(inviter_id: int) -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM users WHERE invited_by = ? AND invite_credited = 1",
        (inviter_id,),
    )
    n = c.fetchone()[0]
    conn.close()
    return n


def db_add_referral_config(text: str) -> int:
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO referral_configs (config_text, created_at) VALUES (?, ?)",
        (text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def db_pop_referral_config(claim_user_id: int):
    """یک کانفیگ آزاد را برمی‌دارد و به نام کاربر می‌زند. None اگر مخزن خالی باشد."""
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id, config_text FROM referral_configs WHERE claimed_by IS NULL ORDER BY id LIMIT 1"
    )
    r = c.fetchone()
    if not r:
        conn.close(); return None
    cid, txt = r
    c.execute(
        "UPDATE referral_configs SET claimed_by = ?, claimed_at = ? WHERE id = ?",
        (claim_user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid),
    )
    conn.commit()
    conn.close()
    return txt


def db_count_unclaimed_configs() -> int:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referral_configs WHERE claimed_by IS NULL")
    n = c.fetchone()[0]
    conn.close()
    return n


def db_count_claimed_configs() -> int:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referral_configs WHERE claimed_by IS NOT NULL")
    n = c.fetchone()[0]
    conn.close()
    return n


def db_count_total_configs() -> int:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referral_configs")
    n = c.fetchone()[0]
    conn.close()
    return n


def db_inc_owed(user_id: int, by: int = 1):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET ref_configs_owed = COALESCE(ref_configs_owed,0) + ? WHERE user_id = ?",
        (by, user_id),
    )
    conn.commit()
    conn.close()


def db_dec_owed(user_id: int, by: int = 1):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET ref_configs_owed = MAX(0, COALESCE(ref_configs_owed,0) - ?) WHERE user_id = ?",
        (by, user_id),
    )
    conn.commit()
    conn.close()


def db_inc_received(user_id: int, by: int = 1):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET ref_configs_received = COALESCE(ref_configs_received,0) + ? WHERE user_id = ?",
        (by, user_id),
    )
    conn.commit()
    conn.close()


def db_get_user_ref_status(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(ref_configs_received,0), COALESCE(ref_configs_owed,0) FROM users WHERE user_id = ?",
        (user_id,),
    )
    r = c.fetchone()
    conn.close()
    if not r:
        return 0, 0
    return r[0], r[1]


def db_list_owed_users():
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, COALESCE(ref_configs_owed,0) FROM users WHERE COALESCE(ref_configs_owed,0) > 0 ORDER BY user_id"
    )
    rows = c.fetchall()
    conn.close()
    return rows


def db_save_discount(code, percent):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO discounts (code, percent, created_at) VALUES (?, ?, ?)",
        (code, percent, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def db_get_discount(code):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT percent FROM discounts WHERE code = ?", (code,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


# ==================== کمک‌ها ====================
def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


def is_admin(user_id: int) -> bool:
    """ادمین سوپر یا ادمین جانبی."""
    return is_super_admin(user_id) or (find_sub_admin(user_id) is not None)


def has_perm(user_id: int, perm: str) -> bool:
    """ادمین سوپر همه مجوزها را دارد. ادمین جانبی فقط مجوزهای فعالش."""
    if is_super_admin(user_id):
        return True
    sa = find_sub_admin(user_id)
    if not sa:
        return False
    return bool((sa.get("perms") or {}).get(perm, False))


def fmt_price(amount: int) -> str:
    return f"{amount:,} تومان"


# ==================== کیبوردها ====================
def kb_main(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            btn(BUTTON_LABELS["main_buy"], "main_buy", callback_data="buy_menu"),
            btn(BUTTON_LABELS["main_freeconf"], "main_freeconf", callback_data="freeconf"),
        ],
        [
            btn(BUTTON_LABELS["main_my"], "main_my", callback_data="my_services"),
            btn(BUTTON_LABELS["main_account"], "main_account", callback_data="account"),
        ],
        [
            btn(BUTTON_LABELS["main_invite"], "main_invite", callback_data="invite"),
            btn(BUTTON_LABELS["main_support"], "main_support", callback_data="support"),
        ],
    ]
    if is_admin(user_id):
        rows.append([btn(BUTTON_LABELS["main_admin"], "main_admin", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_back(target: str = "back_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn(BUTTON_LABELS["back"], "back", callback_data=target)]]
    )


def kb_buy_menu() -> InlineKeyboardMarkup:
    rows = []
    for p in get_products():
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{p['label']} — {fmt_price(p['price'])}",
                    callback_data=f"prod_{p['key']}",
                )
            ]
        )
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_invoice(product: str) -> InlineKeyboardMarkup:
    rows = [
        [btn(BUTTON_LABELS["pay_discount"], "pay_discount", callback_data=f"discount_{product}")],
        [btn(BUTTON_LABELS["pay_card"], "pay_card", callback_data=f"paycard_{product}")],
        [btn(BUTTON_LABELS["back"], "back", callback_data="buy_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_join_required() -> InlineKeyboardMarkup:
    rows = []
    for ch in SETTINGS["channels"]:
        url_ch = ch.lstrip("@")
        rows.append(
            [InlineKeyboardButton(text=f"📢 عضویت در {ch}", url=f"https://t.me/{url_ch}")]
        )
    rows.append([InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin(user_id: int | None = None) -> InlineKeyboardMarkup:
    sales_on = SETTINGS.get("sales_enabled", True)
    bot_on = SETTINGS.get("bot_enabled", True)
    sales_label = "🟢 فروش: روشن (برای خاموش کردن بزنید)" if sales_on else "🔴 فروش: خاموش (برای روشن کردن بزنید)"
    bot_label = "🟢 ربات: روشن (برای خاموش کردن بزنید)" if bot_on else "🔴 ربات: خاموش (برای روشن کردن بزنید)"

    def can(p: str) -> bool:
        # اگر شناسه کاربر داده نشده باشد، همه را نشان بده (سازگاری عقب‌رو)
        if user_id is None:
            return True
        return has_perm(user_id, p)

    rows = []
    if can("stats"):
        rows.append([InlineKeyboardButton(text="📊 آمار ربات", callback_data="adm_stats")])
    if can("toggle_sales"):
        rows.append([InlineKeyboardButton(text=sales_label, callback_data="adm_toggle_sales")])
    if can("toggle_bot"):
        rows.append([InlineKeyboardButton(text=bot_label, callback_data="adm_toggle_bot")])
    if can("broadcast"):
        rows.append([InlineKeyboardButton(text="📢 پیام همگانی", callback_data="adm_broadcast")])
    if can("approve_receipts"):
        rows.append([InlineKeyboardButton(text="✅ تایید همه رسیدها", callback_data="adm_approve_all")])
    if can("users"):
        rows.append([InlineKeyboardButton(text="👥 لیست کاربران", callback_data="adm_users_0")])
    if can("ban"):
        rows.append([
            InlineKeyboardButton(text="🚫 بن کردن کاربر", callback_data="adm_ban"),
            InlineKeyboardButton(text="🔓 آنبن کردن کاربر", callback_data="adm_unban"),
        ])
        rows.append([InlineKeyboardButton(text="📋 لیست کاربران بن‌شده", callback_data="adm_banlist_0")])
    if can("discount"):
        rows.append([InlineKeyboardButton(text="🎁 ساخت کد تخفیف", callback_data="adm_discount")])
    if can("products") or can("prices"):
        rows.append([InlineKeyboardButton(text="💵 مدیریت محصولات و قیمت‌ها", callback_data="adm_prices")])
    if can("approve_receipts"):
        rows.append([InlineKeyboardButton(text="📦 مدیریت کانفیگ‌ها (pool)", callback_data="adm_pool")])
    if can("giftcfg"):
        rows.append([InlineKeyboardButton(text="🎁 مدیریت کانفیگ‌های هدیه دعوت", callback_data="adm_giftcfg")])
    if can("coins"):
        rows.append([InlineKeyboardButton(text="🪙 مدیریت سکه‌ها", callback_data="adm_coins")])
    if can("card"):
        rows.append([InlineKeyboardButton(text="💳 تنظیم شماره کارت", callback_data="adm_card")])
    if can("support_id"):
        rows.append([InlineKeyboardButton(text="🛟 تنظیم آیدی پشتیبانی", callback_data="adm_support")])
    if can("channels"):
        rows.append([InlineKeyboardButton(text="📡 تنظیم چنل جوین اجباری", callback_data="adm_channels")])
    if can("texts"):
        rows.append([InlineKeyboardButton(text="✏️ مدیریت متن‌ها", callback_data="adm_texts")])
    if can("buttons"):
        rows.append([InlineKeyboardButton(text="🔘 مدیریت برچسب دکمه‌ها", callback_data="adm_buttons_0")])
    if can("colors"):
        rows.append([InlineKeyboardButton(text="🎨 تنظیم رنگ دکمه‌ها", callback_data="adm_colors")])
    # مدیریت ادمین‌های جانبی فقط برای ادمین سوپر
    if user_id is None or is_super_admin(user_id):
        rows.append([InlineKeyboardButton(text="👤 مدیریت ادمین‌ها", callback_data="adm_subadmins")])
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin_broadcast() -> InlineKeyboardMarkup:
    """منوی پیام همگانی با گزینه‌های پین/بدون پین/حذف پین."""
    rows = [
        [InlineKeyboardButton(text="📌 پیام همگانی با پین", callback_data="adm_bc_pin")],
        [InlineKeyboardButton(text="📨 پیام همگانی بدون پین", callback_data="adm_bc_nopin")],
        [InlineKeyboardButton(text="🗑 حذف پین‌های قبلی", callback_data="adm_bc_unpin")],
        [btn(BUTTON_LABELS["back"], "back", callback_data="admin_panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin_prices() -> InlineKeyboardMarkup:
    """مدیریت محصولات: تغییر قیمت + حذف + افزودن محصول جدید."""
    rows = []
    for p in get_products():
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {p['label']} — {fmt_price(p['price'])}",
                    callback_data=f"setprice_{p['key']}",
                ),
                InlineKeyboardButton(
                    text="🗑 حذف",
                    callback_data=f"delprod_{p['key']}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ افزودن محصول جدید (حجم + قیمت)", callback_data="addprod")])
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin_channels() -> InlineKeyboardMarkup:
    rows = []
    for ch in SETTINGS["channels"]:
        rows.append(
            [
                InlineKeyboardButton(text=f"📢 {ch}", callback_data="noop"),
                InlineKeyboardButton(text="🗑 حذف", callback_data=f"delch_{ch}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ افزودن چنل", callback_data="addch")])
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_admin_colors() -> InlineKeyboardMarkup:
    rows = []
    for key, label in BUTTON_LABELS.items():
        if key == "back":
            continue
        cur = SETTINGS["colors"].get(key, "default")
        emoji = {"primary": "🔵", "success": "🟢", "danger": "🔴", "default": "⚪"}.get(cur, "⚪")
        rows.append(
            [InlineKeyboardButton(text=f"{emoji} {label}", callback_data=f"color_{key}")]
        )
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_color_choice(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔵 آبی", callback_data=f"setcolor_{key}_primary"),
                InlineKeyboardButton(text="🟢 سبز", callback_data=f"setcolor_{key}_success"),
                InlineKeyboardButton(text="🔴 قرمز", callback_data=f"setcolor_{key}_danger"),
            ],
            [InlineKeyboardButton(text="⚪ معمولی (مات)", callback_data=f"setcolor_{key}_default")],
            [btn(BUTTON_LABELS["back"], "back", callback_data="adm_colors")],
        ]
    )


# ==================== متن خوش‌آمد ====================
def welcome_text() -> str:
    return get_text("welcome")


# ==================== States ====================
class BuyStates(StatesGroup):
    waiting_username = State()
    waiting_receipt = State()
    waiting_discount_code = State()


class AdminStates(StatesGroup):
    ban_user = State()
    unban_user = State()
    discount_input = State()
    set_price = State()
    set_card_number = State()
    set_card_holder = State()
    set_support = State()
    add_channel = State()
    waiting_config = State()
    waiting_sub = State()
    broadcast_message = State()
    broadcast_message_pin = State()
    add_product_label = State()
    add_product_price = State()
    gift_count = State()
    gift_text = State()
    # ادمین جانبی
    add_sub_admin = State()
    # ویرایش متن‌ها
    edit_text = State()
    # ویرایش برچسب دکمه‌ها
    edit_button_label = State()
    # پیام به کاربر
    msg_user_text = State()
    # افزودن/کسر اعتبار
    addbal_amount = State()
    subbal_amount = State()
    # 🪙 سکه
    set_freeconf_coins = State()
    transfer_coins_from = State()
    transfer_coins_to = State()
    transfer_coins_amount = State()
    addcoins_amount = State()
    subcoins_amount = State()
    confirm_clear_coins = State()
    # pool کانفیگ (ذخیره پیش‌فرض برای هر محصول)
    pool_cfg = State()
    pool_sub = State()
    pool_bulk = State()
    # تایید رسید + ارسال کانفیگ
    approve_send_cfg = State()
    approve_send_sub = State()
    # /myvip - ارسال ساب به کاربر
    myvip_send_sub = State()


# ==================== Bot/Dispatcher ====================
dp = Dispatcher(storage=MemoryStorage())
bot: Bot | None = None


# ===== Middleware: خاموش بودن ربات =====
class BotEnabledMiddleware(BaseMiddleware):
    """وقتی ربات خاموشه، به همه‌ی کاربران غیرادمین پیام بروزرسانی می‌دهد."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # اگر ربات روشن است یا کاربر ادمین است، اجازه عبور بده
        user = data.get("event_from_user")
        if SETTINGS.get("bot_enabled", True) or (user and is_admin(user.id)):
            return await handler(event, data)
        # ربات خاموش، کاربر معمولی → پیام بروزرسانی
        text = get_text("bot_off_alert")
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except Exception as e:
            logger.warning(f"bot-disabled notice failed: {e}")
        return None


dp.message.middleware(BotEnabledMiddleware())
dp.callback_query.middleware(BotEnabledMiddleware())


# ===== بررسی عضویت =====
async def check_membership(user_id: int) -> bool:
    # ادمین‌ها از چک عضویت معاف هستند
    if is_admin(user_id):
        return True
    if not bot:
        return True
    for ch in SETTINGS["channels"]:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status in ("left", "kicked"):
                return False
        except Exception as e:
            logger.warning(f"membership check failed for {ch}: {e}")
            return False
    return True


# ==================== رفرال: اعتبار + تحویل کانفیگ هدیه ====================
async def _send_gift_config(user_id: int, config_text: str):
    """ارسال یک کانفیگ هدیه به کاربر."""
    if not bot:
        return
    try:
        await bot.send_message(
            user_id,
            "🎁 کانفیگ هدیه‌ی رفرال شما:\n\n"
            f"<code>{config_text}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"send gift config to {user_id} failed: {e}")


async def _award_one_gift(inviter_id: int) -> bool:
    """تلاش برای تحویل یک کانفیگ آزاد به دعوت‌کننده.
    اگر مخزن خالی باشد به جای آن «بدهی» ثبت می‌شود."""
    cfg = db_pop_referral_config(inviter_id)
    if cfg:
        await _send_gift_config(inviter_id, cfg)
        db_inc_received(inviter_id, 1)
        return True
    db_inc_owed(inviter_id, 1)
    if bot:
        try:
            await bot.send_message(
                inviter_id,
                "🎁 با ۵ رفرال موفق، یک کانفیگ هدیه به شما تعلق گرفت!\n"
                "ولی فعلاً موجودی کانفیگ نداریم؛ به‌محض شارژ شدن، خودکار برایتان ارسال می‌شود.",
            )
        except Exception:
            pass
    return False


async def _credit_referral_if_eligible(new_user_id: int, new_user_name: str):
    """بعد از احراز عضویت در چنل، اعتبار رفرال را به دعوت‌کننده می‌دهد.
    🪙 هر دعوت موفق = N سکه (N از تنظیمات coins_per_referral، پیش‌فرض ۱).
    کاربر می‌تواند با خرج سکه از منوی «کانفیگ رایگان» کانفیگ بگیرد."""
    info = db_get_invited_by(new_user_id)
    if not info:
        return
    inviter, credited = info
    if not inviter or credited:
        return
    db_mark_invite_credited(new_user_id)
    coins_per_ref = int(SETTINGS.get("coins_per_referral", 1) or 1)
    new_balance = db_add_coins(inviter, coins_per_ref)
    total = db_count_credited_referrals(inviter)
    free_cost = int(SETTINGS.get("free_config_coins", 5) or 5)
    # اطلاع لحظه‌ای به دعوت‌کننده
    if bot:
        try:
            extra = ""
            if new_balance >= free_cost:
                extra = (
                    f"\n\n🎁 شما می‌توانید با {fa_digits(free_cost)} سکه یک کانفیگ رایگان دریافت کنید!\n"
                    f"از منوی اصلی ⇐ «کانفیگ رایگان»"
                )
            await bot.send_message(
                inviter,
                "🎉 یک رفرال جدید به ربات اضافه شد!\n"
                f"👤 نام: {new_user_name}\n"
                f"🪙 +{fa_digits(coins_per_ref)} سکه برای شما\n"
                f"💰 موجودی سکه شما: {fa_digits(new_balance)}\n"
                f"👥 جمع رفرال‌های شما: {fa_digits(total)}"
                + extra,
            )
        except Exception as e:
            logger.warning(f"notify inviter {inviter} failed: {e}")


async def _distribute_owed_configs() -> int:
    """تا زمانی که هم کاربر بدهکار داریم و هم کانفیگ آزاد، توزیع کن.
    تعداد کانفیگ توزیع‌شده را برمی‌گرداند."""
    delivered = 0
    while True:
        owed_users = db_list_owed_users()
        if not owed_users:
            break
        if db_count_unclaimed_configs() <= 0:
            break
        progressed = False
        for uid, owed in owed_users:
            if owed <= 0:
                continue
            cfg = db_pop_referral_config(uid)
            if not cfg:
                break
            await _send_gift_config(uid, cfg)
            db_dec_owed(uid, 1)
            db_inc_received(uid, 1)
            delivered += 1
            progressed = True
        if not progressed:
            break
    return delivered


# ==================== /start ====================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    u = message.from_user
    args = message.text.split()
    invited_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            invited_by = int(args[1].split("_")[1])
            if invited_by == u.id:
                invited_by = None
        except Exception:
            pass
    db_add_user(u.id, u.username, u.full_name, invited_by)

    if db_is_banned(u.id) and not is_admin(u.id):
        await message.answer(get_text("banned"))
        return

    if not await check_membership(u.id):
        await message.answer(
            get_text("join_required"),
            reply_markup=kb_join_required(),
        )
        return

    # عضو چنل است → اگر دعوت‌شده و هنوز اعتبار نگرفته، اعتبار بده
    await _credit_referral_if_eligible(u.id, u.full_name or (u.username or "بدون نام"))

    await message.answer(welcome_text(), reply_markup=kb_main(u.id), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "check_join")
async def cb_check_join(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not await check_membership(call.from_user.id):
        await call.answer(get_text("not_joined"), show_alert=True)
        return
    # حالا که عضو چنل است، اعتبار رفرال را اعمال کن
    u = call.from_user
    await _credit_referral_if_eligible(u.id, u.full_name or (u.username or "بدون نام"))
    await call.message.edit_text(welcome_text(), reply_markup=kb_main(call.from_user.id), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_text(welcome_text(), reply_markup=kb_main(call.from_user.id), parse_mode=ParseMode.HTML)
    except Exception:
        await call.message.answer(welcome_text(), reply_markup=kb_main(call.from_user.id), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ==================== خرید ====================
@dp.callback_query(F.data == "buy_menu")
async def cb_buy_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    # چک خاموش بودن فروش (ادمین مستثناست)
    if not SETTINGS.get("sales_enabled", True) and not is_admin(call.from_user.id):
        await call.message.edit_text(
            get_text("sales_off"),
            reply_markup=kb_back("back_main"),
        )
        return
    txt = (
        "🛒 سرویس‌های فروشگاه ما\n"
        "با تضمین کیفیت در بدترین شرایط\n\n"
        "یکی از پکیج‌های زیر را انتخاب کنید 👇"
    )
    await call.message.edit_text(txt, reply_markup=kb_buy_menu())


@dp.callback_query(F.data.startswith("prod_"))
async def cb_select_product(call: CallbackQuery, state: FSMContext):
    await call.answer()
    product = call.data.split("_", 1)[1]
    if not get_product(product):
        return
    if not SETTINGS.get("sales_enabled", True) and not is_admin(call.from_user.id):
        await call.answer(get_text("sales_off").split("\n")[0], show_alert=True)
        return
    await state.update_data(product=product, discount_percent=0)
    await state.set_state(BuyStates.waiting_username)
    await call.message.edit_text(
        f"🛒 سرویس {get_product_label(product)} انتخاب شد.\n\n"
        "لطفا یک نام کاربری با حروف لاتین به طول حداکثر ۲۰ کاراکتر وارد نمایید 👇",
        reply_markup=kb_back("buy_menu"),
    )


@dp.message(BuyStates.waiting_username)
async def msg_get_username(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", text):
        await message.answer("❌ نام کاربری نامعتبر است. فقط حروف لاتین/عدد، ۳ تا ۲۰ کاراکتر.")
        return
    data = await state.get_data()
    product = data["product"]
    base = get_product_price(product)
    discount = data.get("discount_percent", 0)
    final = int(base * (100 - discount) / 100)
    await state.update_data(username=text, base_price=base, final_price=final)

    invoice = (
        f"🧾 پیش‌فاکتور\n\n"
        f"👤 نام کاربری: <code>{text}</code>\n"
        f"📦 سرویس: {get_product_label(product)}\n"
        f"📅 مدت اعتبار: نامحدود\n"
        f"💾 حجم: {get_product_label(product)}\n\n"
    )
    if discount:
        invoice += f"💸 تخفیف: {discount}٪\n"
        invoice += f"💵 قیمت اصلی: {fmt_price(base)}\n"
    invoice += f"💰 مبلغ قابل پرداخت: <b>{fmt_price(final)}</b>\n\n"
    invoice += "سفارش شما آماده پرداخت است."

    await message.answer(invoice, reply_markup=kb_invoice(product), parse_mode=ParseMode.HTML)


# ===== کد تخفیف =====
@dp.callback_query(F.data.startswith("discount_"))
async def cb_apply_discount(call: CallbackQuery, state: FSMContext):
    await call.answer()
    product = call.data.split("_", 1)[1]
    await state.update_data(product=product)
    await state.set_state(BuyStates.waiting_discount_code)
    await call.message.answer("🎁 لطفاً کد تخفیف خود را ارسال کنید 👇")


@dp.message(BuyStates.waiting_discount_code)
async def msg_discount_code(message: Message, state: FSMContext):
    code = (message.text or "").strip()
    percent = db_get_discount(code)
    if percent is None:
        await message.answer("❌ کد تخفیف معتبر نیست.")
        return
    data = await state.get_data()
    product = data.get("product")
    if not product:
        await message.answer("❌ خطا. /start را بزنید.")
        await state.clear()
        return
    base = get_product_price(product)
    final = int(base * (100 - percent) / 100)
    await state.update_data(discount_percent=percent, base_price=base, final_price=final)
    # برمی‌گردیم به مرحله دریافت یوزرنیم اگر هنوز ندارد
    if not data.get("username"):
        await state.set_state(BuyStates.waiting_username)
        await message.answer(
            f"✅ کد تخفیف {percent}٪ اعمال شد.\n\n"
            f"حالا یک نام کاربری با حروف لاتین (۳ تا ۲۰ کاراکتر) ارسال کنید 👇"
        )
    else:
        username = data["username"]
        invoice = (
            f"🧾 پیش‌فاکتور\n\n"
            f"👤 نام کاربری: <code>{username}</code>\n"
            f"📦 سرویس: {get_product_label(product)}\n"
            f"📅 مدت اعتبار: نامحدود\n"
            f"💾 حجم: {get_product_label(product)}\n\n"
            f"💸 تخفیف: {percent}٪\n"
            f"💵 قیمت اصلی: {fmt_price(base)}\n"
            f"💰 مبلغ قابل پرداخت: <b>{fmt_price(final)}</b>"
        )
        await message.answer(invoice, reply_markup=kb_invoice(product), parse_mode=ParseMode.HTML)


# ===== کارت به کارت =====
@dp.callback_query(F.data.startswith("paycard_"))
async def cb_pay_card(call: CallbackQuery, state: FSMContext):
    await call.answer()
    product = call.data.split("_", 1)[1]
    data = await state.get_data()
    if not data.get("username"):
        await call.answer("ابتدا نام کاربری را وارد کنید.", show_alert=True)
        return
    final = data.get("final_price") or get_product_price(product)
    card = SETTINGS.get("card_number") or "تنظیم نشده"
    holder = SETTINGS.get("card_holder") or ""
    holder_line = f"به نام: {holder}" if holder else ""
    txt = (
        f"برای افزایش موجودی، مبلغ {fmt_price(final)} را به شماره‌ی حساب زیر واریز کنید 👇🏻\n\n"
        f"====================\n\n"
        f"<code>{card}</code>\n"
        f"{holder_line}\n\n"
        f"====================\n\n"
        f"🟢این تراکنش به مدت یک ساعت اعتبار دارد پس از آن امکان پرداخت این تراکنش امکان ندارد.\n"
        f"‼️مسئولیت واریز اشتباهی با شماست.\n"
        f"🔝بعد از پرداخت دکمه (ادامه مراحل) رو بزنید و عکس رسید خود را ارسال کنید تا موجودیتون افزایش داده بشه."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 ادامه مراحل (ارسال رسید)", callback_data=f"sendreceipt_{product}")],
        [btn(BUTTON_LABELS["back"], "back", callback_data="back_main")],
    ])
    await call.message.answer(txt, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.callback_query(F.data.startswith("sendreceipt_"))
async def cb_send_receipt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(BuyStates.waiting_receipt)
    await call.message.answer("📸 لطفاً عکس رسید خود را همینجا ارسال کنید 👇")


@dp.message(BuyStates.waiting_receipt, F.photo)
async def msg_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    product = data.get("product")
    username = data.get("username")
    final = data.get("final_price")
    if not (product and username and final):
        await message.answer("❌ خطا. لطفاً از ابتدا اقدام کنید: /start")
        await state.clear()
        return
    photo_id = message.photo[-1].file_id
    rid = db_create_receipt(message.from_user.id, product, username, final, photo_id)
    await message.answer(
        "✅ اوکی! رسید شما دریافت شد.\n"
        "💳 پرداخت شما در سریع‌ترین زمان ممکن تایید می‌شود."
    )
    # ارسال به ادمین‌ها با چهار دکمه
    caption = (
        f"🧾 رسید جدید #{rid}\n"
        f"👤 کاربر: {message.from_user.full_name}\n"
        f"🆔 آیدی: <code>{message.from_user.id}</code>\n"
        f"📦 سرویس: {get_product_label(product)}\n"
        f"🧾 یوزرنیم: <code>{username}</code>\n"
        f"💰 مبلغ: {fmt_price(final)}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تایید و ارسال کانفیگ", callback_data=f"adm_approve_{rid}"),
            InlineKeyboardButton(text="❌ رد رسید", callback_data=f"adm_reject_{rid}"),
        ],
    ])
    for aid in SUPER_ADMIN_IDS:
        try:
            await bot.send_photo(aid, photo_id, caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"notify admin {aid} failed: {e}")
    await state.clear()


@dp.message(BuyStates.waiting_receipt)
async def msg_receipt_wrong(message: Message):
    await message.answer("📸 لطفاً عکس رسید را به صورت تصویر ارسال کنید.")


# ==================== سرویس‌های من / حساب / دعوت / پشتیبانی ====================
@dp.callback_query(F.data == "my_services")
async def cb_my_services(call: CallbackQuery):
    await call.answer()
    rows = db_get_user_delivered_services(call.from_user.id)
    if not rows:
        await call.message.edit_text(
            "📦 شما هنوز سرویس فعالی ندارید.\n(فقط سرویس‌های تاییدشده اینجا نمایش داده می‌شوند.)",
            reply_markup=kb_back("back_main"),
        )
        return
    btns = []
    for r in rows[:20]:
        rid, product, username, config, sub_link = r
        btns.append([InlineKeyboardButton(
            text=f"👤 {username}  |  {get_product_label(product)}",
            callback_data=f"svc_{rid}",
        )])
    btns.append([btn(BUTTON_LABELS["back"], "back", callback_data="back_main")])
    await call.message.edit_text("📦 سرویس‌های شما:\nروی نام کاربری بزنید 👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))


@dp.callback_query(F.data.startswith("svc_"))
async def cb_view_service(call: CallbackQuery):
    await call.answer()
    rid = int(call.data.split("_", 1)[1])
    r = db_get_receipt(rid)
    if not r or r[1] != call.from_user.id:
        await call.answer("یافت نشد", show_alert=True); return
    _, _, product, username, amount, _, status, config, sub_link, created = r
    if product == "free":
        txt = (
            f"🎁 کانفیگ رایگان شما\n\n"
            f"💎 نوع: کانفیگ هدیه (با سکه)\n"
            f"📅 مدت اعتبار: نامحدود"
        )
    else:
        txt = (
            f"📦 سرویس شما\n\n"
            f"👤 نام کاربری: <code>{username}</code>\n"
            f"💾 حجم: {product} گیگابایت\n"
            f"📅 مدت اعتبار: نامحدود\n"
            f"💰 مبلغ پرداختی: {fmt_price(amount)}"
        )
    rows = []
    if sub_link:
        rows.append([InlineKeyboardButton(text="🔗 دریافت لینک ساب", callback_data=f"getsub_{rid}")])
    if config:
        rows.append([InlineKeyboardButton(text="📄 دریافت لینک بدون ساب", callback_data=f"getcfg_{rid}")])
    if not rows:
        txt += "\n\n⏳ کانفیگ هنوز برای شما ارسال نشده. لطفاً صبور باشید."
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="my_services")])
    await call.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("getsub_"))
async def cb_get_sub(call: CallbackQuery):
    rid = int(call.data.split("_", 1)[1])
    r = db_get_receipt(rid)
    if not r or r[1] != call.from_user.id:
        await call.answer("یافت نشد", show_alert=True); return
    sub = r[8]
    if not sub:
        await call.answer("لینک ساب موجود نیست.", show_alert=True); return
    await call.answer()
    await call.message.answer(f"🔗 لینک ساب شما:\n\n<code>{sub}</code>", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("getcfg_"))
async def cb_get_cfg(call: CallbackQuery):
    rid = int(call.data.split("_", 1)[1])
    r = db_get_receipt(rid)
    if not r or r[1] != call.from_user.id:
        await call.answer("یافت نشد", show_alert=True); return
    cfg = r[7]
    if not cfg:
        await call.answer("کانفیگ موجود نیست.", show_alert=True); return
    await call.answer()
    await call.message.answer(f"📄 کانفیگ شما:\n\n<code>{cfg}</code>", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "account")
async def cb_account(call: CallbackQuery):
    await call.answer()
    u = call.from_user
    info = db_get_user_info(u.id)
    # تبدیل تاریخ ورود
    if info["join_date"]:
        try:
            jd = datetime.strptime(info["join_date"], "%Y-%m-%d %H:%M:%S")
            join_str = jalali_date(jd)
        except Exception:
            join_str = "—"
    else:
        join_str = "—"
    now_str = jalali_datetime()
    txt = (
        "👨🏻‍💻اطلاعات حساب کاربری شما:\n\n"
        f"💰 موجودی: {fa_digits('{:,}'.format(info['balance']))} تومان\n\n"
        f"🕴🏻آیدی عددی : {fa_digits(u.id)}\n"
        f"🛍 تعداد سرویس ها: {fa_digits(info['services'])}\n"
        f"🗓 تاریخ ورود به بات: {join_str}\n\n"
        f"📆 {now_str}"
    )
    await call.message.edit_text(txt, reply_markup=kb_back("back_main"))


@dp.callback_query(F.data == "invite")
async def cb_invite(call: CallbackQuery):
    await call.answer()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    refs = db_count_credited_referrals(call.from_user.id)
    received, owed = db_get_user_ref_status(call.from_user.id)
    coins = db_get_coins(call.from_user.id)
    coins_per_ref = int(SETTINGS.get("coins_per_referral", 1) or 1)
    free_cost = int(SETTINGS.get("free_config_coins", 5) or 5)
    remain_coins = max(0, free_cost - coins)
    txt = (
        "🤝 دعوت دوستان\n\n"
        f"🪙 با هر دعوت موفق <b>{fa_digits(coins_per_ref)} سکه</b> دریافت می‌کنید.\n"
        f"🎁 با <b>{fa_digits(free_cost)} سکه</b> می‌توانید یک <b>کانفیگ رایگان</b> از منوی اصلی دریافت کنید.\n\n"
        "⚠️ توجه: اگر کاربری استارت بزند ولی عضو کانال نشود، رفرال شما حساب نمی‌شود.\n\n"
        f"👥 رفرال‌های تأییدشده: {fa_digits(refs)}\n"
        f"🪙 موجودی سکه شما: <b>{fa_digits(coins)}</b>\n"
        f"⏳ تا کانفیگ بعدی: {fa_digits(remain_coins)} سکه دیگر\n"
        f"🎁 کانفیگ‌های دریافت‌شده: {fa_digits(received)}\n"
        f"📦 کانفیگ‌های در انتظار تحویل: {fa_digits(owed)}\n\n"
        f"🔗 لینک دعوت شما:\n<code>{link}</code>"
    )
    await call.message.edit_text(txt, reply_markup=kb_back("back_main"), parse_mode=ParseMode.HTML)


# ==================== 🎁 کانفیگ رایگان (با سکه) ====================
@dp.callback_query(F.data == "freeconf")
async def cb_freeconf(call: CallbackQuery):
    await call.answer()
    coins_needed = int(SETTINGS.get("free_config_coins", 5) or 5)
    user_coins = db_get_coins(call.from_user.id)
    in_pool = db_count_unclaimed_configs()
    txt = (
        "🎁 <b>کانفیگ رایگان</b>\n\n"
        f"🪙 برای دریافت کانفیگ رایگان به <b>{fa_digits(coins_needed)} سکه</b> نیاز دارید.\n"
        f"💰 موجودی سکه شما: <b>{fa_digits(user_coins)}</b>\n\n"
        "💡 با هر دعوت موفق دوستان به ربات، یک سکه دریافت می‌کنید."
    )
    rows = []
    if user_coins >= coins_needed:
        if in_pool > 0:
            rows.append([InlineKeyboardButton(
                text=f"✅ دریافت کانفیگ رایگان ({fa_digits(coins_needed)} سکه)",
                callback_data="freeconf_claim",
            )])
        else:
            txt += "\n\n⚠️ در حال حاضر کانفیگی در مخزن موجود نیست. لطفاً بعداً مراجعه کنید."
    else:
        remaining = coins_needed - user_coins
        txt += f"\n\n⏳ <b>{fa_digits(remaining)} سکه</b> دیگر نیاز دارید. دوستان خود را دعوت کنید!"
        rows.append([InlineKeyboardButton(text="🤝 دعوت دوستان", callback_data="invite")])
    rows.append([btn(BUTTON_LABELS["back"], "back", callback_data="back_main")])
    await call.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "freeconf_claim")
async def cb_freeconf_claim(call: CallbackQuery):
    coins_needed = int(SETTINGS.get("free_config_coins", 5) or 5)
    user_coins = db_get_coins(call.from_user.id)
    if user_coins < coins_needed:
        await call.answer("❌ موجودی سکه شما کافی نیست.", show_alert=True)
        return
    cfg = db_pop_referral_config(call.from_user.id)
    if not cfg:
        await call.answer("⚠️ مخزن کانفیگ خالی است. بعداً مراجعه کنید.", show_alert=True)
        return
    # کسر سکه + ثبت در سرویس‌های من
    new_balance = db_add_coins(call.from_user.id, -coins_needed)
    db_inc_received(call.from_user.id, 1)
    rid = db_create_free_config_receipt(call.from_user.id, cfg)
    await call.answer("✅ کانفیگ رایگان شما آماده شد!", show_alert=False)
    try:
        await call.message.edit_text(
            f"🎁 <b>کانفیگ رایگان شما</b>\n\n"
            f"<code>{cfg}</code>\n\n"
            f"🪙 سکه‌های کسرشده: <b>{fa_digits(coins_needed)}</b>\n"
            f"💰 موجودی سکه باقی‌مانده: <b>{fa_digits(new_balance)}</b>\n\n"
            "✅ این کانفیگ به بخش «📦 سرویس‌های من» اضافه شد.",
            reply_markup=kb_back("back_main"),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await call.message.answer(
            f"🎁 کانفیگ رایگان شما:\n\n<code>{cfg}</code>\n\n"
            f"💰 موجودی سکه باقی‌مانده: {fa_digits(new_balance)}",
            parse_mode=ParseMode.HTML,
        )


@dp.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery):
    await call.answer()
    sup = SETTINGS.get("support_id") or DEFAULT_SUPPORT_ID
    txt = f"📞 ارتباط با پشتیبانی\n\nآیدی پشتیبانی: {sup}"
    await call.message.edit_text(txt, reply_markup=kb_back("back_main"))


# ==================== پنل مدیریت ====================
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    if not is_admin(call.from_user.id):
        await call.answer("❌ دسترسی ندارید.", show_alert=True)
        return
    await call.message.edit_text("👑 پنل مدیریت", reply_markup=kb_admin(call.from_user.id))


# آمار
@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    s = db_stats()
    total_cfg = db_count_total_configs()
    claimed_cfg = db_count_claimed_configs()
    unclaimed_cfg = db_count_unclaimed_configs()
    txt = (
        "📊 آمار ربات\n\n"
        f"👥 کل کاربران: {fa_digits(s['total_users'])}\n"
        f"🆕 کاربران امروز: {fa_digits(s['new_today'])}\n"
        f"⛔ کاربران بن: {fa_digits(s['banned'])}\n\n"
        f"🧾 کل رسیدها: {fa_digits(s['total_receipts'])}\n"
        f"✅ تاییدشده: {fa_digits(s['approved'])}\n"
        f"⏳ در انتظار: {fa_digits(s['pending'])}\n"
        f"💰 مجموع فروش تاییدشده: {fmt_price(s['revenue'])}\n\n"
        f"🎁 کدهای تخفیف فعال: {fa_digits(s['discounts'])}\n\n"
        "🎁 کانفیگ‌های هدیه دعوت:\n"
        f"   • کل ثبت‌شده: {fa_digits(total_cfg)}\n"
        f"   • گرفته‌شده توسط کاربران: {fa_digits(claimed_cfg)}\n"
        f"   • نگرفته‌شده (مانده در مخزن): {fa_digits(unclaimed_cfg)}"
    )
    await call.message.edit_text(txt, reply_markup=kb_back("admin_panel"))


# تایید همه رسیدها
@dp.callback_query(F.data == "adm_approve_all")
async def cb_adm_approve_all(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pending = db_get_pending_receipts()
    count = 0
    for rid, uid, product, username, amount in pending:
        db_approve_receipt(rid)
        count += 1
        try:
            await bot.send_message(
                uid,
                f"✅ رسید #{rid} شما تایید شد!\n"
                f"📦 سرویس: {get_product_label(product)}\n"
                f"👤 یوزرنیم: <code>{username}</code>\n"
                f"💰 مبلغ: {fmt_price(amount)}\n\n"
                f"به‌زودی سرویس برای شما ارسال می‌شود.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    await call.message.edit_text(
        f"✅ {count} رسید تایید شد و به کاربران اطلاع داده شد.",
        reply_markup=kb_back("admin_panel"),
    )


async def _grant_referral_if_first_purchase(buyer_id: int):
    """اولین خرید تاییدشده‌ی دعوت‌شده ⇒ یک تخفیف ۱۰٪ به دعوت‌کننده."""
    conn = db()
    c = conn.cursor()
    c.execute("SELECT invited_by FROM users WHERE user_id = ?", (buyer_id,))
    r = c.fetchone()
    if not r or not r[0]:
        conn.close(); return None
    inviter = r[0]
    c.execute("SELECT COUNT(*) FROM receipts WHERE user_id = ? AND status = 'approved'", (buyer_id,))
    approved_count = c.fetchone()[0]
    conn.close()
    if approved_count == 1:
        db_grant_referral_discount(inviter)
        return inviter
    return None


@dp.callback_query(F.data.startswith("adm_approve_"))
async def cb_adm_approve_one(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    rid = int(call.data.split("_")[2])
    r = db_get_receipt(rid)
    if not r:
        await call.answer("یافت نشد", show_alert=True); return
    _, uid, product, username, amount, _, status, _, _, _ = r
    if status == "approved":
        await call.answer("قبلاً تایید شده", show_alert=True); return

    # بررسی آیا در pool کانفیگ وجود دارد
    pool_item = db_pop_from_pool(product)
    if pool_item:
        # کانفیگ از pool پیدا شد → تایید خودکار و ارسال
        db_approve_receipt(rid)
        db_set_receipt_config(rid, config=pool_item["config"], sub_link=pool_item.get("sub_link", ""))
        cfg = pool_item["config"]
        sub = pool_item.get("sub_link", "")
        label = get_product_label(product)
        try:
            msg_text = (
                f"✅ رسید #{rid} تایید شد!\n"
                f"📦 سرویس: {label}\n"
                f"👤 یوزرنیم: <code>{username}</code>\n\n"
            )
            if cfg and sub:
                msg_text += f"📄 کانفیگ:\n<code>{cfg}</code>\n\n🔗 لینک ساب:\n<code>{sub}</code>"
            elif sub:
                msg_text += f"🔗 لینک ساب:\n<code>{sub}</code>"
            elif cfg:
                msg_text += f"📄 کانفیگ:\n<code>{cfg}</code>"
            await bot.send_message(uid, msg_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await call.answer("✅ تایید + کانفیگ از pool ارسال شد", show_alert=True)
        try:
            await call.message.edit_caption(
                (call.message.caption or "") + f"\n\n✅ تایید شد — کانفیگ از pool ({label})",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    # pool خالی است → از ادمین بخواه کانفیگ بفرستد
    await call.answer()
    await state.update_data(approve_rid=rid, approve_uid=uid, approve_product=product, approve_username=username, approve_amount=amount)
    label = get_product_label(product)
    # نمایش منوی انتخاب نوع کانفیگ
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 کانفیگ + ساب", callback_data=f"adm_asnd_cfgsub_{rid}"),
            InlineKeyboardButton(text="📄 کانفیگ تک", callback_data=f"adm_asnd_cfg_{rid}"),
        ],
    ])
    await call.message.answer(
        f"✅ رسید #{rid} — {label}\n"
        f"👤 {username}\n\n"
        f"⚠️ pool خالی است. نوع کانفیگ را انتخاب کنید و ارسال کنید:",
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("adm_reject_"))
async def cb_adm_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    rid = int(call.data.split("_")[2])
    r = db_get_receipt(rid)
    if not r:
        await call.answer("یافت نشد", show_alert=True); return
    _, uid, product, username, amount, _, status, _, _, _ = r
    if status == "rejected":
        await call.answer("قبلاً رد شده", show_alert=True); return
    db_set_receipt_status(rid, "rejected")
    try:
        await bot.send_message(
            uid,
            f"❌ رسید #{rid} شما توسط ادمین رد شد.\n"
            f"📦 سرویس: {get_product_label(product)}\n"
            f"💰 مبلغ: {fmt_price(amount)}\n\n"
            "در صورت سوال با پشتیبانی در تماس باشید.",
        )
    except Exception:
        pass
    await call.answer("❌ رد شد")
    try:
        await call.message.edit_caption((call.message.caption or "") + "\n\n❌ رد شد", reply_markup=None)
    except Exception:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ==================== کانفیگ‌های هدیه دعوت (مدیر) ====================
def kb_adm_giftcfg() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="➕ افزودن کانفیگ‌های هدیه", callback_data="adm_giftcfg_add")],
        [btn(BUTTON_LABELS["back"], "back", callback_data="admin_panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "adm_giftcfg")
async def cb_adm_giftcfg(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.clear()
    total = db_count_total_configs()
    claimed = db_count_claimed_configs()
    unclaimed = db_count_unclaimed_configs()
    owed_users = db_list_owed_users()
    total_owed = sum(o for _, o in owed_users)
    txt = (
        "🎁 مدیریت کانفیگ‌های هدیه دعوت\n\n"
        "هر ۵ رفرال موفق ⇒ ۱ کانفیگ از این مخزن به دعوت‌کننده تعلق می‌گیرد.\n\n"
        f"📦 کل ثبت‌شده: {fa_digits(total)}\n"
        f"✅ گرفته‌شده: {fa_digits(claimed)}\n"
        f"⏳ نگرفته‌شده (مانده): {fa_digits(unclaimed)}\n"
        f"📌 بدهی به کاربران (در صف تحویل): {fa_digits(total_owed)}"
    )
    await call.message.edit_text(txt, reply_markup=kb_adm_giftcfg())


@dp.callback_query(F.data == "adm_giftcfg_add")
async def cb_adm_giftcfg_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.gift_count)
    await call.message.edit_text(
        "🎁 چند کانفیگ می‌خواهید اضافه کنید؟\n\n"
        "یک عدد بفرستید (مثلاً <code>10</code>):",
        reply_markup=kb_back("adm_giftcfg"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.gift_count)
async def msg_adm_gift_count(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    txt = (message.text or "").strip()
    try:
        n = int(fa_to_en_digits(txt))
        if n <= 0 or n > 1000:
            raise ValueError
    except Exception:
        await message.answer("❌ عدد نامعتبر است. یک عدد بین ۱ تا ۱۰۰۰ بفرستید.")
        return
    await state.update_data(gift_total=n, gift_index=1, gift_collected=[])
    await state.set_state(AdminStates.gift_text)
    await message.answer(
        f"📥 کانفیگ شماره {fa_digits(1)} از {fa_digits(n)} را بفرستید:\n\n"
        "(برای انصراف /cancel)"
    )


@dp.message(AdminStates.gift_text)
async def msg_adm_gift_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ لغو شد.", reply_markup=kb_adm_giftcfg())
        return
    if not text:
        await message.answer("❌ متن خالی است. کانفیگ را بفرستید یا /cancel.")
        return
    data = await state.get_data()
    total = int(data.get("gift_total", 0))
    idx = int(data.get("gift_index", 1))
    collected = list(data.get("gift_collected") or [])
    collected.append(text)
    if idx < total:
        await state.update_data(gift_index=idx + 1, gift_collected=collected)
        await message.answer(
            f"✅ کانفیگ شماره {fa_digits(idx)} ذخیره شد.\n\n"
            f"📥 کانفیگ شماره {fa_digits(idx + 1)} از {fa_digits(total)} را بفرستید:\n\n"
            "(برای انصراف /cancel)"
        )
        return
    # آخرین کانفیگ — همه را در دیتابیس ثبت کن
    saved = 0
    for c in collected:
        try:
            db_add_referral_config(c)
            saved += 1
        except Exception as e:
            logger.warning(f"add referral config failed: {e}")
    await state.clear()
    # تلاش برای توزیع به بدهکاران
    delivered = 0
    try:
        delivered = await _distribute_owed_configs()
    except Exception as e:
        logger.warning(f"distribute owed failed: {e}")
    msg = (
        f"✅ {fa_digits(saved)} کانفیگ هدیه ثبت شد.\n"
    )
    if delivered:
        msg += f"📤 از این تعداد {fa_digits(delivered)} مورد به‌صورت خودکار به کاربران بدهکار تحویل داده شد.\n"
    await message.answer(msg, reply_markup=kb_adm_giftcfg())


# ==================== پیام همگانی ====================
@dp.callback_query(F.data == "adm_broadcast")
async def cb_adm_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.clear()
    pins_count = len(SETTINGS.get("broadcast_pins") or [])
    await call.message.edit_text(
        "📢 پیام همگانی\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید 👇\n\n"
        f"📌 پین‌های فعلی ذخیره‌شده: <b>{fa_digits(pins_count)}</b>",
        reply_markup=kb_admin_broadcast(),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "adm_bc_nopin")
async def cb_adm_bc_nopin(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.broadcast_message)
    await call.message.edit_text(
        "📨 پیام همگانی <b>بدون پین</b>\n\n"
        "متن، عکس، ویدیو یا هر پیامی که می‌خواهید برای همه کاربران ارسال شود را بفرستید 👇",
        reply_markup=kb_back("adm_broadcast"),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "adm_bc_pin")
async def cb_adm_bc_pin(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.broadcast_message_pin)
    await call.message.edit_text(
        "📌 پیام همگانی <b>با پین</b>\n\n"
        "متن، عکس، ویدیو یا هر پیامی که می‌خواهید ارسال و در چت کاربران پین شود را بفرستید 👇",
        reply_markup=kb_back("adm_broadcast"),
        parse_mode=ParseMode.HTML,
    )


async def _do_broadcast(message: Message, pin: bool):
    """ارسال همگانی پیام؛ اگر pin=True تلاش می‌کند پیام را در هر چت پین کند."""
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE COALESCE(is_banned,0)=0")
    users = [row[0] for row in c.fetchall()]
    conn.close()

    sent, failed, pinned = 0, 0, 0
    new_pins = list(SETTINGS.get("broadcast_pins") or [])
    status = await message.answer(f"⏳ در حال ارسال به {fa_digits(len(users))} کاربر...")
    for uid in users:
        try:
            sent_msg = await message.copy_to(chat_id=uid)
            sent += 1
            if pin and bot is not None:
                try:
                    await bot.pin_chat_message(
                        chat_id=uid,
                        message_id=sent_msg.message_id,
                        disable_notification=False,
                    )
                    new_pins.append({"chat_id": uid, "message_id": sent_msg.message_id})
                    pinned += 1
                except Exception as e:
                    logger.warning(f"pin to {uid} failed: {e}")
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    if pin:
        s_set("broadcast_pins", new_pins)

    summary = (
        f"✅ پیام همگانی ارسال شد.\n\n"
        f"📤 موفق: {fa_digits(sent)}\n"
        f"❌ ناموفق: {fa_digits(failed)}"
    )
    if pin:
        summary += f"\n📌 پین‌شده: {fa_digits(pinned)}"
    try:
        await status.edit_text(summary, reply_markup=kb_admin())
    except Exception:
        await message.answer(summary, reply_markup=kb_admin())


@dp.message(AdminStates.broadcast_message)
async def msg_adm_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await _do_broadcast(message, pin=False)


@dp.message(AdminStates.broadcast_message_pin)
async def msg_adm_broadcast_pin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await _do_broadcast(message, pin=True)


@dp.callback_query(F.data == "adm_bc_unpin")
async def cb_adm_bc_unpin(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pins = list(SETTINGS.get("broadcast_pins") or [])
    if not pins:
        await call.message.edit_text(
            "ℹ️ هیچ پین فعالی ذخیره نشده است.",
            reply_markup=kb_admin_broadcast(),
        )
        return
    status = await call.message.edit_text(
        f"⏳ در حال حذف {fa_digits(len(pins))} پین قبلی...",
    )
    removed, failed = 0, 0
    for item in pins:
        try:
            if bot is not None:
                await bot.unpin_chat_message(
                    chat_id=item["chat_id"],
                    message_id=item["message_id"],
                )
            removed += 1
        except Exception as e:
            failed += 1
            logger.warning(f"unpin failed for {item}: {e}")
        await asyncio.sleep(0.03)
    s_set("broadcast_pins", [])
    try:
        await status.edit_text(
            f"✅ حذف پین‌ها انجام شد.\n\n"
            f"🗑 حذف‌شده: {fa_digits(removed)}\n"
            f"❌ ناموفق: {fa_digits(failed)}",
            reply_markup=kb_admin_broadcast(),
        )
    except Exception:
        await call.message.answer(
            f"✅ حذف پین‌ها انجام شد.\n🗑 حذف‌شده: {fa_digits(removed)}\n❌ ناموفق: {fa_digits(failed)}",
            reply_markup=kb_admin_broadcast(),
        )


@dp.callback_query(F.data.startswith("adm_cfgsub_"))
async def cb_adm_cfgsub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rid = int(call.data.split("_")[2])
    await state.update_data(deliver_rid=rid, deliver_mode="cfgsub")
    await state.set_state(AdminStates.waiting_config)
    await call.message.answer(f"📦 برای رسید #{rid}\n\n📄 کانفیگ را ارسال کنید 👇")


@dp.callback_query(F.data.startswith("adm_cfg_"))
async def cb_adm_cfg(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rid = int(call.data.split("_")[2])
    await state.update_data(deliver_rid=rid, deliver_mode="cfg")
    await state.set_state(AdminStates.waiting_config)
    await call.message.answer(f"📦 برای رسید #{rid}\n\n📄 کانفیگ را ارسال کنید 👇")


# ===== ارسال دستی کانفیگ هنگام approve (وقتی pool خالی باشد) =====
@dp.callback_query(F.data.startswith("adm_asnd_cfgsub_"))
async def cb_adm_asnd_cfgsub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rid = int(call.data.split("_")[-1])
    r = db_get_receipt(rid)
    if not r:
        await call.message.answer("❌ رسید یافت نشد."); return
    _, uid, product, username, amount, _, _, _, _, _ = r
    await state.update_data(approve_rid=rid, approve_uid=uid, approve_product=product,
                            approve_username=username, approve_mode="cfgsub")
    await state.set_state(AdminStates.approve_send_cfg)
    await call.message.answer(
        f"📦 رسید #{rid} — {get_product_label(product)}\n"
        f"👤 {username}\n\n📄 کانفیگ را ارسال کنید 👇"
    )


@dp.callback_query(F.data.startswith("adm_asnd_cfg_"))
async def cb_adm_asnd_cfg(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rid = int(call.data.split("_")[-1])
    r = db_get_receipt(rid)
    if not r:
        await call.message.answer("❌ رسید یافت نشد."); return
    _, uid, product, username, amount, _, _, _, _, _ = r
    await state.update_data(approve_rid=rid, approve_uid=uid, approve_product=product,
                            approve_username=username, approve_mode="cfg")
    await state.set_state(AdminStates.approve_send_cfg)
    await call.message.answer(
        f"📄 رسید #{rid} — {get_product_label(product)}\n"
        f"👤 {username}\n\n📄 کانفیگ تک را ارسال کنید 👇"
    )


@dp.message(AdminStates.approve_send_cfg)
async def msg_approve_send_cfg(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    cfg = (message.text or "").strip()
    if not cfg:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    rid = data.get("approve_rid")
    mode = data.get("approve_mode")
    if not rid:
        await state.clear(); return
    db_set_receipt_config(rid, config=cfg)
    if mode == "cfgsub":
        await state.update_data(approve_cfg=cfg)
        await state.set_state(AdminStates.approve_send_sub)
        await message.answer("✅ کانفیگ ثبت شد.\n\n🔗 حالا لینک ساب را ارسال کنید 👇")
        return
    # کانفیگ تک
    db_approve_receipt(rid)
    data2 = await state.get_data()
    uid = data2.get("approve_uid"); username = data2.get("approve_username"); product = data2.get("approve_product")
    label = get_product_label(product)
    try:
        await bot.send_message(
            uid,
            f"✅ سرویس شما آماده شد!\n"
            f"📦 {label}\n"
            f"👤 یوزرنیم: <code>{username}</code>\n\n"
            f"📄 کانفیگ:\n<code>{cfg}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"send approve_cfg to {uid}: {e}")
    await state.clear()
    await message.answer(f"✅ کانفیگ ارسال شد و رسید #{rid} تایید شد.")


@dp.message(AdminStates.approve_send_sub)
async def msg_approve_send_sub(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    sub = (message.text or "").strip()
    if not sub:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    rid = data.get("approve_rid")
    uid = data.get("approve_uid"); username = data.get("approve_username"); product = data.get("approve_product")
    cfg = data.get("approve_cfg", "")
    label = get_product_label(product)
    if not rid:
        await state.clear(); return
    db_set_receipt_config(rid, sub_link=sub)
    db_approve_receipt(rid)
    try:
        await bot.send_message(
            uid,
            f"✅ سرویس شما آماده شد!\n"
            f"📦 {label}\n"
            f"👤 یوزرنیم: <code>{username}</code>\n\n"
            f"📄 کانفیگ:\n<code>{cfg}</code>\n\n"
            f"🔗 لینک ساب:\n<code>{sub}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"send approve_cfgsub to {uid}: {e}")
    await state.clear()
    await message.answer(f"✅ کانفیگ + ساب ارسال شد و رسید #{rid} تایید شد.")


@dp.message(AdminStates.waiting_config)
async def msg_adm_config(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    cfg = (message.text or "").strip()
    if not cfg:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    rid = data.get("deliver_rid")
    mode = data.get("deliver_mode")
    if not rid:
        await state.clear(); return
    db_set_receipt_config(rid, config=cfg)
    if mode == "cfgsub":
        await state.set_state(AdminStates.waiting_sub)
        await message.answer("✅ کانفیگ ثبت شد.\n\n🔗 حالا لطفاً ساب را ارسال کنید 👇")
        return
    # فقط کانفیگ
    db_set_receipt_status(rid, "approved")
    r = db_get_receipt(rid)
    if r:
        uid = r[1]; username = r[3]; product = r[2]
        label = get_product_label(product)
        try:
            await bot.send_message(
                uid,
                f"📦 سرویس شما آماده شد!\n"
                f"👤 یوزرنیم: <code>{username}</code>\n"
                f"💾 سرویس: {label}\n\n"
                f"📄 کانفیگ:\n<code>{cfg}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"send config to {uid} failed: {e}")
    await state.clear()
    await message.answer(f"✅ کانفیگ برای کاربر ارسال شد. (رسید #{rid})")


@dp.message(AdminStates.waiting_sub)
async def msg_adm_sub(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    sub = (message.text or "").strip()
    if not sub:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    rid = data.get("deliver_rid")
    if not rid:
        await state.clear(); return
    db_set_receipt_config(rid, sub_link=sub)
    db_set_receipt_status(rid, "approved")
    r = db_get_receipt(rid)
    if r:
        uid = r[1]; username = r[3]; product = r[2]; cfg = r[7]
        label = get_product_label(product)
        try:
            await bot.send_message(
                uid,
                f"📦 سرویس شما آماده شد!\n"
                f"👤 یوزرنیم: <code>{username}</code>\n"
                f"💾 سرویس: {label}\n\n"
                f"📄 کانفیگ:\n<code>{cfg}</code>\n\n"
                f"🔗 لینک ساب:\n<code>{sub}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"send config+sub to {uid} failed: {e}")
    await state.clear()
    await message.answer(f"✅ کانفیگ + ساب برای کاربر ارسال شد. (رسید #{rid})")


# ==================== 📦 مدیریت Pool کانفیگ‌ها ====================
def kb_pool_products() -> InlineKeyboardMarkup:
    summary = db_pool_summary()
    rows = []
    for p in get_products():
        cnt = summary.get(p["key"], 0)
        rows.append([
            InlineKeyboardButton(
                text=f"{'🟢' if cnt > 0 else '🔴'} {p['label']} — {fa_digits(cnt)} موجود",
                callback_data=f"adm_pool_p_{p['key']}",
            )
        ])
    rows.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_pool_product_detail(pkey: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 افزودن کانفیگ + ساب", callback_data=f"adm_pool_add_cfgsub_{pkey}"),
        ],
        [
            InlineKeyboardButton(text="📄 افزودن کانفیگ تک", callback_data=f"adm_pool_add_cfg_{pkey}"),
        ],
        [
            InlineKeyboardButton(text="📋 افزودن گروهی لینک‌های ساب", callback_data=f"adm_pool_bulk_{pkey}"),
        ],
        [InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_pool")],
    ])


@dp.callback_query(F.data == "adm_pool")
async def cb_adm_pool(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "approve_receipts"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.clear()
    await call.message.edit_text(
        "📦 <b>مدیریت pool کانفیگ‌ها</b>\n\n"
        "برای هر محصول، کانفیگ‌های آماده ذخیره کنید.\n"
        "هنگام تایید رسید، اگر pool موجود باشد خودکار ارسال می‌شود.\n\n"
        "روی هر محصول بزنید تا کانفیگ اضافه کنید:",
        reply_markup=kb_pool_products(),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("adm_pool_p_"))
async def cb_adm_pool_product(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pkey = call.data.split("adm_pool_p_")[1]
    label = get_product_label(pkey)
    cnt = db_count_pool(pkey)
    await call.message.edit_text(
        f"📦 <b>{label}</b>\n\n"
        f"موجودی pool: <b>{fa_digits(cnt)}</b> کانفیگ\n\n"
        "نوع کانفیگ را انتخاب کنید:",
        reply_markup=kb_pool_product_detail(pkey),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("adm_pool_add_cfgsub_"))
async def cb_adm_pool_add_cfgsub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pkey = call.data.split("adm_pool_add_cfgsub_")[1]
    await state.update_data(pool_product=pkey, pool_type="cfgsub")
    await state.set_state(AdminStates.pool_cfg)
    await call.message.answer(
        f"📦 [{get_product_label(pkey)}] — کانفیگ + ساب\n\n📄 کانفیگ را ارسال کنید 👇"
    )


@dp.callback_query(F.data.startswith("adm_pool_add_cfg_"))
async def cb_adm_pool_add_cfg(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pkey = call.data.split("adm_pool_add_cfg_")[1]
    await state.update_data(pool_product=pkey, pool_type="cfg")
    await state.set_state(AdminStates.pool_cfg)
    await call.message.answer(
        f"📄 [{get_product_label(pkey)}] — کانفیگ تک\n\n📄 کانفیگ را ارسال کنید 👇"
    )


@dp.message(AdminStates.pool_cfg)
async def msg_pool_cfg(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    cfg = (message.text or "").strip()
    if not cfg:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    pkey = data.get("pool_product")
    ptype = data.get("pool_type")
    await state.update_data(pool_cfg_text=cfg)
    if ptype == "cfgsub":
        await state.set_state(AdminStates.pool_sub)
        await message.answer("✅ کانفیگ ثبت شد.\n\n🔗 حالا لینک ساب را ارسال کنید 👇")
        return
    db_add_to_pool(pkey, cfg, sub_link="", pool_type="cfg")
    cnt = db_count_pool(pkey)
    await state.clear()
    await message.answer(
        f"✅ کانفیگ تک به pool [{get_product_label(pkey)}] اضافه شد.\n"
        f"📦 موجودی pool: {fa_digits(cnt)}"
    )


@dp.message(AdminStates.pool_sub)
async def msg_pool_sub(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    sub = (message.text or "").strip()
    if not sub:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    pkey = data.get("pool_product")
    cfg = data.get("pool_cfg_text", "")
    db_add_to_pool(pkey, cfg, sub_link=sub, pool_type="cfgsub")
    cnt = db_count_pool(pkey)
    await state.clear()
    await message.answer(
        f"✅ کانفیگ + ساب به pool [{get_product_label(pkey)}] اضافه شد.\n"
        f"📦 موجودی pool: {fa_digits(cnt)}"
    )


# ===== افزودن گروهی لینک‌های ساب به pool =====
@dp.callback_query(F.data.startswith("adm_pool_bulk_"))
async def cb_adm_pool_bulk(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    pkey = call.data.split("adm_pool_bulk_")[1]
    await state.update_data(pool_product=pkey)
    await state.set_state(AdminStates.pool_bulk)
    await call.message.answer(
        f"📋 <b>[{get_product_label(pkey)}] — افزودن گروهی لینک‌های ساب</b>\n\n"
        "تمام لینک‌ها را در یک پیام بفرستید (هر لینک در یک خط).\n\n"
        "نمونه:\n"
        "<code>http://example.com:2095/sub/abc123\n"
        "http://example.com:2095/sub/def456\n"
        "http://example.com:2095/sub/ghi789</code>\n\n"
        "💡 اگر آدرس روی دو خط بود (بیس + مسیر)، خودکار ترکیب می‌شود:\n"
        "<code>http://example.com:2095\n/sub/abc123</code>",
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.pool_bulk)
async def msg_pool_bulk(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    pkey = data.get("pool_product")

    # ترکیب خطوطی که با / شروع می‌شوند با خط قبلی (base URL + path)
    lines = raw.splitlines()
    merged = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("/") and merged:
            merged[-1] = merged[-1].rstrip("/") + line
        else:
            merged.append(line)

    # فیلتر لینک‌های معتبر
    valid_subs = [item.strip() for item in merged
                  if item.strip().startswith("http://") or item.strip().startswith("https://")]

    if not valid_subs:
        await message.answer(
            "❌ هیچ لینک معتبری یافت نشد.\n"
            "لینک‌ها باید با <code>http://</code> یا <code>https://</code> شروع شوند.",
            parse_mode=ParseMode.HTML,
        )
        return

    added = 0
    for sub in valid_subs:
        try:
            db_add_to_pool(pkey, config_text="", sub_link=sub, pool_type="sub")
            added += 1
        except Exception as e:
            logger.warning(f"bulk pool add failed: {e}")

    cnt = db_count_pool(pkey)
    await state.clear()
    await message.answer(
        f"✅ <b>{fa_digits(added)} لینک ساب</b> به pool [{get_product_label(pkey)}] اضافه شد.\n"
        f"📦 موجودی کل pool: <b>{fa_digits(cnt)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 برگشت به pool", callback_data=f"adm_pool_p_{pkey}")],
        ]),
    )


# بن
@dp.callback_query(F.data == "adm_ban")
async def cb_adm_ban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.ban_user)
    await call.message.edit_text("🚫 آیدی عددی کاربر برای بن را ارسال کنید 👇", reply_markup=kb_back("admin_panel"))


@dp.message(AdminStates.ban_user)
async def msg_adm_ban(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        uid = int((message.text or "").strip())
    except Exception:
        await message.answer("❌ آیدی عددی نامعتبر است."); return
    db_set_ban(uid, 1)
    await state.clear()
    await message.answer(f"✅ کاربر <code>{uid}</code> بن شد.", reply_markup=kb_admin(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "adm_unban")
async def cb_adm_unban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.unban_user)
    await call.message.edit_text("🔓 آیدی عددی کاربر برای آنبن را ارسال کنید 👇", reply_markup=kb_back("admin_panel"))


@dp.message(AdminStates.unban_user)
async def msg_adm_unban(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        uid = int((message.text or "").strip())
    except Exception:
        await message.answer("❌ آیدی عددی نامعتبر است."); return
    db_set_ban(uid, 0)
    await state.clear()
    await message.answer(f"✅ کاربر <code>{uid}</code> آنبن شد.", reply_markup=kb_admin(), parse_mode=ParseMode.HTML)


# کد تخفیف
@dp.callback_query(F.data == "adm_discount")
async def cb_adm_discount(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.discount_input)
    await call.message.edit_text(
        "🎁 لطفاً کد تخفیف را به این صورت ارسال کنید:\n\n"
        "<b>Badboy50</b>\n\n"
        "یعنی کلمه + درصد در انتها (۱ تا ۱۰۰).\n"
        "این کد روی همه محصولات اعمال خواهد شد.",
        reply_markup=kb_back("admin_panel"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.discount_input)
async def msg_adm_discount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    text = (message.text or "").strip()
    m = re.match(r"^(.+?)(\d{1,3})$", text)
    if not m:
        await message.answer("❌ فرمت نامعتبر. مثال: Badboy50"); return
    code, percent = m.group(1) + m.group(2), int(m.group(2))
    if not (1 <= percent <= 100):
        await message.answer("❌ درصد باید بین ۱ تا ۱۰۰ باشد."); return
    db_save_discount(code, percent)
    await state.clear()
    await message.answer(
        f"✅ کد تخفیف <code>{code}</code> با {percent}٪ ساخته شد.",
        reply_markup=kb_admin(),
        parse_mode=ParseMode.HTML,
    )


# تنظیم قیمت
@dp.callback_query(F.data == "adm_prices")
async def cb_adm_prices(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "💵 برای تنظیم قیمت، روی محصول مورد نظر بزنید:",
        reply_markup=kb_admin_prices(),
    )


@dp.callback_query(F.data.startswith("setprice_"))
async def cb_set_price(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    p = call.data.split("_", 1)[1]
    if not get_product(p):
        return
    await state.update_data(target_product=p)
    await state.set_state(AdminStates.set_price)
    cur = get_product_price(p)
    await call.message.edit_text(
        f"💵 قیمت فعلی {get_product_label(p)}: {fmt_price(cur)}\n\n"
        "قیمت جدید را به تومان (فقط عدد) ارسال کنید 👇",
        reply_markup=kb_back("adm_prices"),
    )


@dp.message(AdminStates.set_price)
async def msg_set_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    txt = re.sub(r"[^\d]", "", message.text or "")
    if not txt:
        await message.answer("❌ فقط عدد ارسال کنید."); return
    new_price = int(txt)
    data = await state.get_data()
    p = data.get("target_product")
    if not p:
        await state.clear(); return
    update_product_price(p, new_price)
    await state.clear()
    await message.answer(
        f"✅ قیمت {get_product_label(p)} به {fmt_price(new_price)} تنظیم شد.",
        reply_markup=kb_admin_prices(),
    )


# ===== افزودن / حذف محصول =====
@dp.callback_query(F.data == "addprod")
async def cb_add_product(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.add_product_label)
    await call.message.edit_text(
        "➕ افزودن محصول جدید\n\n"
        "🟢 لطفاً <b>حجم</b> محصول را به‌صورت متن ارسال کنید.\n"
        "مثال: <code>4 گیگ</code> یا <code>۲۰ گیگابایت</code>",
        reply_markup=kb_back("adm_prices"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.add_product_label)
async def msg_add_product_label(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    label = (message.text or "").strip()
    if not label or len(label) > 40:
        await message.answer("❌ متن نامعتبر است (۱ تا ۴۰ کاراکتر).")
        return
    await state.update_data(new_product_label=label)
    await state.set_state(AdminStates.add_product_price)
    await message.answer(
        f"✅ حجم ثبت شد: <b>{label}</b>\n\n"
        "💰 حالا <b>قیمت</b> را به تومان (فقط عدد) ارسال کنید 👇",
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.add_product_price)
async def msg_add_product_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    txt = re.sub(r"[^\d]", "", message.text or "")
    if not txt:
        await message.answer("❌ فقط عدد ارسال کنید.")
        return
    price = int(txt)
    data = await state.get_data()
    label = data.get("new_product_label")
    if not label:
        await state.clear()
        return
    key = add_product(label, price)
    await state.clear()
    await message.answer(
        f"✅ محصول جدید اضافه شد:\n\n"
        f"📦 حجم: <b>{label}</b>\n"
        f"💰 قیمت: <b>{fmt_price(price)}</b>",
        reply_markup=kb_admin_prices(),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("delprod_"))
async def cb_del_product(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    key = call.data.split("_", 1)[1]
    p = get_product(key)
    if not p:
        await call.answer("یافت نشد", show_alert=True); return
    label = p["label"]
    if remove_product(key):
        await call.answer(f"🗑 «{label}» حذف شد", show_alert=False)
    else:
        await call.answer("❌ حذف نشد", show_alert=True)
    try:
        await call.message.edit_reply_markup(reply_markup=kb_admin_prices())
    except Exception:
        pass


# ===== خاموش/روشن کردن فروش =====
@dp.callback_query(F.data == "adm_toggle_sales")
async def cb_toggle_sales(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    new_val = not SETTINGS.get("sales_enabled", True)
    s_set("sales_enabled", new_val)
    await call.answer(
        "🟢 فروش روشن شد" if new_val else "🔴 فروش خاموش شد",
        show_alert=False,
    )
    try:
        await call.message.edit_reply_markup(reply_markup=kb_admin())
    except Exception:
        pass


# ===== خاموش/روشن کردن ربات =====
@dp.callback_query(F.data == "adm_toggle_bot")
async def cb_toggle_bot(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    new_val = not SETTINGS.get("bot_enabled", True)
    s_set("bot_enabled", new_val)
    await call.answer(
        "🟢 ربات روشن شد" if new_val else "🔴 ربات خاموش شد (کاربران پیام بروزرسانی می‌بینند)",
        show_alert=False,
    )
    try:
        await call.message.edit_reply_markup(reply_markup=kb_admin())
    except Exception:
        pass


# تنظیم شماره کارت
@dp.callback_query(F.data == "adm_card")
async def cb_adm_card(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    cur_card = SETTINGS.get("card_number") or "تنظیم نشده"
    cur_holder = SETTINGS.get("card_holder") or "تنظیم نشده"
    await state.set_state(AdminStates.set_card_number)
    await call.message.edit_text(
        f"💳 وضعیت فعلی\nکارت: <code>{cur_card}</code>\nبه‌نام: {cur_holder}\n\n"
        "لطفاً شماره کارت جدید را ارسال کنید 👇",
        reply_markup=kb_back("admin_panel"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.set_card_number)
async def msg_card_number(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    card = re.sub(r"\s+", "", message.text or "")
    if not re.fullmatch(r"\d{12,20}", card):
        await message.answer("❌ شماره کارت نامعتبر است."); return
    await state.update_data(card_number=card)
    await state.set_state(AdminStates.set_card_holder)
    await message.answer("✅ شماره کارت ثبت شد.\n\n👤 حالا نام کاربری/نام صاحب کارت را ارسال کنید 👇")


@dp.message(AdminStates.set_card_holder)
async def msg_card_holder(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    holder = (message.text or "").strip()
    if not holder:
        await message.answer("❌ نام نمی‌تواند خالی باشد."); return
    data = await state.get_data()
    SETTINGS["card_number"] = data.get("card_number", "")
    SETTINGS["card_holder"] = holder
    save_settings(SETTINGS)
    await state.clear()
    await message.answer(
        f"✅ ذخیره شد.\n💳 <code>{SETTINGS['card_number']}</code>\n👤 {holder}",
        reply_markup=kb_admin(),
        parse_mode=ParseMode.HTML,
    )


# تنظیم پشتیبانی
@dp.callback_query(F.data == "adm_support")
async def cb_adm_support(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    cur = SETTINGS.get("support_id") or DEFAULT_SUPPORT_ID
    await state.set_state(AdminStates.set_support)
    await call.message.edit_text(
        f"🛟 آیدی پشتیبانی فعلی: {cur}\n\nآیدی جدید را ارسال کنید (مثلاً @VM_GOZARNET) 👇",
        reply_markup=kb_back("admin_panel"),
    )


@dp.message(AdminStates.set_support)
async def msg_set_support(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    sid = (message.text or "").strip()
    if not sid:
        await message.answer("❌"); return
    if not sid.startswith("@"):
        sid = "@" + sid
    s_set("support_id", sid)
    await state.clear()
    await message.answer(f"✅ آیدی پشتیبانی به {sid} تغییر کرد.", reply_markup=kb_admin())


# تنظیم چنل‌ها
@dp.callback_query(F.data == "adm_channels")
async def cb_adm_channels(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "📡 مدیریت چنل‌های جوین اجباری:",
        reply_markup=kb_admin_channels(),
    )


@dp.callback_query(F.data.startswith("delch_"))
async def cb_delch(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    ch = call.data.split("_", 1)[1]
    chs = SETTINGS.get("channels", [])
    if ch in chs:
        chs.remove(ch)
        s_set("channels", chs)
    await call.answer("حذف شد")
    await call.message.edit_reply_markup(reply_markup=kb_admin_channels())


@dp.callback_query(F.data == "addch")
async def cb_addch(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.add_channel)
    await call.message.edit_text(
        "📡 یوزرنیم چنل را ارسال کنید (مثلاً @vm_vpn یا لینک کامل):",
        reply_markup=kb_back("adm_channels"),
    )


@dp.message(AdminStates.add_channel)
async def msg_addch(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    text = (message.text or "").strip()
    m = re.search(r"(?:t\.me/)?@?([A-Za-z][A-Za-z0-9_]{3,})", text)
    if not m:
        await message.answer("❌ فرمت نامعتبر."); return
    ch = "@" + m.group(1)
    chs = SETTINGS.get("channels", [])
    if ch not in chs:
        chs.append(ch)
        s_set("channels", chs)
    await state.clear()
    await message.answer(f"✅ {ch} اضافه شد.", reply_markup=kb_admin_channels())


# رنگ دکمه‌ها
@dp.callback_query(F.data == "adm_colors")
async def cb_adm_colors(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "🎨 یکی از دکمه‌ها را برای تغییر رنگ انتخاب کنید:",
        reply_markup=kb_admin_colors(),
    )


@dp.callback_query(F.data.startswith("color_"))
async def cb_color_pick(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    key = call.data.split("_", 1)[1]
    label = BUTTON_LABELS.get(key, key)
    await call.message.edit_text(
        f"🎨 رنگ دلخواه برای دکمه «{label}» را انتخاب کنید:",
        reply_markup=kb_color_choice(key),
    )


@dp.callback_query(F.data.startswith("setcolor_"))
async def cb_set_color(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    parts = call.data.split("_")
    # setcolor_<key>_<color>
    color = parts[-1]
    key = "_".join(parts[1:-1])
    if color not in ("primary", "success", "danger", "default"):
        await call.answer("نامعتبر", show_alert=True); return
    SETTINGS["colors"][key] = color
    save_settings(SETTINGS)
    await call.answer("✅ ذخیره شد")
    await call.message.edit_text(
        "🎨 یکی از دکمه‌ها را برای تغییر رنگ انتخاب کنید:",
        reply_markup=kb_admin_colors(),
    )


# ==================== لیست کاربران (پنل ادمین) ====================
USERS_PER_PAGE = 10


def kb_users_page(page: int, banned_only: bool = False) -> InlineKeyboardMarkup:
    rows, total = db_get_users_page(page, USERS_PER_PAGE, banned_only=banned_only)
    rows_kb = []
    mode = "bl" if banned_only else "ul"
    for i, r in enumerate(rows):
        # ساختار جدید: (uid, uname, fname, balance, banned, join_date, coins, refs)
        uid, uname, fname, bal, banned, _join, coins, refs = r
        name = fname or uname or str(uid)
        if len(name) > 16:
            name = name[:16] + "…"
        flag = "⛔️ " if banned else ""
        label = f"{flag}{name} | 🪙{fa_digits(coins)} 👥{fa_digits(refs)}"
        # callback شامل ایندکس و صفحه برای ناوبری بعدی/قبلی
        rows_kb.append([InlineKeyboardButton(text=label, callback_data=f"adm_ud_{uid}_{page}_{i}_{mode}")])

    nav = []
    prefix = "adm_banlist_" if banned_only else "adm_users_"
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"{prefix}{page-1}"))
    nav.append(InlineKeyboardButton(text=f"صفحه {page+1}/{max(1,(total+USERS_PER_PAGE-1)//USERS_PER_PAGE)}", callback_data="noop"))
    if (page + 1) * USERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"{prefix}{page+1}"))
    if nav:
        rows_kb.append(nav)
    rows_kb.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows_kb)


def kb_user_detail(uid: int, banned: bool, page: int = 0, idx: int = 0, mode: str = "ul") -> InlineKeyboardMarkup:
    banned_only = (mode == "bl")
    rows_kb = []

    # ناوبری: کاربر قبلی / بعدی
    nav_row = []
    # کاربر قبلی
    if idx > 0:
        prev_rows, _ = db_get_users_page(page, USERS_PER_PAGE, banned_only=banned_only)
        if idx - 1 < len(prev_rows):
            prev_uid = prev_rows[idx - 1][0]
            nav_row.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"adm_ud_{prev_uid}_{page}_{idx-1}_{mode}"))
    elif page > 0:
        prev_page_rows, _ = db_get_users_page(page - 1, USERS_PER_PAGE, banned_only=banned_only)
        if prev_page_rows:
            prev_uid = prev_page_rows[-1][0]
            prev_i = len(prev_page_rows) - 1
            nav_row.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"adm_ud_{prev_uid}_{page-1}_{prev_i}_{mode}"))
    # کاربر بعدی
    cur_rows, total = db_get_users_page(page, USERS_PER_PAGE, banned_only=banned_only)
    if idx + 1 < len(cur_rows):
        next_uid = cur_rows[idx + 1][0]
        nav_row.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"adm_ud_{next_uid}_{page}_{idx+1}_{mode}"))
    elif (page + 1) * USERS_PER_PAGE < total:
        next_page_rows, _ = db_get_users_page(page + 1, USERS_PER_PAGE, banned_only=banned_only)
        if next_page_rows:
            next_uid = next_page_rows[0][0]
            nav_row.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"adm_ud_{next_uid}_{page+1}_0_{mode}"))
    if nav_row:
        rows_kb.append(nav_row)

    # دکمه بن/آنبن
    rows_kb.append([
        InlineKeyboardButton(
            text="🔓 آنبن کردن" if banned else "🚫 بن کردن",
            callback_data=f"adm_uban_{uid}_{page}_{idx}_{mode}",
        )
    ])
    # افزودن موجودی
    rows_kb.append([
        InlineKeyboardButton(text="➕ افزودن موجودی", callback_data=f"adm_addbal_{uid}"),
    ])
    # ارسال سرویس (از /myvip)
    rows_kb.append([
        InlineKeyboardButton(text="🌐 ارسال سرویس (/myvip)", callback_data=f"adm_myvip_u_{uid}"),
    ])
    # بازگشت به لیست
    prefix = "adm_banlist_" if banned_only else "adm_users_"
    rows_kb.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data=f"{prefix}{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows_kb)


def user_detail_text(info: dict) -> str:
    name = info.get("full_name") or info.get("username") or "—"
    uname = f"@{info['username']}" if info.get("username") else "—"
    refs_count = db_count_credited_referrals(info["user_id"])
    buy_count, total_paid, total_gb = db_get_user_purchase_stats(info["user_id"])
    gb_str = fa_digits(int(total_gb)) if total_gb == int(total_gb) else fa_digits(f"{total_gb:.1f}")
    return (
        "👤 <b>اطلاعات کاربر</b>\n\n"
        f"🆔 شناسه: <code>{info['user_id']}</code>\n"
        f"👤 نام: {name}\n"
        f"📛 یوزرنیم: {uname}\n"
        f"📦 تعداد خرید: <b>{fa_digits(buy_count)}</b> بار\n"
        f"💵 مجموع پرداختی: <b>{total_paid:,}</b> تومان\n"
        f"📶 مجموع گیگ خریداری‌شده: <b>{gb_str}</b> گیگ\n"
        f"💰 موجودی فعلی: <b>{info['balance']:,}</b> تومان\n"
        f"🪙 سکه‌ها: <b>{fa_digits(info.get('coins', 0))}</b>\n"
        f"👥 تعداد رفرال‌های موفق: <b>{fa_digits(refs_count)}</b>\n"
        f"📅 تاریخ عضویت: {info.get('join_date') or '—'}\n"
        f"⛔️ وضعیت بن: {'بله' if info['is_banned'] else 'خیر'}\n"
    )


@dp.callback_query(F.data.startswith("adm_users_"))
async def cb_adm_users(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "users"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    page = int(call.data.split("_")[-1])
    rows, total = db_get_users_page(page, USERS_PER_PAGE)
    if total == 0:
        await call.message.edit_text("⛔️ کاربری ثبت نشده است.", reply_markup=kb_back("adm_back"))
        return
    await call.message.edit_text(
        f"👥 <b>لیست کاربران</b> (مجموع: {fa_digits(total)})\n\nروی هر کاربر برای جزئیات بزنید:",
        reply_markup=kb_users_page(page, banned_only=False),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("adm_banlist_"))
async def cb_adm_banlist(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "ban"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    page = int(call.data.split("_")[-1])
    rows, total = db_get_users_page(page, USERS_PER_PAGE, banned_only=True)
    if total == 0:
        await call.message.edit_text("✅ هیچ کاربر بن‌شده‌ای وجود ندارد.", reply_markup=kb_back("adm_back"))
        return
    await call.message.edit_text(
        f"📋 <b>کاربران بن‌شده</b> (مجموع: {fa_digits(total)})\n\nروی هر کاربر بزنید:",
        reply_markup=kb_users_page(page, banned_only=True),
        parse_mode=ParseMode.HTML,
    )


# هندلر جدید: کلیک روی کاربر با اطلاعات صفحه و ایندکس
@dp.callback_query(F.data.startswith("adm_ud_"))
async def cb_adm_ud(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    # فرمت: adm_ud_{uid}_{page}_{idx}_{mode}
    parts = call.data.split("_")
    uid = int(parts[2])
    page = int(parts[3])
    idx = int(parts[4])
    mode = parts[5] if len(parts) > 5 else "ul"
    info = db_get_user_full(uid)
    if not info:
        await call.message.edit_text("❌ کاربر یافت نشد.", reply_markup=kb_back("adm_back"))
        return
    await call.message.edit_text(
        user_detail_text(info),
        reply_markup=kb_user_detail(uid, info["is_banned"], page=page, idx=idx, mode=mode),
        parse_mode=ParseMode.HTML,
    )


# هندلر قدیمی adm_user_ برای سازگاری با کدهای قبلی
@dp.callback_query(F.data.startswith("adm_user_"))
async def cb_adm_user(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    info = db_get_user_full(uid)
    if not info:
        await call.message.edit_text("❌ کاربر یافت نشد.", reply_markup=kb_back("adm_back"))
        return
    await call.message.edit_text(
        user_detail_text(info),
        reply_markup=kb_user_detail(uid, info["is_banned"]),
        parse_mode=ParseMode.HTML,
    )


# هندلر جدید بن/آنبن با context صفحه
@dp.callback_query(F.data.startswith("adm_uban_"))
async def cb_adm_uban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "ban"):
        await call.answer("❌", show_alert=True); return
    # فرمت: adm_uban_{uid}_{page}_{idx}_{mode}
    parts = call.data.split("_")
    uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    idx = int(parts[4]) if len(parts) > 4 else 0
    mode = parts[5] if len(parts) > 5 else "ul"
    cur = db_is_banned(uid)
    db_set_ban(uid, 0 if cur else 1)
    await call.answer("✅ وضعیت بن تغییر کرد.")
    info = db_get_user_full(uid)
    if info:
        await call.message.edit_text(
            user_detail_text(info),
            reply_markup=kb_user_detail(uid, info["is_banned"], page=page, idx=idx, mode=mode),
            parse_mode=ParseMode.HTML,
        )


@dp.callback_query(F.data.startswith("adm_userban_"))
async def cb_adm_userban(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "ban"):
        await call.answer("❌", show_alert=True); return
    uid = int(call.data.split("_")[-1])
    cur = db_is_banned(uid)
    db_set_ban(uid, 0 if cur else 1)
    await call.answer("✅ وضعیت تغییر کرد.")
    info = db_get_user_full(uid)
    if info:
        await call.message.edit_text(
            user_detail_text(info),
            reply_markup=kb_user_detail(uid, info["is_banned"]),
            parse_mode=ParseMode.HTML,
        )


# هندلر دریافت لینک اشتراک کاربر
@dp.callback_query(F.data.startswith("adm_sublink_"))
async def cb_adm_sublink(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    services = db_get_user_sub_links(uid)
    if not services:
        await call.answer("⚠️ این کاربر هیچ لینک یا کانفیگ تاییدشده‌ای ندارد.", show_alert=True)
        return
    lines = [f"🔗 <b>لینک‌های اشتراک کاربر {uid}</b>\n"]
    for rid, product, sub_link, config in services:
        label = get_product_label(str(product))
        lines.append(f"── <b>{label}</b> (رسید #{rid})")
        if sub_link:
            lines.append(f"🌐 لینک: <code>{sub_link}</code>")
        if config:
            lines.append(f"⚙️ کانفیگ:\n<code>{config}</code>")
        lines.append("")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data=f"adm_user_{uid}")]
    ])
    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("adm_msg_"))
async def cb_adm_msg(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "users"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.msg_user_text)
    await call.message.edit_text(
        f"✉️ متن پیام برای کاربر <code>{uid}</code> را ارسال کنید:",
        reply_markup=kb_back(f"adm_user_{uid}"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.msg_user_text)
async def msg_user_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    text = message.text or ""
    try:
        await bot.send_message(uid, f"📩 پیام از مدیر:\n\n{text}")
        await message.answer("✅ پیام ارسال شد.", reply_markup=kb_admin(message.from_user.id))
    except Exception as e:
        await message.answer(f"❌ ارسال نشد: {e}", reply_markup=kb_admin(message.from_user.id))
    await state.clear()


@dp.callback_query(F.data.startswith("adm_addbal_"))
async def cb_adm_addbal(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "users"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.addbal_amount)
    await call.message.edit_text(
        f"➕ مبلغ افزودن به موجودی کاربر <code>{uid}</code> را به تومان ارسال کنید:",
        reply_markup=kb_back(f"adm_user_{uid}"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.addbal_amount)
async def addbal_amount_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int((message.text or "0").strip().replace(",", ""))
        if amt <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    db_add_balance(uid, amt)
    await state.clear()
    await message.answer(f"✅ مبلغ {amt:,} تومان به موجودی کاربر <code>{uid}</code> افزوده شد.",
                         reply_markup=kb_admin(message.from_user.id), parse_mode=ParseMode.HTML)
    try:
        await bot.send_message(uid, f"💰 مدیر مبلغ {amt:,} تومان به موجودی شما افزود.")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_subbal_"))
async def cb_adm_subbal(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "users"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.subbal_amount)
    await call.message.edit_text(
        f"➖ مبلغ کسر از موجودی کاربر <code>{uid}</code> را به تومان ارسال کنید:",
        reply_markup=kb_back(f"adm_user_{uid}"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.subbal_amount)
async def subbal_amount_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int((message.text or "0").strip().replace(",", ""))
        if amt <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    db_add_balance(uid, -amt)
    await state.clear()
    await message.answer(f"✅ مبلغ {amt:,} تومان از موجودی کاربر <code>{uid}</code> کسر شد.",
                         reply_markup=kb_admin(message.from_user.id), parse_mode=ParseMode.HTML)
    try:
        await bot.send_message(uid, f"💰 مدیر مبلغ {amt:,} تومان از موجودی شما کسر کرد.")
    except Exception:
        pass


# ==================== 🪙 افزودن/کسر سکه (روی کاربر مشخص) ====================
@dp.callback_query(F.data.startswith("adm_addcoins_"))
async def cb_adm_addcoins(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.addcoins_amount)
    await call.message.edit_text(
        f"🪙➕ تعداد سکه برای افزودن به کاربر <code>{uid}</code> را ارسال کنید:",
        reply_markup=kb_back(f"adm_user_{uid}"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.addcoins_amount)
async def addcoins_amount_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int(fa_to_en_digits((message.text or "0").strip().replace(",", "")))
        if amt <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    new_balance = db_add_coins(uid, amt)
    await state.clear()
    await message.answer(
        f"✅ {fa_digits(amt)} سکه به کاربر <code>{uid}</code> افزوده شد.\n"
        f"🪙 موجودی جدید: <b>{fa_digits(new_balance)}</b>",
        reply_markup=kb_admin(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )
    try:
        await bot.send_message(uid, f"🪙 مدیر {fa_digits(amt)} سکه به حساب شما افزود. (موجودی: {fa_digits(new_balance)})")
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_subcoins_"))
async def cb_adm_subcoins(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    await state.update_data(target_uid=uid)
    await state.set_state(AdminStates.subcoins_amount)
    await call.message.edit_text(
        f"🪙➖ تعداد سکه برای کسر از کاربر <code>{uid}</code> را ارسال کنید:",
        reply_markup=kb_back(f"adm_user_{uid}"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.subcoins_amount)
async def subcoins_amount_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int(fa_to_en_digits((message.text or "0").strip().replace(",", "")))
        if amt <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    uid = data.get("target_uid")
    new_balance = db_add_coins(uid, -amt)
    await state.clear()
    await message.answer(
        f"✅ {fa_digits(amt)} سکه از کاربر <code>{uid}</code> کسر شد.\n"
        f"🪙 موجودی جدید: <b>{fa_digits(new_balance)}</b>",
        reply_markup=kb_admin(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )
    try:
        await bot.send_message(uid, f"🪙 مدیر {fa_digits(amt)} سکه از حساب شما کسر کرد. (موجودی: {fa_digits(new_balance)})")
    except Exception:
        pass


# ==================== 🪙 منوی مدیریت سکه‌ها ====================
def kb_adm_coins() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⚙️ تنظیم سکه کانفیگ رایگان", callback_data="adm_setfreecoins")],
        [InlineKeyboardButton(text="🔁 انتقال سکه بین کاربران", callback_data="adm_transcoins")],
        [InlineKeyboardButton(text="🧹 حذف همگانی سکه‌ها", callback_data="adm_clearcoins")],
        [InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "adm_coins")
async def cb_adm_coins_menu(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await state.clear()
    await call.answer()
    free_cost = int(SETTINGS.get("free_config_coins", 5) or 5)
    coins_per_ref = int(SETTINGS.get("coins_per_referral", 1) or 1)
    txt = (
        "🪙 <b>مدیریت سکه‌ها</b>\n\n"
        f"⚙️ سکه لازم برای کانفیگ رایگان: <b>{fa_digits(free_cost)}</b>\n"
        f"🤝 سکه به ازای هر دعوت موفق: <b>{fa_digits(coins_per_ref)}</b>\n\n"
        "گزینه‌ای را انتخاب کنید 👇"
    )
    await call.message.edit_text(txt, reply_markup=kb_adm_coins(), parse_mode=ParseMode.HTML)


# --- تنظیم سکه کانفیگ رایگان ---
@dp.callback_query(F.data == "adm_setfreecoins")
async def cb_adm_setfreecoins(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    cur = int(SETTINGS.get("free_config_coins", 5) or 5)
    await state.set_state(AdminStates.set_freeconf_coins)
    await call.message.edit_text(
        "⚙️ <b>تنظیم سکه کانفیگ رایگان</b>\n\n"
        f"مقدار فعلی: <b>{fa_digits(cur)}</b> سکه\n\n"
        "تعداد سکه جدید را ارسال کنید (یک عدد بین ۱ تا ۱۰۰۰):",
        reply_markup=kb_back("adm_coins"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.set_freeconf_coins)
async def msg_set_freeconf_coins(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        n = int(fa_to_en_digits((message.text or "").strip()))
        if n < 1 or n > 1000:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد نامعتبر است (۱ تا ۱۰۰۰).")
        return
    s_set("free_config_coins", n)
    await state.clear()
    await message.answer(
        f"✅ سکه لازم برای کانفیگ رایگان روی <b>{fa_digits(n)}</b> تنظیم شد.",
        reply_markup=kb_adm_coins(),
        parse_mode=ParseMode.HTML,
    )


# --- حذف همگانی سکه‌ها ---
@dp.callback_query(F.data == "adm_clearcoins")
async def cb_adm_clearcoins(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rows = [
        [
            InlineKeyboardButton(text="✅ بله، صفر کن", callback_data="adm_clearcoins_yes"),
            InlineKeyboardButton(text="❌ انصراف", callback_data="adm_coins"),
        ],
    ]
    await call.message.edit_text(
        "⚠️ <b>هشدار</b>\n\n"
        "این عمل سکه‌های <b>تمام کاربران</b> را به صفر می‌رساند و قابل بازگشت نیست.\n\n"
        "آیا مطمئن هستید؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "adm_clearcoins_yes")
async def cb_adm_clearcoins_yes(call: CallbackQuery):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    n = db_clear_all_coins()
    await call.answer(f"✅ سکه {n} کاربر صفر شد", show_alert=True)
    await call.message.edit_text(
        f"🧹 سکه‌های همه کاربران پاک شد.\n\n"
        f"📊 تعداد کاربران متاثر: <b>{fa_digits(n)}</b>",
        reply_markup=kb_adm_coins(),
        parse_mode=ParseMode.HTML,
    )


# --- انتقال سکه بین کاربران (با کسر از مبدا) ---
@dp.callback_query(F.data == "adm_transcoins")
async def cb_adm_transcoins(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "coins"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.transfer_coins_from)
    await call.message.edit_text(
        "🔁 <b>انتقال سکه</b>\n\n"
        "🆔 شناسه عددی کاربر <b>مبدا</b> (کسی که از او کسر شود) را ارسال کنید:",
        reply_markup=kb_back("adm_coins"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.transfer_coins_from)
async def msg_transfer_from(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        from_uid = int(fa_to_en_digits((message.text or "").strip()))
    except Exception:
        await message.answer("❌ شناسه عددی معتبر بفرستید.")
        return
    bal = db_get_coins(from_uid)
    await state.update_data(from_uid=from_uid)
    await state.set_state(AdminStates.transfer_coins_to)
    await message.answer(
        f"✅ مبدا: <code>{from_uid}</code> (موجودی: {fa_digits(bal)} سکه)\n\n"
        "🆔 حالا شناسه عددی کاربر <b>مقصد</b> را ارسال کنید:",
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.transfer_coins_to)
async def msg_transfer_to(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        to_uid = int(fa_to_en_digits((message.text or "").strip()))
    except Exception:
        await message.answer("❌ شناسه عددی معتبر بفرستید.")
        return
    await state.update_data(to_uid=to_uid)
    await state.set_state(AdminStates.transfer_coins_amount)
    await message.answer(
        f"✅ مقصد: <code>{to_uid}</code>\n\n"
        "🪙 تعداد سکه برای انتقال را ارسال کنید:",
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.transfer_coins_amount)
async def msg_transfer_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        amt = int(fa_to_en_digits((message.text or "").strip()))
        if amt <= 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    from_uid = data.get("from_uid"); to_uid = data.get("to_uid")
    ok, msg = db_transfer_coins(from_uid, to_uid, amt)
    await state.clear()
    if not ok:
        await message.answer(f"❌ انتقال انجام نشد: {msg}", reply_markup=kb_adm_coins())
        return
    new_from = db_get_coins(from_uid)
    new_to = db_get_coins(to_uid)
    await message.answer(
        f"✅ <b>انتقال موفق</b>\n\n"
        f"🪙 مقدار: <b>{fa_digits(amt)}</b> سکه\n"
        f"📤 از کاربر <code>{from_uid}</code> ⇐ موجودی جدید: {fa_digits(new_from)}\n"
        f"📥 به کاربر <code>{to_uid}</code> ⇐ موجودی جدید: {fa_digits(new_to)}",
        reply_markup=kb_adm_coins(),
        parse_mode=ParseMode.HTML,
    )
    # اطلاع به دو طرف
    for uid, txt in [
        (from_uid, f"🪙 مدیر {fa_digits(amt)} سکه از حساب شما کسر و به کاربر دیگری منتقل کرد. (موجودی: {fa_digits(new_from)})"),
        (to_uid, f"🪙 مدیر {fa_digits(amt)} سکه به حساب شما واریز کرد. (موجودی: {fa_digits(new_to)})"),
    ]:
        try:
            await bot.send_message(uid, txt)
        except Exception:
            pass


# بازگشت به منوی پنل ادمین
@dp.callback_query(F.data == "adm_back")
async def cb_adm_back(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await state.clear()
    await call.answer()
    await call.message.edit_text("👑 پنل مدیریت", reply_markup=kb_admin(call.from_user.id))


# ==================== ویرایش متن‌ها ====================
def kb_texts() -> InlineKeyboardMarkup:
    rows = []
    for key, label in TEXT_NAMES_FA.items():
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_text_{key}")])
    rows.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "adm_texts")
async def cb_adm_texts(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "texts"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "✏️ یکی از متن‌ها را برای ویرایش انتخاب کنید:",
        reply_markup=kb_texts(),
    )


@dp.callback_query(F.data.startswith("adm_text_"))
async def cb_adm_text_edit(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "texts"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    key = call.data[len("adm_text_"):]
    if key not in DEFAULT_TEXTS:
        await call.answer("نامعتبر", show_alert=True); return
    await state.update_data(text_key=key)
    await state.set_state(AdminStates.edit_text)
    cur = get_text(key)
    await call.message.edit_text(
        f"✏️ ویرایش <b>{TEXT_NAMES_FA.get(key, key)}</b>\n\n"
        f"<b>متن فعلی:</b>\n<pre>{cur}</pre>\n\n"
        "متن جدید را ارسال کنید (یا /skip برای انصراف):",
        reply_markup=kb_back("adm_texts"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.edit_text)
async def edit_text_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if (message.text or "").strip() == "/skip":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_admin(message.from_user.id))
        return
    data = await state.get_data()
    key = data.get("text_key")
    new_text = message.text or ""
    if key:
        set_text(key, new_text)
    await state.clear()
    await message.answer(f"✅ متن «{TEXT_NAMES_FA.get(key, key)}» به‌روزرسانی شد.",
                         reply_markup=kb_admin(message.from_user.id))


# ==================== ویرایش برچسب دکمه‌ها ====================
BUTTONS_PER_PAGE = 10


def kb_buttons_page(page: int) -> InlineKeyboardMarkup:
    keys = list(BUTTON_NAMES_FA.keys())
    total = len(keys)
    offset = page * BUTTONS_PER_PAGE
    page_keys = keys[offset:offset + BUTTONS_PER_PAGE]
    rows = []
    for k in page_keys:
        cur = get_button_label(k)
        if len(cur) > 30:
            cur = cur[:30] + "…"
        rows.append([InlineKeyboardButton(text=f"{BUTTON_NAMES_FA[k]}: {cur}", callback_data=f"adm_btn_{k}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"adm_buttons_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"صفحه {page+1}/{max(1,(total+BUTTONS_PER_PAGE-1)//BUTTONS_PER_PAGE)}", callback_data="noop"))
    if (page + 1) * BUTTONS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"adm_buttons_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("adm_buttons_"))
async def cb_adm_buttons(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "buttons"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    page = int(call.data.split("_")[-1])
    await call.message.edit_text(
        "🔘 یکی از دکمه‌ها را برای تغییر برچسب انتخاب کنید:",
        reply_markup=kb_buttons_page(page),
    )


@dp.callback_query(F.data.startswith("adm_btn_"))
async def cb_adm_btn_edit(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id) or not has_perm(call.from_user.id, "buttons"):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    key = call.data[len("adm_btn_"):]
    if key not in DEFAULT_BUTTON_LABELS:
        await call.answer("نامعتبر", show_alert=True); return
    await state.update_data(btn_key=key)
    await state.set_state(AdminStates.edit_button_label)
    cur = get_button_label(key)
    await call.message.edit_text(
        f"🔘 ویرایش برچسب <b>{BUTTON_NAMES_FA.get(key, key)}</b>\n\n"
        f"<b>برچسب فعلی:</b> {cur}\n\n"
        "برچسب جدید را ارسال کنید (یا /skip برای انصراف):",
        reply_markup=kb_back("adm_buttons_0"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.edit_button_label)
async def edit_btn_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if (message.text or "").strip() == "/skip":
        await state.clear()
        await message.answer("لغو شد.", reply_markup=kb_admin(message.from_user.id))
        return
    data = await state.get_data()
    key = data.get("btn_key")
    new_label = (message.text or "").strip()
    if not new_label:
        await message.answer("❌ برچسب نمی‌تواند خالی باشد.")
        return
    if key:
        set_button_label(key, new_label)
    await state.clear()
    await message.answer(f"✅ برچسب «{BUTTON_NAMES_FA.get(key, key)}» به‌روزرسانی شد.",
                         reply_markup=kb_admin(message.from_user.id))


# ==================== مدیریت ادمین‌های جانبی (فقط سوپر ادمین) ====================
def kb_subadmins() -> InlineKeyboardMarkup:
    rows = []
    for sa in get_sub_admins():
        rows.append([InlineKeyboardButton(text=f"👤 {sa.get('name') or sa.get('user_id')}", callback_data=f"adm_subadm_{sa['user_id']}")])
    rows.append([InlineKeyboardButton(text="➕ افزودن ادمین", callback_data="adm_addsubadm")])
    rows.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_subadmin_detail(uid: int) -> InlineKeyboardMarkup:
    sa = find_sub_admin(uid)
    perms = (sa or {}).get("perms", {})
    rows = []
    for p in ALL_PERMS:
        if isinstance(perms, dict):
            on = bool(perms.get(p, False))
        else:
            on = p in perms
        flag = "✅" if on else "⛔️"
        rows.append([InlineKeyboardButton(text=f"{flag} {PERM_NAMES_FA.get(p, p)}", callback_data=f"adm_tgperm_{uid}_{p}")])
    rows.append([InlineKeyboardButton(text="🗑 حذف ادمین", callback_data=f"adm_delsubadm_{uid}")])
    rows.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="adm_subadmins")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "adm_subadmins")
async def cb_adm_subadmins(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌ فقط مدیر اصلی.", show_alert=True); return
    await call.answer()
    sub_list = get_sub_admins()
    txt = "👤 <b>مدیریت ادمین‌های جانبی</b>\n\n"
    if not sub_list:
        txt += "هیچ ادمین جانبی ثبت نشده."
    else:
        txt += f"تعداد: {len(sub_list)}\nروی هر ادمین برای تنظیم دسترسی‌ها بزنید:"
    await call.message.edit_text(txt, reply_markup=kb_subadmins(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "adm_addsubadm")
async def cb_adm_addsubadm(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.add_sub_admin)
    await call.message.edit_text(
        "🆔 شناسه عددی ادمین جدید را ارسال کنید:\n\n"
        "می‌توانید نام را هم با کاما بعد از شناسه بفرستید، مثلاً:\n"
        "<code>123456789, علی</code>",
        reply_markup=kb_back("adm_subadmins"),
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.add_sub_admin)
async def add_subadm_handler(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    name = ""
    if "," in raw:
        a, b = raw.split(",", 1)
        raw = a.strip(); name = b.strip()
    try:
        uid = int(raw)
    except Exception:
        await message.answer("❌ شناسه عددی معتبر بفرستید.")
        return
    if uid in SUPER_ADMIN_IDS:
        await message.answer("⚠️ این شخص خودش مدیر اصلی است.")
        await state.clear()
        return
    add_sub_admin(uid, name=name, perms=list(ALL_PERMS))
    await state.clear()
    await message.answer(
        f"✅ ادمین <code>{uid}</code> با تمام دسترسی‌ها افزوده شد.",
        reply_markup=kb_admin(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )
    # اطلاع به ادمین جدید
    try:
        await bot.send_message(
            uid,
            "👑 شما به عنوان <b>ادمین جانبی</b> ربات اضافه شدید.\n\n"
            "برای دسترسی به پنل مدیریت دستور /start را ارسال کنید.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_subadm_"))
async def cb_adm_subadm_detail(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    sa = find_sub_admin(uid)
    if not sa:
        await call.message.edit_text("❌ پیدا نشد.", reply_markup=kb_back("adm_subadmins"))
        return
    txt = (
        f"👤 <b>ادمین جانبی</b>\n\n"
        f"🆔 شناسه: <code>{uid}</code>\n"
        f"📛 نام: {sa.get('name') or '—'}\n\n"
        f"دسترسی‌ها (✅ فعال / ⛔️ غیرفعال):"
    )
    await call.message.edit_text(txt, reply_markup=kb_subadmin_detail(uid), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("adm_tgperm_"))
async def cb_adm_tgperm(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    parts = call.data.split("_")
    # adm_tgperm_<uid>_<perm>
    uid = int(parts[2])
    perm = "_".join(parts[3:])
    if perm not in ALL_PERMS:
        await call.answer("نامعتبر", show_alert=True); return
    on = toggle_sub_admin_perm(uid, perm)
    await call.answer("✅ فعال شد" if on else "⛔️ غیرفعال شد")
    sa = find_sub_admin(uid)
    if not sa:
        return
    txt = (
        f"👤 <b>ادمین جانبی</b>\n\n"
        f"🆔 شناسه: <code>{uid}</code>\n"
        f"📛 نام: {sa.get('name') or '—'}\n\n"
        f"دسترسی‌ها (✅ فعال / ⛔️ غیرفعال):"
    )
    try:
        await call.message.edit_text(txt, reply_markup=kb_subadmin_detail(uid), parse_mode=ParseMode.HTML)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("adm_delsubadm_"))
async def cb_adm_delsubadm(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    uid = int(call.data.split("_")[-1])
    remove_sub_admin(uid)
    await call.answer("✅ حذف شد")
    sub_list = get_sub_admins()
    txt = "👤 <b>مدیریت ادمین‌های جانبی</b>\n\n"
    if not sub_list:
        txt += "هیچ ادمین جانبی ثبت نشده."
    else:
        txt += f"تعداد: {len(sub_list)}\nروی هر ادمین برای تنظیم دسترسی‌ها بزنید:"
    await call.message.edit_text(txt, reply_markup=kb_subadmins(), parse_mode=ParseMode.HTML)


# ==================== /myvip — لیست خریداران ====================
BUYERS_PER_PAGE = 10


def kb_buyers_page(page: int) -> InlineKeyboardMarkup:
    rows, total = db_get_buyers_page(page, BUYERS_PER_PAGE)
    rows_kb = []
    for i, r in enumerate(rows):
        uid, uname, fname, buy_count = r
        name = fname or uname or str(uid)
        if len(name) > 18:
            name = name[:18] + "…"
        label = f"👤 {name} | 🛒{fa_digits(buy_count)} خرید"
        rows_kb.append([InlineKeyboardButton(text=label, callback_data=f"vip_u_{uid}_{page}_{i}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"vip_pg_{page-1}"))
    pages = max(1, (total + BUYERS_PER_PAGE - 1) // BUYERS_PER_PAGE)
    nav.append(InlineKeyboardButton(text=f"صفحه {page+1}/{pages}", callback_data="noop"))
    if (page + 1) * BUYERS_PER_PAGE < total:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"vip_pg_{page+1}"))
    if nav:
        rows_kb.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows_kb)


def kb_vip_user(uid: int) -> InlineKeyboardMarkup:
    """منوی خریدار: سرویس‌هایش رو نشون بده + ارسال ساب."""
    rows = db_get_user_delivered_services(uid)
    rows_kb = []
    for rid, product, username, config, sub_link in rows[:10]:
        label = get_product_label(str(product))
        has = "✅" if (sub_link or config) else "⏳"
        rows_kb.append([InlineKeyboardButton(
            text=f"{has} {label} | {username}",
            callback_data=f"vip_svc_{rid}",
        )])
    rows_kb.append([InlineKeyboardButton(text="📤 ارسال ساب/کانفیگ جدید", callback_data=f"vip_send_{uid}")])
    rows_kb.append([InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data="vip_pg_0")])
    return InlineKeyboardMarkup(inline_keyboard=rows_kb)


@dp.message(lambda m: m.text and m.text.strip() in ("/myvip", "/myvpn"))
async def cmd_myvip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    _, total = db_get_buyers_page(0, BUYERS_PER_PAGE)
    if total == 0:
        await message.answer("⛔️ هنوز هیچ کاربری خرید نکرده است.")
        return
    await message.answer(
        f"🛒 <b>لیست خریداران</b> (مجموع: {fa_digits(total)})\n\nروی هر کاربر بزنید:",
        reply_markup=kb_buyers_page(0),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("vip_pg_"))
async def cb_vip_page(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    page = int(call.data.split("_")[-1])
    _, total = db_get_buyers_page(page, BUYERS_PER_PAGE)
    await call.message.edit_text(
        f"🛒 <b>لیست خریداران</b> (مجموع: {fa_digits(total)})\n\nروی هر کاربر بزنید:",
        reply_markup=kb_buyers_page(page),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("vip_u_"))
async def cb_vip_user(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    parts = call.data.split("_")
    uid = int(parts[2])
    info = db_get_user_full(uid)
    if not info:
        await call.message.edit_text("❌ کاربر یافت نشد.")
        return
    buy_count, total_paid, total_gb = db_get_user_purchase_stats(uid)
    name = info.get("full_name") or info.get("username") or str(uid)
    uname = f"@{info['username']}" if info.get("username") else "—"
    gb_str = fa_digits(int(total_gb)) if total_gb == int(total_gb) else fa_digits(f"{total_gb:.1f}")
    txt = (
        f"👤 <b>{name}</b> ({uname})\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"🛒 تعداد خرید: <b>{fa_digits(buy_count)}</b>\n"
        f"💵 مجموع پرداختی: <b>{total_paid:,}</b> تومان\n"
        f"📶 مجموع گیگ: <b>{gb_str}</b>\n\n"
        "سرویس‌های تاییدشده 👇"
    )
    await call.message.edit_text(txt, reply_markup=kb_vip_user(uid), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("vip_svc_"))
async def cb_vip_svc(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    rid = int(call.data.split("_")[-1])
    r = db_get_receipt(rid)
    if not r:
        await call.answer("یافت نشد", show_alert=True); return
    _, uid, product, username, amount, _, status, config, sub_link, created = r
    label = get_product_label(str(product))
    txt = (
        f"📦 <b>سرویس #{rid}</b>\n\n"
        f"👤 یوزرنیم: <code>{username}</code>\n"
        f"💾 حجم: {label}\n"
        f"💰 مبلغ: {fmt_price(amount)}\n"
        f"📅 تاریخ: {created or '—'}\n\n"
    )
    if sub_link:
        txt += f"🔗 ساب:\n<code>{sub_link}</code>\n\n"
    if config:
        txt += f"📄 کانفیگ:\n<code>{config}</code>"
    if not sub_link and not config:
        txt += "⏳ هنوز کانفیگ ارسال نشده."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 آپدیت ساب/کانفیگ", callback_data=f"vip_send_{uid}")],
        [InlineKeyboardButton(text=BUTTON_LABELS["back"], callback_data=f"vip_u_{uid}_0_0")],
    ])
    await call.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("vip_send_"))
async def cb_vip_send(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    info = db_get_user_full(uid)
    name = (info.get("full_name") or info.get("username") or str(uid)) if info else str(uid)
    await state.update_data(myvip_target_uid=uid, myvip_target_name=name)
    await state.set_state(AdminStates.myvip_send_sub)
    await call.message.answer(
        f"📤 ارسال ساب/کانفیگ به <b>{name}</b>\n\n"
        "لینک ساب یا کانفیگ را ارسال کنید (یا هر دو را با خط جدید):",
        parse_mode=ParseMode.HTML,
    )


@dp.message(AdminStates.myvip_send_sub)
async def msg_myvip_send_sub(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ متن خالی است."); return
    data = await state.get_data()
    uid = data.get("myvip_target_uid")
    name = data.get("myvip_target_name", str(uid))
    try:
        await bot.send_message(
            uid,
            f"📡 <b>سرویس شما آپدیت شد!</b>\n\n"
            f"<code>{text}</code>",
            parse_mode=ParseMode.HTML,
        )
        await state.clear()
        await message.answer(f"✅ پیام برای {name} ({uid}) ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ ارسال ناموفق: {e}")
        await state.clear()


@dp.callback_query(F.data.startswith("adm_myvip_u_"))
async def cb_adm_myvip_user(call: CallbackQuery, state: FSMContext):
    """از جزئیات کاربر در لیست کاربران → ارسال سرویس."""
    if not is_admin(call.from_user.id):
        await call.answer("❌", show_alert=True); return
    await call.answer()
    uid = int(call.data.split("_")[-1])
    info = db_get_user_full(uid)
    name = (info.get("full_name") or info.get("username") or str(uid)) if info else str(uid)
    await state.update_data(myvip_target_uid=uid, myvip_target_name=name)
    await state.set_state(AdminStates.myvip_send_sub)
    await call.message.answer(
        f"📤 ارسال ساب/کانفیگ به <b>{name}</b>\n\n"
        "لینک ساب یا کانفیگ را ارسال کنید:",
        parse_mode=ParseMode.HTML,
    )


# ==================== Main ====================
async def main():
    global bot
    init_db()
    bot = Bot(token=BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
