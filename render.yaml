import asyncio
from telethon import TelegramClient, events, functions
from datetime import datetime
import yt_dlp
import os
import re
import random

api_id = 22242100
api_hash = '56a81fbba93ce35282c3e7e310175d1e'
phone_number = input("شماره خود را وارد کنید (مثال: +989123456789): ")

client = TelegramClient('session', api_id, api_hash)

save_users = set()
media_save_users = set()
enemy_users = set()

self_mode = False

enemy_messages = [
    "👎 تو واقعا کسی هستی که توی چاله خودت افتادی! 👎",
    "😜 نه توان فحش دادن داری نه جرئت، بهتره لال بمونی!",
    "👊 همیشه به نظر می‌رسی که دشمن خودت باشی!",
    "💥 تو دیگه چطور آدمی هستی؟! ",
    "😂 بیا، باید ببینی چطور من شکستت میدم!",
    "💣 بذار بگم، شما هیچ وقت در مقابل من حرفی نداری!",
    "🔥 تو هیچ وقت در برابر من کسی نبودی!",
]

def stylize_time():
    raw_time = datetime.now().strftime("%H:%M")
    return raw_time.translate(str.maketrans("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡"))

async def update_bio():
    await client.start(phone_number)
    while True:
        styled = stylize_time()
        await client(functions.account.UpdateProfileRequest(about=styled))
        await asyncio.sleep(60 - datetime.now().second)

@client.on(events.NewMessage(outgoing=True, pattern=r'سلف روشن'))
async def enable_self(event):
    global self_mode
    self_mode = True
    await event.edit("✅ سلف روشن شد! همه دستورات فعال هستند.")

@client.on(events.NewMessage(outgoing=True, pattern=r'سلف خاموش'))
async def disable_self(event):
    global self_mode
    self_mode = False
    save_users.clear()
    media_save_users.clear()
    await event.edit("❌ سلف خاموش شد! همه دستورات غیرفعال شدند.")

@client.on(events.NewMessage(outgoing=True, pattern=r'ذخیره پیوی روشن'))
async def enable_save(event):
    if not self_mode:
        await event.edit("❌ سلف خاموش است. لطفاً سلف را روشن کنید.")
        return
    save_users.add(event.chat_id)
    await event.edit("✅ ذخیره پیوی روشن شد")

@client.on(events.NewMessage(outgoing=True, pattern=r'ذخیره پیوی خاموش'))
async def disable_save(event):
    if not self_mode:
        await event.edit("❌ سلف خاموش است. لطفاً سلف را روشن کنید.")
        return
    save_users.discard(event.chat_id)
    await event.edit("❌ ذخیره پیوی خاموش شد")

@client.on(events.NewMessage(outgoing=True, pattern=r'ذخیره عکس تایم دار روشن'))
async def enable_media_save(event):
    if not self_mode:
        await event.edit("❌ سلف خاموش است. لطفاً سلف را روشن کنید.")
        return
    media_save_users.add(event.chat_id)
    await event.edit("🖼️✅ ذخیره عکس تایم‌دار روشن شد")

@client.on(events.NewMessage(outgoing=True, pattern=r'ذخیره عکس تایم دار خاموش'))
async def disable_media_save(event):
    if not self_mode:
        await event.edit("❌ سلف خاموش است. لطفاً سلف را روشن کنید.")
        return
    media_save_users.discard(event.chat_id)
    await event.edit("🖼️❌ ذخیره عکس تایم‌دار خاموش شد")

@client.on(events.NewMessage(incoming=True))
async def save_private(event):
    if not event.is_private:
        return
    sender = await event.get_sender()
    name = sender.first_name
    username = f"@{sender.username}" if sender.username else "بدون آیدی"
    user_id = sender.id
    info = f"📥 پیام از {name} | یوزرنیم: {username} | آیدی: {user_id}"

    if event.chat_id in save_users and not event.media:
        await client.send_message("me", info)
        await client.forward_messages("me", event.message)
    elif event.chat_id in media_save_users and event.media:
        await client.send_message("me", f"🖼️ {info}")
        await client.forward_messages("me", event.message)

class YTDLLogger:
    def __init__(self):
        self.messages = []
    def debug(self, msg):
        self.messages.append(msg)
    def info(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass

ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'logger': None,
    'quiet': True,
    'cookiefile': 'cookies.txt',  # اینجا فایل کوکی‌ها باید باشه
}

async def show_progress(event, logger):
    progress_msg = None
    while True:
        await asyncio.sleep(1)
        if not logger.messages:
            continue
        last_msg = logger.messages[-1]
        eta_match = re.search(r'ETA (\d+:\d+)', last_msg)
        if eta_match:
            eta = eta_match.group(1)
            minutes, seconds = map(int, eta.split(':'))
            parts = []
            if minutes > 0:
                parts.append(f"{minutes} دقیقه")
            if seconds > 0:
                parts.append(f"{seconds} ثانیه")
            eta_text = " و ".join(parts) + " مونده"
            text = f"⌛ تقریبا {eta_text} تا ارسال آهنگ..."
        else:
            text = "⌛ در حال دانلود آهنگ..."
        try:
            if progress_msg is None:
                progress_msg = await event.respond(text)
            else:
                await progress_msg.edit(text)
        except Exception:
            pass

        if any("100%" in m for m in logger.messages):
            break

async def download_and_send_song(client, chat, query, event):
    os.makedirs('downloads', exist_ok=True)
    loop = asyncio.get_event_loop()

    start_msg = await event.respond(f"🎵 شروع دانلود آهنگ: {query} ...")

    ydl_logger = YTDLLogger()
    ydl_opts['logger'] = ydl_logger

    def run_yt_dlp():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=True)
            filename = ydl.prepare_filename(info['entries'][0])
            mp3_file = os.path.splitext(filename)[0] + '.mp3'
            return mp3_file, info['entries'][0]['title']

    progress_task = asyncio.create_task(show_progress(event, ydl_logger))
    try:
        mp3_file, title = await loop.run_in_executor(None, run_yt_dlp)
    except Exception as e:
        await start_msg.edit(f"❌ خطا در دانلود: {str(e)}")
        return
    await progress_task

    await start_msg.edit("✅ دانلود انجام شد، آهنگ در حال ارسال است...")

    if os.path.exists(mp3_file):
        await client.send_file(chat, mp3_file, caption=f"🎵 آهنگ: {title}")
    else:
        await start_msg.edit("❌ دانلود آهنگ موفقیت‌آمیز نبود.")

@client.on(events.NewMessage(pattern=r'^آهنگ (.+)$'))
async def handler_song(event):
    if not self_mode:
        await event.reply("❌ سلف خاموش است، لطفاً ابتدا سلف را روشن کنید.")
        return
    query = event.pattern_match.group(1)
    await download_and_send_song(client, event.chat_id, query, event)

async def main():
    await client.start(phone_number)
    print("بات شروع به کار کرد.")
    # اگر دوست داری بایو آپدیت اتوماتیک هم روشن باشه
    # asyncio.create_task(update_bio())
    await client.run_until_disconnected()

asyncio.run(main())