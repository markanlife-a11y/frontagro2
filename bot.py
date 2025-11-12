import os
import requests
import telebot
from telebot.types import Message
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from flask import Flask, request, abort

# --- ВАШИ КЛЮЧИ ---
# Возьмите их из настроек хостинга (Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY")
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE")
ROBOFLOW_WORKFLOW_ID = os.environ.get("ROBOFLOW_WORKFLOW_ID")

# URL API (для "Serverless" API)
ROBOFLOW_API_URL = f"https://serverless.roboflow.com/{ROBOFLOW_WORKSPACE}/{ROBOFLOW_WORKFLOW_ID}"
ROBOFLOW_PARAMS = {
    "api_key": ROBOFLOW_API_KEY
}

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN, threaded=False) # threaded=False - это важно

# Инициализация веб-сервера
app = Flask(__name__)

# Функция: Добавляет водяные знаки
def add_watermarks(image_path, text, date_text):
    try:
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        font_size = int(img.height * 0.05)
        
        try:
            font = ImageFont.truetype("font.ttf", font_size)
        except IOError:
            print("Не могу найти font.ttf, использую шрифт по умолчанию")
            font = ImageFont.load_default()

        # Текст (FrontAgro)
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        pos_x = int(img.width * 0.02)
        pos_y = int(img.height * 0.98) - text_height
        draw.text((pos_x + 2, pos_y + 2), text, font=font, fill="black")
        draw.text((pos_x, pos_y), text, font=font, fill="white")

        # Дата (справа)
        date_bbox = draw.textbbox((0, 0), date_text, font=font)
        date_width = date_bbox[2] - date_bbox[0]
        date_height = date_bbox[3] - date_bbox[1]
        pos_x_date = int(img.width * 0.98) - date_width
        pos_y_date = int(img.height * 0.98) - date_height
        draw.text((pos_x_date + 2, pos_y_date + 2), date_text, font=font, fill="black")
        draw.text((pos_x_date, pos_y_date), date_text, font=font, fill="white")
        
        processed_path = "processed_" + os.path.basename(image_path)
        img.save(processed_path)
        return processed_path
    except Exception as e:
        print(f"Ошибка водяного знака: {e}")
        return image_path # Возвращаем оригинал, если ошибка

# --- Логика бота ---

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    try:
        bot.reply_to(message, "Здравствуйте! Отправьте мне фото корзинки подсолнечника, и я посчитаю семена.")
    except Exception as e:
        print(f"!!! ОШИБКА В SEND_WELCOME: {e}")

# Обработчик ПО ФОТОГРАФИИ
@bot.message_handler(content_types=['photo'])
def handle_photo(message: Message):
    chat_id = message.chat.id
    try:
        bot.send_message(chat_id, "📸 Фото получил. Начинаю анализ...")

        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        original_image_path = f"{chat_id}_{message.message_id}.jpg"
        with open(original_image_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Отправляем в Roboflow как multipart/form-data
        with open(original_image_path, 'rb') as f:
            files = {'file': f} 
            response = requests.post(
                ROBOFLOW_API_URL,
                params=ROBOFLOW_PARAMS, 
                files=files, 
                timeout=30
            )
        
        if response.status_code != 200:
            print(f"Ошибка Roboflow. Статус: {response.status_code}, Ответ: {response.text}")
            bot.send_message(chat_id, f"Ошибка сервера Roboflow: {response.text}")
            return

        result_json = response.json()
        
        seed_count = 0
        # Ищем наш оранжевый блок 'count_objects'
        if result_json.get('outputs') and isinstance(result_json['outputs'], list) and len(result_json['outputs']) > 0:
            for output in result_json['outputs']:
                if output.get('task_type') == 'Property Definition' and output.get('property_name') == 'count_objects':
                    seed_count = output.get('value', 0)
                    break
        
        today_date = datetime.now().strftime("%d.%m.%Y")
        watermarked_image_path = add_watermarks(original_image_path, "FrontAgro", today_date)

        caption = f"🌻 Найдено: {seed_count} семян"
        with open(watermarked_image_path, 'rb') as photo:
            # --- ❗️ ВОТ ИСПРАВЛЕНИЕ (добавлена ')' в конце) ---
            bot.send_photo(chat_id, photo, caption=caption, reply_to_message_id=message.message_id)

        # Очистка
        os.remove(original_image_path)
        os.remove(watermarked_image_path)

    except Exception as e:
        print(f"!!! ОШИБКА В HANDLE_PHOTO: {e}")
        bot.send_message(chat_id, f"Произошла внутренняя ошибка: {e}")

# --- Логика Веб-сервера (Webhook) ---

# Это адрес, который будет "слушать" Telegram
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def get_message():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '!', 200
    else:
        abort(403)

# Это адрес для ручной установки Webhook (нужно открыть 1 раз)
@app.route("/")
def set_webhook():
    # URL сервиса, который вам даст Render (https://frontagro2.onrender.com)
    APP_URL = os.environ.get("RENDER_EXTERNAL_URL")
    if not APP_URL:
        print("!!! ОШИБКА: не найдена переменная RENDER_EXTERNAL_URL")
        return "Ошибка: не найдена переменная RENDER_EXTERNAL_URL", 500
        
    # Устанавливаем Webhook
    bot.remove_webhook()
    bot.set_webhook(url=f"{APP_URL}/{BOT_TOKEN}")
    return f"Webhook установлен на {APP_URL}/{BOT_TOKEN}", 200

# Запуск сервера
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
