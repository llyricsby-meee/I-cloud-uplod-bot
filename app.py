import os
import time
import shutil
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyicloud import PyiCloudService
from flask import Flask

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

RENDER_SECRETS_DIR = "/etc/secrets"
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

app = Flask(__name__)
bot = None

if BOT_TOKEN:
    try:
        bot = telebot.TeleBot(BOT_TOKEN.strip())
    except Exception as e:
        print(f"❌ बॉट सेट करने में गड़बड़: {str(e)}")

api = None
waiting_for_2fa = False
current_youtube_link = None 

# --- Flask Server ---
@app.route('/')
def home():
    return "iCloud Pro Bot (Multi-API Auto-Fallback) is Running! 🚀"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

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

def init_icloud(chat_id):
    global api, waiting_for_2fa
    setup_cookies()
    try:
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=WORKING_COOKIE_DIR)
        if api.requires_2fa:
            bot.send_message(chat_id, "🔐 कुकी एक्सपायर है। नया 2FA कोड भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        bot.send_message(chat_id, f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

# --- 🔥 Multi-API Fallback Engine (कभी न रुकने वाला सिस्टम) ---
def get_download_url_with_fallback(link, is_audio):
    """यह फ़ंक्शन एक-एक करके सभी APIs को ट्राई करेगा"""
    
    # --- LAYER 1: Cobalt API ---
    try:
        response = requests.post(
            "https://api.cobalt.tools/api/json", 
            json={"url": link, "vQuality": "720", "isAudioOnly": is_audio},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=10
        )
        if response.status_code == 200 and response.json().get("status") != "error":
            return response.json().get("url"), "Cobalt Server"
    except:
        pass # अगर Cobalt फेल हुआ, तो चुपचाप अगले पर जाओ

    # --- LAYER 2: AllTube API (Backup 1) ---
    try:
        # AllTube का फॉर्मेट थोड़ा अलग होता है, यह डायरेक्ट वीडियो/ऑडियो एक्स्ट्रेक्ट करता है
        api_url = f"https://alltube.herokuapp.com/json?url={link}"
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # ऑडियो या वीडियो का डायरेक्ट लिंक ढूंढना
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

    # --- LAYER 3: Y2Mate Public API Gateway (Backup 2) ---
    try:
        # यह एक और यूनिवर्सल बाईपास गेटवे है
        api_url = "https://tomp3.cc/api/ajax/search"
        payload = {"query": link, "vt": "home"}
        res = requests.post(api_url, data=payload, timeout=10)
        if res.status_code == 200 and res.json().get("status") == "success":
            # कनवर्टर लिंक निकालना
            links = res.json().get("links", {})
            # पहले उपलब्ध लिंक को चुनना
            for k, v in links.items():
                for quality_key, quality_val in v.items():
                    # कन्वर्ट करके डाउनलोड लिंक लेना
                    convert_url = "https://tomp3.cc/api/ajax/convert"
                    conv_payload = {"vid": res.json().get("vid"), "k": quality_val.get("k")}
                    conv_res = requests.post(convert_url, data=conv_payload, timeout=10)
                    if conv_res.status_code == 200 and conv_res.json().get("status") == "success":
                        return conv_res.json().get("dlink"), "Tomp3 Premium Server"
    except:
        pass

    return None, None

# --- Main YouTube Downloader ---
def process_youtube_download(chat_id, link, is_audio):
    global api
    if api is None and not init_icloud(chat_id):
        return

    msg = bot.send_message(chat_id, "📡 क्लाउड सर्वर से लिंक जनरेट किया जा रहा है...")
    
    try:
        # ऑटो-बैकअप सिस्टम से लिंक ढूंढो
        download_url, server_name = get_download_url_with_fallback(link, is_audio)
        
        if not download_url:
            bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text="❌ मेरे सभी 3 बैकअप सर्वर अभी बिजी हैं। कृपया कुछ देर बाद दोबारा लिंक भेजें।")
            return
            
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"🚀 {server_name} कनेक्ट हो गया!\n📥 फाइल डाउनलोड की जा रही है...")
        
        file_ext = "mp3" if is_audio else "mp4"
        file_name = f"youtube_media.{file_ext}"
        
        # रेंडर सर्वर पर फाइल डाउनलोड करना
        file_response = requests.get(download_url, stream=True)
        with open(file_name, 'wb') as f:
            for chunk in file_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text="☁️ डाउनलोड पूरा! अब iCloud पर अपलोड किया जा रहा है...")
        
        # iCloud अपलोड
        with open(file_name, 'rb') as f:
            api.drive.root.upload(f)
            
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"✅ सफलता! फाइल सीधे iCloud पर सेव हो गई! 🎉\n(Processed via {server_name})")
        os.remove(file_name)
        
    except Exception as e:
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"❌ कुछ गड़बड़ हुई: {str(e)}")

