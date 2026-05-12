# С логированием (уведомлением на почту), сохранением в гугл эксель
# и поддержкой динамических параметров из Google Sheets -> GitHub Actions

import requests
import os
import json
import sys
import logging
import smtplib
from datetime import datetime, date, timedelta
from io import StringIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# ==================== 🛠 Настройка Логирования ====================
log_buffer = StringIO()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.StreamHandler(log_buffer)]
)
logger = logging.getLogger(__name__)

# Список для хранения статусов по листам
execution_stats = []


# ==================== 📧 Функция отправки почты ====================
def send_log_email(content, is_success=True):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")
    server_host = os.getenv("SMTP_SERVER", "smtp.yandex.ru")
    server_port = int(os.getenv("SMTP_PORT", 587))

    if not all([sender, password, receiver]):
        logger.warning("❌ Данные для почты не найдены в .env")
        return

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver

    status_label = "✅ Успех" if is_success else "❌ Ошибка"
    msg['Subject'] = f"{status_label}: Отчет MPStats по запросам - {date.today()}"

    # Основной текст письма
    msg.attach(MIMEText(content, 'plain'))

    try:
        with smtplib.SMTP(server_host, server_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки почты: {e}")


# ==================== 📤 Функция отправки в Google Sheets ====================
def send_to_sheet(df: pd.DataFrame, sheet_name: str):
    if df.empty:
        return False

    payload = {"sheet": sheet_name, "data": df.to_dict(orient="records")}

    try:
        resp = requests.post(
            os.getenv("WEBHOOK_URL"),
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},  # Изменили на application/json
            timeout=60
        )
        if resp.status_code == 200 and "OK" in resp.text:
            # Сохраняем строку для успешного отчета
            execution_stats.append(f"Лист '{sheet_name}' обновлён ({len(df)} строк)")
            return True
        else:
            logger.error(f"Ошибка записи '{sheet_name}': {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Ошибка сети при записи '{sheet_name}': {e}")
        return False


# ==================== ⚙️ Основная логика ====================
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL",
                        "https://script.google.com/macros/s/AKfycbyqSfFpQN_NoMvM2dwY6-DtKDH2qOXXLGMQxgQlXdMz3lYlCTCGHqNZmXx8fGymnKKn/exec")
os.environ["WEBHOOK_URL"] = WEBHOOK_URL  # сохраняем для функции

# --- ДИНАМИЧЕСКОЕ ПОЛУЧЕНИЕ ПАРАМЕТРОВ ---
# Пытаемся получить параметры из GitHub Actions (при запуске по кнопке)
CATEGORY_PATH = os.getenv("CATEGORY_PATH") or "Мебель/По помещениям/Гостиная/Стеллажи"

d_from_env = os.getenv("DATE_FROM")
d_to_env = os.getenv("DATE_TO")

if d_from_env and d_to_env:
    try:
        # Переводим строки YYYY-MM-DD из Google Таблицы обратно в формат дат
        DATE_FROM = datetime.strptime(d_from_env, "%Y-%m-%d").date()
        DATE_TO = datetime.strptime(d_to_env, "%Y-%m-%d").date()
        logger.info(f"Используются пользовательские даты: {DATE_FROM} - {DATE_TO}")
    except ValueError:
        logger.error("Ошибка формата дат из окружения. Используются даты по умолчанию.")
        DATE_FROM = date.today() - timedelta(days=31)
        DATE_TO = date.today() - timedelta(days=1)
else:
    # По умолчанию: за последний месяц
    DATE_FROM = date.today() - timedelta(days=31)
    DATE_TO = date.today() - timedelta(days=1)
    logger.info(f"Используются даты по умолчанию: {DATE_FROM} - {DATE_TO}")

PERIOD_LABEL = f"{DATE_FROM} - {DATE_TO}"
logger.info(f"Категория: {CATEGORY_PATH}")

try:
    # Запрос к API
    BASE_URL = "https://mpstats.io/api/analytics/v1/wb/category/keywords"
    params = {"path": CATEGORY_PATH, "d1": str(DATE_FROM), "d2": str(DATE_TO), "fbs": 0}
    headers = {"X-Mpstats-TOKEN": TOKEN, "Content-Type": "application/json"}

    response = requests.post(BASE_URL, params=params, json={}, headers=headers, timeout=40)
    response.raise_for_status()
    raw_data = response.json()

    # 1. Обработка Запросов
    if "queries" in raw_data:
        df_q = pd.DataFrame(raw_data["queries"])
        if not df_q.empty:
            df_q.insert(0, "period", PERIOD_LABEL)
            # Вставляем категорию, чтобы в таблице было понятно, по чему отчет
            df_q.insert(1, "category", CATEGORY_PATH)
            df_q.rename(columns={"word": "request"}, inplace=True)
            send_to_sheet(df_q, "Запросы")

    # 2. Обработка Слов
    if "words" in raw_data and isinstance(raw_data["words"], list):
        flat_words = []
        for item in raw_data["words"]:
            row = {
                "count": item.get("count"),
                "keys_count_sum": item.get("keys_count_sum"),
                "keys_items_count_sum": item.get("keys_items_count_sum"),
                "keys_wb_count_sum": item.get("keys_wb_count_sum"),
                "word": item.get("word"),
                "word_forms": ", ".join(item.get("words", []))  # Массив форм → строка через запятую
            }
            flat_words.append(row)

        df_words = pd.DataFrame(flat_words)
        if not df_words.empty:
            # Жёсткий порядок колонок
            words_cols = ["word", "word_forms", "count", "keys_count_sum", "keys_items_count_sum", "keys_wb_count_sum"]
            df_words = df_words[words_cols]

            df_words.insert(0, "period", PERIOD_LABEL)
            df_words.insert(1, "category", CATEGORY_PATH)

            send_to_sheet(df_words, "Слова")

    # Формируем финальное сообщение, если всё прошло успешно
    if execution_stats:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        lines = [now_str] + execution_stats + [f"Категория: {CATEGORY_PATH}", "Данные успешно вставлены!"]
        final_report = "\n".join(lines)

        logger.info("Скрипт успешно завершен.")
        send_log_email(final_report, is_success=True)
    else:
        logger.warning("Скрипт выполнился, но данных для вставки не найдено.")
        send_log_email("Скрипт выполнился, но данных от API не получено.", is_success=False)
        # --- НОВОЕ: Отправляем Гуглу сигнал, что данных нет ---
        try:
            requests.post(
                os.getenv("WEBHOOK_URL"),
                json={"status": "error", "message": "Нет данных за этот период или по этой категории."},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
        except Exception as err:
            logger.error(f"Не удалось отправить сигнал в Таблицу: {err}")

except Exception as e:
    error_msg = f"Критическая ошибка:\n{e}\n\nПолный лог:\n{log_buffer.getvalue()}"
    logger.error(error_msg)
    send_log_email(error_msg, is_success=False)
