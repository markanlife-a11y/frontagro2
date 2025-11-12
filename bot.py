import os
import requests
import json
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from flask import Flask, request, abort
import base64
from roboflow import InferenceHTTPClient # ❗️ ИСПОЛЬЗУЕМ ОФИЦИАЛЬНУЮ БИБЛИОТЕКУ

# --- ВАШИ КЛЮЧИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY")
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE")
ROBOFLOW_WORKFLOW_ID = os.environ.get("ROBOFLOW_WORKFLOW_ID")

# --- URL API ТЕЛЕГРАМА ---
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- ИНИЦИАЛИЗИРУЕМ ОФИЦИАЛЬНЫЙ КЛИЕНТ ROBOFLOW ---
rf_client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=ROBOFLOW_API_KEY
)

# Инициализация веб-сервера
app = Flask(__name__)

# --- 1. Функции отправки ответа (теперь вручную) ---
def send_message(chat_id, text, reply_to_msg_id=None):
    try:
        payload = {
            'chat_id': chat_id,
            'text': text,
            'reply_to_message_id': reply_to_msg_id
        }
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    except Exception as e:
        print(f"!!! ОШИБКА send_message: {e}")

def send_photo(chat_id, photo_blob, caption, reply_to_msg_id):
    try:
        files = {'photo': ('image.jpg', photo_blob, 'image/jpeg')}
        payload = {
            'chat_id': chat_id,
            'caption': caption,
            'reply_to_message_id': reply_to_msg_id
        }
        requests.post(f"{TELEGRAM_API}/sendPhoto", data=payload, files=files)
    except Exception as e:
        print(f"!!! ОШИБКА send_photo: {e}")

# --- 2. Функция водяных знаков (без изменений) ---
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

# --- 3. Логика бота (теперь это обычные функции) ---
def handle_start(chat_id, message_id):
    try:
        send_message(chat_id, "Здравствуйте! Отправьте мне фото корзинки подсолнечника, и я посчитаю семена.", message_id)
    except Exception as e:
        print(f"!!! ОШИБКА В handle_start: {e}")

def handle_photo(chat_id, message_id, photo_list):
    try:
        send_message(chat_id, "📸 Фото получил. Сжимаю... Начинаю анализ...", message_id)

        file_id = photo_list[-1]['file_id'] # Берем самое большое фото
        
        # Получаем путь к файлу
        file_info_res = requests.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")
        file_path = file_info_res.json()['result']['file_path']
        
        # Скачиваем файл
        downloaded_file_res = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
        
        original_image_path = f"{chat_id}_{message_id}.jpg"
        with open(original_image_path, 'wb') as new_file:
            new_file.write(downloaded_file_res.content)

        # --- СЖАТИЕ ФОТО (исправление ошибки 502) ---
        pil_image = Image.open(original_image_path)
        pil_image.thumbnail((640, 640)) # Уменьшаем до 640px
        pil_image.save(original_image_path, "JPEG")
        
        # --- Вызов Roboflow (через SDK) ---
        result = rf_client.run_workflow(
            workspace_name=ROBOFLOW_WORKSPACE,
            workflow_id=ROBOFLOW_WORKFLOW_ID,
            images={"image": original_image_path}
        )
        
        seed_count = 0
        if result.get('outputs') and isinstance(result['outputs'], list) and len(result['outputs']) > 0:
            for output in result['outputs']:
                if output.get('task_type') == 'Property Definition' and output.get('property_name') == 'count_objects':
                    seed_count = output.get('value', 0)
                    break
        
        today_date = datetime.now().strftime("%d.%m.%Y")
        watermarked_image_path = add_watermarks(original_image_path, "FrontAgro", today_date)

        caption = f"🌻 Найдено: {seed_count} семян"
        with open(watermarked_image_path, 'rb') as photo_blob:
            send_photo(chat_id, photo_blob, caption, message_id)

        # Очистка
        os.remove(original_image_path)
        if watermarked_image_path != original_image_path:
             os.remove(watermarked_image_path)

    except Exception as e:
        print(f"!!! ОШИБКА В handle_photo: {e}")
        if 'result' in locals():
            print(f"!!! ROBOFLOW RAW RESULT: {result}")
        send_message(chat_id, f"Произошла внутренняя ошибка: {e}", message_id)

# --- 4. Логика Веб-сервера (Webhook) ---

# Это адрес, который будет "слушать" Telegram
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def get_message():
    try:
        json_string = request.get_data().decode('utf-8')
        update = json.loads(json_string)
        message = update.get('message')
        
        if not message:
            return '!', 200 # Игнорируем обновления без 'message'

        chat_id = message['chat']['id']
        message_id = message['message_id']

        if 'text' in message and message['text'] == '/start':
            handle_start(chat_id, message_id)
        elif 'photo' in message:
            handle_photo(chat_id, message_id, message['photo'])
        else:
            send_message(chat_id, "Пожалуйста, отправьте /start или фотографию.", message_id)
            
        return '!', 200 # Говорим "ОК" Telegram ТОЛЬКО ПОСЛЕ того, как все сделали

    except Exception as e:
        print(f"!!! КРИТИЧЕСКАЯ ОШИБКА В GET_MESSAGE: {e}")
        return 'Error', 500

# Это адрес для ручной установки Webhook (нужно открыть 1 раз)
@app.route("/")
def set_webhook():
    APP_URL = os.environ.get("RENDER_EXTERNAL_URL")
    if not APP_URL:
        print("!!! ОШИБКА: не найдена переменная RENDER_EXTERNAL_URL")
        return "Ошибка: не найдена переменная RENDER_EXTERNAL_URL", 500
        
    # Устанавливаем Webhook
    set_hook_url = f"{TELEGRAM_API}/setWebhook?url={APP_URL}/{BOT_TOKEN}"
    response = requests.get(set_hook_url)
    return response.json(), 200

# Запуск сервера
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))

