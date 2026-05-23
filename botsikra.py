import logging
import sqlite3
import os
import json
import re
import io
import base64
import tempfile
import subprocess
import shutil
import urllib.parse
from datetime import datetime, date

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile, FSInputFile
import asyncio

# ==================== Bold همه متن‌های ربات ====================
# تمام متن‌هایی که از طریق Bot.send_message / Message.answer / Message.edit_text
# ارسال می‌شن به طور خودکار داخل تگ <b>...</b> پیچیده می‌شن. اگه قبلاً با
# تگ <b> شروع شده باشن، دوباره تکرار نمی‌شه. تگ‌های HTML داخلی (مثل <code>،
# <tg-emoji>، <i>) داخل <b> به درستی توسط تلگرام رندر می‌شن.
def _bold_wrap_text(text):
    if text is None or not isinstance(text, str) or not text:
        return text
    s = text.lstrip()
    if s.startswith("<b>") or s.startswith("<B>"):
        return text
    return f"<b>{text}</b>"

def _patch_bold_methods():
    try:
        _orig_bot_send = Bot.send_message
        async def _bot_send_message_bold(self, chat_id, text=None, *args, **kwargs):
            if text is not None:
                text = _bold_wrap_text(text)
            return await _orig_bot_send(self, chat_id, text, *args, **kwargs)
        Bot.send_message = _bot_send_message_bold
    except Exception:
        pass
    try:
        _orig_msg_answer = Message.answer
        async def _msg_answer_bold(self, text=None, *args, **kwargs):
            if text is not None:
                text = _bold_wrap_text(text)
            return await _orig_msg_answer(self, text, *args, **kwargs)
        Message.answer = _msg_answer_bold
    except Exception:
        pass
    try:
        _orig_msg_edit_text = Message.edit_text
        async def _msg_edit_text_bold(self, text=None, *args, **kwargs):
            if text is not None:
                text = _bold_wrap_text(text)
            return await _orig_msg_edit_text(self, text, *args, **kwargs)
        Message.edit_text = _msg_edit_text_bold
    except Exception:
        pass

_patch_bold_methods()

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import jdatetime
except ImportError:
    jdatetime = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

try:
    from mutagen.id3 import ID3, TIT2, TPE1
    from mutagen.mp3 import MP3
except ImportError:
    ID3 = TIT2 = TPE1 = MP3 = None

try:
    from aiogram.enums import ButtonStyle as _RealButtonStyle
    class ButtonStyle:
        PRIMARY = _RealButtonStyle.PRIMARY
        DANGER  = _RealButtonStyle.DANGER
        SUCCESS = _RealButtonStyle.SUCCESS
        DEFAULT = None
except Exception:
    class ButtonStyle:
        PRIMARY = "primary"
        DANGER  = "danger"
        SUCCESS = "success"
        DEFAULT = None
    _orig_ikb_init = InlineKeyboardButton.__init__
    def _patched_ikb_init(self, **kwargs):
        kwargs.pop("style", None)
        _orig_ikb_init(self, **kwargs)
    InlineKeyboardButton.__init__ = _patched_ikb_init

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== تنظیمات ====================
BOT_TOKEN        = "8757886517:AAFWSPrMbu12Eo_Mdm0tqNHkwrGANIq4fs8"
SUPER_ADMIN_IDS  = [8478999016, 6189730344]   # ادمین‌های اصلی - دسترسی کامل
COINS_PER_REFERRAL  = 1
COINS_TO_GET_CONFIG = 3
GEMINI_API_KEY   = "AIzaSyCyyipjH2hBzXMakEwCcMaTfeIOF14aawk"
GEMINI_TEXT_MODEL  = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image-preview"

_BASE_DIR   = "/storage/emulated/0/coinsfil" if os.path.exists("/storage/emulated/0") else os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(_BASE_DIR, "bot@S1K2IR.db")
STATUS_FILE = os.path.join(_BASE_DIR, "bot_status.json")

ALL_PERMS = ["toggle_bot", "stats", "users", "add_config", "delete_configs", "broadcast", "coins", "channels", "support_id", "texts", "buttons", "colors", "ad_channels", "premium_emojis", "start_reaction", "ban_reaction", "smart_channels", "leave_alert", "missions"]
PERM_NAMES = {
    "toggle_bot": "🔴🟢 خاموش/روشن ربات",
    "stats":      "📊 آمار کلی",
    "users":      "👥 لیست کاربران",
    "add_config": "➕ افزودن کانفیگ",
    "delete_configs": "🗑 حذف همه کانفیگ‌ها",
    "broadcast":  "📢 ارسال همگانی",
    "coins":      "💰 مدیریت سکه",
    "channels":   "📡 مدیریت چنل‌ها",
    "support_id": "🛟 تنظیم پشتیبانی",
    "texts":      "✏️ مدیریت متن‌ها",
    "buttons":    "🔘 مدیریت دکمه‌ها",
    "colors":     "🎨 تنظیم رنگ دکمه‌ها",
    "ad_channels":"📣 اد لیست (لینک‌های کمکی)",
    "premium_emojis":"💎 ایموجی پریمیوم",
    "start_reaction":"😀 ری‌اکشن استارت",
    "ban_reaction":"🚫 ری‌اکشن کاربر بن شده",
    "smart_channels":"🤖 جوین اجباری هوشمند",
    "leave_alert":"💬 پیام لفت دادن",
    "missions":   "🎯 مدیریت ماموریت‌ها",
}

# ==================== اموجی پریمیوم ====================
# برای استفاده از اموجی پریمیوم در متن پیام‌ها (روی دکمه‌های شیشه‌ای تلگرام
# قابل استفاده نیست چون تلگرام اجازه نمی‌ده). شناسه اموجی پریمیوم رو از
# پک استیکر پریمیوم برمی‌داری: روی اموجی نگه دار → Copy Emoji → بعد با ربات
# @idstickerbot یا فوروارد به @userinfobot شناسه (custom_emoji_id) رو می‌گیری.
# نمونه استفاده داخل متن: f"سلام {pe('5377498341074542751', '🔥')} خوش اومدی"
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

