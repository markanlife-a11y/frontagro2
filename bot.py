import os
import requests
import telebot
from telebot.types import Message
from PIL import Image, ImageDraw, ImageFont # ❗️ PIL нам нужен для СЖАТИЯ
from datetime import datetime
from flask import Flask, request, abort
import base64
from inference_sdk import InferenceHTTPClient # ❗️❗️❗️ ВОТ ПРАВИЛЬНЫЙ ИМПОРТ ❗️❗️❗️

# --- ВАШИ КЛЮЧИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY")
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE")
ROBOFLOW_WORKFLOW_ID = os.environ.get("ROBOFLOW_WORKFLOW_ID")

# --- ИНИЦИАЛИЗИРУЕМ ОФИЦИАЛЬНЫЙ КЛИЕНТ ---
rf_client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=ROBOFLOW_API_KEY
)

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
            # Убедись, что 'font.ttf' лежит в корне твоего проекта на GitHub
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
    original_image_path = f"{chat_id}_{message.message_id}.jpg"
    watermarked_image_path = None # Инициализируем, чтобы знать, что удалять

    try:
        bot.send_message(chat_id, "📸 Фото получил. Сжимаю... Начинаю анализ...")

        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open(original_image_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # --- СЖАТИЕ ФОТО (исправление ошибки 502) ---
        pil_image = Image.open(original_image_path)
        pil_image.thumbnail((640, 640)) # Уменьшаем до 640px
        pil_image.save(original_image_path, "JPEG")
        
        # --- Вызов Roboflow (через SDK) ---
        result = rf_client.run_workflow(
            workspace_name=ROBOFLOW_WORKSPACE,
            workflow_id=ROBOFLOW_WORKFLOW_ID,
            images={
                "image": original_image_path
            }
        )
        
        # --- ❗️❗️❗️ НАЧАЛО ИСПРАВЛЕНИЯ ❗️❗️❗️ ---
        #
        # Ошибка ('list' object has no attribute 'get') возникала здесь.
        # Твой лог показывал, что 'result' - это СПИСОК (list), а не СЛОВАРЬ (dict).
        # Мы ожидаем структуру (из логов): [{'count_objects': 159, ...}]
        
        seed_count = 0
        
        # 1. Проверяем, что это список и он не пустой
        if isinstance(result, list) and len(result) > 0:
            # 2. Берем ПЕРВЫЙ элемент (который, как мы ожидаем, является словарем)
            main_output = result[0] 
            
            # 3. Теперь, когда main_output - это словарь, мы можем безопасно использовать .get()
            #    и достать 'count_objects' (как в твоем логе)
            seed_count = main_output.get('count_objects', 0)
            
        else:
            # На случай, если Roboflow вернет что-то неожиданное
            print(f"!!! НЕОЖИДАННАЯ СТРУКТУРА ROBOFLOW: {result}")
            bot.send_message(chat_id, "Не смог распознать ответ от Roboflow (неожиданная структура).")
            # Выходим из функции, 'finally' почистит файлы
            return

        # --- ❗️❗️❗️ КОНЕЦ ИСПРАВЛЕНИЯ ❗️❗️❗️ ---
        
        today_date = datetime.now().strftime("%d.%m.%Y")
        # Функция водяных знаков сработает на сжатом фото
        watermarked_image_path = add_watermarks(original_image_path, "FrontAgro", today_date)

        caption = f"🌻 Найдено: {seed_count} семян"
        with open(watermarked_image_path, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption, reply_to_message_id=message.message_id)

    except Exception as e:
        print(f"!!! ОШИБКА В HANDLE_PHOTO: {e}")
        # Если 'result' успел создаться, напечатаем его, чтобы понять ошибку
        if 'result' in locals():
            print(f"!!! ROBOFLOW RAW RESULT: {result}")
        bot.send_message(chat_id, f"Произошла внутренняя ошибка: {e}")

    finally:
        # --- Обязательная Очистка ---
        # Этот блок 'finally' выполнится всегда, даже если была ошибка,
        # чтобы не засорять сервер
        try:
            if os.path.exists(original_image_path):
                os.remove(original_image_path)
            
            # watermarked_image_path создается только после УСПЕШНОГО водяного знака
            # И он не должен быть равен оригиналу
            if watermarked_image_path and (watermarked_image_path != original_image_path) and os.path.exists(watermarked_image_path):
                 os.remove(watermarked_image_path)
        except Exception as clean_e:
            print(f"!!! ОШИБКА ОЧИСТКИ ФАЙЛОВ: {clean_e}")


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
