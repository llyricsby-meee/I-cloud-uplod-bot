import os
import shutil
import threading
import queue
import telebot
from pyicloud import PyiCloudService
from flask import Flask

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

RENDER_SECRETS_DIR = "/etc/secrets"
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN.strip())

api = None
file_queue = queue.Queue()

# Flask App (Render के लिए जरूरी)
@app.route('/')
def home():
    return "iCloud Pro Bot is Running! 🚀"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

def setup_icloud():
    global api
    if api is None:
        if not os.path.exists(WORKING_COOKIE_DIR): os.makedirs(WORKING_COOKIE_DIR)
        if os.path.exists(RENDER_SECRETS_DIR):
            for f in os.listdir(RENDER_SECRETS_DIR):
                shutil.copy2(os.path.join(RENDER_SECRETS_DIR, f), os.path.join(WORKING_COOKIE_DIR, f))
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=WORKING_COOKIE_DIR)
    return api

# कतार (Queue) से फाइल अपलोड करने वाला इंजन
def process_queue():
    while True:
        chat_id, file_id, name, content_type = file_queue.get()
        try:
            icloud = setup_icloud()
            file_info = bot.get_file(file_id)
            ext = file_info.file_path.split('.')[-1]
            filename = f"{name}.{ext}"
            
            with open(filename, 'wb') as f: f.write(bot.download_file(file_info.file_path))
            with open(filename, 'rb') as f: icloud.drive.root.upload(f)
            
            bot.send_message(chat_id, f"✅ '{filename}' सफलतापूर्वक अपलोड हो गई! 🌟")
            os.remove(filename)
        except Exception as e:
            bot.send_message(chat_id, f"❌ एरर: {str(e)}")
        finally:
            file_queue.task_done()

# फाइल लिस्ट कमांड
@bot.message_handler(commands=['list'])
def list_files(message):
    try:
        icloud = setup_icloud()
        files = [f['name'] for f in icloud.drive.root.dir() if f['type'] == 'file']
        bot.reply_to(message, "📂 फाइल्स:\n\n" + ("\n".join(files) if files else "खाली है।"))
    except Exception as e:
        bot.reply_to(message, f"❌ एरर: {str(e)}")

# फाइल डिलीट कमांड
@bot.message_handler(commands=['delete'])
def delete_file(message):
    file_name = message.text.replace('/delete', '').strip()
    if not file_name:
        bot.reply_to(message, "⚠️ नाम लिखें। जैसे: /delete song.mp3")
        return
    try:
        icloud = setup_icloud()
        icloud.drive.root[file_name].delete()
        bot.reply_to(message, f"✅ '{file_name}' हटा दी गई!")
    except:
        bot.reply_to(message, "❌ फाइल नहीं मिली।")

# फाइल हैंडलर (फोटो, वीडियो, डॉक्यूमेंट, ऑडियो)
@bot.message_handler(content_types=['photo', 'video', 'document', 'audio'])
def handle_files(message):
    if message.content_type == 'photo': file_id, name = message.photo[-1].file_id, "photo"
    elif message.content_type == 'video': file_id, name = message.video.file_id, "video"
    elif message.content_type == 'audio': 
        file_id = message.audio.file_id
        name = message.audio.file_name.split('.')[0] if message.audio.file_name else "audio"
    else: 
        file_id = message.document.file_id
        name = message.document.file_name.split('.')[0] if message.document.file_name else "doc"

    file_queue.put((message.chat.id, file_id, name, message.content_type))
    bot.reply_to(message, "📥 फाइल कतार में जुड़ गई है।")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=process_queue, daemon=True).start()
    bot.infinity_polling()
    
