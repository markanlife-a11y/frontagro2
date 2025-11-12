import os
import requests
import telebot
from telebot.types import Message
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# --- ВАШИ КЛЮЧИ ---
# Возьмите их из настроек хостинга (Render)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# ❗️ НОВЫЕ ПЕРЕМЕННЫЕ
ROBOFLOW_API_KEY = os.environ.get("ROBOFLOW_API_KEY")
ROBOFLOW_WORKSPACE = os.environ.get("ROBOFLOW_WORKSPACE")
ROBOFLOW_WORKFLOW_ID = os.environ.get("ROBOFLOW_WORKFLOW_ID")

# ❗️ НОВЫЙ URL API (для "Serverless" API)
ROBOFLOW_API_URL = f"https://serverless.roboflow.com/{ROBOFLOW_WORKSPACE}/{ROBOFLOW_WORKFLOW_ID}?api_key={ROBOFLOW_API_KEY}"

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# Функция: Добавляет водяные знаки
def add_watermarks(image_path, text, date_text):
    try:
        # Открываем изображение
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        
        # Загружаем шрифт (файл font.ttf должен быть рядом)
        # Выбираем размер шрифта = 5% от высоты изображения
        font_size = int(img.height * 0.05)
        try:
            font = ImageFont.truetype("font.ttf", font_size)
        except IOError:
            print("Не могу найти font.ttf, использую шрифт по умолчанию")
            font = ImageFont.load_default()

        # 1. Добавляем основной текст (например, "FrontAgro")
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        # Позиция: 2% от края внизу слева
        pos_x = int(img.width * 0.02)
        pos_y = int(img.height * 0.98) - text_height
        
        # Рисуем черную "тень" для читаемости
        draw.text((pos_x + 2, pos_y + 2), text, font=font, fill="black")
        # Рисуем белый текст
        draw.text((pos_x, pos_y), text, font=font, fill="white")

        # 2. Добавляем дату (внизу справа)
        date_bbox = draw.textbbox((0, 0), date_text, font=font)
        date_width = date_bbox[2] - date_bbox[0]
        date_height = date_bbox[3] - date_bbox[1]
        
        # Позиция: 2% от правого края
        pos_x_date = int(img.width * 0.98) - date_width
        pos_y_date = int(img.height * 0.98) - date_height

        draw.text((pos_x_date + 2, pos_y_date + 2), date_text, font=font, fill="black")
        draw.text((pos_x_date, pos_y_date), date_text, font=font, fill="white")
        
        # Сохраняем обработанное изображение
        processed_path = "processed_" + os.path.basename(image_path)
        img.save(processed_path)
        return processed_path

    except Exception as e:
        print(f"Ошибка водяного знака: {e}")
        return image_path # Возвращаем оригинал, если ошибка

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    bot.reply_to(message, "Здравствуйте! Отправьте мне фото корзинки подсолнечника, и я посчитаю семена.")

# Обработчик ПО ФОТОГРАФИИ
@bot.message_handler(content_types=['photo'])
def handle_photo(message: Message):
    chat_id = message.chat.id
    try:
        bot.reply_to(message, "📸 Фото получил. Начинаю анализ... (это займет до 30 секунд)")

        # 1. Получаем ID фото (самого большого)
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        
        # 2. Скачиваем фото
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Сохраняем на сервере
        original_image_path = f"{chat_id}_{message.message_id}.jpg"
        with open(original_image_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # 3. Отправляем в Roboflow (как бинарный файл)
        with open(original_image_path, 'rb') as f:
            # ❗️ ИСПОЛЬЗУЕМ НОВЫЙ URL
            response = requests.post(
                ROBOFLOW_API_URL,
                data=f, # Отправляем бинарные данные
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )
        
        # 4. Получаем результат
        if response.status_code != 200:
            bot.send_message(chat_id, f"Ошибка сервера Roboflow: {response.text}")
            return

        result_json = response.json()
        
        # ❗️ НОВАЯ ЛОГИКА ПОДСЧЕТА (из блока 'count_objects')
        seed_count = 0
        if result_json.get('outputs') and isinstance(result_json['outputs'], list) and len(result_json['outputs']) > 0:
            # Ищем наш оранжевый блок 'count_objects'
            for output in result_json['outputs']:
                if output.get('task_type') == 'Property Definition' and output.get('property_name') == 'count_objects':
                    seed_count = output.get('value', 0)
                    break
        
        # 5. Добавляем водяные знаки
        today_date = datetime.now().strftime("%d.%m.%Y")
        watermarked_image_path = add_watermarks(original_image_path, "FrontAgro", today_date)

        # 6. Отправляем фото С ВОДЯНЫМ ЗНАКОМ и подписью
        caption = f"🌻 Найдено: {seed_count} семян"
        with open(watermarked_image_path, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=caption, reply_to_message_id=message.message_id)

        # 7. Очистка (удаляем временные файлы)
        os.remove(original_image_path)
        os.remove(watermarked_image_path)

    except Exception as e:
        print(e)
        bot.send_message(chat_id, f"Произошла внутренняя ошибка: {e}")

# Запуск бота
print("Бот запущен...")
bot.polling(none_stop=True)