def pe(emoji_id: str, fallback: str) -> str:
    """ساخت تگ اموجی پریمیوم برای متن HTML."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

def pe_key(key: str, fallback: str) -> str:
    """ساخت تگ اموجی پریمیوم با استفاده از کلید (قابل تغییر از پنل ادمین)."""
    eid = PREMIUM_EMOJIS.get(key, "")
    if not eid:
        return fallback
    return pe(eid, fallback)

# fallback پیش‌فرض برای هر کلید پریمیوم (برای دکمه‌های شیشه‌ای و نمایش اولیه)
PE_KEY_FALLBACK = {
    "fire": "🔥", "heart": "❤️", "rocket": "🚀", "star": "⭐",
    "check": "✅", "crown": "👑", "lock": "🔒", "money": "💰",
    "gift": "🎁", "phone": "📞",
}

def pe_fallback_char(key: str) -> str:
    """fallback کاراکتری برای یک کلید ایموجی پریمیوم (برای دکمه‌های شیشه‌ای)."""
    return PE_KEY_FALLBACK.get(key, "✨")

# ==================== کانفیگ ====================
DEFAULT_TEXTS = {
    "start": (
        f"🔐 با هر بار دعوت یه دوست = 1 سکه 🪙\n"
        f"🎁 با 3 سکه ← یه اتصال رایگان دریافت کن!\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"از منوی پایین شروع کن {pe(PREMIUM_EMOJIS['rocket'], '🚀')}"
    ),
    "join_required": "❌ برای استفاده از ربات باید در کانال ما عضو بشی:",
    "join_required_short": "❌ برای استفاده باید عضو کانال باشی:",
    "not_joined": "❌ هنوز عضو نشدی!",
    "vip_join_required": "🚫 جوین چنل‌های اد لیست نیستی!\n━━━━━━━━━━━━━━━\n\nبرای استفاده از ربات باید توی همه چنل‌های ادلیست VIP زیر هم عضو بشی:",
    "help": "⚠️ راهنمای استفاده از ربات\n━━━━━━━━━━━━━━━\n\n1️⃣ لینک دعوت خودتو از بخش «لینک دعوت» بگیر\n2️⃣ لینکتو برای دوستات بفرست\n3️⃣ به ازای هر دوست = 1 سکه 🪙 می‌گیری\n4️⃣ با 3 سکه → یه اتصال رایگان دریافت کن!",
    "support": "🟢 پشتیبانی\n━━━━━━━━━━━━━━━\n\n📌 در چه مواردی کمک می‌کنیم:\n• مشکل در دریافت کانفیگ\n• مشکل در لینک دعوت\n• اشکال در عملکرد ربات\n\n❌ موارد پشتیبانی نمی‌شه:\n• درخواست کانفیگ رایگان بدون سکه\n• مشکلات اینترنت شخصی\n\n━━━━━━━━━━━━━━━\nنوع درخواست:",
    "sponsor_prompt": "💼 درخواست اسپانسر\n━━━━━━━━━━━━━━━\n\nپیام خود را برای اسپانسر شدن بنویسید:\n\n💡 لطفاً ذکر کنید:\n• معرفی کانال/گروه\n• تعداد اعضا\n• نوع همکاری\n\nپیام خود را ارسال کنید 👇",
    "support_question_prompt": "❓ سوال / مشکل\n━━━━━━━━━━━━━━━\n\nسوال یا مشکل خود را بنویسید 👇",
    "referral_response": (
        "🔗 لینک دعوت تو:\n\n<code>{link}</code>\n\n━━━━━━━━━━━━━━━\n"
        "👥 تعداد دعوت‌شده‌ها: {ref_count} نفر\n🪙 سکه‌های فعلی: {coins}\n"
        "🎯 نیاز داری: {needed} سکه\n━━━━━━━━━━━━━━━\n\n"
        "هر دعوت = {per_ref} سکه 🪙\nلینکتو برای دوستات بفرست!"
    ),
    "leave_alert": "😔 رفیق چرا لفت دادی از {channel}؟\n\nبرای استفاده از ربات حتما باید عضو کانال باشی.\nبرگرد دوباره عضو شو 🙏",
    "bot_disabled": "🔴 ربات درحال بروزرسانی هست\nبزودی روشن می‌شود 🙏",
    "banned_user": "⛔️ حساب شما مسدود شده است.",
    "no_coins": "❌ سکه کافی نداری رفیق!\n\n🪙 سکه فعلی تو: {coins}\n🎯 نیاز داری: {needed} سکه\n📉 کمبود داری: {lacking} سکه\n\n👥 دوستاتو دعوت کن!\nهر دعوت = {per_ref} سکه 🪙",
    "no_config_available": "😔 متأسفانه در حال حاضر کانفیگ موجود نیست.\nکمی صبر کن!",
    "config_received": "✅ اتصال رایگان تو اینه رفیق!\n\n<code>{config}</code>\n\n🪙 {cost} سکه از حسابت کسر شد.",
    "referral_notif": "🎉 یه نفر با لینک دعوت تو وارد ربات شد و عضو کانال شد!\n+{coins} سکه به حسابت اضافه شد 🪙",
    "account_info": "👤 حساب من\n━━━━━━━━━━━━━━━\n🆔 آیدی: <code>{user_id}</code>\n📛 نام: {name}\n🪙 سکه: {coins}\n👥 زیرمجموعه: {refs} نفر\n📉 سکه مصرف‌شده: {spent}\n🎁 اتصال دریافت‌شده: {configs}\n📌 وضعیت: {status}\n━━━━━━━━━━━━━━━",
    "my_configs_empty": "📦 کانفیگ‌های من\n━━━━━━━━━━━━━━━\n\nهنوز هیچ کانفیگی دریافت نکردی!\nاز منوی اصلی روی «اتصال رایگان» بزن تا اولین کانفیگتو بگیری 🎁",
    "my_configs_header": "📦 کانفیگ‌های من\n━━━━━━━━━━━━━━━\n\nتعداد کل کانفیگ‌های دریافتی: {count}\n\nدر حال ارسال کانفیگ‌ها برای شما... 👇",
    "config_item": "📦 کانفیگ #{num}\n📅 تاریخ دریافت: {date}\n\n<code>{config}</code>",
    "coin_transfer_notif": "🎁 ادمین ربات {amount} سکه به حسابت اضافه کرد!\n\n🪙 سکه جدید: {new_coins}",
    "missions_header": "🎯 ماموریت‌ها\n━━━━━━━━━━━━━━━\n\nبا انجام ماموریت‌ها سکه رایگان بگیر!\nپیشرفت خودت رو ببین و جایزه بگیر 👇",
    "missions_empty": "🎯 ماموریت‌ها\n━━━━━━━━━━━━━━━\n\nهنوز هیچ ماموریتی تعریف نشده!\nبزودی ماموریت‌های جدید اضافه می‌شن 🚀",
    "mission_completed_notif": "🎉 ماموریت «{title}» رو انجام دادی!\n+{reward} سکه به حسابت اضافه شد 🪙",
    "mission_already_claimed": "✅ جایزه این ماموریت قبلاً دریافت شده است.",
    "mission_not_done": "❌ هنوز این ماموریت رو کامل نکردی!\n\n📊 پیشرفت فعلی: {progress}/{target}",
    "leaderboard_header_refs": "🏆 نفرات برتر — بیشترین دعوت\n━━━━━━━━━━━━━━━\n\n👥 برترین‌ها بر اساس تعداد دعوت:\n\n",
    "leaderboard_header_coins": "🏆 نفرات برتر — بیشترین سکه\n━━━━━━━━━━━━━━━\n\n🪙 برترین‌ها بر اساس سکه:\n\n",
    "leaderboard_header_configs": "🏆 نفرات برتر — بیشترین اتصال\n━━━━━━━━━━━━━━━\n\n📦 برترین‌ها بر اساس اتصال دریافت‌شده:\n\n",
    "leaderboard_your_rank": "\n━━━━━━━━━━━━━━━\n📌 رتبه شما: #{rank}",
    "leaderboard_not_ranked": "\n━━━━━━━━━━━━━━━\n📌 رتبه شما در این جدول ثبت نشده.",
}

TEXT_NAMES = {
    "start": "متن شروع / منوی اصلی",
    "join_required": "متن الزام عضویت (کانال اصلی)",
    "join_required_short": "متن الزام عضویت کوتاه",
    "not_joined": "متن هنوز عضو نشدی",
    "vip_join_required": "متن الزام عضویت ادلیست VIP",
    "help": "متن راهنما",
    "support": "متن پشتیبانی",
    "sponsor_prompt": "متن درخواست اسپانسر",
    "support_question_prompt": "متن سوال / مشکل",
    "referral_response": "متن لینک دعوت ({link} {ref_count} {coins} {needed} {per_ref})",
    "leave_alert": "متن لفت دادن از کانال ({channel})",
    "bot_disabled": "متن ربات خاموش است",
    "no_coins": "متن کمبود سکه ({coins} {needed} {lacking} {per_ref})",
    "no_config_available": "متن نبود کانفیگ موجود",
    "config_received": "متن دریافت کانفیگ ({config} {cost})",
    "referral_notif": "متن اطلاع‌رسانی دعوت به معرف ({coins})",
    "account_info": "متن حساب کاربری ({user_id} {name} {coins} {refs} {spent} {configs} {status})",
    "my_configs_empty": "متن نبود کانفیگ در «کانفیگ‌های من»",
    "my_configs_header": "متن سربرگ «کانفیگ‌های من» ({count})",
    "config_item": "متن هر کانفیگ در لیست ({num} {date} {config})",
    "coin_transfer_notif": "متن اطلاع‌رسانی انتقال سکه به کاربر ({amount} {new_coins})",
    "missions_header": "متن سربرگ بخش ماموریت‌ها",
    "missions_empty": "متن وقتی ماموریتی تعریف نشده",
    "mission_completed_notif": "متن اعلان تکمیل ماموریت ({title} {reward})",
    "mission_already_claimed": "متن جایزه قبلاً دریافت شده",
    "mission_not_done": "متن ماموریت تکمیل نشده ({progress} {target})",
    "leaderboard_header_refs": "متن سربرگ جدول دعوت‌ها",
    "leaderboard_header_coins": "متن سربرگ جدول سکه‌ها",
    "leaderboard_header_configs": "متن سربرگ جدول اتصال‌ها",
    "leaderboard_your_rank": "متن رتبه کاربر در جدول ({rank})",
    "leaderboard_not_ranked": "متن وقتی کاربر رتبه ندارد",
}

DEFAULT_BUTTONS = {
    "main_get_config": "اتصال رایگان 🤩",
    "main_my_configs": "کانفیگ‌های من 📦",
    "main_account": "حساب من 👤",
    "main_referral": "لینک دعوت 🔗",
    "main_support": "پشتیبانی 🟢",
    "main_help": "راهنما 📖",
    "main_admin": "🛠 پنل مدیریت",
    "admin_toggle_on": "🟢 ربات روشن | خاموش کن",
    "admin_toggle_off": "🔴 ربات خاموش | روشن کن",
    "admin_support": "🛟 پشتیبانی:",
    "admin_stats": "📊 آمار کلی",
    "admin_users": "👥 لیست کاربران",
    "admin_add_config": "➕ افزودن کانفیگ",
    "admin_broadcast": "📢 ارسال همگانی",
    "admin_addcoins": "💰 انتقال سکه",
    "admin_subcoins": "➖ کسر سکه",
    "admin_reset_all_coins": "🗑 حذف سکه همگانی",
    "confirm_reset_coins": "✅ تایید",
    "reject_reset_coins": "❌ رد",
    "admin_set_coins_needed": "🎯 تنظیم سکه دریافت کانفیگ",
    "admin_channels": "📡 مدیریت چنل‌ها",
    "admin_texts": "✏️ مدیریت متن‌ها",
    "admin_buttons": "🔘 مدیریت دکمه‌ها",
    "admin_manage_admins": "👤 مدیریت ادمین‌ها",
    "admin_ban_direct": "🚫 بن کاربر",
    "admin_unban_direct": "🔓 آنبن کاربر",
    "admin_banlist": "📋 لیست بن‌ها",
    "back_main": "🔙 بازگشت",
    "back_panel": "🔙 بازگشت به پنل",
    "cancel": "❌ لغو",
    "cancel_action": "❌ انصراف",
    "check_join": "✅ عضو شدم",
    "join_channel": "عضویت در",
    "ban_user": "🚫 بن کاربر",
    "unban_user": "🔓 آنبن کاربر",
    "msg_user": "✉️ پیام به کاربر",
    "send_coin_user": "➕ فرستادن سکه",
    "sub_coin_user": "➖ کسر سکه",
    "delete_admin": "🗑 حذف این ادمین",
    "get_referral": "🔗 دریافت لینک رفرال",
    "support_sponsor": "💼 اسپانسر",
    "support_question": "❓ سوالات غیر اسپانسری",
    "bot_off": "🔴 خاموش",
    "bot_on": "🟢 روشن",
    "prev_page": "◀️ قبلی",
    "next_page": "بعدی ▶️",
    "add_channel": "➕ اضافه کردن چنل",
    "delete_channel": "🗑 حذف",
    "add_admin": "➕ اضافه کردن ادمین",
    "broadcast_pin": "📌 ارسال + پین",
    "broadcast_send": "📤 فقط ارسال",
    "broadcast_unpin_all": "📍 حذف پین همگانی",
    "confirm_unban": "✅ تایید آنبن",
    "like_btn": "♥️",
    "admin_colors": "🎨 تنظیم رنگ دکمه‌ها",
    "color_red": "🔴 قرمز",
    "color_green": "🟢 سبز",
    "color_blue": "🔵 آبی",
    "color_default": "⚪ معمولی (شیشه‌ای)",
    "admin_ad_channels": "📣 ادلیست VIP",
    "admin_premium_emojis": "💎 ایموجی پریمیوم متن‌ها",
    "admin_start_reaction": "😀 ری‌اکشن استارت",
    "ad_add": "➕ افزودن ادلیست VIP",
    "ad_delete": "🗑 حذف",
    "ad_edit_text": "✏️ تغییر متن",
    "ad_edit_color": "🎨 تغییر رنگ",
    "premium_add": "➕ افزودن/ویرایش ایموجی",
    "premium_delete": "🗑 حذف",
    "reaction_set": "✏️ تنظیم آیدی ایموجی",
    "reaction_clear": "🗑 خاموش کردن ری‌اکشن",
    "admin_smart_channels": "🤖 جوین اجباری هوشمند",
    "admin_leave_alert": "💬 پیام لفت دادن",
    "admin_delete_all_configs": "🗑 حذف همه کانفیگ‌ها",
    "confirm_delete_configs": "✅ بله، همه پاک شن",
    "reject_delete_configs": "❌ نه، صرف نظر",
    "smart_add": "➕ افزودن کانال هوشمند",
    "smart_set_threshold": "🎯 تنظیم حد عضو",
    "smart_remove_now": "🗑 حذف فوری",
    "leave_alert_toggle": "🔁 تغییر وضعیت",
    "leave_alert_edit": "✏️ ویرایش متن",
    "pe_pos_left": "⬅️ چپ (اول)",
    "pe_pos_right": "➡️ راست (آخر)",
    "main_missions": "🎯 ماموریت‌ها",
    "main_leaderboard": "🏆 نفرات برتر",
    "admin_missions": "🎯 مدیریت ماموریت‌ها",
    "mission_claim": "✅ دریافت جایزه",
    "mission_add": "➕ ماموریت جدید",
    "mission_toggle_active": "✅ فعال",
    "mission_toggle_inactive": "🔴 غیرفعال",
    "mission_delete": "🗑 حذف",
    "leaderboard_by_refs": "👥 برترین دعوت‌کننده‌ها",
    "leaderboard_by_coins": "🪙 بیشترین سکه",
    "leaderboard_by_configs": "📦 بیشترین اتصال",
}

BUTTON_NAMES = {
    "main_get_config": "دکمه اتصال رایگان",
    "main_my_configs": "دکمه کانفیگ‌های من",
    "main_account": "دکمه حساب من",
    "main_referral": "دکمه لینک دعوت",
    "main_support": "دکمه پشتیبانی",
    "main_help": "دکمه راهنما",
    "main_admin": "دکمه پنل مدیریت",
    "admin_toggle_on": "دکمه وضعیت ربات وقتی روشن است",
    "admin_toggle_off": "دکمه وضعیت ربات وقتی خاموش است",
    "admin_support": "دکمه تنظیم پشتیبانی",
    "admin_stats": "دکمه آمار کلی",
    "admin_users": "دکمه لیست کاربران",
    "admin_add_config": "دکمه افزودن کانفیگ",
    "admin_broadcast": "دکمه ارسال همگانی",
    "admin_addcoins": "دکمه انتقال سکه",
    "admin_subcoins": "دکمه کسر سکه",
    "admin_reset_all_coins": "دکمه حذف سکه همگانی",
    "confirm_reset_coins": "دکمه تایید حذف سکه همگانی",
    "reject_reset_coins": "دکمه رد حذف سکه همگانی",
    "admin_set_coins_needed": "دکمه تنظیم سکه نیاز برای دریافت کانفیگ",
    "admin_channels": "دکمه مدیریت چنل‌ها",
    "admin_texts": "دکمه مدیریت متن‌ها",
    "admin_buttons": "دکمه مدیریت دکمه‌ها",
    "admin_manage_admins": "دکمه مدیریت ادمین‌ها",
    "admin_ban_direct": "دکمه بن کاربر در پنل",
    "admin_unban_direct": "دکمه آنبن کاربر در پنل",
    "admin_banlist": "دکمه لیست بن‌ها",
    "back_main": "دکمه بازگشت",
    "back_panel": "دکمه بازگشت به پنل",
    "cancel": "دکمه لغو",
    "cancel_action": "دکمه انصراف",
    "check_join": "دکمه عضو شدم",
    "join_channel": "دکمه عضویت در کانال",
    "ban_user": "دکمه بن کاربر",
    "unban_user": "دکمه آنبن کاربر",
    "msg_user": "دکمه پیام به کاربر",
    "send_coin_user": "دکمه فرستادن سکه",
    "sub_coin_user": "دکمه کسر سکه از کاربر",
    "delete_admin": "دکمه حذف ادمین",
    "get_referral": "دکمه دریافت لینک رفرال",
    "support_sponsor": "دکمه اسپانسر",
    "support_question": "دکمه سوالات غیر اسپانسری",
    "bot_off": "دکمه خاموش کردن",
    "bot_on": "دکمه روشن کردن",
    "prev_page": "دکمه صفحه قبلی",
    "next_page": "دکمه صفحه بعدی",
    "add_channel": "دکمه اضافه کردن چنل",
    "delete_channel": "دکمه حذف چنل",
    "add_admin": "دکمه اضافه کردن ادمین",
    "broadcast_pin": "دکمه ارسال همگانی + پین",
    "broadcast_send": "دکمه ارسال همگانی بدون پین",
    "broadcast_unpin_all": "دکمه حذف پین همگانی",
    "confirm_unban": "دکمه تایید آنبن",
    "like_btn": "دکمه لایک پست",
    "admin_colors": "دکمه تنظیم رنگ دکمه‌ها در پنل",
    "admin_ad_channels": "دکمه مدیریت اد لیست در پنل",
    "admin_premium_emojis": "دکمه ایموجی پریمیوم در پنل",
    "admin_start_reaction": "دکمه ری‌اکشن استارت در پنل",
    "ad_add": "دکمه افزودن به اد لیست",
    "ad_delete": "دکمه حذف از اد لیست",
    "ad_edit_text": "دکمه تغییر متن آیتم اد لیست",
    "ad_edit_color": "دکمه تغییر رنگ آیتم اد لیست",
    "premium_add": "دکمه افزودن/ویرایش ایموجی پریمیوم",
    "premium_delete": "دکمه حذف ایموجی پریمیوم",
    "reaction_set": "دکمه تنظیم آیدی ری‌اکشن",
    "reaction_clear": "دکمه خاموش کردن ری‌اکشن",
    "admin_smart_channels": "دکمه جوین اجباری هوشمند در پنل",
    "admin_leave_alert": "دکمه پیام لفت دادن در پنل",
    "admin_delete_all_configs": "دکمه حذف همه کانفیگ‌ها",
    "confirm_delete_configs": "دکمه تایید حذف کل کانفیگ‌ها",
    "reject_delete_configs": "دکمه رد حذف کل کانفیگ‌ها",
    "smart_add": "دکمه افزودن کانال هوشمند",
    "smart_set_threshold": "دکمه تنظیم حد عضو هوشمند",
    "smart_remove_now": "دکمه حذف فوری کانال هوشمند",
    "leave_alert_toggle": "دکمه تغییر وضعیت پیام لفت",
    "leave_alert_edit": "دکمه ویرایش متن پیام لفت",
    "pe_pos_left": "دکمه قرار دادن ایموجی چپ",
    "pe_pos_right": "دکمه قرار دادن ایموجی راست",
    "main_missions": "دکمه ماموریت‌ها در منوی اصلی",
    "main_leaderboard": "دکمه نفرات برتر در منوی اصلی",
    "admin_missions": "دکمه مدیریت ماموریت‌ها در پنل",
    "mission_claim": "دکمه دریافت جایزه ماموریت",
    "mission_add": "دکمه افزودن ماموریت جدید",
    "mission_delete": "دکمه حذف ماموریت",
    "leaderboard_by_refs": "دکمه جدول برترین دعوت‌کننده‌ها",
    "leaderboard_by_coins": "دکمه جدول بیشترین سکه",
    "leaderboard_by_configs": "دکمه جدول بیشترین اتصال",
}

# ==================== رنگ پیش‌فرض دکمه‌ها ====================
DEFAULT_BUTTON_COLORS = {
    "main_get_config": "primary",
    "main_account": "danger",
    "main_referral": "danger",
    "main_my_configs": "primary",
    "main_support": "success",
    "main_help": "success",
    "main_admin": "default",
    "like_btn": "success",
    "support_sponsor": "primary",
    "support_question": "success",
    "delete_admin": "danger",
    "delete_channel": "danger",
    "add_channel": "success",
    "add_admin": "success",
    "broadcast_pin": "primary",
    "broadcast_send": "success",
    "confirm_unban": "danger",
    "join_channel": "danger",
    "check_join": "success",
    "get_referral": "primary",
    "main_missions": "primary",
    "main_leaderboard": "success",
    "mission_claim": "success",
}

def load_config() -> dict:
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["texts"] = {**DEFAULT_TEXTS, **data.get("texts", {})}
                data["buttons"] = {**DEFAULT_BUTTONS, **data.get("buttons", {})}
                data["colors"] = {**DEFAULT_BUTTON_COLORS, **data.get("colors", {})}
                data.setdefault("like_posts", {})
                data.setdefault("ad_channels", [])
                data.setdefault("premium_emojis_overrides", {})
                data.setdefault("start_reaction", {"enabled": False, "emoji_id": "", "fallback": "🔥"})
                data.setdefault("leave_alert_enabled", True)
                data.setdefault("smart_channels", [])
                return data
    except:
        pass
    return {"enabled": True, "support_id": "", "channels": ["@v2ray_404"], "sub_admins": {},
            "texts": DEFAULT_TEXTS.copy(), "buttons": DEFAULT_BUTTONS.copy(),
            "colors": DEFAULT_BUTTON_COLORS.copy(), "like_posts": {},
            "ad_channels": [], "premium_emojis_overrides": {},
            "start_reaction": {"enabled": False, "emoji_id": "", "fallback": "🔥"},
            "leave_alert_enabled": True,
            "smart_channels": []}

def save_config(data: dict):
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass

_config      = load_config()
BOT_ENABLED  = _config.get("enabled", True)
SUPPORT_ID   = _config.get("support_id", "")
try:
    COINS_TO_GET_CONFIG = int(_config.get("coins_to_get_config", COINS_TO_GET_CONFIG))
except Exception:
    pass
CHANNEL_IDS: list = _config.get("channels", ["@v2ray_404"])
SUB_ADMINS: dict  = _config.get("sub_admins", {})
BOT_TEXTS: dict    = {**DEFAULT_TEXTS, **_config.get("texts", {})}
BOT_BUTTONS: dict  = {**DEFAULT_BUTTONS, **_config.get("buttons", {})}
BOT_COLORS: dict   = {**DEFAULT_BUTTON_COLORS, **_config.get("colors", {})}
LIKE_POSTS: dict   = _config.get("like_posts", {})

# اد لیست (لینک‌های کمکی) - هر آیتم: {"text": "...", "url": "...", "color": "primary|danger|success|default"}
AD_CHANNELS: list = _config.get("ad_channels", [])
# overrideهای ایموجی پریمیوم - کلید همان کلید PREMIUM_EMOJIS است
PREMIUM_EMOJIS_OVERRIDES: dict = _config.get("premium_emojis_overrides", {})
# اعمال override روی PREMIUM_EMOJIS
for _k, _v in PREMIUM_EMOJIS_OVERRIDES.items():
    if _v:
        PREMIUM_EMOJIS[_k] = str(_v)
# تنظیمات ری‌اکشن استارت
START_REACTION: dict = _config.get("start_reaction", {"enabled": False, "emoji_id": "", "fallback": "🔥"})
# تنظیمات ری‌اکشن کاربر بن شده
BAN_REACTION: dict = _config.get("ban_reaction", {"enabled": False, "emoji": "👎"})
# آیا پیام «لفت دادی» فعال باشد
LEAVE_ALERT_ENABLED: bool = bool(_config.get("leave_alert_enabled", True))
# کانال‌های جوین اجباری هوشمند: لیست از dict
# هر آیتم: {"chat_id": "@username یا -100...", "url": "https://t.me/...", "threshold": 1000, "label": "..."}
SMART_CHANNELS: list = _config.get("smart_channels", [])

def save_smart_channels():
    cfg = load_config(); cfg["smart_channels"] = SMART_CHANNELS; save_config(cfg)

def save_leave_alert_enabled():
    cfg = load_config(); cfg["leave_alert_enabled"] = LEAVE_ALERT_ENABLED; save_config(cfg)

_COLOR_TO_STYLE = {
    "primary": ButtonStyle.PRIMARY,
    "danger":  ButtonStyle.DANGER,
    "success": ButtonStyle.SUCCESS,
    "default": ButtonStyle.DEFAULT,
}

def get_btn_color(key: str) -> str:
    return BOT_COLORS.get(key, DEFAULT_BUTTON_COLORS.get(key, "default"))

def style_of(key: str):
    return _COLOR_TO_STYLE.get(get_btn_color(key), ButtonStyle.DEFAULT)

def save_btn_color(key: str, color: str):
    BOT_COLORS[key] = color
    cfg = load_config(); cfg["colors"] = BOT_COLORS; save_config(cfg)

def save_like_posts():
    cfg = load_config(); cfg["like_posts"] = LIKE_POSTS; save_config(cfg)

def get_bot_text(key: str) -> str:
    return BOT_TEXTS.get(key, DEFAULT_TEXTS.get(key, ""))

def save_bot_text(key: str, value: str):
    BOT_TEXTS[key] = value
    cfg = load_config()
    cfg["texts"] = BOT_TEXTS
    save_config(cfg)

def get_button_text(key: str) -> str:
    return BOT_BUTTONS.get(key, DEFAULT_BUTTONS.get(key, ""))

def save_button_text(key: str, value: str):
    BOT_BUTTONS[key] = value
    cfg = load_config()
    cfg["buttons"] = BOT_BUTTONS
    save_config(cfg)

# ==================== توابع اد لیست ====================
def save_ad_channels():
    cfg = load_config()
    cfg["ad_channels"] = AD_CHANNELS
    save_config(cfg)

def style_of_color(color: str):
    return _COLOR_TO_STYLE.get(color, ButtonStyle.DEFAULT)

# ==================== توابع ایموجی پریمیوم ====================
def save_premium_overrides():
    cfg = load_config()
    cfg["premium_emojis_overrides"] = PREMIUM_EMOJIS_OVERRIDES
    save_config(cfg)

def set_premium_emoji(key: str, emoji_id: str):
    key = key.strip()
    emoji_id = emoji_id.strip()
    if not key:
        return
    PREMIUM_EMOJIS_OVERRIDES[key] = emoji_id
    PREMIUM_EMOJIS[key] = emoji_id
    save_premium_overrides()

def remove_premium_emoji(key: str):
    PREMIUM_EMOJIS_OVERRIDES.pop(key, None)
    PREMIUM_EMOJIS.pop(key, None)
    save_premium_overrides()

# ==================== توابع کار با ایموجی پریمیوم در پیام ====================
def first_premium_emoji_id(message) -> str:
    """اولین custom_emoji_id را از entity‌های پیام برمی‌گرداند (اگر کاربر ایموجی پریمیوم فرستاده باشد)."""
    try:
        ents = list(getattr(message, "entities", None) or []) + list(getattr(message, "caption_entities", None) or [])
        for e in ents:
            if getattr(e, "type", None) == "custom_emoji" and getattr(e, "custom_emoji_id", None):
                return str(e.custom_emoji_id)
    except Exception:
        pass
    return ""

def first_premium_emoji_char(message) -> str:
    """خود کاراکتر ایموجی پریمیوم در متن پیام را برمی‌گرداند (برای fallback / دکمه‌ها)."""
    try:
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "")
        ents = list(getattr(message, "entities", None) or []) + list(getattr(message, "caption_entities", None) or [])
        if not text:
            return ""
        utf16 = text.encode("utf-16-le")
        for e in ents:
            if getattr(e, "type", None) == "custom_emoji":
                start = e.offset * 2
                end = start + e.length * 2
                return utf16[start:end].decode("utf-16-le", errors="ignore")
    except Exception:
        pass
    return ""

def text_with_premium_html(message) -> str:
    """متن پیام را با جایگزینی ایموجی‌های پریمیوم با تگ <tg-emoji> برمی‌گرداند تا داخل پیام HTML کار کند."""
    try:
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "")
        ents = list(getattr(message, "entities", None) or []) + list(getattr(message, "caption_entities", None) or [])
        if not text:
            return ""
        custom_emojis = [e for e in ents if getattr(e, "type", None) == "custom_emoji"]
        if not custom_emojis:
            return text
        utf16 = text.encode("utf-16-le")
        # از انتها به ابتدا تا offsetها بهم نریزن
        sorted_ents = sorted(custom_emojis, key=lambda e: e.offset, reverse=True)
        for ent in sorted_ents:
            start = ent.offset * 2
            end = start + ent.length * 2
            chunk = utf16[start:end].decode("utf-16-le", errors="ignore")
            rep = f'<tg-emoji emoji-id="{ent.custom_emoji_id}">{chunk}</tg-emoji>'
            utf16 = utf16[:start] + rep.encode("utf-16-le") + utf16[end:]
        return utf16.decode("utf-16-le", errors="ignore")
    except Exception:
        return getattr(message, "text", None) or getattr(message, "caption", None) or ""

# ==================== توابع ری‌اکشن استارت ====================
def save_start_reaction():
    cfg = load_config()
    cfg["start_reaction"] = START_REACTION
    save_config(cfg)

def save_ban_reaction():
    cfg = load_config()
    cfg["ban_reaction"] = BAN_REACTION
    save_config(cfg)

# ==================== توابع دسترسی ====================
def is_any_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS or str(user_id) in SUB_ADMINS

def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS

def has_perm(user_id: int, perm: str) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    perms = SUB_ADMINS.get(str(user_id), {})
    return perms.get(perm, False)

# ==================== FSM States ====================
class AdminStates(StatesGroup):
    waiting_config_count    = State()
    waiting_config_item     = State()
    config_forward_session  = State()   # آپلود کانفیگ یک‌به‌یک (فوروارد + دون)
    broadcast               = State()
    broadcast_choose_pin    = State()
    broadcast_delete_id     = State()   # حذف پیام همگانی با شناسه
    add_coins_id            = State()
    add_coins_amount        = State()
    sub_coins_id            = State()
    sub_coins_amount        = State()
    msg_user_text           = State()
    set_support_id          = State()
    add_channel             = State()
    add_admin_id            = State()
    edit_bot_text           = State()
    edit_button_text        = State()
    ban_direct_id           = State()
    unban_direct_id         = State()
    set_coins_needed        = State()
    ad_add_text             = State()
    ad_add_url              = State()
    ad_add_chat_id          = State()
    ad_add_count            = State()
    ad_add_channels         = State()
    ad_add_label            = State()
    ad_edit_text            = State()
    premium_add_key         = State()
    premium_add_id          = State()
    reaction_set_id         = State()
    smart_add_chat          = State()
    smart_add_url           = State()
    smart_add_threshold     = State()
    smart_set_threshold     = State()
    leave_alert_edit        = State()
    mission_add_title       = State()
    mission_add_desc        = State()
    mission_add_type        = State()
    mission_add_target      = State()
    mission_add_reward      = State()

class SpecialStates(StatesGroup):
    like_link            = State()
    like_name            = State()
    ai_chat              = State()
    dl_link              = State()
    music_query          = State()
    logo_name            = State()
    voice_title          = State()

class UserStates(StatesGroup):
    sponsor_msg  = State()
    support_msg  = State()

# ==================== دیتابیس ====================
def init_db():
    if os.path.dirname(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
        coins INTEGER DEFAULT 0, referred_by INTEGER DEFAULT NULL,
        join_date TEXT, is_banned INTEGER DEFAULT 0, configs_received INTEGER DEFAULT 0,
        referral_credited INTEGER DEFAULT 0)""")
    try:
        c.execute("ALTER TABLE users ADD COLUMN referral_credited INTEGER DEFAULT 0")
    except:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
        is_used INTEGER DEFAULT 0, used_by INTEGER DEFAULT NULL, used_at TEXT DEFAULT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)""")
    for key in ("total_users", "configs_given", "total_referrals"):
        c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)", (key,))
    c.execute("""CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        reward_coins INTEGER DEFAULT 10,
        mission_type TEXT NOT NULL,
        target_count INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_missions (
        user_id INTEGER NOT NULL,
        mission_id INTEGER NOT NULL,
        claimed INTEGER DEFAULT 0,
        claimed_at TEXT,
        PRIMARY KEY (user_id, mission_id)
    )""")
    # جدول پیام‌های ارسال‌شده در بردکست (برای قابلیت حذف)
    c.execute("""CREATE TABLE IF NOT EXISTS broadcast_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        broadcast_tag TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL
    )""")
    # جدول پری‌بن (بن کاربرانی که هنوز ربات رو استارت نزدن)
    c.execute("""CREATE TABLE IF NOT EXISTS pre_bans (
        user_id INTEGER PRIMARY KEY
    )""")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone(); conn.close(); return row

def add_user(user_id, username, full_name, referred_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO users
        (user_id, username, full_name, coins, referred_by, join_date, is_banned, configs_received)
        VALUES (?, ?, ?, 0, ?, ?, 0, 0)""",
        (user_id, username, full_name, referred_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    inserted = c.rowcount; conn.commit(); conn.close(); return inserted == 1

def get_all_users_paginated(page, per_page=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, full_name, coins, is_banned, configs_received FROM users LIMIT ? OFFSET ?",
              (per_page, page * per_page))
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]; conn.close(); return rows, total

def get_banned_users_paginated(page, per_page=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, full_name, coins FROM users WHERE is_banned = 1 LIMIT ? OFFSET ?",
              (per_page, page * per_page))
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    total = c.fetchone()[0]; conn.close(); return rows, total

def get_user_detail(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT user_id, username, full_name, coins, is_banned, configs_received,
               (SELECT COUNT(*) FROM users WHERE referred_by = ?) FROM users WHERE user_id = ?""",
               (user_id, user_id))
    row = c.fetchone(); conn.close(); return row

def get_user_configs(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, content, used_at FROM configs WHERE used_by = ? ORDER BY id DESC", (user_id,))
    rows = c.fetchall(); conn.close(); return rows

def update_coins(user_id, delta):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?", (delta, user_id))
    conn.commit(); conn.close()

def db_ban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
    affected = c.rowcount
    conn.commit(); conn.close()
    return affected

def db_pre_ban_user(user_id: int):
    """بن کردن کاربری که هنوز ربات رو استارت نزده."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO pre_bans (user_id) VALUES (?)", (user_id,))
    conn.commit(); conn.close()

