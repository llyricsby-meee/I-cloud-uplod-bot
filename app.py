import os
import time
import threading
import queue
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyicloud import PyiCloudService
from flask import Flask
import yt_dlp

# --- Credentials ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APPLE_ID = os.environ.get("APPLE_ID")
APPLE_PASSWORD = os.environ.get("APPLE_PASSWORD")

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN.strip())

api = None
file_queue = queue.Queue()
last_update_time = {} # Telegram स्पैम से बचने के लिए

# --- Flask Server (Render के लिए) ---
@app.route('/')
def home():
    return "iCloud Pro Bot is Running! 🚀"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

# --- iCloud Setup ---
def setup_icloud():
    global api
    if api is None:
        api = PyiCloudService(APPLE_ID, APPLE_PASSWORD)
    return api

# --- Progress Bar (Telegram Update) ---
def progress_hook(d, chat_id, message_id):
    if d['status'] == 'downloading':
        now = time.time()
        # हर 3 सेकंड में अपडेट करेगा ताकि Telegram ब्लॉक न करे
        if now - last_update_time.get(message_id, 0) > 3:
            p = d.get('_percent_str', 'N/A').strip()
            s = d.get('_speed_str', 'N/A').strip()
            try:
                bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text=f"⏳ सर्वर पर डाउनलोड हो रहा है...\n📊 प्रोग्रेस: {p}\n🚀 स्पीड: {s}"
                )
                last_update_time[message_id] = now
            except Exception:
                pass # अगर सेम मैसेज एडिट हो तो एरर इग्नोर करो

# --- Queue Processor (Background Task) ---
def process_queue():
    while True:
        task = file_queue.get()
        chat_id = task['chat_id']
        link = task['link']
        is_audio = task['is_audio']
        
        # प्रोग्रेस दिखाने के लिए पहला मैसेज
        msg = bot.send_message(chat_id, "🚀 डाउनलोडिंग शुरू की जा रही है...")
        
        try:
            icloud = setup_icloud()
            
            # yt-dlp की सेटिंग्स
            ydl_opts = {
                'format': 'bestaudio/best' if is_audio else 'best',
                'outtmpl': 'downloaded_media.%(ext)s',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'progress_hooks': [lambda d: progress_hook(d, chat_id, msg.message_id)]
            }
            
            # फाइल डाउनलोड करो
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=True)
                file_ext = info.get('ext', 'mp3' if is_audio else 'mp4')
                file_name = f"downloaded_media.{file_ext}"
                title = info.get('title', 'Media')

            # iCloud पर अपलोड करो
            bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"☁️ डाउनलोड पूरा हुआ!\nअब '{title}' को iCloud पर अपलोड कर रहा हूँ...")
            
            with open(file_name, 'rb') as f:
                icloud.drive.root.upload(f)
            
            # सक्सेस मैसेज और फाइल डिलीट
            bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"✅ '{title}' सफलतापूर्वक iCloud पर सेव हो गई! 🎉")
            os.remove(file_name)
            
        except Exception as e:
            bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id, text=f"❌ कुछ गड़बड़ हो गई: {str(e)}")
        finally:
            file_queue.task_done()

# --- Message Handler ---
@bot.message_handler(func=lambda message: "youtube.com" in message.text or "youtu.be" in message.text)
def handle_yt(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"audio|{message.text}"))
    markup.add(InlineKeyboardButton("🎥 Video (MP4)", callback_data=f"video|{message.text}"))
    bot.reply_to(message, "आपको क्या डाउनलोड करना है?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id, "कतार में जोड़ा जा रहा है...")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    data = call.data.split("|")
    is_audio = data[0] == "audio"
    link = data[1]
    
    file_queue.put({'chat_id': call.message.chat.id, 'link': link, 'is_audio': is_audio})
    bot.send_message(call.message.chat.id, "📥 लिंक कतार में लग गया है, कृपया इंतज़ार करें।")

# --- Start Threads ---
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=process_queue, daemon=True).start()
    print("Bot is starting...")
    bot.infinity_polling()

