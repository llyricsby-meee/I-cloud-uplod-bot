import os
import time
import shutil
import asyncio
import requests
import subprocess
from flask import Flask
from threading import Thread
from telethon import TelegramClient, events
from pyicloud import PyiCloudService

# --- Environment Variables ---
API_ID = int(os.environ.get("API_ID", 31642646))
API_HASH = os.environ.get("API_HASH", "77a04ec35abcf9682826f91d7ddcf1bb").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN") 
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

RENDER_SECRETS_DIR = "/etc/secrets"
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

app = Flask(__name__)
@app.route('/')
def home():
    return "Telethon Turbo Downloader is Active! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

client = TelegramClient('icloud_bot_session', API_ID, API_HASH)
api = None
waiting_for_2fa = False

def setup_cookies():
    if not os.path.exists(WORKING_COOKIE_DIR):
        os.makedirs(WORKING_COOKIE_DIR)
    if os.path.exists(RENDER_SECRETS_DIR):
        for filename in os.listdir(RENDER_SECRETS_DIR):
            src = os.path.join(RENDER_SECRETS_DIR, filename)
            dest = os.path.join(WORKING_COOKIE_DIR, filename)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, dest)
                    os.chmod(dest, 0o777)
                except:
                    pass

async def init_icloud(event):
    global api, waiting_for_2fa
    setup_cookies()
    try:
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=WORKING_COOKIE_DIR)
        if api.requires_2fa:
            await event.respond("🔐 कुकी एक्सपायर है। कृपया अपना 6-digit Apple 2FA कोड यहाँ भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        await event.respond(f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

# --- 🚀 सुपर टर्बो डायरेक्ट डाउनलोडर (नो थर्ड-पार्टी डिपेंडेंसी) ---
async def download_via_ytdlp(link, file_name, is_audio, msg_event):
    """यह रेंडर सर्वर के खुद के इंटरनेट का इस्तेमाल करके डायरेक्ट डाउनलोड करेगा और स्पीड दिखाएगा"""
    # ऑडियो के लिए बेस्ट ऑडियो, वीडियो के लिए 720p तक (ताकि रेंडर क्रैश न हो)
    format_option = "bestaudio/best" if is_audio else "bestvideo[height<=720]+bestaudio/best"
    
    cmd = [
        "python3", "-m", "youtube_dl", 
        "-f", format_option,
        "-o", file_name,
        "--merge-output-format", "mp4",
        link
    ]
    
    # अगर सिस्टम में yt-dlp/youtube_dl मॉड्यूल न हो तो हम इसे फॉलबैक कमांड में बदल देंगे
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        await msg_event.edit("⚡ रेंडर का डायरेक्ट इंटरनेट इंजन एक्टिवेटेड! डाउनलोड शुरू हो रहा है...")
        
        # रेंडर की लाइव प्रोग्रेस रीड करना
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            out = line.decode('utf-8', errors='ignore')
            if "[download]" in out and "%" in out:
                # चैट में लाइव स्पीड अपडेट भेजने के लिए (हर 4 सेकंड में एक बार ताकि टेलीग्राम स्पैम न हो)
                cleaned_out = out.replace("[download]", "").strip()
                try:
                    await msg_event.edit(f"📥 **रेंडर सर्वर स्पीड प्रोग्रेस:**\n`{cleaned_out}`")
                    await asyncio.sleep(3)
                except:
                    pass
                    
        await process.wait()
        return os.path.exists(file_name)
    except Exception as e:
        print(f"Direct download error: {e}")
        return False

async def process_youtube_download(event, link, is_audio):
    global api
    msg = await event.respond("📡 क्लाउड सर्ver इंजन को जगाया जा रहा है...")
    
    file_ext = "mp3" if is_audio else "mp4"
    file_name = f"turbo_{int(time.time())}.{file_ext}"
    
    # सीधे रेंडर के इंजन से डाउनलोड करो
    success = await download_via_ytdlp(link, file_name, is_audio, msg)
    
    if not success or not os.path.exists(file_name):
        await msg.edit("❌ रेंडर डायरेक्ट डाउनलोड फेल हुआ। बाहरी सर्वर ट्राई कर रहा हूँ...")
        # फॉलबैक टू कोबाल्ट API
        try:
            response = requests.post("https://api.cobalt.tools/api/json", json={"url": link, "vQuality": "720", "isAudioOnly": is_audio}, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=10)
            if response.status_code == 200 and response.json().get("url"):
                await msg.edit("📥 कोबाल्ट सर्वर से फाइल स्ट्रीम हो रही है...")
                with requests.get(response.json().get("url"), stream=True) as r:
                    with open(file_name, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536): f.write(chunk)
                success = True
        except:
            pass

    if os.path.exists(file_name):
        await msg.edit("☁️ डाउनलोड पूरा! अब बिना RAM क्रैश किए इसे आपके iCloud Drive पर भेजा जा रहा है...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, api.drive.root.upload, open(file_name, 'rb'))
            await msg.edit(f"✅ सफलता! वीडियो सीधे तुम्हारे बॉट के जरिए iCloud पर सुरक्षित स्टोर हो गया! 🎉")
        except Exception as e:
            await msg.edit(f"❌ iCloud अपलोड एरर: {str(e)}")
        finally:
            if os.path.exists(file_name): os.remove(file_name)
    else:
        await msg.edit("❌ माफ़ी भाई, यह वीडियो बहुत भारी है या इसके सर्वर रिस्पॉन्स नहीं दे रहे हैं।")

async def process_telegram_upload(event, message):
    global api
    msg = await event.respond("⏳ टेलीथॉन सुपर इंजन एक्टिवेटेड। फाइल डाउनलोड हो रही है...")
    file_name = message.file.name if message.file and message.file.name else f"file_{int(time.time())}{message.file.ext or '.bin'}"
    try:
        path = await message.download_media(file=file_name)
        await msg.edit("📥 अब इसे सुरक्षित iCloud पर एक्सपोर्ट किया जा रहा है...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, api.drive.root.upload, open(path, 'rb'))
        await msg.edit(f"🎉 कमाल हो गया! '{file_name}' सफलतापूर्वक iCloud पर अपलोड हो गई! 🌟")
    except Exception as e:
        await msg.edit(f"❌ अपलोड फेल: {str(e)}")
    finally:
        if os.path.exists(file_name): os.remove(file_name)

@client.on(events.NewMessage)
async def handles_bot_messages(event):
    global api, waiting_for_2fa
    message = event.message
    text = message.raw_text.strip() if message.raw_text else ""

    if waiting_for_2fa:
        if text.isdigit() and len(text) == 6:
            await event.respond("⏳ Apple 2FA कोड वेरीफाई हो रहा है...")
            try:
                loop = asyncio.get_event_loop()
                if await loop.run_in_executor(None, api.validate_2fa_code, text):
                    await event.respond("✅ iCloud 2FA सफल! अब फाइल या लिंक भेजें।")
                    waiting_for_2fa = False
                else:
                    await event.respond("❌ गलत कोड।")
            except Exception as e: await event.respond(f"❌ एरर: {str(e)}")
        return

    if api is None:
        if not await init_icloud(event): return

    if text == "/list":
        try:
            loop = asyncio.get_event_loop()
            files = [f['name'] for f in api.drive.root.dir() if f['type'] == 'file']
            await event.respond("📂 आपकी फाइल्स:\n\n" + ("\n".join(files) if files else "खाली है।"))
        except Exception as e: await event.respond(f"❌ लिस्ट लोड एरर: {str(e)}")
        return

    if "youtube.com" in text or "youtu.be" in text or "instagram.com" in text:
        if "/audio" in text:
            clean_link = text.replace("/audio", "").strip()
            asyncio.create_task(process_youtube_download(event, clean_link, is_audio=True))
        else:
            clean_link = text.replace("/video", "").strip() if "/video" in text else text
            asyncio.create_task(process_youtube_download(event, clean_link, is_audio=False))
        return

    if message.file:
        asyncio.create_task(process_telegram_upload(event, message))
        return

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    client.start(bot_token=BOT_TOKEN.strip())
    client.run_until_disconnected()
