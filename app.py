import os
import time
import shutil
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyicloud import PyiCloudService
from flask import Flask
import yt_dlp

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
last_update_time = {}

# 🔥 टेलीग्राम बटन डेटा लिमिट (64 Bytes) को बायपास करने के लिए ग्लोबल स्टोरेज
current_youtube_link = None 

# --- Flask Server ---
@app.route('/')
def home():
    return "iCloud Pro Bot is Running! 🚀"

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

# --- YouTube Progress Hook ---
def progress_hook(d, chat_id, message_id):
    if d['status'] == 'downloading':
        now = time.time()
        if now - last_update_time.get(message_id, 0) > 3:
            p = d.get('_percent_str', 'N/A').strip()
            s = d.get('_speed_str', 'N/A').strip()
            try:
                bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, 
                    text=f"⏳ सर्वर पर डाउनलोड हो रहा है...\n📊 प्रोग्रेस: {p}\n🚀 स्पीड: {s}"
                )
                last_update_time[message_id] = now
            except:
                pass

# --- Direct Download & Upload Function ---
def process_youtube_download(chat_id, link, is_audio):
    global api
    if api is None and not init_icloud(chat_id):
        return

    msg = bot.send_message(chat_id, "🚀 YouTube से सीधे डाउनलोडिंग शुरू की जा रही है...")
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best' if is_audio else 'best',
            'outtmpl': 'downloaded_media.%(ext)s',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'progress_hooks': [lambda d: progress_hook(d, chat_id, msg.message_id)]
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            file_ext = info.get('ext', 'mp3' if is_audio else 'mp4')
            file_name = f"downloaded_media.{file_ext}"
            title = info.get('title', 'Media')

        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"☁️ '{title}' को iCloud पर अपलोड कर रहा हूँ...")
        
        with open(file_name, 'rb') as f:
            api.drive.root.upload(f)
        
        bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"✅ '{title}' सफलतापूर्वक iCloud पर सेव हो गई! 🎉")
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
        current_youtube_link = message.text.strip() # लिंक को यहाँ सुरक्षित रख लिया
        
        markup = InlineKeyboardMarkup()
        # बटन डेटा को छोटा रखा ताकि 64 bytes की लिमिट कभी न टूटे
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
        
        # सीधे थ्रेड में चलाओ
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
