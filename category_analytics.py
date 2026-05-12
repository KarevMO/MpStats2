import os
import sys
import json
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv  # Потом убрать

load_dotenv()
CATEGORY = os.getenv("CATEGORY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL_AC")
GDRIVE_JSON = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

def send_to_webhook(payload):
    try:
        requests.post(WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"},
                      timeout=10, )
    except requests.exceptions.ReadTimeout:
        pass
    sys.exit(0)


def send_error(msg):
    send_to_webhook({"status": "error", "message": msg})


if not all([CATEGORY, WEBHOOK_URL, GDRIVE_JSON, SPREADSHEET_ID]):
    send_error("Не настроены переменные среды (WEBHOOK_URL, GDRIVE_JSON и т.д.).")

# --- 2. ЧИТАЕМ БАЗУ ДАННЫХ ---
try:
    creds_dict = json.loads(GDRIVE_JSON)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("mpstats_general")
    data = sheet.get_all_records()
except Exception as e:
    send_error(f"Ошибка чтения базы данных: {e}")

if not data:
    send_error("Лист mpstats_general пуст.")

df = pd.DataFrame(data)

# Ищем нужную категорию
df_filtered = df[df['category'] == CATEGORY].copy()

if df_filtered.empty:
    send_error(f"Категория '{CATEGORY}' не найдена в базе данных.")

# Переводим даты в формат времени и сортируем
df_filtered['start_date_dt'] = pd.to_datetime(df_filtered['start_date'], format='%Y-%m-%d', errors='coerce')
df_filtered = df_filtered.sort_values(by='start_date_dt', ascending=False)

if df_filtered.empty:
    send_error("Для данной категории нет корректных дат.")

# --- 3. ИЩЕМ ДАТЫ ДЛЯ СРАВНЕНИЯ ---
latest_date = df_filtered['start_date_dt'].iloc[0]
prev_year_date = latest_date - pd.DateOffset(years=1)

row_latest = df_filtered[df_filtered['start_date_dt'] == latest_date]
row_prev = df_filtered[df_filtered['start_date_dt'] == prev_year_date]

# --- 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_orders(row, default=0):
    try:
        est_rev = row['revenue_estimated'].loc[row['seller_name'] == 'total'].iloc[0]
        # Правильный порядок: сначала пустота, потом float
        if pd.isnull(est_rev) or str(est_rev).strip() == '' or float(est_rev) == 0:
            rev = row['revenue'].loc[row['seller_name'] == 'total'].iloc[0]
        else:
            rev = est_rev

        items = row['items_with_sells'].loc[row['seller_name'] == 'total'].iloc[0]

        if pd.isnull(items) or str(items).strip() == '' or float(items) == 0:
            return default

        if pd.isnull(rev) or str(rev).strip() == '':
            rev = 0

        val = float(rev) / float(items)
        return int(val) if pd.notnull(val) else 0
    except (IndexError, AttributeError, KeyError, ValueError, ZeroDivisionError):
        return default

def get_revenue(row, default=0):
    try:
        est_val = row['revenue_estimated'].loc[row['seller_name'] == 'total'].iloc[0]
        # Правильный порядок: сначала пустота, потом float
        if pd.isnull(est_val) or str(est_val).strip() == '' or float(est_val) == 0:
            val = row['revenue'].loc[row['seller_name'] == 'total'].iloc[0]
        else:
            val = est_val

        if pd.isnull(val) or str(val).strip() == '':
            return default
        return int(float(val))
    except (IndexError, AttributeError, KeyError, ValueError):
        return default

def get_sales(row, default=0):
    try:
        est_val = row['sales_estimated'].loc[row['seller_name'] == 'total'].iloc[0]
        # Правильный порядок: сначала пустота, потом float
        if pd.isnull(est_val) or str(est_val).strip() == '' or float(est_val) == 0:
            val = row['sales'].loc[row['seller_name'] == 'total'].iloc[0]
        else:
            val = est_val

        if pd.isnull(val) or str(val).strip() == '':
            return default
        return int(float(val))
    except (IndexError, AttributeError, KeyError, ValueError):
        return default

def format_money(val):
    try:
        if pd.isnull(val) or str(val).strip() == '':
            return "0 ₽"
        return f"{int(float(val)):,} ₽".replace(",", " ")
    except:
        return "0 ₽"

def get_growth(cur, prev):
    try:
        if prev == 0 or pd.isnull(prev) or str(prev).strip() == '':
            return "-"
        growth = ((float(cur) - float(prev)) / float(prev)) * 100
        return f"{int(growth)}%"
    except:
        return "-"

def get_items_with_sells(row, default=0):
    try:
        val = row['items_with_sells'].loc[row['seller_name'] == 'total'].iloc[0]
        if pd.isnull(val) or str(val).strip() == '':
            return default
        return int(float(val))
    except (IndexError, AttributeError, KeyError, ValueError):
        return default

def get_average_order(row, default=0):
    try:
        val = row['average_order_value'].loc[row['seller_name'] == 'total'].iloc[0]
        if pd.isnull(val) or str(val).strip() == '':
            return default
        return int(float(val))
    except (IndexError, AttributeError, KeyError, ValueError):
        return default

over_latest=get_average_order(row_latest)
over_prev=get_average_order(row_prev)

orders_latest = get_orders(row_latest)
orders_prev = get_orders(row_prev)

sal_latest = get_sales(row_latest)
sal_prev = get_sales(row_prev)

rev_latest = get_revenue(row_latest)
rev_prev = get_revenue(row_prev)

items_latest = get_items_with_sells(row_latest)
items_prev = get_items_with_sells(row_prev)

growth_over=get_growth(over_latest, over_prev)
growth_or = get_growth(orders_latest, orders_prev)
growth_sal = get_growth(sal_latest, sal_prev)
growth = get_growth(rev_latest, rev_prev)
growth_items = get_growth(items_latest, items_prev)

latest_str = latest_date.strftime('%d.%m.%Y')
prev_str = prev_year_date.strftime('%d.%m.%Y')

# --- 5. ФОРМИРУЕМ ГОТОВУЮ СТРОКУ ---
result_dict = {
    "Категория": df_filtered['category'].iloc[0],

    f"{latest_str}": format_money(rev_latest),
    f"{prev_str}": format_money(rev_prev),
    "Рост": growth,
    f"{latest_str} ":f"{items_latest:,}".replace(",", " "),
    f"{prev_str} ":f"{items_prev:,}".replace(",", " "),
    "Рост ":growth_items,
    f"{latest_str}   ":f"{sal_latest:,}".replace(",", " "),
    f"{prev_str}   ":f"{sal_prev:,}".replace(",", " "),
    "Рост   ": growth_sal,
    f"{latest_str}    ":format_money(orders_latest),
    f"{prev_str}    ":format_money(orders_prev),
    "Рост    ":growth_or,
    f"{latest_str}     ":format_money(over_latest),
    f"{prev_str}     ":format_money(over_prev),
    "Рост     ": growth_over,
}

# Отправляем на лист "Результат"
send_to_webhook({"sheet": "Settings", "data": [result_dict]})
