import os
import threading
import telebot
from pyicloud import PyiCloudService
from flask import Flask

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

# लोकल कुकी डायरेक्टरी
COOKIE_DIR = "./cl_cookies"
if not os.path.exists(COOKIE_DIR):
    os.makedirs(COOKIE_DIR)

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
    return "iCloud Cookie Extractor Bot is Live!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def init_icloud(chat_id):
    global api, waiting_for_2fa
    try:
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD, cookie_directory=COOKIE_DIR)
        
        if api.requires_2fa:
            bot.send_message(chat_id, "🔐 Apple ID को 2FA कोड की ज़रूरत है। कृपया 6-डिजिट का कोड यहाँ भेजें।")
            waiting_for_2fa = True
            return False
        
        # अगर बिना 2FA के ही लॉगिन हो गया (पहले से कुकी मौजूद थी)
        send_cookie_to_user(chat_id)
        return True
    except Exception as e:
        bot.send_message(chat_id, f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

def send_cookie_to_user(chat_id):
    try:
        # pyicloud कुकी फ़ाइल को आपकी एप्पल आईडी के नाम से (बिना डोमेन के) सेव करता है
        cookie_filename = APPLE_ID.split('@')[0]
        cookie_path = os.path.join(COOKIE_DIR, cookie_filename)
        
        if os.path.exists(cookie_path):
            bot.send_message(chat_id, "🍪 बेहतरीन! लॉगिन सफल रहा। ये रही आपकी आईक्लाउड कुकी फाइल। इसे डाउनलोड करके अपने पास रख लें:")
            with open(cookie_path, 'rb') as f:
                bot.send_document(chat_id, f, visible_file_name="icloud_cookie.json")
        else:
            # बैकअप चेक: अगर पूरी डायरेक्टरी में कोई भी फाइल बनी हो
            files = os.listdir(COOKIE_DIR)
            if files:
                with open(os.path.join(COOKIE_DIR, files[0]), 'rb') as f:
                    bot.send_document(chat_id, f, visible_file_name="icloud_cookie.json")
            else:
                bot.send_message(chat_id, "⚠️ कुकी फाइल फोल्डर में नहीं मिल पाई।")
    except Exception as e:
        bot.send_message(chat_id, f"❌ कुकी भेजने में एरर: {str(e)}")

def upload_after_login(chat_id, file_id, default_name, file_type):
    global api
    filename = None
    try:
        bot.send_message(chat_id, "⏳ फाइल डाउनलोड की जा रही है...")
        file_info = bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        filename = f"{default_name}_{file_id[:6]}.{ext}"
        
        downloaded_file = bot.download_file(file_info.file_path)
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.send_message(chat_id, "📥 डाउनलोड पूरा! अब सीधे आपके iCloud Drive पर अपलोड हो रहा है...")
        
        with open(filename, 'rb') as file_obj:
            api.drive.upload_file(file_obj, filename=filename)
            
        bot.send_message(chat_id, f"🎉 सफलता! '{filename}' आपके iCloud Drive पर अपलोड हो गई है।")
        
        # फाइल अपलोड होने के बाद कुकी यूजर को भेजें
        send_cookie_to_user(chat_id)
        
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
                bot.send_message(chat_id, "⏳ कोड को वेरीफाई किया जा रहा है...")
                try:
                    if api.validate_2fa_code(text):
                        bot.send_message(chat_id, "✅ 2FA वेरिफिकेशन सफल!")
                        waiting_for_2fa = False
                        
                        # वेरिफिकेशन के तुरंत बाद कुकी भेजें
                        send_cookie_to_user(chat_id)
                        
                        if saved_file_id:
                            upload_after_login(chat_id, saved_file_id, saved_file_name, saved_file_type)
                            saved_file_id = None
                    else:
                        bot.send_message(chat_id, "❌ गलत कोड। कृपया दोबारा सही कोड भेजें।")
                except Exception as e:
                    bot.send_message(chat_id, f"❌ एरर: {str(e)}")
            else:
                bot.send_message(chat_id, "⚠️ कृपया केवल 6 अंकों का कोड भेजें।")
            return

        bot.reply_to(message, "👋 नमस्ते भाई! मुझे कोई भी फोटो या फाइल भेजो, मैं कुकी निकाल कर दे दूंगा।")

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
