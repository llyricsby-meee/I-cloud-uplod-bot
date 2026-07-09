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

# 🍪 रेंडर की Secret Files का पाथ जहाँ आपकी कुकी रखी है
RENDER_SECRETS_DIR = "/etc/secrets"

# 🛠️ वर्किंग पाथ जहाँ कोड कुकी को मॉडिफ़ाई कर पाएगा (Read-Write Allowed)
WORKING_COOKIE_DIR = "/tmp/icloud_cookies"

app = Flask(__name__)
bot = None

if BOT_TOKEN:
    try:
        bot = telebot.TeleBot(BOT_TOKEN.strip())
    except Exception as e:
        print(f"❌ बॉट इनिशियलाइजेशन में गड़बड़: {str(e)}")

api = None
waiting_for_2fa = False
saved_file_id = None
saved_file_name = None
saved_file_type = None

@app.route('/')
def home():
    return "iCloud Read-Write Fixed Bot is Live!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def setup_cookies():
    """यह फ़ंक्शन Read-only कुकी को उठाकर लिखने योग्य /tmp फ़ोल्डर में कॉपी करेगा"""
    if not os.path.exists(WORKING_COOKIE_DIR):
        os.makedirs(WORKING_COOKIE_DIR)
    
    # रेंडर की सीक्रेट डायरेक्टरी में जो भी कुकीज़ हैं उन्हें /tmp में कॉपी करो
    if os.path.exists(RENDER_SECRETS_DIR):
        for filename in os.listdir(RENDER_SECRETS_DIR):
            src_file = os.path.join(RENDER_SECRETS_DIR, filename)
            dest_file = os.path.join(WORKING_COOKIE_DIR, filename)
            if os.path.isfile(src_file):
                try:
                    shutil.copy2(src_file, dest_file)
                    # फ़ाइल को पूरी परमिशन दे रहे हैं ताकि एरर न आए
                    os.chmod(dest_file, 0o777)
                except Exception as e:
                    print(f"कुकी कॉपी एरर: {e}")

def init_icloud(chat_id):
    global api, waiting_for_2fa
    try:
        # लॉगिन से पहले कुकीज़ को सही जगह सेटअप करें
        setup_cookies()
        
        # अब यह /tmp वाले फ़ोल्डर से कुकी यूज़ करेगा जहाँ लिखने की आज़ादी है
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=WORKING_COOKIE_DIR)
        
        if api.requires_2fa:
            bot.send_message(chat_id, "🔐 कुकी मैच नहीं हुई या एक्सपायर हो गई है। कृपया नया 2FA कोड भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        bot.send_message(chat_id, f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

def upload_after_login(chat_id, file_id, default_name, file_type):
    global api
    filename = None
    try:
        bot.send_message(chat_id, "⏳ टेलीग्राम से फाइल डाउनलोड की जा रही है...")
        file_info = bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        filename = f"{default_name}_{file_id[:6]}.{ext}"
        
        downloaded_file = bot.download_file(file_info.file_path)
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.send_message(chat_id, "📥 डाउनलोड पूरा! अब सुरक्षित कुकी के ज़रिए iCloud Drive पर भेजा जा रहा है...")
        
        with open(filename, 'rb') as file_obj:
            api.drive.upload_file(file_obj, filename=filename)
            
        bot.send_message(chat_id, f"🎉 सफलता! '{filename}' आपके iCloud Drive पर सीधे अपलोड हो गई है।")
    except Exception as e:
        bot.send_message(chat_id, f"❌ अपलोड फेल: {str(e)}")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)

if bot:
    @bot.message_handler(content_types=['text'])
    def handle_text(message):
        global api, waiting_for_2fa, saved_file_id, saved_file_name, saved_file_type
        chat_id = message.chat.id
        text = message.text.strip()

        if waiting_for_2fa:
            if text.isdigit() and len(text) == 6:
                bot.send_message(chat_id, "⏳ कोड वेरीफाई किया जा रहा है...")
                try:
                    if api.validate_2fa_code(text):
                        bot.send_message(chat_id, "✅ 2FA सफल!")
                        waiting_for_2fa = False
                        if saved_file_id:
                            upload_after_login(chat_id, saved_file_id, saved_file_name, saved_file_type)
                            saved_file_id = None
                    else:
                        bot.send_message(chat_id, "❌ गलत कोड।")
                except Exception as e:
                    bot.send_message(chat_id, f"❌ एरर: {str(e)}")
            return

        bot.reply_to(message, "👋 नमस्ते भाई! कुकीज़ लोड हो चुकी हैं। मुझे कोई भी फाइल भेजो, बिना 2FA के अपलोड हो जाएगी!")

    def handle_incoming_file(message, file_id, default_name, file_type):
        global api, waiting_for_2fa, saved_file_id, saved_file_name, saved_file_type
        chat_id = message.chat.id
        
        if api is None:
            saved_file_id = file_id
            saved_file_name = default_name
            saved_file_type = file_type
            init_icloud(chat_id)
        else:
            upload_after_login(chat_id, file_id, default_name, file_type)

    @bot.message_handler(content_types=['photo', 'video', 'document'])
    def handle_files(message):
        if message.content_type == 'photo':
            handle_incoming_file(message, message.photo[-1].file_id, "photo", "photo")
        elif message.content_type == 'video':
            handle_incoming_file(message, message.video.file_id, "video", "video")
        elif message.content_type == 'document':
            orig_name = message.document.file_name if message.document.file_name else "doc"
            name_without_ext = orig_name.split('.')[0]
            handle_incoming_file(message, message.document.file_id, name_without_ext, "document")

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    bot.infinity_polling(skip_pending=True)
