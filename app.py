import os
import telebot
from yt_dlp import YoutubeDL
from pyicloud import PyiCloudService
from flask import Flask, request

# Flask ऐप सेटअप (वर्सल को शांत रखने के लिए)
app = Flask(__name__)

# वर्सल के डैशबोर्ड से वेरिएबल्स उठाना
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
APPLE_ID = os.environ.get("your_apple_id", "your_apple_id@email.com")
APPLE_PASSWORD = os.environ.get("your_apple_password", "your_apple_password")

bot = telebot.TeleBot(BOT_TOKEN)

# ग्लोबल वेरिएबल ताकि लॉगिन स्टेट याद रहे
api = None
waiting_for_2fa = False

# वर्सल के लिए एक डमी होम पेज ताकि एरर न आए
@app.route('/')
def home():
    return "iCloud Upload Bot is Running Live!"

# वर्सल जब भी जागता है, इस रूट पर टेलीग्राम के अपडेट्स आ सकते हैं
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

def init_icloud(chat_id):
    global api, waiting_for_2fa
    try:
        bot.send_message(chat_id, "iCloud से कनेक्ट करने की कोशिश की जा रही है...")
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD)
        
        # अगर टू-फैक्टर ऑथेंटिकेशन (2FA) चालू है
        if api.requires_2fa:
            bot.send_message(chat_id, "🔐 Apple ID को 2FA कोड की ज़रूरत है। आपके Apple डिवाइस पर एक कोड आया होगा। कृपया वह 6-डिजिट का कोड यहाँ चैट में टाइप करके भेजें।")
            waiting_for_2fa = True
            return False
        return True
    except Exception as e:
        bot.send_message(chat_id, f"❌ iCloud लॉगिन एरर: {str(e)}")
        return False

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    global api, waiting_for_2fa
    chat_id = message.chat.id
    text = message.text.strip()

    # अगर बॉट आपके 2FA कोड का इंतज़ार कर रहा है
    if waiting_for_2fa:
        if text.isdigit() and len(text) == 6:
            bot.send_message(chat_id, "कोड को वेरीफाई किया जा रहा है...")
            result = api.validate_2fa_code(text)
            if result:
                bot.send_message(chat_id, "✅ 2FA वेरिफिकेशन सफल! आपका iCloud अब कनेक्टेड है।")
                waiting_for_2fa = False
            else:
                bot.send_message(chat_id, "❌ गलत कोड। कृपया सही 6-डिजिट का कोड दोबारा भेजें।")
        else:
            bot.send_message(chat_id, "⚠️ कृपया केवल 6 अंकों का संख्यात्मक (Numeric) कोड ही भेजें।")
        return

    # अगर सामान्य YouTube लिंक आता है
    if "youtube.com" in text or "youtu.be" in text:
        bot.reply_to(message, "⏳ वीडियो डाउनलोड होना शुरू हो गया है, कृपया इंतज़ार करें...")
        
        filename = f"video_{chat_id}.mp4"
        ydl_opts = {
            'outtmpl': filename, 
            'format': 'best[ext=mp4]/best', 
        }
        
        # 1. यूट्यूब से वीडियो डाउनलोड
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([text])
        except Exception as e:
            bot.reply_to(message, f"❌ यूट्यूब डाउनलोड फेल: {str(e)}")
            return

        bot.reply_to(message, "📥 डाउनलोड पूरा हुआ! अब इसे आपके iCloud Drive पर अपलोड किया जा रहा है...")

        # 2. iCloud पर अपलोड की प्रक्रिया
        try:
            if api is None or api.requires_2fa:
                success = init_icloud(chat_id)
                if not success:
                    if os.path.exists(filename): os.remove(filename)
                    return

            with open(filename, 'rb') as file_obj:
                api.drive.upload_file(file_obj)
                
            bot.reply_to(message, "🎉 वीडियो सफलतापूर्वक आपके iCloud पर अपलोड हो गया है! अब आप इसे अपने टैबलेट पर देख सकते हैं।")
            
        except Exception as e:
            bot.reply_to(message, f"❌ iCloud अपलोड फेल हुआ: {str(e)}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
    else:
        bot.reply_to(message, "👋 नमस्ते! कृपया मुझे कोई भी YouTube लिंक भेजें, मैं उसे डाउनलोड करके आपके iCloud पर डाल दूँगा।")

# लोकल टेस्टिंग के लिए (यह हिस्सा वर्सल इग्नोर कर देगा)
if __name__ == "__main__":
    print("बॉट शुरू हो चुका है...")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