def process_telegram_upload(chat_id, file_id, default_name):
    global api
    if api is None and not init_icloud(chat_id):
        return
        
    bot.send_message(chat_id, "⏳ फाइल डाउनलोड हो रही है...")
    filename = None
    try:
        file_info = bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        filename = f"{default_name}_{file_id[:6]}.{ext}"
        
        downloaded_file = bot.download_file(file_info.file_path)
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.send_message(chat_id, "📥 डाउनलोड पूरा! iCloud Drive पर भेजा जा रहा है...")
        with open(filename, 'rb') as file_obj:
            api.drive.root.upload(file_obj)
            
        bot.send_message(chat_id, f"🎉 सफलता! '{filename}' iCloud पर अपलोड हो गई। 🌟")
    except Exception as e:
        bot.send_message(chat_id, f"❌ अपलोड फेल: {str(e)}")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)

# --- Message Handlers ---
if bot:
    @bot.message_handler(commands=['list'])
    def list_files(message):
        global api
        if api is None and not init_icloud(message.chat.id): return
        try:
            files = [f['name'] for f in api.drive.root.dir() if f['type'] == 'file']
            bot.reply_to(message, "📂 फाइल्स:\n\n" + ("\n".join(files) if files else "खाली है।"))
        except Exception as e:
            bot.reply_to(message, f"❌ एरर: {str(e)}")

    @bot.message_handler(func=lambda message: "youtube.com" in message.text or "youtu.be" in message.text)
    def handle_yt(message):
        global current_youtube_link
        current_youtube_link = message.text.strip()
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🎵 Audio (MP3)", callback_data="download_audio"))
        markup.add(InlineKeyboardButton("🎥 Video (MP4)", callback_data="download_video"))
        bot.reply_to(message, "क्या डाउनलोड करना है?", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data in ["download_audio", "download_video"])
    def callback_query(call):
        global current_youtube_link
        bot.answer_callback_query(call.id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        if not current_youtube_link:
            bot.send_message(call.message.chat.id, "❌ लिंक खो गया है, कृपया दोबारा भेजें।")
            return
            
        is_audio = call.data == "download_audio"
        threading.Thread(target=process_youtube_download, args=(call.message.chat.id, current_youtube_link, is_audio)).start()

    @bot.message_handler(content_types=['photo', 'video', 'document', 'audio'])
    def handle_files(message):
        if message.content_type == 'photo': 
            file_id, name = message.photo[-1].file_id, "photo"
        elif message.content_type == 'video': 
            file_id, name = message.video.file_id, "video"
        elif message.content_type == 'audio': 
            file_id = message.audio.file_id
            name = message.audio.file_name.split('.')[0] if message.audio.file_name else "audio"
        else: 
            file_id = message.document.file_id
            name = message.document.file_name.split('.')[0] if message.document.file_name else "doc"
            
        threading.Thread(target=process_telegram_upload, args=(message.chat.id, file_id, name)).start()

    @bot.message_handler(content_types=['text'])
    def handle_text(message):
        global api, waiting_for_2fa
        chat_id = message.chat.id
        text = message.text.strip()

        if waiting_for_2fa:
            if text.isdigit() and len(text) == 6:
                bot.send_message(chat_id, "⏳ कोड वेरीफाई हो रहा है...")
                try:
                    if api.validate_2fa_code(text):
                        bot.send_message(chat_id, "✅ 2FA सफल! अब आप फाइल या लिंक भेज सकते हैं।")
                        waiting_for_2fa = False
                    else:
                        bot.send_message(chat_id, "❌ गलत कोड।")
                except Exception as e:
                    bot.send_message(chat_id, f"❌ एरर: {str(e)}")
            return
        bot.reply_to(message, "👋 प्रो बॉट रेडी है! कोई भी फाइल या YouTube लिंक भेजो।")

def start_bot():
    if bot:
        bot.remove_webhook()
        time.sleep(2) 
        bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    start_bot()
