import os
import threading
import telebot
from pyicloud import PyiCloudService
from flask import Flask

# Variables - ये हम रेंडर के Environment Variables में डालेंगे
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APPLE_ID = os.environ.get("your_apple_id")
APPLE_PASSWORD = os.environ.get("your_apple_password")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

api = None
waiting_for_2fa = False
saved_file_id = None
saved_file_name = None
saved_file_type = None

@app.route('/')
def home():
    return "iCloud Direct File Upload Bot is Live on Render!"

def run_flask():
    # रेंडर खुद 'PORT' वेरिएबल देता है, अगर न मिले तो 5000 पर चलेगा
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def init_icloud(chat_id):
    global api, waiting_for_2fa
    try:
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD)
        if api.requires_2fa:
            bot.send_message(chat_id, "🔐 Apple ID को 2FA कोड की ज़रूरत है। आपके Apple डिवाइस पर एक कोड आया होगा। कृपया वह 6-डिजिट का कोड यहाँ भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        bot.send_message(chat_id, f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

def upload_after_login(chat_id, file_id, default_name, file_type):
    try:
        bot.send_message(chat_id, "⏳ फाइल डाउनलोड की जा रही है...")
        file_info = bot.get_file(file_id)
        ext = file_info.file_path.split('.')[-1]
        filename = f"{default_name}_{file_id[:6]}.{ext}"
        
        downloaded_file = bot.download_file(file_info.file_path)
        with open(filename, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.send_message(chat_id, "📥 डाउनलोड पूरा! अब iCloud Drive पर अपलोड हो रहा है...")
        with open(filename, 'rb') as file_obj:
            api.drive.upload_file(file_obj)
            
        bot.send_message(chat_id, f"🎉 सफलता! '{filename}' आपके iCloud Drive पर अपलोड हो गई है।")
    except Exception as e:
        bot.send_message(chat_id, f"❌ अपलोड फेल: {str(e)}")
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

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

    bot.reply_to(message, "👋 नमस्ते भाई! रेंडर पर बॉट एकदम रेडी है। मुझे सीधे कोई भी फोटो, वीडियो या फाइल भेजो, मैं उसे आपके iCloud Drive पर अपलोड कर दूंगा!")

def handle_incoming_file(message, file_id, default_name, file_type):
    global api, waiting_for_2fa, saved_file_id, saved_file_name, saved_file_type
    chat_id = message.chat.id
    
    if api is None:
        saved_file_id = file_id
        saved_file_name = default_name
        saved_file_type = file_type
        init_icloud(chat_id)
    elif api.requires_2fa:
        saved_file_id = file_id
        saved_file_name = default_name
        saved_file_type = file_type
        waiting_for_2fa = True
        bot.send_message(chat_id, "🔐 Apple ID का सेशन समाप्त हो गया है। कृपया नया 2FA कोड भेजें।")
    else:
        upload_after_login(chat_id, file_id, default_name, file_type)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    handle_incoming_file(message, message.photo[-1].file_id, "photo", "photo")

@bot.message_handler(content_types=['video'])
def handle_video(message):
    handle_incoming_file(message, message.video.file_id, "video", "video")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    orig_name = message.document.file_name if message.document.file_name else "doc"
    name_without_ext = orig_name.split('.')[0]
    handle_incoming_file(message, message.document.file_id, name_without_ext, "document")

if __name__ == "__main__":
    try:
        bot.remove_webhook()
    except:
        pass

    # Flask को रेंडर के लिए बैकग्राउंड में चलाना
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    print("टेलीग्राम बॉट रेंडर पर शुरू हो चुका है...")
    bot.infinity_polling(skip_pending=True)
