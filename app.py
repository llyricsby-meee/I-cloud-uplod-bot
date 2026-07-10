import os
import time
import shutil
import asyncio
import requests
from flask import Flask
from threading import Thread
from telethon import TelegramClient, events
from pyicloud import PyiCloudService

# --- SAFE Environment Variables ---
# अब ये चाबियां पूरी तरह सुरक्षित हैं और कोड इन्हें सीधे Render के Environment से उठाएगा।
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH").strip()
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

RENDER_SECRETS_DIR = "/etc/secrets"
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

# Flask Server SETUP (Render को एक्टिव रखने के लिए)
app = Flask(__name__)
@app.route('/')
def home():
    return "Telethon iCloud Premium Userbot is Running Securely! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# Telethon Client Initialization
client = TelegramClient('icloud_userbot_session', API_ID, API_HASH)
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
            await event.respond("🔐 कुकी एक्सपायर है या नया लॉगिन है। कृपया अपना 6-digit Apple 2FA कोड यहाँ भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        await event.respond(f"❌ iCloud लॉगिन एरर: {str(e)}\nकृपया Render पर Apple ID/Password चेक करें।")
        return False

# --- Multi-API YouTube Fallback Engine ---
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

# --- PROCESSORS ---
async def process_youtube_download(event, link, is_audio):
    global api
    msg = await event.respond("📡 क्लाउड सर्वर से YouTube लिंक बाईपास किया जा रहा है...")
    
    loop = asyncio.get_event_loop()
    download_url, server_name = await loop.run_in_executor(None, get_download_url_with_fallback, link, is_audio)
    
    if not download_url:
        await msg.edit("❌ यूट्यूब सर्वर्स अभी व्यस्त हैं। कृपया थोड़ी देर बाद प्रयास करें।")
        return
        
    await msg.edit(f"🚀 {server_name} कनेक्टेड!\n📥 बड़ी फाइल को सीधे सर्वर पर स्ट्रीम किया जा रहा है...")
    
    file_ext = "mp3" if is_audio else "mp4"
    file_name = f"yt_stream_{int(time.time())}.{file_ext}"
    
    try:
        def download_file():
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                with open(file_name, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk: f.write(chunk)
                        
        await loop.run_in_executor(None, download_file)
        await msg.edit("☁️ स्ट्रीम पूरी हुई! अब बिना RAM भरे इसे iCloud Drive पर भेजा जा रहा है...")
        
        await loop.run_in_executor(None, api.drive.root.upload, open(file_name, 'rb'))
        await msg.edit(f"✅ सफलता! वीडियो/ऑдио सीधा iCloud पर स्टोर हो गया! 🎉\n(स्रोतः {server_name})")
    except Exception as e:
        await msg.edit(f"❌ गड़बड़ हुई: {str(e)}")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

# --- TELEGRAM INCOMING FILE HANDLER (NO LIMIT) ---
async def process_telegram_upload(event, message):
    global api
    msg = await event.respond("⏳ Telethon इंजन एक्टिवेटेड। टेलीग्राम से फाइल सीधे स्ट्रीम हो रही है...")
    
    file_name = "telegram_file"
    if message.file and message.file.name:
        file_name = message.file.name
    else:
        ext = message.file.ext if message.file and message.file.ext else ".bin"
        file_name = f"file_{int(time.time())}{ext}"

    try:
        await msg.edit(f"📥 डाउनलोडिंग '{file_name}' (बिना किसी MB लिमिट के डायरेक्ट स्ट्रीम)...")
        path = await message.download_media(file=file_name)
        
        await msg.edit("📥 ट्रांसफर सफल! अब इसे iCloud पर एक्सपोर्ट किया जा रहा है...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, api.drive.root.upload, open(path, 'rb'))
        
        await msg.edit(f"🎉 कमाल हो गया! '{file_name}' बिना किसी एरर के सफलतापूर्वक iCloud पर अपलोड हो गई! 🌟")
    except Exception as e:
        await msg.edit(f"❌ अपलोड फेल: {str(e)}")
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

# --- 100% LOCKED SECURITY FILTER (Only Listens to your Saved Messages) ---
@client.on(events.NewMessage(chats='me'))
async def handles_everything_safely(event):
    global api, waiting_for_2fa
    message = event.message
    text = message.raw_text.strip() if message.raw_text else ""

    # Check 2FA Code
    if waiting_for_2fa:
        if text.isdigit() and len(text) == 6:
            await event.respond("⏳ Apple 2FA कोड वेरीफाई हो रहा है...")
            try:
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, api.validate_2fa_code, text)
                if success:
                    await event.respond("✅ iCloud 2FA सफल! आपका सुरक्षा कवच एक्टिव है।")
                    waiting_for_2fa = False
                else:
                    await event.respond("❌ गलत कोड। कृपया दोबारा सही कोड भेजें।")
            except Exception as e:
                await event.respond(f"❌ एरर: {str(e)}")
        return

    # Initialize iCloud on demand if not ready
    if api is None:
        initialized = await init_icloud(event)
        if not initialized: return

    # Command: List Files
    if text == "/list":
        try:
            loop = asyncio.get_event_loop()
            files = [f['name'] for f in api.drive.root.dir() if f['type'] == 'file']
            await event.respond("📂 आपके iCloud की फाइल्स:\n\n" + ("\n".join(files) if files else "फोल्डर खाली है।"))
        except Exception as e:
            await event.respond(f"❌ लिस्ट लोड करने में एरर: {str(e)}")
        return

    # YouTube Link Detection
    if "youtube.com" in text or "youtu.be" in text:
        if "/audio" in text:
            clean_link = text.replace("/audio", "").strip()
            asyncio.create_task(process_youtube_download(event, clean_link, is_audio=True))
        else:
            clean_link = text.replace("/video", "").strip() if "/video" in text else text
            asyncio.create_task(process_youtube_download(event, clean_link, is_audio=False))
        return

    # Direct File Upload (Photo, Video, Voice, Audio, Documents)
    if message.file:
        asyncio.create_task(process_telegram_upload(event, message))
        return

# --- STARTUP ENGINE ---
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    
    print("⚡ Telethon Userbot शुरू हो रहा है...")
    client.start()
    print("🚀 यूज़रबॉट सफलतापूर्ण लॉग-इन हो गया! केवल अपने Saved Messages में टेस्ट करें।")
    client.run_until_disconnected()