def db_is_pre_banned(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM pre_bans WHERE user_id = ?", (user_id,))
    row = c.fetchone(); conn.close()
    return row is not None

def db_remove_pre_ban(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pre_bans WHERE user_id = ?", (user_id,))
    conn.commit(); conn.close()

def db_save_broadcast_msgs(tag: str, records: list):
    """records = [(user_id, message_id), ...]"""
    if not records:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executemany("INSERT INTO broadcast_messages (broadcast_tag, user_id, message_id) VALUES (?,?,?)",
                  [(tag, uid, mid) for uid, mid in records])
    conn.commit(); conn.close()

def db_get_broadcast_tags() -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT broadcast_tag, COUNT(*) as cnt FROM broadcast_messages GROUP BY broadcast_tag ORDER BY MIN(id) DESC")
    rows = c.fetchall(); conn.close()
    return rows

def db_delete_broadcast_msgs(tag: str) -> int:
    """پیام‌های یک بردکست خاص رو برمی‌گردونه و از جدول پاک می‌کنه."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, message_id FROM broadcast_messages WHERE broadcast_tag = ?", (tag,))
    rows = c.fetchall()
    c.execute("DELETE FROM broadcast_messages WHERE broadcast_tag = ?", (tag,))
    conn.commit(); conn.close()
    return rows

def db_unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
    affected = c.rowcount
    conn.commit(); conn.close()
    return affected

def get_stat(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM stats WHERE key = ?", (key,))
    row = c.fetchone(); conn.close(); return row[0] if row else 0

def increment_stat(key, amount=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)", (key,))
    c.execute("UPDATE stats SET value = value + ? WHERE key = ?", (amount, key))
    conn.commit(); conn.close()

def get_free_config():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, content FROM configs WHERE is_used = 0 LIMIT 1")
    row = c.fetchone(); conn.close(); return row

def mark_config_used(config_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE configs SET is_used=1, used_by=?, used_at=? WHERE id=?",
              (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), config_id))
    c.execute("UPDATE users SET configs_received=configs_received+1 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def add_config(content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO configs (content) VALUES (?)", (content.strip(),))
    conn.commit(); conn.close()

def delete_all_configs() -> int:
    """فقط کانفیگ‌های آماده (مصرف‌نشده) رو حذف می‌کنه تا آمار کل دست‌نخورده بمونه."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM configs WHERE is_used = 0")
    n = c.fetchone()[0]
    c.execute("DELETE FROM configs WHERE is_used = 0")
    conn.commit(); conn.close()
    return int(n or 0)

def get_referral_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    count = c.fetchone()[0]; conn.close(); return count

def credit_referral(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT referred_by, referral_credited FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row or not row[0] or row[1]:
        conn.close()
        return None
    referred_by = row[0]
    ref_user_row = c.execute("SELECT is_banned FROM users WHERE user_id = ?", (referred_by,)).fetchone()
    if not ref_user_row or ref_user_row[0]:
        conn.close()
        return None
    c.execute("UPDATE users SET referral_credited = 1 WHERE user_id = ?", (user_id,))
    c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (COINS_PER_REFERRAL, referred_by))
    conn.commit()
    conn.close()
    increment_stat("total_referrals")
    return referred_by

def get_configs_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM configs WHERE is_used = 0")
    free = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM configs")
    total = c.fetchone()[0]; conn.close(); return free, total

def get_today_stats():
    today = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE join_date LIKE ?", (today + "%",))
    new_today = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM configs WHERE used_at LIKE ?", (today + "%",))
    configs_today = c.fetchone()[0]
    # total_used: کل کانفیگ‌هایی که تا الان استفاده شدن (حتی اگه ردیف از DB حذف شده باشه، آمار stats رو می‌خوندیم)
    c.execute("SELECT COUNT(*) FROM configs WHERE is_used = 1")
    total_used_db = c.fetchone()[0]
    # از stats هم یه مقدار داریم (configs_given)؛ بزرگتر رو نشون بده
    c.execute("SELECT value FROM stats WHERE key = 'configs_given'")
    stat_row = c.fetchone()
    stat_given = stat_row[0] if stat_row else 0
    total_used = max(total_used_db, stat_given)
    conn.close()
    return new_today, configs_today, total_used

# ==================== بررسی عضویت ====================
def _ad_required_channels() -> list:
    """لیست chat_id کانال‌هایی که در اد لیست ست شدن و باید عضویت‌شون چک بشه."""
    out = []
    for ad in AD_CHANNELS:
        cid = (ad.get("chat_id") or "").strip()
        if cid:
            out.append(cid)
    return out

async def check_membership(user_id: int, bot: Bot) -> bool:
    # هم چنل‌های عضویت اجباری اصلی و هم اد لیست‌هایی که chat_id دارن
    all_channels = list(CHANNEL_IDS) + _ad_required_channels()
    for channel in all_channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logger.warning(f"خطا در بررسی عضویت {channel}: {e}")
            return False
    return True

async def check_main_membership(user_id: int, bot: Bot) -> bool:
    """فقط عضویت چنل‌های اجباری اصلی."""
    for channel in CHANNEL_IDS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logger.warning(f"خطا در بررسی عضویت اصلی {channel}: {e}")
            return False
    return True

async def check_vip_membership(user_id: int, bot: Bot) -> bool:
    """فقط عضویت چنل‌های ادلیست VIP."""
    for channel in _ad_required_channels():
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logger.warning(f"خطا در بررسی عضویت VIP {channel}: {e}")
            return False
    return True

# ==================== کیبوردها ====================
def main_keyboard(show_admin_btn: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=get_button_text("main_get_config"), callback_data="get_config", style=style_of("main_get_config"))],
        [
            InlineKeyboardButton(text=get_button_text("main_account"), callback_data="my_account", style=style_of("main_account")),
            InlineKeyboardButton(text=get_button_text("main_referral"), callback_data="referral", style=style_of("main_referral")),
        ],
        [InlineKeyboardButton(text=get_button_text("main_my_configs"), callback_data="my_configs", style=style_of("main_my_configs"))],
        [
            InlineKeyboardButton(text=get_button_text("main_support"), callback_data="support", style=style_of("main_support")),
            InlineKeyboardButton(text=get_button_text("main_help"), callback_data="help", style=style_of("main_help")),
        ],
    ]
    # اد لیست (لینک‌های کمکی) - زیر منوی اصلی نمایش داده می‌شود
    for ad in AD_CHANNELS:
        try:
            txt = ad.get("text", "").strip() or "🔗"
            url = ad.get("url", "").strip()
            if not url:
                continue
            rows.append([InlineKeyboardButton(text=txt, url=url, style=style_of_color(ad.get("color", "default")))])
        except Exception:
            continue
    if show_admin_btn:
        rows.append([InlineKeyboardButton(text=get_button_text("main_admin"), callback_data="open_admin_panel", style=style_of("main_admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = []
    if has_perm(user_id, "toggle_bot"):
        status_text = get_button_text("admin_toggle_on") if BOT_ENABLED else get_button_text("admin_toggle_off")
        rows.append([InlineKeyboardButton(text=status_text, callback_data="admin_toggle_bot")])
    sup = SUPPORT_ID if SUPPORT_ID else "تنظیم نشده"
    if has_perm(user_id, "support_id"):
        rows.append([InlineKeyboardButton(text=f"{get_button_text('admin_support')} {sup}", callback_data="admin_set_support")])
    if has_perm(user_id, "stats"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_stats"), callback_data="admin_stats")])
    # ردیف بن/آنبن (لیست کاربران حذف شده، فقط بن مستقیم باقی‌ست)
    if has_perm(user_id, "users"):
        rows.append([
            InlineKeyboardButton(text=get_button_text("admin_ban_direct"), callback_data="admin_ban_direct"),
            InlineKeyboardButton(text=get_button_text("admin_unban_direct"), callback_data="admin_unban_direct"),
        ])
        rows.append([InlineKeyboardButton(text=get_button_text("admin_banlist"), callback_data="admin_banlist_0")])
    row2 = []
    if has_perm(user_id, "add_config"):
        row2.append(InlineKeyboardButton(text=get_button_text("admin_add_config"), callback_data="admin_add_config"))
    if has_perm(user_id, "broadcast"):
        row2.append(InlineKeyboardButton(text=get_button_text("admin_broadcast"), callback_data="admin_broadcast"))
    if row2:
        rows.append(row2)
    row3 = []
    if has_perm(user_id, "coins"):
        row3.append(InlineKeyboardButton(text=get_button_text("admin_addcoins"), callback_data="admin_addcoins"))
        row3.append(InlineKeyboardButton(text=get_button_text("admin_subcoins"), callback_data="admin_subcoins"))
    if row3:
        rows.append(row3)
    if has_perm(user_id, "coins"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_reset_all_coins"), callback_data="admin_reset_all_coins")])
    if has_perm(user_id, "coins"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_set_coins_needed"), callback_data="admin_set_coins_needed")])
    if has_perm(user_id, "channels"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_channels"), callback_data="admin_channels")])
    if has_perm(user_id, "smart_channels"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_smart_channels"), callback_data="admin_smart_channels")])
    if has_perm(user_id, "delete_configs"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_delete_all_configs"), callback_data="admin_delete_all_configs")])
    if has_perm(user_id, "texts"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_texts"), callback_data="admin_texts")])
    if has_perm(user_id, "buttons"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_buttons"), callback_data="admin_buttons_0")])
    if has_perm(user_id, "colors"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_colors"), callback_data="admin_colors_0")])
    if has_perm(user_id, "start_reaction"):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_start_reaction"), callback_data="admin_start_reaction")])
    if has_perm(user_id, "ban_reaction"):
        rows.append([InlineKeyboardButton(text="🚫 ری‌اکشن کاربر بن شده", callback_data="admin_ban_reaction")])
    if is_super_admin(user_id):
        rows.append([InlineKeyboardButton(text=get_button_text("admin_manage_admins"), callback_data="admin_manage_admins")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def bot_texts_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, name in TEXT_NAMES.items():
        rows.append([InlineKeyboardButton(text=name, callback_data=f"admin_edittext_{key}")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def bot_buttons_keyboard(page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    items = list(BUTTON_NAMES.items())
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    rows = []
    for key, name in items[start:start + per_page]:
        rows.append([InlineKeyboardButton(text=name, callback_data=f"admin_editbutton_{key}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=get_button_text("prev_page"), callback_data=f"admin_buttons_{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text=get_button_text("next_page"), callback_data=f"admin_buttons_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def join_keyboard() -> InlineKeyboardMarkup:
    """فقط چنل‌های اجباری اصلی + دکمه چک عضویت.
    
    هر entry در CHANNEL_IDS می‌تونه:
      - @username  → لینک عمومی
      - -100xxxxxxxxxx  → آیدی عددی (باید با چنل جداگانه ذخیره بشه)
      - https://t.me/+xxx  → لینک دعوت خصوصی
    اگه join_channel متن تنظیم شده باشه، اون متن به‌عنوان لیبل کامل دکمه استفاده می‌شه.
    """
    buttons = []
    prefix = get_button_text("join_channel").strip()
    for entry in CHANNEL_IDS:
        entry = entry.strip()
        # تشخیص نوع ورودی برای تولید URL
        if entry.startswith("https://") or entry.startswith("http://") or entry.startswith("t.me"):
            url = entry if entry.startswith("http") else f"https://{entry}"
            ch_display = entry
        elif entry.lstrip("-").isdigit():
            # آیدی عددی - نمی‌تونیم لینک عمومی بسازیم؛ باید URL جداگانه داشته باشیم
            # این حالت رو اینجا skip می‌کنیم (از طریق smart_channels url ست می‌شه)
            continue
        else:
            username = entry.lstrip("@")
            url = f"https://t.me/{username}"
            ch_display = entry
        label = prefix if prefix else ch_display
        buttons.append([InlineKeyboardButton(text=label, url=url, style=style_of("join_channel"))])
    buttons.append([InlineKeyboardButton(text=get_button_text("check_join"), callback_data="check_join", style=style_of("check_join"))])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def vip_join_keyboard() -> InlineKeyboardMarkup:
    """فقط چنل‌های ادلیست VIP که chat_id دارن + دکمه چک عضویت."""
    buttons = []
    seen = set()
    for ad in AD_CHANNELS:
        cid = (ad.get("chat_id") or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        text = ad.get("text") or cid
        url = ad.get("url") or (f"https://t.me/{cid.lstrip('@')}" if cid.startswith("@") else "")
        if not url:
            continue
        buttons.append([InlineKeyboardButton(text=text, url=url, style=style_of("join_channel"))])
    buttons.append([InlineKeyboardButton(text=get_button_text("check_join"), callback_data="check_join", style=style_of("check_join"))])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def user_detail_keyboard(uid, is_banned) -> InlineKeyboardMarkup:
    ban_btn = (InlineKeyboardButton(text=get_button_text("unban_user"), callback_data=f"admin_unban_{uid}")
               if is_banned else InlineKeyboardButton(text=get_button_text("ban_user"), callback_data=f"admin_ban_{uid}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [ban_btn],
        [InlineKeyboardButton(text=get_button_text("msg_user"), callback_data=f"admin_msguser_{uid}")],
        [InlineKeyboardButton(text=get_button_text("send_coin_user"), callback_data=f"admin_addcoin_{uid}"),
         InlineKeyboardButton(text=get_button_text("sub_coin_user"), callback_data=f"admin_subcoin_{uid}")],
        [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="admin_users_0")],
    ])

def support_action_keyboard(uid, is_banned) -> InlineKeyboardMarkup:
    ban_btn = (InlineKeyboardButton(text=get_button_text("unban_user"), callback_data=f"admin_unban_{uid}")
               if is_banned else InlineKeyboardButton(text=get_button_text("ban_user"), callback_data=f"admin_ban_{uid}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [ban_btn],
        [InlineKeyboardButton(text=get_button_text("msg_user"), callback_data=f"admin_msguser_{uid}")],
        [InlineKeyboardButton(text=get_button_text("send_coin_user"), callback_data=f"admin_addcoin_{uid}"),
         InlineKeyboardButton(text=get_button_text("sub_coin_user"), callback_data=f"admin_subcoin_{uid}")],
    ])

def sub_admin_perms_keyboard(target_id: int) -> InlineKeyboardMarkup:
    perms = SUB_ADMINS.get(str(target_id), {})
    rows = []
    for perm, name in PERM_NAMES.items():
        has = perms.get(perm, False)
        icon = "✅" if has else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {name}",
            callback_data=f"admin_toggleperm_{target_id}_{perm}"
        )])
    rows.append([InlineKeyboardButton(text=get_button_text("delete_admin"), callback_data=f"admin_removeadmin_{target_id}", style=ButtonStyle.DANGER)])
    rows.append([InlineKeyboardButton(text=get_button_text("back_main"), callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

dp  = Dispatcher(storage=MemoryStorage())
bot: Bot = None

# ==================== ری‌اکشن استارت ====================
# لیست ایموجی‌های مجاز تلگرام برای ری‌اکشن (ایموجی استاندارد). اگه fallback
# داخل این لیست نباشه، تلگرام BAD_REQUEST می‌ده. این لیست رسمی تلگرامه:
ALLOWED_REACTION_EMOJIS_LIST = [
    "👍","👎","❤","🔥","🥰","👏","😁","🤔","🤯","😱","🤬","😢","🎉","🤩","🤮","💩",
    "🙏","👌","🕊","🤡","🥱","🥴","😍","🐳","❤‍🔥","🌚","🌭","💯","🤣","⚡","🍌","🏆",
    "💔","🤨","😐","🍓","🍾","💋","🖕","😈","😴","😭","🤓","👻","👨‍💻","👀","🎃","🙈",
    "😇","😨","🤝","✍","🤗","🫡","🎅","🎄","☃","💅","🤪","🗿","🆒","💘","🙉","🦄",
    "😘","💊","🙊","😎","👾","🤷‍♂","🤷","🤷‍♀","😡"
]
ALLOWED_REACTION_EMOJIS = set(ALLOWED_REACTION_EMOJIS_LIST)

async def _set_standard_reaction(message: Message, emoji: str):
    """ست کردن ری‌اکشن استاندارد روی یه پیام، با fallback به API خام. is_big=True باعث انیمیشن بزرگ‌شده می‌شود."""
    try:
        from aiogram.types import ReactionTypeEmoji
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
            is_big=True,
        )
        return True
    except Exception as e:
        logger.warning(f"Standard reaction failed با ایموجی {emoji}: {e}")
    # آخرین تلاش: API خام
    try:
        if aiohttp is None:
            return False
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
        payload = {
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "reaction": json.dumps([{"type": "emoji", "emoji": emoji}]),
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"Raw reaction API failed: {resp.status} {body}")
                    return False
                return True
    except Exception as e:
        logger.warning(f"خطا در ست ری‌اکشن (raw): {e}")
        return False

async def react_to_banned_start(message: Message) -> bool:
    """ری‌اکشن مخصوص کاربر بن شده (اگه فعال باشه). True اگه ست شد."""
    if not BAN_REACTION.get("enabled"):
        return False
    emoji = (BAN_REACTION.get("emoji") or "👎").strip() or "👎"
    if emoji not in ALLOWED_REACTION_EMOJIS:
        emoji = "👎"
    await _set_standard_reaction(message, emoji)
    return True

async def react_to_start(message: Message):
    """ری‌اکشن گذاشتن روی پیام /start کاربر (ایموجی پریمیوم یا معمولی)."""
    if not START_REACTION.get("enabled"):
        return
    emoji_id = (START_REACTION.get("emoji_id") or "").strip()
    fallback = (START_REACTION.get("fallback") or "🔥").strip() or "🔥"
    # اگه fallback در لیست مجاز تلگرام نیست، یه ایموجی پیش‌فرض مجاز بذار
    if fallback not in ALLOWED_REACTION_EMOJIS:
        fallback = "🔥"

    # 1) تلاش برای ری‌اکشن پریمیوم (نیاز به Bot Premium داره)
    if emoji_id:
        try:
            from aiogram.types import ReactionTypeCustomEmoji
            await bot.set_message_reaction(
                chat_id=message.chat.id,
                message_id=message.message_id,
                reaction=[ReactionTypeCustomEmoji(custom_emoji_id=emoji_id)],
                is_big=True,
            )
            return
        except Exception as e:
            logger.warning(f"Premium reaction failed (نیاز به Bot Premium داره)، می‌رم سراغ fallback: {e}")

    # 2) ری‌اکشن استاندارد (fallback) - با انیمیشن بزرگ
    try:
        from aiogram.types import ReactionTypeEmoji
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=fallback)],
            is_big=True,
        )
        return
    except Exception as e:
        logger.warning(f"Standard reaction failed با ایموجی {fallback}: {e}")

    # 3) آخرین تلاش: API خام تلگرام
    try:
        if aiohttp is None:
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
        payload = {
            "chat_id": message.chat.id,
            "message_id": message.message_id,
            "reaction": json.dumps([{"type": "emoji", "emoji": fallback}]),
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"Raw reaction API failed: {resp.status} {body}")
    except Exception as e:
        logger.warning(f"خطا در ست ری‌اکشن استارت (آخرین تلاش): {e}")

# ==================== /start ====================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    # اگه کاربر بن شده و ری‌اکشن بن فعاله، اول اون رو می‌زنیم؛ وگرنه ری‌اکشن استارت معمولی
    db_user_pre = get_user(user.id)
    is_user_banned = bool(db_user_pre and db_user_pre[6])
    if is_user_banned:
        asyncio.create_task(react_to_banned_start(message))
    else:
        asyncio.create_task(react_to_start(message))
    args = message.text.split()
    referred_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referred_by = int(args[1].split("_")[1])
            if referred_by == user.id: referred_by = None
        except: pass

    is_new = add_user(user.id, user.username, user.full_name, referred_by)
    if is_new: increment_stat("total_users")

    # بررسی پری‌بن — اگه ادمین از قبل این آیدی رو پری‌بن کرده بود
    if db_is_pre_banned(user.id):
        db_ban_user(user.id)
        db_remove_pre_ban(user.id)
        await message.answer(get_bot_text("banned_user")); return

    if not BOT_ENABLED and not is_any_admin(user.id):
        await message.answer(get_bot_text("bot_disabled")); return

    if not await check_main_membership(user.id, bot):
        await message.answer(get_bot_text("join_required"), reply_markup=join_keyboard()); return
    if not await check_vip_membership(user.id, bot):
        await message.answer(get_bot_text("vip_join_required"), reply_markup=vip_join_keyboard()); return

    db_user = get_user(user.id)
    if db_user and db_user[6]:
        await message.answer(get_bot_text("banned_user")); return

    referred_by_credited = credit_referral(user.id)
    if referred_by_credited:
        try:
            notif_tmpl = get_bot_text("referral_notif")
            try:
                notif_body = notif_tmpl.format(coins=COINS_PER_REFERRAL)
            except Exception:
                notif_body = notif_tmpl
            await bot.send_message(referred_by_credited, notif_body)
        except: pass

    await message.answer(get_bot_text("start"), reply_markup=main_keyboard(show_admin_btn=is_any_admin(user.id)))

# ==================== باز کردن پنل ادمین ====================
@dp.callback_query(F.data == "open_admin_panel")
async def cb_open_admin_panel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    if not is_any_admin(call.from_user.id):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.message.edit_text("👑 پنل مدیریت", reply_markup=admin_keyboard(call.from_user.id))

# ==================== check_join ====================
@dp.callback_query(F.data == "check_join")
async def cb_check_join(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not BOT_ENABLED and not is_any_admin(call.from_user.id):
        await call.message.edit_text(get_bot_text("bot_disabled")); return
    if not await check_main_membership(call.from_user.id, bot):
        await call.message.edit_text(get_bot_text("not_joined"), reply_markup=join_keyboard()); return
    if not await check_vip_membership(call.from_user.id, bot):
        await call.message.edit_text(get_bot_text("vip_join_required"), reply_markup=vip_join_keyboard()); return
    db_user = get_user(call.from_user.id)
    if db_user and db_user[6]:
        await call.message.edit_text(get_bot_text("banned_user")); return

    referred_by = credit_referral(call.from_user.id)
    if referred_by:
        try:
            notif_tmpl2 = get_bot_text("referral_notif")
            try:
                notif_body2 = notif_tmpl2.format(coins=COINS_PER_REFERRAL)
            except Exception:
                notif_body2 = notif_tmpl2
            await bot.send_message(referred_by, notif_body2)
        except: pass

    await call.message.edit_text(get_bot_text("start"), reply_markup=main_keyboard(show_admin_btn=is_any_admin(call.from_user.id)))

# ==================== back_main ====================
@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text(get_bot_text("start"), reply_markup=main_keyboard(show_admin_btn=is_any_admin(call.from_user.id)))

# ==================== get_config ====================
@dp.callback_query(F.data == "get_config")
async def cb_get_config(call: CallbackQuery):
    await call.answer()
    user = call.from_user
    if not BOT_ENABLED and not is_any_admin(user.id):
        await call.message.edit_text(get_bot_text("bot_disabled")); return
    is_member = await check_membership(user.id, bot)
    if not is_member:
        await call.message.edit_text(get_bot_text("join_required_short"), reply_markup=join_keyboard()); return
    db_user = get_user(user.id)
    if not db_user:
        await call.answer("ابتدا /start بزن.", show_alert=True); return
    if db_user[6]:
        await call.answer(get_bot_text("banned_user"), show_alert=True); return
    coins = db_user[3]
    if coins < COINS_TO_GET_CONFIG:
        needed = COINS_TO_GET_CONFIG - coins
        no_coins_tmpl = get_bot_text("no_coins")
        try:
            no_coins_body = no_coins_tmpl.format(
                coins=coins, needed=COINS_TO_GET_CONFIG,
                lacking=needed, per_ref=COINS_PER_REFERRAL)
        except Exception:
            no_coins_body = no_coins_tmpl
        await call.message.edit_text(
            no_coins_body,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("get_referral"), callback_data="referral", style=style_of("get_referral"))],
                [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")],
            ])); return
    config = get_free_config()
    if not config:
        await call.message.edit_text(get_bot_text("no_config_available"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]])); return
    update_coins(user.id, -COINS_TO_GET_CONFIG)
    mark_config_used(config[0], user.id)
    increment_stat("configs_given")
    cfg_tmpl = get_bot_text("config_received")
    try:
        cfg_body = cfg_tmpl.format(config=config[1], cost=COINS_TO_GET_CONFIG)
    except Exception:
        cfg_body = cfg_tmpl
    await call.message.edit_text(
        cfg_body,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

# ==================== کانفیگ‌های من ====================
@dp.callback_query(F.data == "my_configs")
async def cb_my_configs(call: CallbackQuery):
    await call.answer()
    user = call.from_user
    db_user = get_user(user.id)
    if not db_user:
        await call.answer("ابتدا /start بزن.", show_alert=True); return
    configs = get_user_configs(user.id)
    if not configs:
        await call.message.edit_text(
            get_bot_text("my_configs_empty"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))
        return
    header_tmpl = get_bot_text("my_configs_header")
    try:
        header_body = header_tmpl.format(count=len(configs))
    except Exception:
        header_body = header_tmpl
    await call.message.edit_text(
        header_body,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))
    for idx, (cid, content, used_at) in enumerate(configs, start=1):
        try:
            item_tmpl = get_bot_text("config_item")
            try:
                item_body = item_tmpl.format(num=idx, date=used_at or '-', config=content)
            except Exception:
                item_body = item_tmpl
            await bot.send_message(user.id, item_body, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"خطا در ارسال کانفیگ به کاربر {user.id}: {e}")

# ==================== referral ====================
@dp.callback_query(F.data == "referral")
async def cb_referral(call: CallbackQuery):
    await call.answer()
    db_user = get_user(call.from_user.id)
    if not db_user:
        await call.answer("ابتدا /start بزن.", show_alert=True); return
    ref_count = get_referral_count(call.from_user.id)
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    template = get_bot_text("referral_response")
    try:
        body = template.format(
            link=ref_link,
            ref_count=ref_count,
            coins=db_user[3],
            needed=COINS_TO_GET_CONFIG,
            per_ref=COINS_PER_REFERRAL,
        )
    except Exception:
        # اگر کاربر متن جدیدی بدون پلیس‌هولدر گذاشته بود، خود متن نمایش داده شود
        body = template
    await call.message.edit_text(
        body,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

# ==================== my_account ====================
@dp.callback_query(F.data == "my_account")
async def cb_my_account(call: CallbackQuery):
    await call.answer()
    db_user = get_user(call.from_user.id)
    if not db_user:
        await call.answer("ابتدا /start بزن.", show_alert=True); return
    ref_count = get_referral_count(call.from_user.id)
    status = "🚫 مسدود" if db_user[6] else "✅ فعال"
    acc_tmpl = get_bot_text("account_info")
    try:
        acc_body = acc_tmpl.format(
            user_id=db_user[0],
            name=db_user[2],
            coins=db_user[3],
            refs=ref_count,
            spent=db_user[7] * COINS_TO_GET_CONFIG,
            configs=db_user[7],
            status=status,
        )
    except Exception:
        acc_body = acc_tmpl
    await call.message.edit_text(
        acc_body,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

# ==================== help ====================
@dp.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        get_bot_text("help"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

# ==================== پشتیبانی ====================
@dp.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        get_bot_text("support"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("support_sponsor"), callback_data="support_sponsor", style=style_of("support_sponsor"))],
            [InlineKeyboardButton(text=get_button_text("support_question"), callback_data="support_question", style=style_of("support_question"))],
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")],
        ]))

@dp.callback_query(F.data == "support_sponsor")
async def cb_support_sponsor(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(UserStates.sponsor_msg)
    await call.message.edit_text(
        get_bot_text("sponsor_prompt"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="back_main")]]))

@dp.message(UserStates.sponsor_msg)
async def hdl_sponsor_msg(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db_user = get_user(user.id)
    coins = db_user[3] if db_user else 0
    is_banned = db_user[6] if db_user else 0
    configs_received = db_user[7] if db_user else 0
    ref_count = get_referral_count(user.id)
    username = f"@{user.username}" if user.username else "ندارد"
    admin_text = (f"💼 درخواست اسپانسر جدید\n━━━━━━━━━━━━━━━\n\n"
                  f"👤 نام: {user.full_name}\n📛 یوزرنیم: {username}\n"
                  f"🆔 آیدی: <code>{user.id}</code>\n🪙 سکه: {coins}\n"
                  f"🎁 کانفیگ دریافتی: {configs_received}\n👥 زیرمجموعه: {ref_count} نفر\n"
                  f"━━━━━━━━━━━━━━━\n\n📝 پیام اسپانسر:")
    for aid in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(aid, admin_text, parse_mode=ParseMode.HTML, reply_markup=support_action_keyboard(user.id, is_banned))
            # کپی پیام کاربر (مدیا/متن)
            await bot.copy_message(chat_id=aid, from_chat_id=message.chat.id, message_id=message.message_id)
        except: pass
    await message.answer("✅ درخواست اسپانسر شما ارسال شد!\nبه زودی با شما تماس می‌گیریم 🙏",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

@dp.callback_query(F.data == "support_question")
async def cb_support_question(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(UserStates.support_msg)
    await call.message.edit_text(get_bot_text("support_question_prompt"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="back_main")]]))

@dp.message(UserStates.support_msg)
async def hdl_support_msg(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    db_user = get_user(user.id)
    coins = db_user[3] if db_user else 0
    is_banned = db_user[6] if db_user else 0
    configs_received = db_user[7] if db_user else 0
    ref_count = get_referral_count(user.id)
    username = f"@{user.username}" if user.username else "ندارد"
    admin_text = (f"❓ سوال / مشکل جدید\n━━━━━━━━━━━━━━━\n\n"
                  f"👤 نام: {user.full_name}\n📛 یوزرنیم: {username}\n"
                  f"🆔 آیدی: <code>{user.id}</code>\n🪙 سکه: {coins}\n"
                  f"🎁 کانفیگ دریافتی: {configs_received}\n👥 زیرمجموعه: {ref_count} نفر\n"
                  f"━━━━━━━━━━━━━━━\n\n📝 پیام:")
    for aid in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(aid, admin_text, parse_mode=ParseMode.HTML, reply_markup=support_action_keyboard(user.id, is_banned))
            # کپی پیام کاربر (مدیا/متن/صدا/ویدیو)
            await bot.copy_message(chat_id=aid, from_chat_id=message.chat.id, message_id=message.message_id)
        except: pass
    await message.answer("✅ پیام شما ارسال شد!\nبه زودی پاسخ می‌گیرید 🙏",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_main"), callback_data="back_main")]]))

# ==================== خاموش/روشن ====================
@dp.callback_query(F.data == "admin_toggle_bot")
async def cb_toggle_bot(call: CallbackQuery):
    if not has_perm(call.from_user.id, "toggle_bot"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    status_text = "🟢 روشن" if BOT_ENABLED else "🔴 خاموش"
    await call.message.edit_text(f"⚙️ وضعیت ربات\n\nوضعیت فعلی: {status_text}\n\nیکی رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("bot_off"), callback_data="admin_bot_off")],
            [InlineKeyboardButton(text=get_button_text("bot_on"), callback_data="admin_bot_on")],
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")],
        ]))

@dp.callback_query(F.data == "admin_bot_on")
async def cb_bot_on(call: CallbackQuery):
    global BOT_ENABLED
    if not has_perm(call.from_user.id, "toggle_bot"): return
    await call.answer()
    BOT_ENABLED = True
    cfg = load_config(); cfg["enabled"] = True; save_config(cfg)
    await call.message.edit_text("✅ ربات روشن شد!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))

@dp.callback_query(F.data == "admin_bot_off")
async def cb_bot_off(call: CallbackQuery):
    global BOT_ENABLED
    if not has_perm(call.from_user.id, "toggle_bot"): return
    await call.answer()
    BOT_ENABLED = False
    cfg = load_config(); cfg["enabled"] = False; save_config(cfg)
    await call.message.edit_text("🔴 ربات خاموش شد!\nکاربران پیام «درحال بروزرسانی» می‌بینن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))

# ==================== آمار ====================
@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    if not has_perm(call.from_user.id, "stats"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    total_users = get_stat("total_users")
    free_configs, _ = get_configs_count()
    new_today, configs_today, total_used = get_today_stats()
    bot_status = "🟢 روشن" if BOT_ENABLED else "🔴 خاموش"
    sup = SUPPORT_ID if SUPPORT_ID else "تنظیم نشده"
    await call.message.edit_text(
        f"وضعیت ربات: {bot_status}\nآیدی پشتیبانی فعلی: {sup}\n\n📊 آمار کلی:\n"
        f"👥 تعداد کل کاربران: {total_users}\n🔥 کاربران فعال امروز: {new_today}\n"
        f"🌱 ورودی‌های جدید امروز: {new_today}\n\n✅ کانفیگ های موجود فعلی: {free_configs}\n"
        f"🟢 کانفیگ‌های مصرف‌شده امروز: {configs_today}\n🔴 کل کانفیگ‌های منقضی/مصرف‌شده: {total_used}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))

# ==================== مدیریت متن‌ها ====================
@dp.callback_query(F.data == "admin_texts")
async def cb_admin_texts(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "texts"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "✏️ مدیریت متن‌ها\n\nیکی از متن‌ها را انتخاب کن تا متن فعلی را ببینی و متن جدید بفرستی:",
        reply_markup=bot_texts_keyboard())

@dp.callback_query(F.data.startswith("admin_edittext_"))
async def cb_admin_edit_text(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "texts"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    key = call.data.replace("admin_edittext_", "")
    if key not in TEXT_NAMES:
        await call.answer("این متن پیدا نشد.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.edit_bot_text)
    await state.update_data(text_key=key)
    await call.message.edit_text(
        f"✏️ تغییر {TEXT_NAMES[key]}\n\nمتن فعلی:\n\n{get_bot_text(key)}\n\n━━━━━━━━━━━━━━━\nمتن جدید را همینجا بفرست:\n\n💎 می‌تونی از کیبورد ایموجی پایین تلگرام، ایموجی پریمیوم هم داخل متن استفاده کنی — خودکار ذخیره و در پیام‌ها نمایش داده می‌شه.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_texts")]]))

@dp.message(AdminStates.edit_bot_text)
async def hdl_admin_edit_text(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "texts"):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("text_key")
    if key not in TEXT_NAMES:
        await state.clear()
        await message.answer("❌ خطا در انتخاب متن.", reply_markup=admin_keyboard(message.from_user.id))
        return
    # اگر کاربر ایموجی پریمیوم در متن فرستاده، با تگ tg-emoji ذخیره می‌کنیم
    new_text = text_with_premium_html(message).strip()
    if not new_text:
        await message.answer("❌ متن خالی قابل ذخیره نیست. متن جدید را بفرست:")
        return
    save_bot_text(key, new_text)
    await state.clear()
    await message.answer(
        f"✅ {TEXT_NAMES[key]} ذخیره شد.\n\nمتن جدید:\n\n{new_text}",
        reply_markup=bot_texts_keyboard())

# ==================== مدیریت دکمه‌ها ====================
@dp.callback_query(F.data.startswith("admin_buttons_"))
async def cb_admin_buttons(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "buttons"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    try:
        page = int(call.data.split("_")[-1])
    except:
        page = 0
    await call.message.edit_text(
        "🔘 مدیریت دکمه‌های شیشه‌ای\n\nیکی از دکمه‌ها را انتخاب کن تا اسم فعلی را ببینی و اسم جدید بفرستی:",
        reply_markup=bot_buttons_keyboard(page))

@dp.callback_query(F.data.startswith("admin_editbutton_"))
async def cb_admin_edit_button(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "buttons"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    key = call.data.replace("admin_editbutton_", "")
    if key not in BUTTON_NAMES:
        await call.answer("این دکمه پیدا نشد.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.edit_button_text)
    await state.update_data(button_key=key)
    await call.message.edit_text(
        f"🔘 تغییر {BUTTON_NAMES[key]}\n\nاسم فعلی:\n\n{get_button_text(key)}\n\n━━━━━━━━━━━━━━━\nاسم جدید دکمه را بفرست:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_buttons_0")]]))

@dp.message(AdminStates.edit_button_text)
async def hdl_admin_edit_button(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "buttons"):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("button_key")
    if key not in BUTTON_NAMES:
        await state.clear()
        await message.answer("❌ خطا در انتخاب دکمه.", reply_markup=admin_keyboard(message.from_user.id))
        return
    raw = message.text or ""
    new_text = raw.strip()
    # دکمه‌های شیشه‌ای (inline) از سمت تلگرام تگ HTML قبول نمی‌کنن، پس
    # اگر کاربر ایموجی پریمیوم فرستاده، فقط خود کاراکتر ایموجی (fallback)
    # داخل متن دکمه باقی می‌مونه (همون چیزی که کاربر دیده).
    premium_used = bool(first_premium_emoji_id(message))
    # برای دکمه «عضویت در کانال» اجازه ذخیره مقدار خالی داده می‌شود تا
    # کنار آیدی کانال متنی نمایش داده نشود. برای حذف کامل، کاربر می‌تواند
    # یک خط خالی یا یک نقطه «-» بفرستد که خالی محسوب شود.
    if key == "join_channel":
        if new_text in ("-", "خالی", "empty", "-خالی-"):
            new_text = ""
        save_button_text(key, new_text)
        await state.clear()
        shown = new_text if new_text else "(خالی - فقط آیدی کانال نمایش داده می‌شود)"
        await message.answer(
            f"✅ {BUTTON_NAMES[key]} ذخیره شد.\n\nاسم جدید:\n\n{shown}",
            reply_markup=bot_buttons_keyboard())
        return
    if not new_text:
        await message.answer("❌ اسم خالی قابل ذخیره نیست. اسم جدید دکمه را بفرست:\n\n💡 برای دکمه «عضویت در کانال» می‌توانی «-» بفرستی تا متنش حذف شود.")
        return
    save_button_text(key, new_text)
    await state.clear()
    note = ""
    if premium_used:
        note = "\n\n⚠️ نکته: تلگرام ایموجی پریمیوم رو روی دکمه‌های شیشه‌ای نمایش نمی‌ده، فقط ایموجی معمولی همین متن نشون داده می‌شه."
    await message.answer(
        f"✅ {BUTTON_NAMES[key]} ذخیره شد.\n\nاسم جدید:\n\n{new_text}{note}",
        reply_markup=bot_buttons_keyboard())

# ==================== لیست کاربران ====================
@dp.callback_query(F.data.startswith("admin_users_"))
async def cb_admin_users(call: CallbackQuery):
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    page = int(call.data.split("_")[-1])
    users, total = get_all_users_paginated(page, 20)
    if not users:
        await call.message.edit_text("هیچ کاربری یافت نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]])); return
    buttons = []
    for u in users:
        banned = "🚫" if u[3] else ""
        buttons.append([InlineKeyboardButton(text=f"{banned}{u[1]} | 🪙{u[2]}", callback_data=f"admin_userdetail_{u[0]}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text=get_button_text("prev_page"), callback_data=f"admin_users_{page-1}"))
    if (page+1)*20 < total: nav.append(InlineKeyboardButton(text=get_button_text("next_page"), callback_data=f"admin_users_{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    await call.message.edit_text(f"👥 لیست کاربران (صفحه {page+1})\nکل: {total} کاربر",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("admin_userdetail_"))
async def cb_user_detail_view(call: CallbackQuery):
    if not is_any_admin(call.from_user.id): return
    await call.answer()
    target_id = int(call.data.split("_")[-1])
    u = get_user_detail(target_id)
    if not u:
        await call.answer("کاربر یافت نشد.", show_alert=True); return
    status = "🚫 مسدود" if u[4] else "✅ فعال"
    await call.message.edit_text(
        f"👤 جزئیات کاربر\n━━━━━━━━━━━━━━━\n🆔 آیدی: <code>{u[0]}</code>\n"
        f"📛 یوزرنیم: @{u[1] or 'ندارد'}\n👤 نام: {u[2]}\n🪙 سکه: {u[3]}\n"
        f"📌 وضعیت: {status}\n🎁 کانفیگ دریافتی: {u[5]}\n👥 زیرمجموعه: {u[6]}\n━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML, reply_markup=user_detail_keyboard(u[0], u[4]))

@dp.callback_query(F.data.startswith("admin_ban_") & ~F.data.startswith("admin_ban_direct") & ~F.data.startswith("admin_banlist"))
async def cb_ban(call: CallbackQuery):
    if not is_any_admin(call.from_user.id): return
    target_id = int(call.data.split("_")[-1])
    db_ban_user(target_id)
    await call.answer(f"✅ کاربر {target_id} بن شد.", show_alert=True)
    u = get_user_detail(target_id)
    if u:
        try: await call.message.edit_reply_markup(reply_markup=user_detail_keyboard(u[0], u[4]))
        except:
            try: await call.message.edit_reply_markup(reply_markup=support_action_keyboard(u[0], u[4]))
            except: pass

@dp.callback_query(F.data.startswith("admin_unban_") & ~F.data.startswith("admin_unban_direct"))
async def cb_unban(call: CallbackQuery):
    if not is_any_admin(call.from_user.id): return
    target_id = int(call.data.split("_")[-1])
    db_unban_user(target_id)
    await call.answer(f"✅ کاربر {target_id} آنبن شد.", show_alert=True)
    u = get_user_detail(target_id)
    if u:
        try: await call.message.edit_reply_markup(reply_markup=user_detail_keyboard(u[0], u[4]))
        except:
            try: await call.message.edit_reply_markup(reply_markup=support_action_keyboard(u[0], u[4]))
            except: pass

# ==================== بن مستقیم از پنل (با آیدی عددی) ====================
@dp.callback_query(F.data == "admin_ban_direct")
async def cb_admin_ban_direct(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.ban_direct_id)
    await call.message.edit_text(
        "🚫 بن کردن کاربر\n\nآیدی عددی کاربری که می‌خوای بن بشه رو بفرست:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.ban_direct_id)
async def hdl_admin_ban_direct(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "users"):
        await state.clear(); return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("❌ آیدی عددی معتبر بفرست:"); return
    target_id = int(txt)
    u = get_user(target_id)
    if not u:
        # کاربر هنوز ربات رو استارت نزده — پری‌بن می‌کنیم
        db_pre_ban_user(target_id)
        await state.clear()
        await message.answer(
            f"⚠️ کاربر <code>{target_id}</code> هنوز ربات رو استارت نزده.\n"
            f"✅ پری‌بن شد — اگه فردا ربات رو استارت بزنه، خودکار بن می‌شه.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(message.from_user.id))
        return
    db_ban_user(target_id)
    await state.clear()
    await message.answer(
        f"✅ کاربر <code>{target_id}</code> با موفقیت بن شد.\n👤 نام: {u[2]}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(message.from_user.id))

@dp.callback_query(F.data == "admin_unban_direct")
async def cb_admin_unban_direct(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.unban_direct_id)
    await call.message.edit_text(
        "🔓 آنبن کردن کاربر\n\nآیدی عددی کاربری که می‌خوای آنبن بشه رو بفرست:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.unban_direct_id)
async def hdl_admin_unban_direct(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "users"):
        await state.clear(); return
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("❌ آیدی عددی معتبر بفرست:"); return
    target_id = int(txt)
    u = get_user(target_id)
    if not u:
        await message.answer("❌ کاربری با این آیدی در ربات یافت نشد. آیدی دیگه‌ای بفرست یا لغو کن:"); return
    db_unban_user(target_id)
    await state.clear()
    await message.answer(
        f"✅ کاربر <code>{target_id}</code> با موفقیت آنبن شد.\n👤 نام: {u[2]}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(message.from_user.id))

# ==================== لیست بن‌ها ====================
@dp.callback_query(F.data.startswith("admin_banlist_"))
async def cb_admin_banlist(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    try:
        page = int(call.data.split("_")[-1])
    except:
        page = 0
    users, total = get_banned_users_paginated(page, 20)
    if total == 0:
        await call.message.edit_text(
            "📋 لیست بن‌ها\n━━━━━━━━━━━━━━━\n\nهیچ کاربر بن‌شده‌ای وجود نداره ✅",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))
        return
    buttons = []
    for u in users:
        buttons.append([InlineKeyboardButton(
            text=f"🚫 {u[1]} | 🆔 {u[0]}",
            callback_data=f"admin_bannedview_{u[0]}"
        )])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text=get_button_text("prev_page"), callback_data=f"admin_banlist_{page-1}"))
    if (page+1)*20 < total: nav.append(InlineKeyboardButton(text=get_button_text("next_page"), callback_data=f"admin_banlist_{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    await call.message.edit_text(
        f"📋 لیست بن‌ها (صفحه {page+1})\nکل کاربران بن‌شده: {total}\n\nروی کاربر بزن تا آنبن بشه:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("admin_bannedview_"))
async def cb_admin_banned_view(call: CallbackQuery):
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    target_id = int(call.data.split("_")[-1])
    u = get_user_detail(target_id)
    if not u:
        await call.answer("کاربر یافت نشد.", show_alert=True); return
    await call.message.edit_text(
        f"👤 کاربر بن‌شده\n━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{u[0]}</code>\n"
        f"📛 یوزرنیم: @{u[1] or 'ندارد'}\n"
        f"👤 نام: {u[2]}\n"
        f"🪙 سکه: {u[3]}\n"
        f"🎁 کانفیگ دریافتی: {u[5]}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"این کاربر آنبن شود؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("confirm_unban"), callback_data=f"admin_confirmunban_{target_id}")],
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_banlist_0")],
        ]))

@dp.callback_query(F.data.startswith("admin_confirmunban_"))
async def cb_admin_confirm_unban(call: CallbackQuery):
    if not has_perm(call.from_user.id, "users"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    target_id = int(call.data.split("_")[-1])
    db_unban_user(target_id)
    await call.answer(f"✅ کاربر {target_id} آنبن شد.", show_alert=True)
    users, total = get_banned_users_paginated(0, 20)
    if total == 0:
        await call.message.edit_text(
            "📋 لیست بن‌ها\n━━━━━━━━━━━━━━━\n\nهیچ کاربر بن‌شده‌ای وجود نداره ✅",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))
        return
    buttons = []
    for u in users:
        buttons.append([InlineKeyboardButton(
            text=f"🚫 {u[1]} | 🆔 {u[0]}",
            callback_data=f"admin_bannedview_{u[0]}"
        )])
    if total > 20:
        buttons.append([InlineKeyboardButton(text=get_button_text("next_page"), callback_data=f"admin_banlist_1")])
    buttons.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    await call.message.edit_text(
        f"✅ کاربر {target_id} آنبن شد.\n\n📋 لیست بن‌ها (صفحه 1)\nکل کاربران بن‌شده: {total}\n\nروی کاربر بزن تا آنبن بشه:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# ==================== افزودن کانفیگ (bulk + session یک‌به‌یک) ====================
@dp.callback_query(F.data == "admin_add_config")
async def cb_add_config(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "add_config"): return
    await call.answer()
    await call.message.edit_text(
        "➕ افزودن کانفیگ\n\nکدوم روش رو می‌خوای؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 ارسال دسته‌ای (چند خط یا یه متن)", callback_data="add_config_bulk")],
            [InlineKeyboardButton(text="📨 ارسال یک‌به‌یک (فوروارد تا «تموم شد»)", callback_data="add_config_session")],
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data == "add_config_bulk")
async def cb_add_config_bulk(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "add_config"): return
    await call.answer()
    await state.set_state(AdminStates.waiting_config_item)
    await call.message.edit_text(
        "📋 ارسال دسته‌ای\n\n"
        "کانفیگ‌ها رو بفرست:\n"
        "• می‌تونی یه کانفیگ بفرستی\n"
        "• یا چند کانفیگ رو باهم کپی‌پیست کنی (هر کانفیگ یه خط)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data == "add_config_session")
async def cb_add_config_session(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "add_config"): return
    await call.answer()
    await state.set_state(AdminStates.config_forward_session)
    await state.update_data(session_added=0)
    await call.message.edit_text(
        "📨 حالت ارسال یک‌به‌یک\n\n"
        "کانفیگ‌ها رو یکی‌یکی بفرست (می‌تونی فوروارد هم کنی).\n"
        "وقتی تموم شد، دکمه «تمام شد» رو بزن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تمام شد (Done)", callback_data="config_session_done")],
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data == "config_session_done")
async def cb_config_session_done(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "add_config"): return
    data = await state.get_data()
    added = data.get("session_added", 0)
    await state.clear()
    await call.answer(f"✅ {added} کانفیگ اضافه شد.", show_alert=True)
    await call.message.edit_text(
        f"✅ سشن افزودن کانفیگ بسته شد.\n🎁 تعداد کانفیگ اضافه‌شده: {added}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]]))

@dp.message(AdminStates.config_forward_session)
async def hdl_config_forward_session(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    raw = (message.text or message.caption or "").strip()
    if not raw:
        await message.answer("❌ متن خالی. کانفیگ رو بفرست:"); return
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    added_now = 0
    for line in lines:
        add_config(line)
        added_now += 1
    data = await state.get_data()
    total = data.get("session_added", 0) + added_now
    await state.update_data(session_added=total)
    await message.answer(
        f"✅ {added_now} کانفیگ ذخیره شد. (مجموع این سشن: {total})\nادامه بده یا «تمام شد» بزن.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تمام شد (Done)", callback_data="config_session_done")],
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.waiting_config_item)
async def hdl_config_item(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ متن خالیه. کانفیگ‌ها رو بفرست:"); return
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    added = 0
    for line in lines:
        add_config(line)
        added += 1
    await state.clear()
    if added == 1:
        await message.answer(f"✅ ۱ کانفیگ اضافه شد!", reply_markup=admin_keyboard(message.from_user.id))
    else:
        await message.answer(f"✅ {added} کانفیگ با موفقیت اضافه شدن!", reply_markup=admin_keyboard(message.from_user.id))

# ==================== سکه ====================
@dp.callback_query(F.data == "admin_addcoins")
async def cb_add_coins(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "coins"): return
    await call.answer()
    await state.set_state(AdminStates.add_coins_id)
    await call.message.edit_text("💰 انتقال سکه\n\nآیدی عددی کاربر رو بفرست:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data.startswith("admin_addcoin_"))
async def cb_add_coin_direct(call: CallbackQuery, state: FSMContext):
    if not is_any_admin(call.from_user.id): return
    await call.answer()
    target_id = int(call.data.split("_")[-1])
    await state.update_data(add_coins_target=target_id, back_to_uid=target_id)
    await state.set_state(AdminStates.add_coins_amount)
    await call.message.edit_text(f"💰 چند سکه به کاربر {target_id} اضافه کنم?\nعدد بفرست:")

@dp.message(AdminStates.add_coins_id)
async def hdl_add_coins_id(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    if not message.text.strip().isdigit():
        await message.answer("❌ آیدی عددی معتبر بفرست:"); return
    u = get_user(int(message.text.strip()))
    if not u:
        await message.answer("❌ کاربر یافت نشد:"); return
    await state.update_data(add_coins_target=int(message.text.strip()))
    await state.set_state(AdminStates.add_coins_amount)
    await message.answer(f"✅ کاربر: {u[2]}\n🪙 سکه فعلی: {u[3]}\n\nچند سکه اضافه کنم?")

@dp.message(AdminStates.add_coins_amount)
async def hdl_add_coins_amount(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("❌ عدد معتبر بفرست:"); return
    data = await state.get_data()
    amount = int(message.text.strip())
    target_id = data["add_coins_target"]
    update_coins(target_id, amount)
    u = get_user(target_id)
    new_coins = u[3] if u else amount
    await state.clear()
    # اطلاع‌رسانی به گیرنده
    notif_tmpl = get_bot_text("coin_transfer_notif")
    notif_text = notif_tmpl.format(amount=amount, new_coins=new_coins)
    try:
        await bot.send_message(target_id, notif_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"نتونستم اطلاع‌رسانی سکه رو به {target_id} بفرستم: {e}")
    # پس از ارسال، اگه context کاربر ذخیره شده بود برگرد به صفحه کاربر
    back_uid = data.get("back_to_uid")
    if back_uid:
        u2 = get_user_detail(back_uid)
        if u2:
            status = "🚫 مسدود" if u2[4] else "✅ فعال"
            await message.answer(
                f"✅ {amount} سکه به {target_id} اضافه شد.\n🪙 سکه جدید: {new_coins}\n\n"
                f"👤 جزئیات کاربر\n━━━━━━━━━━━━━━━\n🆔 آیدی: <code>{u2[0]}</code>\n"
                f"📛 یوزرنیم: @{u2[1] or 'ندارد'}\n👤 نام: {u2[2]}\n🪙 سکه: {u2[3]}\n"
                f"📌 وضعیت: {status}\n🎁 کانفیگ دریافتی: {u2[5]}\n👥 زیرمجموعه: {u2[6]}\n━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.HTML, reply_markup=user_detail_keyboard(u2[0], u2[4]))
            return
    await message.answer(f"✅ {amount} سکه به {target_id} اضافه شد.\n🪙 سکه جدید: {new_coins}",
        reply_markup=admin_keyboard(message.from_user.id))

@dp.callback_query(F.data == "admin_subcoins")
async def cb_sub_coins(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "coins"): return
    await call.answer()
    await state.set_state(AdminStates.sub_coins_id)
    await call.message.edit_text("➖ کسر سکه\n\nآیدی عددی کاربر رو بفرست:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data.startswith("admin_subcoin_"))
async def cb_sub_coin_direct(call: CallbackQuery, state: FSMContext):
    if not is_any_admin(call.from_user.id): return
    await call.answer()
    target_id = int(call.data.split("_")[-1])
    await state.update_data(sub_coins_target=target_id, back_to_uid=target_id)
    await state.set_state(AdminStates.sub_coins_amount)
    await call.message.edit_text(f"➖ چند سکه از کاربر {target_id} کسر کنم?\nعدد بفرست:")

@dp.message(AdminStates.sub_coins_id)
async def hdl_sub_coins_id(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    if not message.text.strip().isdigit():
        await message.answer("❌ آیدی عددی معتبر بفرست:"); return
    u = get_user(int(message.text.strip()))
    if not u:
        await message.answer("❌ کاربر یافت نشد:"); return
    await state.update_data(sub_coins_target=int(message.text.strip()))
    await state.set_state(AdminStates.sub_coins_amount)
    await message.answer(f"✅ کاربر: {u[2]}\n🪙 سکه فعلی: {u[3]}\n\nچند سکه کسر کنم?")

@dp.message(AdminStates.sub_coins_amount)
async def hdl_sub_coins_amount(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("❌ عدد معتبر بفرست:"); return
    data = await state.get_data()
    amount = int(message.text.strip())
    target_id = data["sub_coins_target"]
    update_coins(target_id, -amount)
    u = get_user(target_id)
    new_coins = u[3] if u else 0
    back_uid = data.get("back_to_uid")
    await state.clear()
    if back_uid:
        u2 = get_user_detail(back_uid)
        if u2:
            status = "🚫 مسدود" if u2[4] else "✅ فعال"
            await message.answer(
                f"✅ {amount} سکه از {target_id} کسر شد.\n🪙 سکه جدید: {new_coins}\n\n"
                f"👤 جزئیات کاربر\n━━━━━━━━━━━━━━━\n🆔 آیدی: <code>{u2[0]}</code>\n"
                f"📛 یوزرنیم: @{u2[1] or 'ندارد'}\n👤 نام: {u2[2]}\n🪙 سکه: {u2[3]}\n"
                f"📌 وضعیت: {status}\n🎁 کانفیگ دریافتی: {u2[5]}\n👥 زیرمجموعه: {u2[6]}\n━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.HTML, reply_markup=user_detail_keyboard(u2[0], u2[4]))
            return
    await message.answer(f"✅ {amount} سکه از {target_id} کسر شد.\n🪙 سکه جدید: {new_coins}",
        reply_markup=admin_keyboard(message.from_user.id))

# ==================== حذف سکه همگانی ====================
@dp.callback_query(F.data == "admin_reset_all_coins")
async def cb_reset_all_coins(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "coins"): return
    await call.answer()
    await call.message.edit_text(
        "⚠️ کل سکه‌های کاربران ریست شود؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("confirm_reset_coins"), callback_data="admin_reset_all_coins_confirm"),
             InlineKeyboardButton(text=get_button_text("reject_reset_coins"), callback_data="open_admin_panel")],
        ]))

@dp.callback_query(F.data == "admin_reset_all_coins_confirm")
async def cb_reset_all_coins_confirm(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "coins"): return
    await call.answer()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET coins = 0")
    conn.commit(); conn.close()
    await call.message.edit_text("✅ تمام سکه‌های کاربران ریست شد.",
        reply_markup=admin_keyboard(call.from_user.id))

# ==================== تنظیم سکه نیاز برای دریافت کانفیگ ====================
@dp.callback_query(F.data == "admin_set_coins_needed")
async def cb_set_coins_needed(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "coins"): return
    await call.answer()
    await state.set_state(AdminStates.set_coins_needed)
    await call.message.edit_text(
        f"🎯 تنظیم سکه نیاز برای دریافت کانفیگ\n━━━━━━━━━━━━━━━\n\n"
        f"مقدار فعلی: {COINS_TO_GET_CONFIG} سکه\n\n"
        f"تعداد سکه جدید رو بفرست (عدد مثبت):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.set_coins_needed)
async def hdl_set_coins_needed(message: Message, state: FSMContext):
    global COINS_TO_GET_CONFIG
    if not is_any_admin(message.from_user.id): return
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("❌ عدد معتبر بفرست:"); return
    new_val = int(message.text.strip())
    COINS_TO_GET_CONFIG = new_val
    cfg = load_config(); cfg["coins_to_get_config"] = new_val; save_config(cfg)
    await state.clear()
    await message.answer(
        f"✅ مقدار سکه نیاز برای دریافت کانفیگ به {new_val} تغییر کرد.",
        reply_markup=admin_keyboard(message.from_user.id))

# ==================== پیام به کاربر ====================
@dp.callback_query(F.data.startswith("admin_msguser_"))
async def cb_msg_user(call: CallbackQuery, state: FSMContext):
    if not is_any_admin(call.from_user.id): return
    await call.answer()
    target_id = int(call.data.split("_")[-1])
    await state.update_data(msg_user_target=target_id, back_to_uid=target_id)
    await state.set_state(AdminStates.msg_user_text)
    await call.message.edit_text(
        f"✉️ پیام به کاربر {target_id}\n\n"
        "متن، عکس، ویدیو، صدا یا فایل رو بفرست (با کپشن یا بدون کپشن):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.msg_user_text)
async def hdl_msg_user_text(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    data = await state.get_data()
    target_id = data["msg_user_target"]
    back_uid = data.get("back_to_uid")
    try:
        # از copy_message استفاده می‌کنیم تا همه انواع مدیا + ایموجی پریمیوم حفظ بشه
        await bot.copy_message(
            chat_id=target_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        ok = True
    except Exception as e:
        ok = False
        await message.answer(f"❌ ارسال ناموفق: {e}", reply_markup=admin_keyboard(message.from_user.id))
    await state.clear()
    if ok:
        # برگشت به جزئیات کاربر اگه از تیکت پشتیبانی اومدیم
        if back_uid:
            u2 = get_user_detail(back_uid)
            if u2:
                status = "🚫 مسدود" if u2[4] else "✅ فعال"
                await message.answer(
                    f"✅ پیام ارسال شد.\n\n"
                    f"👤 جزئیات کاربر\n━━━━━━━━━━━━━━━\n🆔 آیدی: <code>{u2[0]}</code>\n"
                    f"📛 یوزرنیم: @{u2[1] or 'ندارد'}\n👤 نام: {u2[2]}\n🪙 سکه: {u2[3]}\n"
                    f"📌 وضعیت: {status}\n🎁 کانفیگ دریافتی: {u2[5]}\n👥 زیرمجموعه: {u2[6]}\n━━━━━━━━━━━━━━━",
                    parse_mode=ParseMode.HTML, reply_markup=user_detail_keyboard(u2[0], u2[4]))
                return
        await message.answer("✅ پیام ارسال شد.", reply_markup=admin_keyboard(message.from_user.id))

# ==================== ارسال همگانی (با گزینه پین + مدیا + لغو + حذف) ====================

# متغیر گلوبال برای لغو بردکست در حال اجرا (per admin_id)
_broadcast_cancel_flags: dict = {}

@dp.callback_query(F.data == "admin_broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"): return
    await call.answer()
    await state.set_state(AdminStates.broadcast)
    tags = db_get_broadcast_tags()
    del_btn = []
    if tags:
        del_btn = [[InlineKeyboardButton(text="🗑 حذف پیام‌های بردکست قبلی", callback_data="admin_broadcast_del_menu")]]
    await call.message.edit_text(
        "📢 ارسال همگانی\n\n"
        "پیام رو بفرست (متن، عکس، ویدیو، صدا، فایل — همه پشتیبانی می‌شن):\n\n"
        "💡 همچنین می‌تونی یه پیام رو از کانال/چنل فوروارد کنی تا عیناً همون پیام به همه کاربران ارسال بشه.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=del_btn + [
            [InlineKeyboardButton(text=get_button_text("broadcast_unpin_all"), callback_data="admin_unpin_all")],
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.callback_query(F.data == "admin_broadcast_del_menu")
async def cb_broadcast_del_menu(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await state.clear()
    tags = db_get_broadcast_tags()
    if not tags:
        await call.message.edit_text("❌ هیچ بردکست قابل حذفی پیدا نشد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_broadcast")]]))
        return
    rows = []
    for tag, cnt in tags[:10]:
        rows.append([InlineKeyboardButton(text=f"🗑 {tag}  ({cnt} نفر)", callback_data=f"bc_del_{tag}")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_broadcast")])
    await call.message.edit_text("🗑 کدوم بردکست رو می‌خوای از سمت کاربران حذف کنی؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("bc_del_"))
async def cb_broadcast_do_delete(call: CallbackQuery):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    tag = call.data[len("bc_del_"):]
    records = db_delete_broadcast_msgs(tag)
    await call.message.edit_text(f"⏳ در حال حذف پیام‌های بردکست «{tag}» از سمت کاربران...")
    ok = failed = 0
    for uid, mid in records:
        try:
            await bot.delete_message(uid, mid)
            ok += 1
        except:
            failed += 1
    await bot.send_message(call.from_user.id,
        f"✅ حذف بردکست «{tag}» تموم شد.\n🗑 حذف‌شده: {ok}\n❌ ناموفق: {failed}",
        reply_markup=admin_keyboard(call.from_user.id))

@dp.callback_query(F.data == "admin_unpin_all")
async def cb_unpin_all(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await state.clear()
    await call.message.edit_text("⏳ در حال حذف پین‌ها در چت کاربران...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = c.fetchall(); conn.close()
    ok = failed = 0
    for (uid,) in users:
        try:
            await bot.unpin_all_chat_messages(uid)
            ok += 1
        except Exception as e:
            failed += 1
            logger.warning(f"خطا در حذف پین برای {uid}: {e}")
    await bot.send_message(
        call.from_user.id,
        f"✅ حذف پین همگانی تموم شد.\n📍 موفق: {ok}\n❌ ناموفق: {failed}",
        reply_markup=admin_keyboard(call.from_user.id))

@dp.message(AdminStates.broadcast)
async def hdl_broadcast(message: Message, state: FSMContext):
    if not is_any_admin(message.from_user.id): return
    # ذخیره message_id و chat_id برای copy_message بعداً
    await state.update_data(
        bc_from_chat=message.chat.id,
        bc_msg_id=message.message_id,
        bc_has_text=bool(message.text),
        bc_preview=(message.text or message.caption or "")[:200],
    )
    await state.set_state(AdminStates.broadcast_choose_pin)
    preview = message.text or message.caption or f"[{message.content_type}]"
    await message.answer(
        f"📢 پیش‌نمایش پیام همگانی:\n━━━━━━━━━━━━━━━\n\n{preview[:400]}\n\n━━━━━━━━━━━━━━━\n\n"
        f"یکی رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("broadcast_pin"), callback_data="admin_broadcast_pin")],
            [InlineKeyboardButton(text=get_button_text("broadcast_send"), callback_data="admin_broadcast_send")],
            [InlineKeyboardButton(text="📣 ارسال به کانال‌های اسپانسر هم", callback_data="admin_broadcast_ad")],
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")],
        ]))

async def _do_broadcast(call: CallbackQuery, state: FSMContext, pin: bool, also_to_ads: bool = False):
    import datetime as _dt_mod
    data = await state.get_data()
    from_chat = data.get("bc_from_chat")
    msg_id = data.get("bc_msg_id")
    await state.clear()
    if not from_chat or not msg_id:
        await call.message.edit_text("❌ پیامی برای ارسال پیدا نشد.", reply_markup=admin_keyboard(call.from_user.id))
        return
    # تگ یکتا برای این بردکست (برای قابلیت حذف بعدی)
    bc_tag = _dt_mod.datetime.now().strftime("%Y%m%d_%H%M%S")
    await call.message.edit_text(
        f"⏳ در حال ارسال همگانی...\n\n"
        f"🔴 برای لغو /cancel_broadcast بزن",
    )
    _broadcast_cancel_flags[call.from_user.id] = False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = c.fetchall(); conn.close()
    sent = failed = pinned = pin_failed = 0
    sent_records = []
    for (uid,) in users:
        if _broadcast_cancel_flags.get(call.from_user.id):
            break
        try:
            sent_msg = await bot.copy_message(
                chat_id=uid,
                from_chat_id=from_chat,
                message_id=msg_id,
            )
            sent_records.append((uid, sent_msg.message_id))
            sent += 1
            if pin:
                try:
                    await bot.pin_chat_message(uid, sent_msg.message_id, disable_notification=True)
                    pinned += 1
                except Exception as e:
                    pin_failed += 1
        except:
            failed += 1
    # ذخیره شناسه پیام‌ها در DB
    if sent_records:
        db_save_broadcast_msgs(bc_tag, sent_records)
    # ارسال به کانال‌های اسپانسر
    if also_to_ads:
        for ad in AD_CHANNELS:
            cid = (ad.get("chat_id") or "").strip()
            if not cid:
                continue
            try:
                chat_target = int(cid) if cid.lstrip("-").isdigit() else cid
                await bot.copy_message(chat_id=chat_target, from_chat_id=from_chat, message_id=msg_id)
            except Exception as e:
                logger.warning(f"خطا در ارسال بردکست به اسپانسر {cid}: {e}")
    _broadcast_cancel_flags.pop(call.from_user.id, None)
    was_cancelled = _broadcast_cancel_flags.get(call.from_user.id, False)
    summary = f"{'⚠️ بردکست لغو شد.' if was_cancelled else '✅ ارسال همگانی تموم شد.'}\n"
    summary += f"📤 ارسال‌شده: {sent}\n❌ ناموفق: {failed}"
    if pin:
        summary += f"\n📌 پین‌شده: {pinned}\n📌❌ پین ناموفق: {pin_failed}"
    if sent_records:
        summary += f"\n🗂 تگ بردکست: <code>{bc_tag}</code> (برای حذف بعدی)"
    await bot.send_message(call.from_user.id, summary, parse_mode=ParseMode.HTML, reply_markup=admin_keyboard(call.from_user.id))

@dp.callback_query(F.data == "admin_broadcast_pin")
async def cb_broadcast_pin(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await _do_broadcast(call, state, pin=True)

@dp.callback_query(F.data == "admin_broadcast_send")
async def cb_broadcast_send(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await _do_broadcast(call, state, pin=False)

@dp.callback_query(F.data == "admin_broadcast_ad")
async def cb_broadcast_ad(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "broadcast"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    await _do_broadcast(call, state, pin=False, also_to_ads=True)

@dp.message(F.text == "/cancel_broadcast")
async def hdl_cancel_broadcast(message: Message):
    if not is_any_admin(message.from_user.id): return
    if message.from_user.id in _broadcast_cancel_flags:
        _broadcast_cancel_flags[message.from_user.id] = True
        await message.answer("⚠️ درخواست لغو ثبت شد. بردکست بعد از کاربر فعلی متوقف می‌شه.")
    else:
        await message.answer("ℹ️ در حال حاضر بردکستی در جریان نیست.")

# ==================== تنظیم ایدی پشتیبانی ====================
@dp.callback_query(F.data == "admin_set_support")
async def cb_set_support(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "support_id"): return
    await call.answer()
    await state.set_state(AdminStates.set_support_id)
    await call.message.edit_text(
        f"🛟 تنظیم ایدی پشتیبانی\n\nایدی فعلی: {SUPPORT_ID or 'تنظیم نشده'}\n\nایدی جدید رو بفرست (مثلاً @username):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_cancel")]]))

@dp.message(AdminStates.set_support_id)
async def hdl_set_support_id(message: Message, state: FSMContext):
    global SUPPORT_ID
    if not is_any_admin(message.from_user.id): return
    new_id = message.text.strip()
    if not new_id.startswith("@"): new_id = "@" + new_id
    SUPPORT_ID = new_id
    cfg = load_config(); cfg["support_id"] = new_id; save_config(cfg)
    await state.clear()
    await message.answer(f"✅ ایدی پشتیبانی به {new_id} تغییر کرد!", reply_markup=admin_keyboard(message.from_user.id))

# ==================== مدیریت چنل‌ها ====================
def channels_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for idx, ch in enumerate(CHANNEL_IDS):
        display = ch if len(ch) <= 30 else ch[:27] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"{get_button_text('delete_channel')} {display}",
            callback_data=f"admin_delchannel_idx_{idx}",
            style=ButtonStyle.DANGER)])
    buttons.append([InlineKeyboardButton(text=get_button_text("add_channel"), callback_data="admin_addchannel", style=ButtonStyle.SUCCESS)])
    buttons.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "admin_channels")
async def cb_admin_channels(call: CallbackQuery):
    if not has_perm(call.from_user.id, "channels"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    ch_list = "\n".join([f"• {ch}" for ch in CHANNEL_IDS]) if CHANNEL_IDS else "هیچ چنلی ثبت نشده"
    await call.message.edit_text(
        f"📡 مدیریت چنل‌های عضویت اجباری\n━━━━━━━━━━━━━━━\n\nچنل‌های فعلی:\n{ch_list}\n\n"
        f"برای حذف روی چنل بزن:", reply_markup=channels_keyboard())

@dp.callback_query(F.data == "admin_addchannel")
async def cb_add_channel(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "channels"): return
    await call.answer()
    await state.set_state(AdminStates.add_channel)
    await call.message.edit_text(
        "➕ اضافه کردن چنل\n\n"
        "یکی از فرمت‌های زیر رو بفرست:\n"
        "• <code>@mychannel</code> — یوزرنیم عمومی\n"
        "• <code>-1001234567890</code> — آیدی عددی\n"
        "• <code>https://t.me/+AbCdEfGhIj</code> — لینک دعوت خصوصی\n\n"
        "⚠️ برای لینک‌های خصوصی، ربات باید ادمین/عضو اون کانال باشه تا بتونه عضویت رو چک کنه.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_channels")]]))

@dp.message(AdminStates.add_channel)
async def hdl_add_channel(message: Message, state: FSMContext):
    global CHANNEL_IDS
    if not is_any_admin(message.from_user.id): return
    ch = (message.text or "").strip()
    # تشخیص نوع ورودی
    if ch.startswith("https://") or ch.startswith("http://") or ch.startswith("t.me"):
        # لینک دعوت خصوصی — ذخیره همون‌طوری
        entry = ch if ch.startswith("http") else f"https://{ch}"
    elif ch.lstrip("-").isdigit():
        entry = ch  # آیدی عددی
    else:
        entry = ch if ch.startswith("@") else f"@{ch}"
    if entry not in CHANNEL_IDS:
        CHANNEL_IDS.append(entry)
        cfg = load_config(); cfg["channels"] = CHANNEL_IDS; save_config(cfg)
        await message.answer(f"✅ چنل اضافه شد!\n<code>{entry}</code>",
            parse_mode=ParseMode.HTML, reply_markup=channels_keyboard())
    else:
        await message.answer(f"⚠️ این چنل قبلاً ثبت شده!", reply_markup=channels_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("admin_delchannel_idx_"))
async def cb_del_channel(call: CallbackQuery):
    global CHANNEL_IDS
    if not has_perm(call.from_user.id, "channels"): return
    await call.answer()
    try:
        idx = int(call.data.replace("admin_delchannel_idx_", ""))
        removed = CHANNEL_IDS[idx]
        CHANNEL_IDS.pop(idx)
        cfg = load_config(); cfg["channels"] = CHANNEL_IDS; save_config(cfg)
        removed_display = removed
    except (IndexError, ValueError):
        removed_display = "?"
    ch_list = "\n".join([f"• {c}" for c in CHANNEL_IDS]) if CHANNEL_IDS else "هیچ چنلی ثبت نشده"
    await call.message.edit_text(
        f"✅ چنل حذف شد!\n<code>{removed_display}</code>\n\n📡 چنل‌های فعلی:\n{ch_list}\n\nبرای حذف روی چنل بزن:",
        parse_mode=ParseMode.HTML, reply_markup=channels_keyboard())

# ==================== مدیریت ادمین‌ها ====================
@dp.callback_query(F.data == "admin_manage_admins")
async def cb_manage_admins(call: CallbackQuery):
    if not is_super_admin(call.from_user.id):
        await call.answer("❌ فقط ادمین اصلی دسترسی دارد.", show_alert=True); return
    await call.answer()
    rows = []
    for uid_str, perms in SUB_ADMINS.items():
        active = sum(1 for v in perms.values() if v)
        rows.append([InlineKeyboardButton(text=f"👤 {uid_str} | {active}/{len(ALL_PERMS)} دسترسی",
            callback_data=f"admin_editadmin_{uid_str}")])
    rows.append([InlineKeyboardButton(text=get_button_text("add_admin"), callback_data="admin_addadmin", style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    count = len(SUB_ADMINS)
    await call.message.edit_text(
        f"👤 مدیریت ادمین‌ها\n━━━━━━━━━━━━━━━\n\nادمین‌های فعلی: {count} نفر\n\nروی ادمین بزن تا دسترسی‌هاشو تنظیم کنی:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "admin_addadmin")
async def cb_add_admin(call: CallbackQuery, state: FSMContext):
    if not is_super_admin(call.from_user.id): return
    await call.answer()
    await state.set_state(AdminStates.add_admin_id)
    await call.message.edit_text(
        "➕ اضافه کردن ادمین جدید\n\nآیدی عددی یا یوزرنیم @ کاربر رو بفرست:\nمثال: 123456789 یا @username",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel"), callback_data="admin_manage_admins")]]))

@dp.message(AdminStates.add_admin_id)
async def hdl_add_admin_id(message: Message, state: FSMContext):
    global SUB_ADMINS
    if not is_super_admin(message.from_user.id): return
    text = message.text.strip().lstrip("@")
    if not text.isdigit():
        await message.answer("❌ لطفاً آیدی عددی بفرست (نه یوزرنیم):"); return
    uid_str = text
    if uid_str not in SUB_ADMINS:
        SUB_ADMINS[uid_str] = {p: False for p in ALL_PERMS}
        cfg = load_config(); cfg["sub_admins"] = SUB_ADMINS; save_config(cfg)
    await state.clear()
    await message.answer(
        f"✅ ادمین {uid_str} اضافه شد!\nالان دسترسی‌هاشو تنظیم کن:",
        reply_markup=sub_admin_perms_keyboard(int(uid_str)))

@dp.callback_query(F.data.startswith("admin_editadmin_"))
async def cb_edit_admin(call: CallbackQuery):
    if not is_super_admin(call.from_user.id): return
    await call.answer()
    target_id = int(call.data.replace("admin_editadmin_", ""))
    perms = SUB_ADMINS.get(str(target_id), {})
    active = sum(1 for v in perms.values() if v)
    await call.message.edit_text(
        f"👤 ادمین: {target_id}\n━━━━━━━━━━━━━━━\n"
        f"دسترسی‌های فعال: {active}/{len(ALL_PERMS)}\n\nروی هر گزینه بزن تا آن/آف بشه:",
        reply_markup=sub_admin_perms_keyboard(target_id))

@dp.callback_query(F.data.startswith("admin_toggleperm_"))
async def cb_toggle_perm(call: CallbackQuery):
    global SUB_ADMINS
    if not is_super_admin(call.from_user.id): return
    await call.answer()
    parts = call.data.replace("admin_toggleperm_", "").split("_", 1)
    target_id = parts[0]
    perm = parts[1]
    if target_id not in SUB_ADMINS:
        SUB_ADMINS[target_id] = {p: False for p in ALL_PERMS}
    current = SUB_ADMINS[target_id].get(perm, False)
    SUB_ADMINS[target_id][perm] = not current
    cfg = load_config(); cfg["sub_admins"] = SUB_ADMINS; save_config(cfg)
    active = sum(1 for v in SUB_ADMINS[target_id].values() if v)
    await call.message.edit_text(
        f"👤 ادمین: {target_id}\n━━━━━━━━━━━━━━━\n"
        f"دسترسی‌های فعال: {active}/{len(ALL_PERMS)}\n\nروی هر گزینه بزن تا آن/آف بشه:",
        reply_markup=sub_admin_perms_keyboard(int(target_id)))

@dp.callback_query(F.data.startswith("admin_removeadmin_"))
async def cb_remove_admin(call: CallbackQuery):
    global SUB_ADMINS
    if not is_super_admin(call.from_user.id): return
    await call.answer()
    target_id = call.data.replace("admin_removeadmin_", "")
    SUB_ADMINS.pop(target_id, None)
    cfg = load_config(); cfg["sub_admins"] = SUB_ADMINS; save_config(cfg)
    rows = []
    for uid_str, perms in SUB_ADMINS.items():
        active = sum(1 for v in perms.values() if v)
        rows.append([InlineKeyboardButton(text=f"👤 {uid_str} | {active}/{len(ALL_PERMS)} دسترسی",
            callback_data=f"admin_editadmin_{uid_str}")])
    rows.append([InlineKeyboardButton(text=get_button_text("add_admin"), callback_data="admin_addadmin", style=ButtonStyle.SUCCESS)])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    await call.message.edit_text(
        f"✅ ادمین {target_id} حذف شد!\n\n👤 مدیریت ادمین‌ها\nادمین‌های فعلی: {len(SUB_ADMINS)} نفر",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

# ==================== لغو ====================
@dp.callback_query(F.data == "admin_cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await call.message.edit_text("❌ عملیات لغو شد.", reply_markup=admin_keyboard(call.from_user.id))

# ==================== ریست متن‌ها به مقادیر پیش‌فرض ====================
@dp.message(Command("refresh_texts"))
async def cmd_refresh_texts(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS and not has_perm(message.from_user.id, "texts"):
        await message.answer("❌ دسترسی نداری.")
        return
    global BOT_TEXTS
    BOT_TEXTS = DEFAULT_TEXTS.copy()
    cfg = load_config()
    cfg["texts"] = BOT_TEXTS
    save_config(cfg)
    await message.answer(
        "✅ تمام متن‌های ربات به مقادیر پیش‌فرض جدید ریست شدن.\n"
        "حالا متن start با اموجی پریمیوم نمایش داده میشه.\n\n"
        "برای تست، /start بزن."
    )

# ==================== تنظیم رنگ دکمه‌ها ====================
def colors_list_keyboard(page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    items = list(BUTTON_NAMES.items())
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    rows = []
    color_emoji = {"primary": "🔵", "danger": "🔴", "success": "🟢", "default": "⚪"}
    for key, name in items[start:start + per_page]:
        cur = get_btn_color(key)
        rows.append([InlineKeyboardButton(text=f"{color_emoji.get(cur,'⚪')} {name}",
                                          callback_data=f"admin_colorpick_{key}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=get_button_text("prev_page"), callback_data=f"admin_colors_{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text=get_button_text("next_page"), callback_data=f"admin_colors_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("admin_colors_"))
async def cb_admin_colors(call: CallbackQuery):
    if not has_perm(call.from_user.id, "colors"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    try: page = int(call.data.replace("admin_colors_", ""))
    except: page = 0
    await call.message.edit_text(
        "🎨 تنظیم رنگ دکمه‌ها\n━━━━━━━━━━━━━━━\n\n"
        "روی دکمه‌ای که می‌خوای رنگش رو عوض کنی بزن:\n"
        "🔵 آبی | 🔴 قرمز | 🟢 سبز | ⚪ معمولی (شیشه‌ای)",
        reply_markup=colors_list_keyboard(page))

@dp.callback_query(F.data.startswith("admin_colorpick_"))
async def cb_admin_color_pick(call: CallbackQuery):
    if not has_perm(call.from_user.id, "colors"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    await call.answer()
    key = call.data.replace("admin_colorpick_", "")
    name = BUTTON_NAMES.get(key, key)
    cur = get_btn_color(key)
    color_fa = {"primary": "🔵 آبی", "danger": "🔴 قرمز", "success": "🟢 سبز", "default": "⚪ معمولی"}
    rows = [
        [InlineKeyboardButton(text=get_button_text("color_red"),     callback_data=f"admin_setcolor_{key}_danger",  style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=get_button_text("color_green"),   callback_data=f"admin_setcolor_{key}_success", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text=get_button_text("color_blue"),    callback_data=f"admin_setcolor_{key}_primary", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text=get_button_text("color_default"), callback_data=f"admin_setcolor_{key}_default", style=ButtonStyle.DEFAULT)],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_colors_0")],
    ]
    await call.message.edit_text(
        f"🎨 تغییر رنگ\n━━━━━━━━━━━━━━━\n\n"
        f"دکمه: {name}\nرنگ فعلی: {color_fa.get(cur,'⚪ معمولی')}\n\nرنگ جدید رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("admin_setcolor_"))
async def cb_admin_set_color(call: CallbackQuery):
    if not has_perm(call.from_user.id, "colors"):
        await call.answer("❌ دسترسی ندارید.", show_alert=True); return
    rest = call.data.replace("admin_setcolor_", "")
    last = rest.rfind("_")
    if last == -1:
        await call.answer(); return
    key, color = rest[:last], rest[last+1:]
    if color not in _COLOR_TO_STYLE:
        await call.answer("❌ رنگ نامعتبر.", show_alert=True); return
    save_btn_color(key, color)
    await call.answer("✅ رنگ ذخیره شد.")
    await call.message.edit_text(
        "🎨 تنظیم رنگ دکمه‌ها\n━━━━━━━━━━━━━━━\n\n✅ رنگ با موفقیت تغییر کرد.\n\n"
        "روی دکمه دیگری بزن یا برگرد:",
        reply_markup=colors_list_keyboard(0))

# ==================== هندلر اضافه شدن ربات به گروه به عنوان ادمین ====================
@dp.my_chat_member()
async def on_bot_chat_member(event):
    """وقتی ربات به گروهی به عنوان ادمین اضافه بشه، یه game action ارسال می‌کنه."""
    try:
        new_status = event.new_chat_member.status if event.new_chat_member else None
        old_status = event.old_chat_member.status if event.old_chat_member else None
        # فقط وقتی ربات به ادمین ارتقا پیدا کرده
        if new_status == "administrator" and old_status != "administrator":
            from aiogram.enums import ChatAction
            try:
                await bot.send_chat_action(event.chat.id, action=ChatAction.PLAYING)
            except Exception as e:
                logger.info(f"نتونستم ChatAction.PLAYING بفرستم به {event.chat.id}: {e}")
    except Exception as e:
        logger.warning(f"خطا در on_bot_chat_member: {e}")

# ==================== هندلر لفت دادن از کانال اجباری ====================
@dp.chat_member()
async def on_chat_member_update(event):
    """وقتی کاربر از یکی از کانال‌های اجباری لفت بده، بهش پیام می‌دیم بیاد برگرده."""
    try:
        if not LEAVE_ALERT_ENABLED:
            return
        chat = event.chat
        # فقط کانال‌های اجباری ربات
        chat_username = f"@{chat.username}" if getattr(chat, "username", None) else None
        chat_id_str = str(chat.id)
        # بررسی می‌کنیم که این چت در لیست کانال‌های اجباری هست
        # کانال‌ها می‌تونن @username، آیدی عددی، یا لینک خصوصی باشن
        def _in_channels(ch_ids: list) -> bool:
            if chat_username and chat_username in ch_ids: return True
            if chat_id_str in ch_ids: return True
            # برای لینک‌های خصوصی، چک می‌کنیم که chat.id داخل یه entry خاص باشه
            # (لینک‌های خصوصی قابل مقایسه با chat.id نیستن مگه اینکه resolv بشن)
            return False
        if not _in_channels(CHANNEL_IDS):
            return
        old = event.old_chat_member.status if event.old_chat_member else None
        new = event.new_chat_member.status if event.new_chat_member else None
        # وضعیت‌های قبلی که عضو بوده
        was_member = old in ("member", "administrator", "creator", "restricted")
        # وضعیت‌های جدید که دیگه عضو نیست
        is_left = new in ("left", "kicked")
        if not (was_member and is_left):
            return
        user = event.new_chat_member.user
        if not user or user.is_bot:
            return
        ch_label = chat_username or chat.title or str(chat.id)
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"🔙 برگشت به {ch_label}",
                    url=f"https://t.me/{(chat_username or '').lstrip('@')}" if chat_username else f"https://t.me/c/{str(chat.id).lstrip('-100')}",
                )]
            ])
            template = get_bot_text("leave_alert")
            try:
                body = template.format(channel=ch_label)
            except Exception:
                body = template
            await bot.send_message(
                user.id,
                body,
                reply_markup=kb,
            )
        except Exception as e:
            logger.info(f"نتونستم به کاربر {user.id} پیام لفت بدم: {e}")
    except Exception as e:
        logger.warning(f"خطا در on_chat_member_update: {e}")

# ==================== ادمین: مدیریت اد لیست ====================
def ad_channels_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i, ad in enumerate(AD_CHANNELS):
        txt = ad.get("text", "(بدون متن)")
        rows.append([InlineKeyboardButton(text=f"✏️ {i+1}. {txt[:25]}", callback_data=f"ad_edit_{i}")])
    rows.append([InlineKeyboardButton(text=get_button_text("ad_add"), callback_data="ad_add")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ad_item_keyboard(idx: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=get_button_text("ad_edit_text"), callback_data=f"ad_etxt_{idx}")],
        [InlineKeyboardButton(text=get_button_text("ad_edit_color"), callback_data=f"ad_ecol_{idx}_0")],
        [InlineKeyboardButton(text=get_button_text("ad_delete"), callback_data=f"ad_del_{idx}", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_ad_channels")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def ad_color_keyboard(idx: int, page: int = 0) -> InlineKeyboardMarkup:
    colors = list(_COLOR_TO_STYLE.keys())
    per = 6
    chunk = colors[page*per:(page+1)*per]
    rows = []
    for c in chunk:
        rows.append([InlineKeyboardButton(text=COLOR_NAMES.get(c, c), callback_data=f"ad_setcol_{idx}_{c}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"ad_ecol_{idx}_{page-1}"))
    if (page+1)*per < len(colors):
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"ad_ecol_{idx}_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"ad_edit_{idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "admin_ad_channels")
async def cb_admin_ad_channels(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await state.clear()
    await call.message.edit_text(
        f"📣 ادلیست VIP\n━━━━━━━━━━━━━━━\n\nتعداد فعلی: {len(AD_CHANNELS)}\n\nروی هر مورد بزن تا ویرایشش کنی، یا یه ادلیست جدید اضافه کن.",
        reply_markup=ad_channels_keyboard())

@dp.callback_query(F.data.startswith("ad_edit_"))
async def cb_ad_edit(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    idx = int(call.data.split("_")[2])
    if idx < 0 or idx >= len(AD_CHANNELS):
        await call.answer("❌ پیدا نشد.", show_alert=True); return
    ad = AD_CHANNELS[idx]
    await call.message.edit_text(
        f"✏️ ویرایش مورد {idx+1}\n━━━━━━━━━━━━━━━\n\n📝 متن: {ad.get('text','')}\n🔗 لینک: {ad.get('url','')}\n🎨 رنگ: {COLOR_NAMES.get(ad.get('color','default'), ad.get('color','default'))}",
        reply_markup=ad_item_keyboard(idx))

@dp.callback_query(F.data == "ad_add")
async def cb_ad_add(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await state.clear()
    await state.set_state(AdminStates.ad_add_count)
    await state.update_data(ad_collected=[])
    await call.message.edit_text(
        "📊 ادلیست VIP جدید\n━━━━━━━━━━━━━━━\n\nچنتا کانال توی این ادلیست هست؟\nیه عدد بفرست (مثلاً <b>3</b>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_ad_channels")]]))

@dp.message(AdminStates.ad_add_count)
async def hdl_ad_add_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ فقط یه عدد بفرست (مثلاً 3):")
        return
    n = int(raw)
    if n < 1 or n > 20:
        await message.answer("❌ عدد باید بین 1 تا 20 باشه. دوباره بفرست:")
        return
    await state.update_data(ad_total=n, ad_collected=[])
    await state.set_state(AdminStates.ad_add_channels)
    await message.answer(
        f"📡 آیدی کانال <b>۱</b> رو بفرست:\n\n"
        f"مثال: <code>@my_channel</code> یا <code>https://t.me/my_channel</code> یا <code>-1001234567890</code>\n\n"
        f"⚠️ <b>مهم:</b> ربات حتماً باید توی اون کانال ادمین باشه."
    )

async def _normalize_and_validate_channel(raw: str):
    """آیدی کانال رو نرمالایز و عضویت ربات رو چک می‌کنه. (chat_id, url, error_msg) برمی‌گردونه."""
    raw = raw.strip()
    if raw.startswith("https://t.me/"):
        raw = "@" + raw[len("https://t.me/"):].split("/")[0].split("?")[0]
    elif raw.startswith("t.me/"):
        raw = "@" + raw[len("t.me/"):].split("/")[0].split("?")[0]
    if raw.startswith("@") or raw.startswith("-100") or raw.lstrip("-").isdigit():
        chat_id = raw
    else:
        chat_id = "@" + raw.lstrip("@")
    url = f"https://t.me/{chat_id.lstrip('@')}" if chat_id.startswith("@") else ""
    try:
        me = await bot.get_me()
        bot_member = await bot.get_chat_member(chat_id, me.id)
        if bot_member.status not in ("administrator", "creator"):
            return None, None, f"⚠️ ربات در {chat_id} ادمین نیست! اول ربات رو ادمین کن، بعد دوباره آیدی همین کانال رو بفرست."
        if not url:
            try:
                chat = await bot.get_chat(chat_id)
                if getattr(chat, "username", None):
                    url = f"https://t.me/{chat.username}"
                elif getattr(chat, "invite_link", None):
                    url = chat.invite_link
            except Exception:
                pass
    except Exception as e:
        return None, None, f"❌ نتونستم کانال {chat_id} رو پیدا کنم یا ربات اونجا ادمین نیست.\nخطا: <code>{e}</code>\n\nدوباره آیدی صحیح بفرست."
    return chat_id, url, None

@dp.message(AdminStates.ad_add_channels)
async def hdl_ad_add_channels(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ آیدی خالیه. دوباره بفرست:")
        return
    chat_id, url, err = await _normalize_and_validate_channel(raw)
    if err:
        await message.answer(err)
        return
    data = await state.get_data()
    collected = list(data.get("ad_collected", []))
    total = int(data.get("ad_total", 0))
    if any(c.get("chat_id") == chat_id for c in collected):
        await message.answer(f"⚠️ کانال {chat_id} قبلاً اضافه شده. یه آیدی دیگه بفرست:")
        return
    collected.append({"chat_id": chat_id, "url": url or ""})
    await state.update_data(ad_collected=collected)
    if len(collected) < total:
        nxt = len(collected) + 1
        await message.answer(
            f"✅ کانال {len(collected)} از {total} ثبت شد: <code>{chat_id}</code>\n\n"
            f"📡 آیدی کانال <b>{nxt}</b> رو بفرست:"
        )
    else:
        await state.set_state(AdminStates.ad_add_label)
        await message.answer(
            f"✅ همه {total} کانال ثبت شدن.\n━━━━━━━━━━━━━━━\n\n"
            f"📝 حالا متن دکمه ادلیست رو بفرست (همین متن روی منوی اصلی به کاربر نشون داده می‌شه):"
        )

@dp.message(AdminStates.ad_add_label)
async def hdl_ad_add_label(message: Message, state: FSMContext):
    label = (message.text or "").strip()
    if not label:
        await message.answer("❌ متن خالیه. دوباره بفرست:")
        return
    data = await state.get_data()
    collected = list(data.get("ad_collected", []))
    if not collected:
        await state.clear()
        await message.answer("❌ خطا: هیچ کانالی ثبت نشده. از اول شروع کن.", reply_markup=ad_channels_keyboard())
        return
    added = 0
    for ch in collected:
        AD_CHANNELS.append({
            "text": label,
            "url": ch.get("url", ""),
            "color": "default",
            "chat_id": ch.get("chat_id", ""),
        })
        added += 1
    save_ad_channels()
    await state.clear()
    ids = "\n".join(f"  • <code>{c.get('chat_id','')}</code>" for c in collected)
    await message.answer(
        f"✅ ادلیست VIP اضافه شد!\n━━━━━━━━━━━━━━━\n\n"
        f"📝 متن دکمه: <b>{label}</b>\n"
        f"📡 تعداد کانال: <b>{added}</b>\n{ids}\n\n"
        f"از این به بعد کاربرها برای استفاده از ربات باید عضو همه این کانال‌ها هم باشن.",
        reply_markup=ad_channels_keyboard())

@dp.callback_query(F.data.startswith("ad_del_"))
async def cb_ad_del(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    idx = int(call.data.split("_")[2])
    if 0 <= idx < len(AD_CHANNELS):
        AD_CHANNELS.pop(idx)
        save_ad_channels()
        await call.answer("✅ حذف شد.")
    await call.message.edit_text("📢 مدیریت اد لیست", reply_markup=ad_channels_keyboard())

@dp.callback_query(F.data.startswith("ad_etxt_"))
async def cb_ad_etxt(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    idx = int(call.data.split("_")[2])
    await state.set_state(AdminStates.ad_edit_text)
    await state.update_data(ad_idx=idx)
    await call.message.edit_text("📝 متن جدید رو بفرست:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"ad_edit_{idx}")]]))

@dp.message(AdminStates.ad_edit_text)
async def hdl_ad_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data.get("ad_idx", -1)
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("❌ متن خالیه. دوباره بفرست:")
        return
    if 0 <= idx < len(AD_CHANNELS):
        AD_CHANNELS[idx]["text"] = txt
        save_ad_channels()
    await state.clear()
    await message.answer("✅ متن ذخیره شد.", reply_markup=ad_channels_keyboard())

@dp.callback_query(F.data.startswith("ad_ecol_"))
async def cb_ad_ecol(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split("_")
    idx = int(parts[2]); page = int(parts[3])
    await call.message.edit_text("🎨 رنگ مورد نظر رو انتخاب کن:", reply_markup=ad_color_keyboard(idx, page))

@dp.callback_query(F.data.startswith("ad_setcol_"))
async def cb_ad_setcol(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ad_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split("_")
    idx = int(parts[2]); color = parts[3]
    if color not in _COLOR_TO_STYLE:
        await call.answer("❌ رنگ نامعتبر.", show_alert=True); return
    if 0 <= idx < len(AD_CHANNELS):
        AD_CHANNELS[idx]["color"] = color
        save_ad_channels()
        await call.answer("✅ رنگ ذخیره شد.")
    await call.message.edit_text("📢 مدیریت اد لیست", reply_markup=ad_channels_keyboard())

# ==================== ادمین: مدیریت ایموجی‌های پریمیوم ====================
def premium_emojis_keyboard() -> InlineKeyboardMarkup:
    rows = []
    # کلیدهای پیش‌فرض موجود + کلیدهای override شده
    keys = sorted(set(list(PREMIUM_EMOJIS.keys()) + list(PREMIUM_EMOJIS_OVERRIDES.keys())))
    for k in keys:
        # ⚠️ توی متن دکمه inline نمی‌تونیم تگ HTML بذاریم.
        # فقط وضعیت ست بودن و چند رقم آخر ID رو نشون می‌دیم.
        eid = PREMIUM_EMOJIS.get(k, "")
        if eid:
            tail = eid[-6:] if len(eid) > 6 else eid
            label = f"✅ {k} ({tail})"
        else:
            label = f"⚪ {k} (تنظیم نشده)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"pe_view_{k}")])
    rows.append([InlineKeyboardButton(text=get_button_text("premium_add"), callback_data="pe_add")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "admin_premium_emojis")
async def cb_admin_premium_emojis(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    try:
        await call.message.edit_text(
            "✨ مدیریت ایموجی‌های پریمیوم\n━━━━━━━━━━━━━━━\n\n"
            "این ایموجی‌ها در متن‌های ربات (تگ tg-emoji) استفاده می‌شن.\n"
            "برای ست کردن، روی هر کلید بزن و یه ایموجی پریمیوم بفرست — خودش به ID تبدیل می‌شه.",
            reply_markup=premium_emojis_keyboard())
    except Exception as e:
        logger.warning(f"خطا در باز کردن منوی ایموجی پریمیوم: {e}")
        try:
            await call.message.answer(
                "✨ مدیریت ایموجی‌های پریمیوم",
                reply_markup=premium_emojis_keyboard())
        except Exception as e2:
            logger.error(f"خطا در ارسال منوی ایموجی پریمیوم: {e2}")
            await call.answer(f"❌ خطا: {e2}", show_alert=True)

@dp.callback_query(F.data.startswith("pe_view_"))
async def cb_pe_view(call: CallbackQuery):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    key = call.data[len("pe_view_"):]
    cur_id = PREMIUM_EMOJIS.get(key, "")
    preview = pe_key(key, pe_fallback_char(key)) if cur_id else "(تنظیم نشده)"
    rows = [
        [InlineKeyboardButton(text="✏️ تغییر / تنظیم این ایموجی", callback_data=f"pe_edit_{key}")],
        [InlineKeyboardButton(text="📌 درج این ایموجی در یک متن یا دکمه", callback_data=f"peins:{key}")],
        [InlineKeyboardButton(text=get_button_text("premium_delete"), callback_data=f"pe_del_{key}", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_premium_emojis")],
    ]
    await call.message.edit_text(
        f"🔑 کلید: <code>{key}</code>\n"
        f"🆔 custom_emoji_id فعلی: <code>{cur_id or '-'}</code>\n"
        f"👁 پیش‌نمایش: {preview}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

# ===== درج ایموجی پریمیوم در متن‌ها / دکمه‌ها =====
PE_PAGE_SIZE = 8

@dp.callback_query(F.data.startswith("peins:"))
async def cb_pe_insert_menu(call: CallbackQuery):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    pe_k = call.data.split(":", 1)[1]
    cur_id = PREMIUM_EMOJIS.get(pe_k, "")
    if not cur_id:
        await call.answer("❌ این کلید هنوز ID نداره. اول تنظیمش کن.", show_alert=True); return
    await call.answer()
    rows = [
        [InlineKeyboardButton(text="📝 لیست متن‌های ربات", callback_data=f"pelt:{pe_k}:0")],
        [InlineKeyboardButton(text="🔘 لیست دکمه‌های شیشه‌ای", callback_data=f"pelb:{pe_k}:0")],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"pe_view_{pe_k}")],
    ]
    await call.message.edit_text(
        f"📌 درج ایموجی <b>{pe_k}</b> ({pe_key(pe_k, pe_fallback_char(pe_k))})\n\n"
        "می‌خوای این ایموجی به کجا اضافه بشه؟\n\n"
        "• <b>متن‌ها:</b> ایموجی پریمیوم واقعی (تگ tg-emoji) به آخر متن اضافه می‌شه.\n"
        "• <b>دکمه‌ها:</b> چون تلگرام HTML در دکمه‌ها قبول نمی‌کنه، فقط نسخه fallback (ایموجی استاندارد) اضافه می‌شه.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

def _pe_paginated_keyboard(items: list, prefix: str, pe_k: str, page: int, back_cb: str) -> InlineKeyboardMarkup:
    """ساخت کیبورد صفحه‌بندی شده برای انتخاب متن یا دکمه."""
    total = len(items)
    pages = max(1, (total + PE_PAGE_SIZE - 1) // PE_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * PE_PAGE_SIZE
    end = start + PE_PAGE_SIZE
    rows = []
    for k, label in items[start:end]:
        # محدود کردن طول لیبل برای دکمه
        short = label if len(label) <= 40 else label[:37] + "…"
        rows.append([InlineKeyboardButton(text=short, callback_data=f"{prefix}:{pe_k}:{k}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"{'pelt' if prefix=='peat' else 'pelb'}:{pe_k}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"{'pelt' if prefix=='peat' else 'pelb'}:{pe_k}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("pelt:"))
async def cb_pe_list_texts(call: CallbackQuery):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":")
    pe_k = parts[1]
    try:
        page = int(parts[2])
    except Exception:
        page = 0
    await call.answer()
    items = sorted([(k, v) for k, v in TEXT_NAMES.items()], key=lambda x: x[1])
    kb = _pe_paginated_keyboard(items, "peat", pe_k, page, back_cb=f"peins:{pe_k}")
    await call.message.edit_text(
        f"📝 یک متن انتخاب کن تا ایموجی <b>{pe_k}</b> به آخرش اضافه بشه:",
        parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data.startswith("pelb:"))
async def cb_pe_list_buttons(call: CallbackQuery):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":")
    pe_k = parts[1]
    try:
        page = int(parts[2])
    except Exception:
        page = 0
    await call.answer()
    items = sorted([(k, v) for k, v in BUTTON_NAMES.items()], key=lambda x: x[1])
    kb = _pe_paginated_keyboard(items, "peab", pe_k, page, back_cb=f"peins:{pe_k}")
    await call.message.edit_text(
        f"🔘 یک دکمه انتخاب کن تا ایموجی fallback <b>{pe_k}</b> ({pe_fallback_char(pe_k)}) به اول اسمش اضافه بشه:",
        parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data.startswith("peat:"))
async def cb_pe_apply_text(call: CallbackQuery):
    """در مرحله اول فقط می‌پرسیم چپ یا راست؛ سپس peatx اعمال می‌کنه."""
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":", 2)
    pe_k = parts[1]
    text_key = parts[2]
    if text_key not in TEXT_NAMES:
        await call.answer("❌ این متن پیدا نشد.", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        f"📝 ایموجی <b>{pe_k}</b> رو کجای متن «{TEXT_NAMES[text_key]}» بذارم؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_button_text("pe_pos_left"),  callback_data=f"peatx:{pe_k}:L:{text_key}"),
                InlineKeyboardButton(text=get_button_text("pe_pos_right"), callback_data=f"peatx:{pe_k}:R:{text_key}"),
            ],
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"pelt:{pe_k}:0")],
        ]))

@dp.callback_query(F.data.startswith("peatx:"))
async def cb_pe_apply_text_pos(call: CallbackQuery):
    """اعمال نهایی ایموجی روی متن با موقعیت چپ یا راست."""
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":", 3)
    pe_k = parts[1]
    pos = parts[2]
    text_key = parts[3]
    cur_id = PREMIUM_EMOJIS.get(pe_k, "")
    if not cur_id:
        await call.answer("❌ این ایموجی هنوز ID نداره.", show_alert=True); return
    if text_key not in TEXT_NAMES:
        await call.answer("❌ این متن پیدا نشد.", show_alert=True); return
    fallback = pe_fallback_char(pe_k)
    tag = pe(cur_id, fallback)
    cur_text = get_bot_text(text_key) or ""
    if cur_id in cur_text:
        await call.answer("⚠️ این ایموجی از قبل توی این متن هست.", show_alert=True)
        return
    if pos == "L":
        new_text = (tag + " " + cur_text).strip()
    else:
        new_text = (cur_text + " " + tag).strip()
    save_bot_text(text_key, new_text)
    await call.answer("✅ اضافه شد.", show_alert=False)
    pos_label = "چپ (اول)" if pos == "L" else "راست (آخر)"
    await call.message.edit_text(
        f"✅ ایموجی <b>{pe_k}</b> از سمت {pos_label} به متن «{TEXT_NAMES[text_key]}» اضافه شد.\n\n"
        f"متن جدید:\n<code>{new_text[:500]}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 درج در متن دیگه", callback_data=f"pelt:{pe_k}:0")],
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"pe_view_{pe_k}")],
        ]))

@dp.callback_query(F.data.startswith("peab:"))
async def cb_pe_apply_button(call: CallbackQuery):
    """مرحله اول: می‌پرسیم چپ یا راست؛ سپس peabx اعمال می‌کنه."""
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":", 2)
    pe_k = parts[1]
    btn_key = parts[2]
    if btn_key not in BUTTON_NAMES:
        await call.answer("❌ این دکمه پیدا نشد.", show_alert=True); return
    await call.answer()
    fallback = pe_fallback_char(pe_k)
    await call.message.edit_text(
        f"🔘 ایموجی <b>{pe_k}</b> ({fallback}) رو کجای اسم دکمه «{BUTTON_NAMES[btn_key]}» بذارم؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_button_text("pe_pos_left"),  callback_data=f"peabx:{pe_k}:L:{btn_key}"),
                InlineKeyboardButton(text=get_button_text("pe_pos_right"), callback_data=f"peabx:{pe_k}:R:{btn_key}"),
            ],
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"pelb:{pe_k}:0")],
        ]))

@dp.callback_query(F.data.startswith("peabx:"))
async def cb_pe_apply_button_pos(call: CallbackQuery):
    """اعمال نهایی ایموجی fallback روی دکمه با موقعیت چپ یا راست."""
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    parts = call.data.split(":", 3)
    pe_k = parts[1]
    pos = parts[2]
    btn_key = parts[3]
    if btn_key not in BUTTON_NAMES:
        await call.answer("❌ این دکمه پیدا نشد.", show_alert=True); return
    fallback = pe_fallback_char(pe_k)
    cur_text = get_button_text(btn_key) or ""
    if fallback in cur_text:
        await call.answer("⚠️ این ایموجی از قبل توی این دکمه هست.", show_alert=True)
        return
    if pos == "L":
        new_text = f"{fallback} {cur_text}".strip()
    else:
        new_text = f"{cur_text} {fallback}".strip()
    save_button_text(btn_key, new_text)
    await call.answer("✅ اضافه شد.", show_alert=False)
    pos_label = "چپ (اول)" if pos == "L" else "راست (آخر)"
    await call.message.edit_text(
        f"✅ ایموجی fallback <b>{pe_k}</b> ({fallback}) از سمت {pos_label} به دکمه «{BUTTON_NAMES[btn_key]}» اضافه شد.\n\n"
        f"اسم جدید: <code>{new_text}</code>\n\n"
        f"⚠️ یادآوری: تلگرام اجازه نمی‌ده ایموجی پریمیوم واقعی روی دکمه‌های شیشه‌ای استفاده بشه — فقط ایموجی استاندارد ممکنه.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔘 درج در دکمه دیگه", callback_data=f"pelb:{pe_k}:0")],
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=f"pe_view_{pe_k}")],
        ]))

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@dp.callback_query(F.data.startswith("pe_edit_"))
async def cb_pe_edit(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    key = call.data[len("pe_edit_"):]
    await state.set_state(AdminStates.premium_add_id)
    await state.update_data(pe_key=key)
    await call.message.edit_text(
        f"✨ ایموجی جدید برای کلید «{key}» رو بفرست:\n\n"
        "1️⃣ از کیبورد ایموجی پایین تلگرام، یک ایموجی پریمیوم بذار و بفرست — خودش به ID تبدیل می‌شه.\n"
        "2️⃣ یا اگه custom_emoji_id رو دستی داری، فقط عدد ID رو بفرست.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_premium_emojis")]]))

@dp.callback_query(F.data.startswith("pe_del_"))
async def cb_pe_del(call: CallbackQuery):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    key = call.data[len("pe_del_"):]
    remove_premium_emoji(key)
    await call.answer("✅ حذف شد.")
    await call.message.edit_text("✨ مدیریت ایموجی‌های پریمیوم", reply_markup=premium_emojis_keyboard())

@dp.callback_query(F.data == "pe_add")
async def cb_pe_add(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "premium_emojis"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await state.set_state(AdminStates.premium_add_key)
    await call.message.edit_text(
        "🔑 نام کلید ایموجی رو بفرست (مثلاً fire یا star):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="admin_premium_emojis")]]))

@dp.message(AdminStates.premium_add_key)
async def hdl_pe_add_key(message: Message, state: FSMContext):
    key = (message.text or "").strip()
    if not key or not key.replace("_","").isalnum():
        await message.answer("❌ کلید معتبر نیست. فقط حروف انگلیسی/عدد/_ مجازه. دوباره بفرست:")
        return
    await state.update_data(pe_key=key)
    await state.set_state(AdminStates.premium_add_id)
    await message.answer(
        f"✨ حالا برای کلید «{key}» یکی از این دو کار رو بکن:\n\n"
        "1️⃣ از منوی ایموجی پایین تلگرام، یک ایموجی پریمیوم انتخاب کن و بفرست (توصیه می‌شود).\n"
        "2️⃣ یا اگه custom_emoji_id رو دستی داری، فقط عدد ID رو بفرست."
    )

@dp.message(AdminStates.premium_add_id)
async def hdl_pe_add_id(message: Message, state: FSMContext):
    # اولویت با ایموجی پریمیوم در پیام
    eid = first_premium_emoji_id(message)
    if not eid:
        raw = (message.text or "").strip()
        if raw.isdigit():
            eid = raw
        else:
            await message.answer(
                "❌ پیدا نشد. یا یک ایموجی پریمیوم از منوی ایموجی پایین بفرست،\n"
                "یا custom_emoji_id رو به‌صورت عدد بفرست."
            )
            return
    data = await state.get_data()
    set_premium_emoji(data.get("pe_key",""), eid)
    await state.clear()
    await message.answer(f"✅ ایموجی پریمیوم ذخیره شد.\n🆔 {eid}", reply_markup=premium_emojis_keyboard())

# ==================== ادمین: ری‌اکشن استارت ====================
def start_reaction_keyboard() -> InlineKeyboardMarkup:
    enabled = START_REACTION.get("enabled", True)
    rows = [
        [InlineKeyboardButton(
            text=("🟢 فعاله - برای خاموش کردن بزن" if enabled else "🔴 خاموشه - برای فعال کردن بزن"),
            callback_data="sr_toggle")],
        [InlineKeyboardButton(text=get_button_text("reaction_set"), callback_data="sr_set")],
        [InlineKeyboardButton(text=get_button_text("reaction_clear"), callback_data="sr_clear", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "admin_start_reaction")
async def cb_admin_start_reaction(call: CallbackQuery):
    if not has_perm(call.from_user.id, "start_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    enabled = "🟢 فعال" if START_REACTION.get("enabled") else "🔴 غیرفعال"
    eid = START_REACTION.get("emoji_id") or "(تنظیم نشده)"
    fb = START_REACTION.get("fallback") or "🔥"
    await call.message.edit_text(
        f"💥 ری‌اکشن /start\n━━━━━━━━━━━━━━━\n\n"
        f"وضعیت: {enabled}\n🆔 custom_emoji_id: {eid}\n🔄 ایموجی پشتیبان: {fb}",
        reply_markup=start_reaction_keyboard())

@dp.callback_query(F.data == "sr_toggle")
async def cb_sr_toggle(call: CallbackQuery):
    if not has_perm(call.from_user.id, "start_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    START_REACTION["enabled"] = not START_REACTION.get("enabled", True)
    save_start_reaction()
    await call.answer("✅ ذخیره شد.")
    await cb_admin_start_reaction(call)

def _emoji_grid_keyboard(prefix: str, back_cb: str, cols: int = 8) -> InlineKeyboardMarkup:
    """گرید همه ایموجی‌های مجاز تلگرام برای انتخاب."""
    rows = []
    line = []
    for i, e in enumerate(ALLOWED_REACTION_EMOJIS_LIST):
        line.append(InlineKeyboardButton(text=e, callback_data=f"{prefix}:{e}"))
        if len(line) == cols:
            rows.append(line); line = []
    if line:
        rows.append(line)
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "sr_set")
async def cb_sr_set(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "start_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await state.set_state(AdminStates.reaction_set_id)
    await call.answer()
    await call.message.edit_text(
        "✨ <b>انتخاب ایموجی ری‌اکشن /start</b>\n━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>توجه مهم:</b> ربات‌های معمولی (غیر Bot Premium) <u>نمی‌تونن</u> ایموجی پریمیوم به عنوان ری‌اکشن بذارن — این محدودیت سمت تلگراست.\n"
        "پس از لیست ایموجی‌های استاندارد زیر یکی رو انتخاب کن. این ایموجی روی پیام /start همه کاربرها می‌خوره:\n\n"
        "💡 یا اگه می‌خوای دستی custom_emoji_id بدی (برای روزی که Bot Premium شدی)، فقط عدد ID رو بفرست.",
        parse_mode=ParseMode.HTML,
        reply_markup=_emoji_grid_keyboard("srpick", back_cb="admin_start_reaction"))

@dp.callback_query(F.data.startswith("srpick:"))
async def cb_sr_pick(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "start_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    emoji = call.data.split(":", 1)[1]
    if emoji not in ALLOWED_REACTION_EMOJIS:
        await call.answer("❌ این ایموجی مجاز نیست.", show_alert=True); return
    START_REACTION["fallback"] = emoji
    START_REACTION["enabled"] = True
    save_start_reaction()
    await state.clear()
    await call.answer(f"✅ {emoji} ست شد.", show_alert=False)
    await cb_admin_start_reaction(call)

@dp.message(AdminStates.reaction_set_id)
async def hdl_sr_set(message: Message, state: FSMContext):
    # اولویت ۱: ایموجی پریمیوم در پیام
    eid = first_premium_emoji_id(message)
    fallback_char = first_premium_emoji_char(message)
    raw = (message.text or "").strip()
    if eid:
        START_REACTION["emoji_id"] = eid
        if fallback_char:
            START_REACTION["fallback"] = fallback_char
    elif raw.isdigit():
        # custom_emoji_id دستی
        START_REACTION["emoji_id"] = raw
    elif raw:
        # ایموجی معمولی
        START_REACTION["emoji_id"] = ""
        START_REACTION["fallback"] = raw
    else:
        await message.answer("❌ خالی نمی‌تونه باشه. دوباره بفرست:")
        return
    START_REACTION["enabled"] = True
    save_start_reaction()
    await state.clear()
    eid_view = START_REACTION.get("emoji_id") or "(پریمیوم نداره)"
    fb_view = START_REACTION.get("fallback") or "🔥"
    await message.answer(
        f"✅ ری‌اکشن ذخیره شد.\n\n🆔 پریمیوم: {eid_view}\n🔄 پشتیبان: {fb_view}",
        reply_markup=start_reaction_keyboard())

@dp.callback_query(F.data == "sr_clear")
async def cb_sr_clear(call: CallbackQuery):
    if not has_perm(call.from_user.id, "start_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    START_REACTION["emoji_id"] = ""
    save_start_reaction()
    await call.answer("✅ پاک شد.")
    await cb_admin_start_reaction(call)

# ==================== ادمین: ری‌اکشن کاربر بن شده ====================
def ban_reaction_keyboard() -> InlineKeyboardMarkup:
    enabled = BAN_REACTION.get("enabled", False)
    rows = [
        [InlineKeyboardButton(
            text=("🟢 فعاله - برای خاموش کردن بزن" if enabled else "🔴 خاموشه - برای فعال کردن بزن"),
            callback_data="br_toggle")],
        [InlineKeyboardButton(text="✏️ انتخاب ایموجی", callback_data="br_set")],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "admin_ban_reaction")
async def cb_admin_ban_reaction(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ban_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    enabled = "🟢 فعال" if BAN_REACTION.get("enabled") else "🔴 غیرفعال"
    emoji = BAN_REACTION.get("emoji") or "👎"
    await call.message.edit_text(
        f"🚫 <b>ری‌اکشن کاربر بن شده</b>\n━━━━━━━━━━━━━━━\n\n"
        f"وقتی یه کاربر مسدوده و /start می‌زنه، این ایموجی روی پیامش زده می‌شه.\n\n"
        f"وضعیت: {enabled}\n"
        f"ایموجی فعلی: {emoji}",
        parse_mode=ParseMode.HTML,
        reply_markup=ban_reaction_keyboard())

@dp.callback_query(F.data == "br_toggle")
async def cb_br_toggle(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ban_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    BAN_REACTION["enabled"] = not BAN_REACTION.get("enabled", False)
    save_ban_reaction()
    await call.answer("✅ ذخیره شد.")
    await cb_admin_ban_reaction(call)

@dp.callback_query(F.data == "br_set")
async def cb_br_set(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ban_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    cur = BAN_REACTION.get("emoji") or "👎"
    await call.message.edit_text(
        f"🚫 <b>انتخاب ایموجی برای کاربر بن شده</b>\n━━━━━━━━━━━━━━━\n\n"
        f"ایموجی فعلی: {cur}\n\n"
        f"یکی از ایموجی‌های زیر رو انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=_emoji_grid_keyboard("brpick", back_cb="admin_ban_reaction"))

@dp.callback_query(F.data.startswith("brpick:"))
async def cb_br_pick(call: CallbackQuery):
    if not has_perm(call.from_user.id, "ban_reaction"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    emoji = call.data.split(":", 1)[1]
    if emoji not in ALLOWED_REACTION_EMOJIS:
        await call.answer("❌ این ایموجی مجاز نیست.", show_alert=True); return
    BAN_REACTION["emoji"] = emoji
    BAN_REACTION["enabled"] = True
    save_ban_reaction()
    await call.answer(f"✅ {emoji} ست شد.", show_alert=False)
    await cb_admin_ban_reaction(call)

# ==================== ادمین: حذف همه کانفیگ‌ها ====================
@dp.callback_query(F.data == "admin_delete_all_configs")
async def cb_admin_delete_all_configs(call: CallbackQuery):
    if not has_perm(call.from_user.id, "delete_configs"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    free_count, _ = get_configs_count()
    await call.message.edit_text(
        f"🗑 <b>حذف کلی کانفیگ‌ها</b>\n━━━━━━━━━━━━━━━\n\n"
        f"تعداد کانفیگ‌های آماده فعلی: <b>{free_count}</b>\n\n"
        f"⚠️ هشدار: با تایید، فقط کانفیگ‌های آماده (is_used=0) از دیتابیس پاک می‌شن. کانفیگ‌های مصرف‌شده باقی می‌مونن. این عملیات بازگشت‌پذیر نیست.\n\nمطمئنی؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_button_text("confirm_delete_configs"), callback_data="admin_delete_all_configs_confirm"),
                InlineKeyboardButton(text=get_button_text("reject_delete_configs"),  callback_data="open_admin_panel"),
            ],
        ]))

@dp.callback_query(F.data == "admin_delete_all_configs_confirm")
async def cb_admin_delete_all_configs_confirm(call: CallbackQuery):
    if not has_perm(call.from_user.id, "delete_configs"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    n = delete_all_configs()
    await call.answer(f"✅ {n} کانفیگ حذف شد.", show_alert=True)
    await call.message.edit_text(
        f"✅ همه کانفیگ‌ها پاک شدن.\n\nتعداد رکوردهای حذف‌شده: <b>{n}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")]
        ]))

# ==================== ادمین: متن پیام لفت ====================
def leave_alert_keyboard() -> InlineKeyboardMarkup:
    enabled = LEAVE_ALERT_ENABLED
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=("🟢 فعاله - برای خاموش کردن بزن" if enabled else "🔴 خاموشه - برای فعال کردن بزن"),
            callback_data="leave_alert_toggle")],
        [InlineKeyboardButton(text=get_button_text("leave_alert_edit"), callback_data="leave_alert_edit")],
        [InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")],
    ])

@dp.callback_query(F.data == "admin_leave_alert")
async def cb_admin_leave_alert(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "leave_alert"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    enabled = "🟢 فعال" if LEAVE_ALERT_ENABLED else "🔴 غیرفعال"
    cur = get_bot_text("leave_alert")
    await call.message.edit_text(
        f"💬 <b>پیام لفت دادن از کانال اجباری</b>\n━━━━━━━━━━━━━━━\n\n"
        f"وضعیت: {enabled}\n\nمتن فعلی:\n<code>{cur}</code>\n\n"
        f"در متن می‌تونی از پلیس‌هولدر <code>{{channel}}</code> برای نام کانال استفاده کنی.",
        parse_mode=ParseMode.HTML,
        reply_markup=leave_alert_keyboard())

@dp.callback_query(F.data == "leave_alert_toggle")
async def cb_leave_alert_toggle(call: CallbackQuery, state: FSMContext):
    global LEAVE_ALERT_ENABLED
    if not has_perm(call.from_user.id, "leave_alert"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    LEAVE_ALERT_ENABLED = not LEAVE_ALERT_ENABLED
    save_leave_alert_enabled()
    await call.answer("✅ وضعیت تغییر کرد.")
    await cb_admin_leave_alert(call, state)

@dp.callback_query(F.data == "leave_alert_edit")
async def cb_leave_alert_edit(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "leave_alert"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.leave_alert_edit)
    await call.message.edit_text(
        "✏️ متن جدید پیام لفت رو بفرست:\n\n"
        "می‌تونی از پلیس‌هولدر <code>{channel}</code> استفاده کنی.\n"
        "برای حذف کامل (یعنی پیامی فرستاده نشه): دکمه «خاموش کردن» در صفحه قبل رو بزن.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_leave_alert")]]))

@dp.message(AdminStates.leave_alert_edit)
async def hdl_leave_alert_edit(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "leave_alert"):
        await state.clear(); return
    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("❌ متن خالی قابل ذخیره نیست. متن جدید رو بفرست:")
        return
    save_bot_text("leave_alert", new_text)
    await state.clear()
    await message.answer(
        f"✅ متن پیام لفت ذخیره شد:\n\n<code>{new_text}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=leave_alert_keyboard())

# ==================== ادمین: جوین اجباری هوشمند ====================
def smart_channels_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i, sc in enumerate(SMART_CHANNELS):
        label = sc.get("chat_id") or sc.get("url") or f"کانال {i+1}"
        thr = sc.get("threshold", 0)
        rows.append([
            InlineKeyboardButton(text=f"📡 {label} | 🎯 {thr}", callback_data=f"smart_view_{i}"),
        ])
    rows.append([InlineKeyboardButton(text=get_button_text("smart_add"), callback_data="smart_add")])
    rows.append([InlineKeyboardButton(text=get_button_text("back_panel"), callback_data="open_admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "admin_smart_channels")
async def cb_admin_smart_channels(call: CallbackQuery, state: FSMContext):
    await state.clear()
    if not has_perm(call.from_user.id, "smart_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    await call.message.edit_text(
        "🤖 <b>جوین اجباری هوشمند</b>\n━━━━━━━━━━━━━━━\n\n"
        "ربات تعداد اعضای هر کانال رو مرتب چک می‌کنه و وقتی به حد تعیین‌شده رسید، کانال رو از لیست جوین اجباری خودش حذف می‌کنه. "
        "هم آی‌دی @username پشتیبانی می‌شه، هم لینک دعوت خصوصی (https://t.me/+xxx).\n\nلیست:",
        parse_mode=ParseMode.HTML,
        reply_markup=smart_channels_keyboard())

@dp.callback_query(F.data == "smart_add")
async def cb_smart_add(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "smart_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.smart_add_chat)
    await call.message.edit_text(
        "📡 <b>افزودن کانال هوشمند — مرحله ۱/۳</b>\n\n"
        "آی‌دی کانال رو بفرست. نمونه:\n• <code>@channel_name</code>\n• <code>-1001234567890</code>\n\n"
        "نکته: ربات باید عضو/ادمین کانال باشه تا بتونه تعداد اعضا رو بخونه.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_smart_channels")]]))

@dp.message(AdminStates.smart_add_chat)
async def hdl_smart_add_chat(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "smart_channels"):
        await state.clear(); return
    chat_id = (message.text or "").strip()
    if not chat_id:
        await message.answer("❌ آی‌دی معتبر بفرست:"); return
    await state.update_data(smart_chat_id=chat_id)
    await state.set_state(AdminStates.smart_add_url)
    await message.answer(
        "🔗 <b>مرحله ۲/۳</b> — لینک دعوت کانال رو بفرست.\n\n"
        "نمونه‌ها:\n• <code>https://t.me/channel_name</code>\n• <code>https://t.me/+AbCdEfGhIj</code>\n\n"
        "اگه کانال عمومی هست و نمی‌خوای لینک خاصی بدی، یک خط تیره <code>-</code> بفرست.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_smart_channels")]]))

@dp.message(AdminStates.smart_add_url)
async def hdl_smart_add_url(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "smart_channels"):
        await state.clear(); return
    url = (message.text or "").strip()
    if url == "-":
        url = ""
    elif not (url.startswith("http://") or url.startswith("https://") or url.startswith("t.me")):
        await message.answer("❌ لینک معتبر بفرست (با http/https) یا - برای رد کردن:"); return
    await state.update_data(smart_url=url)
    await state.set_state(AdminStates.smart_add_threshold)
    await message.answer(
        "🎯 <b>مرحله ۳/۳</b> — حد عضو رو بفرست (عدد).\n\n"
        "وقتی تعداد اعضای کانال به این عدد رسید، کانال خودکار از لیست جوین اجباری/تبلیغات حذف می‌شه.\n\n"
        "نمونه: <code>1000</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data="admin_smart_channels")]]))

@dp.message(AdminStates.smart_add_threshold)
async def hdl_smart_add_threshold(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "smart_channels"):
        await state.clear(); return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❌ عدد مثبت بفرست:"); return
    threshold = int(txt)
    data = await state.get_data()
    chat_id = data.get("smart_chat_id", "")
    url = data.get("smart_url", "")
    SMART_CHANNELS.append({
        "chat_id": chat_id,
        "url": url,
        "threshold": threshold,
        "label": chat_id,
    })
    save_smart_channels()
    await state.clear()
    await message.answer(
        f"✅ کانال هوشمند ذخیره شد.\n\n"
        f"📡 آی‌دی: <code>{chat_id}</code>\n"
        f"🔗 لینک: <code>{url or '-'}</code>\n"
        f"🎯 حد عضو: <b>{threshold}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=smart_channels_keyboard())

@dp.callback_query(F.data.startswith("smart_view_"))
async def cb_smart_view(call: CallbackQuery):
    if not has_perm(call.from_user.id, "smart_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    try:
        idx = int(call.data.split("_")[-1])
    except Exception:
        await call.answer("❌ خطا.", show_alert=True); return
    if idx < 0 or idx >= len(SMART_CHANNELS):
        await call.answer("❌ یافت نشد.", show_alert=True); return
    sc = SMART_CHANNELS[idx]
    await call.answer()
    # تلاش برای خواندن تعداد عضو فعلی
    cur_count = "نامشخص"
    try:
        chat_ref = sc.get("chat_id", "")
        if chat_ref:
            chat_target = int(chat_ref) if chat_ref.lstrip("-").isdigit() else chat_ref
            cur_count = str(await bot.get_chat_member_count(chat_target))
    except Exception as e:
        cur_count = f"خطا ({e.__class__.__name__})"
    await call.message.edit_text(
        f"📡 <b>کانال هوشمند #{idx+1}</b>\n━━━━━━━━━━━━━━━\n\n"
        f"آی‌دی: <code>{sc.get('chat_id','')}</code>\n"
        f"لینک: <code>{sc.get('url','-') or '-'}</code>\n"
        f"حد عضو: <b>{sc.get('threshold', 0)}</b>\n"
        f"تعداد عضو فعلی: <b>{cur_count}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("smart_set_threshold"), callback_data=f"smart_setthr_{idx}")],
            [InlineKeyboardButton(text=get_button_text("smart_remove_now"),    callback_data=f"smart_del_{idx}")],
            [InlineKeyboardButton(text=get_button_text("back_panel"),          callback_data="admin_smart_channels")],
        ]))

@dp.callback_query(F.data.startswith("smart_setthr_"))
async def cb_smart_setthr(call: CallbackQuery, state: FSMContext):
    if not has_perm(call.from_user.id, "smart_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    try:
        idx = int(call.data.split("_")[-1])
    except Exception:
        await call.answer("❌ خطا.", show_alert=True); return
    await call.answer()
    await state.set_state(AdminStates.smart_set_threshold)
    await state.update_data(smart_idx=idx)
    await call.message.edit_text(
        "🎯 حد عضو جدید رو بفرست (عدد):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_button_text("cancel_action"), callback_data=f"smart_view_{idx}")]]))

@dp.message(AdminStates.smart_set_threshold)
async def hdl_smart_set_threshold(message: Message, state: FSMContext):
    if not has_perm(message.from_user.id, "smart_channels"):
        await state.clear(); return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❌ عدد مثبت بفرست:"); return
    data = await state.get_data()
    idx = data.get("smart_idx", -1)
    if idx < 0 or idx >= len(SMART_CHANNELS):
        await state.clear()
        await message.answer("❌ کانال یافت نشد.", reply_markup=smart_channels_keyboard()); return
    SMART_CHANNELS[idx]["threshold"] = int(txt)
    save_smart_channels()
    await state.clear()
    await message.answer(f"✅ حد عضو روی {txt} ست شد.", reply_markup=smart_channels_keyboard())

@dp.callback_query(F.data.startswith("smart_del_"))
async def cb_smart_del(call: CallbackQuery):
    if not has_perm(call.from_user.id, "smart_channels"):
        await call.answer("❌ دسترسی نداری.", show_alert=True); return
    try:
        idx = int(call.data.split("_")[-1])
    except Exception:
        await call.answer("❌ خطا.", show_alert=True); return
    if idx < 0 or idx >= len(SMART_CHANNELS):
        await call.answer("❌ یافت نشد.", show_alert=True); return
    removed = SMART_CHANNELS.pop(idx)
    save_smart_channels()
    # همچنین از CHANNEL_IDS و AD_CHANNELS هم حذف کنیم
    try:
        cid = removed.get("chat_id", "")
        if cid and cid in CHANNEL_IDS:
            CHANNEL_IDS.remove(cid)
            cfg = load_config(); cfg["channels"] = CHANNEL_IDS; save_config(cfg)
    except Exception:
        pass
    try:
        url = removed.get("url", "")
        for ad in list(AD_CHANNELS):
            if (ad.get("url") and ad.get("url") == url) or (ad.get("chat_id") and ad.get("chat_id") == removed.get("chat_id")):
                AD_CHANNELS.remove(ad)
        cfg = load_config(); cfg["ad_channels"] = AD_CHANNELS; save_config(cfg)
    except Exception:
        pass
    await call.answer("✅ حذف شد.", show_alert=True)
    await call.message.edit_text(
        "🤖 <b>جوین اجباری هوشمند</b>\n━━━━━━━━━━━━━━━\n\nکانال حذف شد. لیست به‌روزشده:",
        parse_mode=ParseMode.HTML,
        reply_markup=smart_channels_keyboard())

# ==================== تسک پس‌زمینه: پایش کانال‌های هوشمند ====================
async def smart_channels_monitor():
    """هر چند دقیقه یک‌بار تعداد اعضا رو چک می‌کنه و کانال‌های پُرشده رو حذف می‌کنه."""
    await asyncio.sleep(20)
    while True:
        try:
            removed_any = False
            for sc in list(SMART_CHANNELS):
                try:
                    chat_ref_raw = sc.get("chat_id", "")
                    threshold = int(sc.get("threshold", 0) or 0)
                    if not chat_ref_raw or threshold <= 0:
                        continue
                    chat_target = int(chat_ref_raw) if chat_ref_raw.lstrip("-").isdigit() else chat_ref_raw
                    cnt = await bot.get_chat_member_count(chat_target)
                    if cnt is not None and cnt >= threshold:
                        # حد رسیده — کانال رو از همه لیست‌ها بردار
                        try:
                            SMART_CHANNELS.remove(sc)
                        except ValueError:
                            pass
                        try:
                            if chat_ref_raw in CHANNEL_IDS:
                                CHANNEL_IDS.remove(chat_ref_raw)
                                cfg = load_config(); cfg["channels"] = CHANNEL_IDS; save_config(cfg)
                        except Exception:
                            pass
                        try:
                            url = sc.get("url", "")
                            for ad in list(AD_CHANNELS):
                                if (url and ad.get("url") == url) or ad.get("chat_id") == chat_ref_raw:
                                    AD_CHANNELS.remove(ad)
                            cfg = load_config(); cfg["ad_channels"] = AD_CHANNELS; save_config(cfg)
                        except Exception:
                            pass
                        removed_any = True
                        logger.info(f"کانال هوشمند {chat_ref_raw} با {cnt} عضو به حد {threshold} رسید و حذف شد.")
                except Exception as e:
                    logger.warning(f"خطا در پایش کانال هوشمند {sc.get('chat_id')}: {e}")
            if removed_any:
                save_smart_channels()
        except Exception as e:
            logger.warning(f"خطا در smart_channels_monitor: {e}")
        # هر 5 دقیقه یک‌بار چک کن
        await asyncio.sleep(300)

# ==================== قیمت دلار / ارز ====================
import time as _time_mod
import re as _re_mod

_price_cache: dict = {}
_price_cache_time: float = 0.0
_PRICE_CACHE_TTL = 90  # ثانیه - کش ۹۰ ثانیه

# (coin_gecko_id, نام نمایشی, آیا کریپتو, کد فیات اگه غیر کریپتو)
_KEYWORD_MAP = {
    "دلار":    ("tether",       "💵 تتر (USDT)",          True,  None),
    "تتر":     ("tether",       "💵 تتر (USDT)",          True,  None),
    "usdt":    ("tether",       "💵 تتر (USDT)",          True,  None),
    "ترون":    ("tron",         "⚡ ترون (TRX)",           True,  None),
    "trx":     ("tron",         "⚡ ترون (TRX)",           True,  None),
    "بیتکوین": ("bitcoin",      "₿ بیتکوین (BTC)",        True,  None),
    "btc":     ("bitcoin",      "₿ بیتکوین (BTC)",        True,  None),
    "اتریوم":  ("ethereum",     "🔷 اتریوم (ETH)",         True,  None),
    "eth":     ("ethereum",     "🔷 اتریوم (ETH)",         True,  None),
    "بایننس":  ("binancecoin",  "🟡 بایننس کوین (BNB)",   True,  None),
    "bnb":     ("binancecoin",  "🟡 بایننس کوین (BNB)",   True,  None),
    "سولانا":  ("solana",       "🟣 سولانا (SOL)",         True,  None),
    "sol":     ("solana",       "🟣 سولانا (SOL)",         True,  None),
    "دوج":     ("dogecoin",     "🐕 دوج‌کوین (DOGE)",     True,  None),
    "doge":    ("dogecoin",     "🐕 دوج‌کوین (DOGE)",     True,  None),
    "ریپل":    ("ripple",       "🔵 ریپل (XRP)",           True,  None),
    "xrp":     ("ripple",       "🔵 ریپل (XRP)",           True,  None),
    "یورو":    (None,           "🇪🇺 یورو (EUR)",           False, "EUR"),
    "پوند":    (None,           "🇬🇧 پوند (GBP)",           False, "GBP"),
    "درهم":    (None,           "🇦🇪 درهم (AED)",           False, "AED"),
    "لیر":     (None,           "🇹🇷 لیر ترکیه (TRY)",     False, "TRY"),
    "یوان":    (None,           "🇨🇳 یوان (CNY)",           False, "CNY"),
    "طلا":     (None,           "🥇 طلا (هر اونس)",        False, "XAU"),
    "نقره":    (None,           "🥈 نقره (هر اونس)",       False, "XAG"),
}

_CRYPTO_IDS = "tether,tron,bitcoin,ethereum,binancecoin,solana,dogecoin,ripple"


async def _fetch_all_prices() -> dict | None:
    """
    کریپتو → CoinGecko (قیمت USD + تغییر ۲۴h)
    نرخ USD→Toman + فیات → fawazahmed0 community API (بازار آزاد)
    """
    global _price_cache, _price_cache_time
    now = _time_mod.monotonic()
    if _price_cache and (now - _price_cache_time) < _PRICE_CACHE_TTL:
        return _price_cache
    if aiohttp is None:
        return None
    result = {}
    headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # ۱. قیمت کریپتو از CoinGecko (USD + تغییر ۲۴h)
            gecko_url = (
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={_CRYPTO_IDS}"
                "&vs_currencies=usd"
                "&include_24hr_change=true"
            )
            try:
                async with session.get(gecko_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        for cid, info in data.items():
                            result[cid] = {
                                "usd":    float(info.get("usd", 0)),
                                "change": float(info.get("usd_24h_change") or 0),
                            }
            except Exception as e:
                logger.warning(f"CoinGecko error: {e}")

            # ۲. نرخ ارزها از Community Currency API (بازار آزاد)
            comm_url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
            try:
                async with session.get(comm_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        cdata = await r.json()
                        rates = cdata.get("usd", {})
                        irr_per_usd = float(rates.get("irr", 0))
                        toman_per_usd = irr_per_usd / 10 if irr_per_usd else 0
                        result["_rates"] = {
                            "toman_per_usd": toman_per_usd,
                            "EUR": float(rates.get("eur", 0)),
                            "GBP": float(rates.get("gbp", 0)),
                            "AED": float(rates.get("aed", 0)),
                            "TRY": float(rates.get("try", 0)),
                            "CNY": float(rates.get("cny", 0)),
                            "XAU": float(rates.get("xau", 0)),
                            "XAG": float(rates.get("xag", 0)),
                        }
            except Exception as e:
                logger.warning(f"Community currency API error: {e}")

    except Exception as e:
        logger.warning(f"_fetch_all_prices error: {e}")

    if result:
        _price_cache = result
        _price_cache_time = now
        return result
    return None


def _fmt_usd(n: float) -> str:
    if n == 0:
        return "—"
    if n >= 1:
        return f"${n:,.2f}"
    if n >= 0.01:
        return f"${n:.4f}"
    return f"${n:.8f}"

def _fmt_toman(t: float) -> str:
    if t <= 0:
        return "—"
    return f"{round(t):,}".replace(",", "٬") + " تومان"

def _chg(pct: float) -> str:
    if pct > 0:   return f"📈 +{pct:.2f}%"
    elif pct < 0: return f"📉 {pct:.2f}%"
    return f"➡️ {pct:.2f}%"

def _persian_datetime() -> str:
    if jdatetime is None:
        return datetime.now().strftime("%Y/%m/%d | %H:%M:%S")
    return jdatetime.datetime.now().strftime("%Y/%m/%d | %H:%M:%S")

def _extract_amount(text: str) -> float | None:
    """یه عدد از متن استخراج می‌کنه (مثل ۵ دلار یا 10.5 ترون)."""
    text = text.replace("٬", "").replace(",", "")
    m = _re_mod.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return None

def _detect_keyword(text: str) -> str | None:
    t = text.lower()
    for kw in _KEYWORD_MAP:
        if kw in t:
            return kw
    return None


@dp.message(F.text.func(lambda t: bool(t and _detect_keyword(t.lower()))))
async def hdl_price_query(message: Message):
    text = message.text or ""
    kw = _detect_keyword(text.lower())
    if not kw:
        return
    coin_id, display_name, is_crypto, fiat_code = _KEYWORD_MAP[kw]

    prices = await _fetch_all_prices()
    if not prices:
        await message.reply("⚠️ سرویس قیمت‌دهی موقتاً در دسترس نیست. چند دقیقه دیگه امتحان کن.")
        return

    rates = prices.get("_rates", {})
    toman_per_usd = rates.get("toman_per_usd", 0)

    # تشخیص عدد در پیام (مثل «5 دلار» یا «10 ترون»)
    amount = _extract_amount(text)
    # اگه عدد نبود یا عدد 0 یا 1 بود، نرخ واحد رو نشون می‌ده
    show_calc = amount is not None and amount > 0 and amount != 1

    lines = []

    if is_crypto:
        p = prices.get(coin_id, {})
        usd_price = p.get("usd", 0)
        change    = p.get("change", 0)
        toman_price = usd_price * toman_per_usd if toman_per_usd else 0

        if show_calc:
            total_usd   = usd_price * amount
            total_toman = toman_price * amount
            amt_str = f"{amount:g}"
            lines.append(f"🧮 {amt_str} {display_name.split('(')[0].strip()}")
            lines.append(f"━━━━━━━━━━━━━━━")
            lines.append(f"💲 = {_fmt_usd(total_usd)}")
            lines.append(f"🏦 = {_fmt_toman(total_toman)}")
            lines.append(f"")
            lines.append(f"📌 نرخ پایه: {_fmt_usd(usd_price)} | {_fmt_toman(toman_price)}")
            lines.append(f"📉📈 تغییر ۲۴h: {_chg(change)}")
        else:
            lines.append(f"💹 {display_name}")
            lines.append(f"━━━━━━━━━━━━━━━")
            lines.append(f"💲 قیمت دلاری: {_fmt_usd(usd_price)}")
            lines.append(f"🏦 معادل تومان: {_fmt_toman(toman_price)}")
            lines.append(f"📉📈 تغییر ۲۴h: {_chg(change)}")
            if toman_price > 0 and abs(change) > 0.01:
                profit = round((change / 100) * 1_000_000)
                sign = "+" if profit >= 0 else ""
                p_str = f"{abs(profit):,}".replace(",", "٬")
                lines.append(f"💡 سود/زیان ۱M تومن در ۲۴h: {sign}{p_str} تومن")

    else:
        # ارز فیات یا کالا
        fiat_rate = rates.get(fiat_code, 0)  # واحدهای این ارز در برابر ۱ دلار
        if fiat_code in ("XAU", "XAG"):
            # XAU و XAG بصورت «چند اونس در برابر ۱ دلار» ذخیره شده → معکوس کن
            usd_per_unit = (1 / fiat_rate) if fiat_rate else 0
        else:
            usd_per_unit = (1 / fiat_rate) if fiat_rate else 0
        toman_per_unit = usd_per_unit * toman_per_usd if toman_per_usd else 0

        if show_calc:
            amt_str = f"{amount:g}"
            lines.append(f"🧮 {amt_str} {display_name.split('(')[0].strip()}")
            lines.append(f"━━━━━━━━━━━━━━━")
            lines.append(f"💲 = {_fmt_usd(usd_per_unit * amount)}")
            lines.append(f"🏦 = {_fmt_toman(toman_per_unit * amount)}")
            lines.append(f"")
            lines.append(f"📌 نرخ پایه: {_fmt_usd(usd_per_unit)} | {_fmt_toman(toman_per_unit)}")
        else:
            lines.append(f"💹 {display_name}")
            lines.append(f"━━━━━━━━━━━━━━━")
            if usd_per_unit:
                lines.append(f"💲 برابر دلار: {_fmt_usd(usd_per_unit)}")
            if toman_per_unit:
                lines.append(f"🏦 معادل تومان: {_fmt_toman(toman_per_unit)}")
            if not usd_per_unit and not toman_per_unit:
                lines.append("❌ اطلاعات دریافت نشد.")

    lines.append(f"")
    lines.append(f"📅 {_persian_datetime()}")

    await message.reply("\n".join(lines))

# ==================== main ====================
async def main():
    global bot
    init_db()
    # تلاش چند مرحله‌ای برای ساخت Bot با parse_mode=HTML پیش‌فرض
    # تا ایموجی‌های پریمیوم (تگ <tg-emoji>) داخل متن‌ها رندر بشن.
    bot = None
    try:
        from aiogram.client.default import DefaultBotProperties
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except Exception as e:
        logger.warning(f"DefaultBotProperties در دسترس نیست: {e}")
    if bot is None:
        try:
            bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
        except TypeError:
            # نسخه‌های جدید aiogram دیگه parse_mode رو مستقیم قبول نمی‌کنن
            bot = Bot(token=BOT_TOKEN)
            logger.warning("⚠️ parse_mode پیش‌فرض ست نشد؛ ممکنه ایموجی پریمیوم در متن‌ها رندر نشه.")
    print("✅ ربات شروع به کار کرد...")
    # تسک پس‌زمینه برای پایش تعداد اعضای کانال‌های هوشمند
    try:
        asyncio.create_task(smart_channels_monitor())
    except Exception as e:
        logger.warning(f"نتونستم smart_channels_monitor رو راه بندازم: {e}")
    # برای دریافت آپدیت‌های chat_member باید همه آپدیت‌ها allowed بشن
    try:
        allowed = dp.resolve_used_update_types()
        if "chat_member" not in allowed:
            allowed.append("chat_member")
        await dp.start_polling(bot, allowed_updates=allowed)
    except Exception:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    asyncio.run(main())
