import os
import shutil
import threading
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
waiting_for_2fa = False
saved_file_id = None
saved_file_name = None
saved_file_type = None

@app.route('/')
def home():
    return "Bot is Live!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

def setup_cookies():
    if not os.path.exists(WORKING_COOKIE_DIR):
        os.makedirs(WORKING_COOKIE_DIR)
    if os.path.exists(RENDER_SECRETS_DIR):
        for filename in os.listdir(RENDER_SECRETS_DIR):
            shutil.copy2(os.path.join(RENDER_SECRETS_DIR, filename), os.path.join(WORKING_COOKIE_DIR, filename))

def init_icloud(chat_id):
    global api, waiting_for_2fa
    setup_cookies()
    api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=WORKING_COOKIE_DIR)
    if api.requires_2fa:
        bot.send_message(chat_id, "🔐 2FA कोड भेजें:")
        waiting_for_2fa = True
        return False
    return True

def upload_file(chat_id, file_id, default_name):
    global api
    file_info = bot.get_file(file_id)
    ext = file_info.file_path.split('.')[-1]
    filename = f"{default_name}.{ext}"
    downloaded_file = bot.download_file(file_info.file_path)
    with open(filename, 'wb') as f:
        f.write(downloaded_file)
    with open(filename, 'rb') as f:
        api.drive.root.upload(f)
    os.remove(filename)
    bot.send_message(chat_id, "✅ अपलोड सफल!")

@bot.message_handler(content_types=['photo', 'video', 'document', 'audio'])
def handle_files(message):
    global api, saved_file_id, saved_file_name
    chat_id = message.chat.id
    
    # फाइल पहचानना
    file_id = None
    name = "file"
    if message.content_type == 'photo':
        file_id = message.photo[-1].file_id
    elif message.content_type == 'video':
        file_id = message.video.file_id
    elif message.content_type == 'audio':
        file_id = message.audio.file_id
        name = message.audio.file_name.split('.')[0] if message.audio.file_name else "audio"
    else:
        file_id = message.document.file_id
        name = message.document.file_name.split('.')[0] if message.document.file_name else "doc"

    if api is None:
        saved_file_id, saved_file_name = file_id, name
        init_icloud(chat_id)
    else:
        upload_file(chat_id, file_id, name)

# 2FA हैंडलर
@bot.message_handler(func=lambda m: waiting_for_2fa)
def verify_2fa(message):
    global waiting_for_2fa
    if api.validate_2fa_code(message.text):
        waiting_for_2fa = False
        bot.send_message(message.chat.id, "✅ 2FA सफल! अपलोड जारी है...")
        upload_file(message.chat.id, saved_file_id, saved_file_name)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling()
