import os
import time
import shutil
import asyncio
import requests
from flask import Flask
from threading import Thread
from telethon import TelegramClient, events
from pyicloud import PyiCloudService

# --- Environment Variables ---
API_ID = int(os.environ.get("API_ID", 31642646))
API_HASH = os.environ.get("API_HASH", "77a04ec35abcf9682826f91d7ddcf1bb").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN") # रेंडर से तुम्हारा बॉट टोकन उठाएगा
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

RENDER_SECRETS_DIR = "/etc/secrets"
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

# Flask Server (Render को जिंदा रखने के लिए)
app = Flask(__name__)
@app.route('/')
def home():
    return "Telethon iCloud Bot is Running Smoothly! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# --- TELETHON CLIENT (लॉगिन एरर फिक्स के साथ) ---
# यहाँ हमने bot_token को सीधे पास कर दिया है, अब यह कोई फोन नंबर नहीं मांगेगा!
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

# --- Fallback Engine ---
def get_download_url_with_fallback(link, is_audio):
    try:
        response = requests.post(
            "https://api.cobalt.tools/api/json", 
            json={"url": link, "vQuality": "720", "isAudioOnly": is_audio},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=15
        )
        if response.status_code == 200 and response.json().get("status") != "error":
            return response.json().get("url"), "Cobalt Server"
    except:
        pass 

    try:
        api_url = f"https://alltube.herokuapp.com/json?url={link}"
        response = requests.get(api_url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            streams = data.get("formats", [])
            for stream in streams:
                if is_audio and "audio" in stream.get("format", "").lower():
                    return stream.get("url"), "AllTube Audio Server"
                elif not is_audio and "mp4" in stream.get("ext", "").lower():
                    return stream.get("url"), "AllTube Video Server"
            if streams:
                return streams[0].get("url"), "AllTube Default Server"
    except:
        pass
    return None, None

# --- Processors ---
async def process_youtube_download(event, link, is_audio):
    global api
    msg = await event.respond("📡 क्लाउड सर्वर से YouTube लिंक बाईपास किया जा रहा है...")
    
    loop = asyncio.get_event_loop()
    download_url, server_name = await loop.run_in_executor(None, get_download_url_with_fallback, link, is_audio)
    
    if not download_url:
        await msg.edit("❌ सर्वर्स अभी व्यस्त हैं। कृपया थोड़ी देर बाद प्रयास करें।")
        return
        
    await msg.edit(f"🚀 {server_name} कनेक्टेड!\n📥 बड़ी फाइल को सीधे स्ट्रीम किया जा रहा है...")
    
    file_ext = "mp3" if is_audio else "mp4"
    file_name = f"yt_{int(time.time())}.{file_ext}"
    
    try:
        def download_file():
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                with open(file_name, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: f.write(chunk)
                        
        await loop.run_in_executor(None, download_file)
        await msg.edit("☁️ ट्रांसफर सफल! अब बिना RAM क्रैश किए इसे iCloud Drive पर भेजा जा रहा है...")
        
        await loop.run_in_executor(None, api.drive.root.upload, open(file_name, 'rb'))
        await msg.edit(f"✅ सफलता! वीडियो/ऑडियो सीधे तुम्हारे बॉट के जरिए iCloud पर स्टोर हो गया! 🎉")
    except Exception as e:
        await msg.edit(f"❌ गड़बड़ हुई: {str(e)}")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

async def process_telegram_upload(event, message):
    global api
    msg = await event.respond("⏳ टेलीथॉन इंजन एक्टिवेटेड। फाइल डाउनलोड हो रही है...")
    
    file_name = message.file.name if message.file and message.file.name else f"file_{int(time.time())}{message.file.ext or '.bin'}"

    try:
        await msg.edit(f"📥 डाउनलोडिंग '{file_name}' (यह बिना किसी 20MB लिमिट के डायरेक्ट हो रहा है)...")
        path = await message.download_media(file=file_name)
        
        await msg.edit("📥 अब इसे सुरक्षित iCloud पर एक्सपोर्ट किया जा रहा है...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, api.drive.root.upload, open(path, 'rb'))
        
        await msg.edit(f"🎉 कमाल हो गया! '{file_name}' बिना किसी एरर के सफलतापूर्वक iCloud पर अपलोड हो गई! 🌟")
    except Exception as e:
        await msg.edit(f"❌ अपलोड फेल: {str(e)}")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

# --- बॉट इवेंट्स हैंडलर ---
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
                success = await loop.run_in_executor(None, api.validate_2fa_code, text)
                if success:
                    await event.respond("✅ iCloud 2FA सफल! अब फाइल या लिंक भेजें।")
                    waiting_for_2fa = False
                else:
                    await event.respond("❌ गलत कोड।")
            except Exception as e:
                await event.respond(f"❌ एरर: {str(e)}")
        return

    if api is None:
        initialized = await init_icloud(event)
        if not initialized: return

    if text == "/list":
        try:
            loop = asyncio.get_event_loop()
            files = [f['name'] for f in api.drive.root.dir() if f['type'] == 'file']
            await event.respond("📂 आपकी फाइल्स:\n\n" + ("\n".join(files) if files else "खाली है।"))
        except Exception as e:
            await event.respond(f"❌ लिस्ट लोड एरर: {str(e)}")
        return

    if "youtube.com" in text or "youtu.be" in text:
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

# --- START BOT AS A BOT TOKEN ---
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    print("⚡ Telethon Bot starting via Token...")
    # यहाँ हमने client.start() में bot_token दे दिया है जिससे टर्मिनल में इनपुट नहीं मांगेगा!
    client.start(bot_token=BOT_TOKEN.strip()) 
    print("🚀 बॉट टोकन के जरिए सफलतापूर्वक लाइव हो गया!")
    client.run_until_disconnected()
