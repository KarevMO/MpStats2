import requests
import os
import time
import sys
import json
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

# Загружаем ключи и URL вебхука
TOKEN = os.getenv("TOKEN")
mp_auth = os.getenv("mp_auth")
WEBHOOK_URL = os.getenv("WEBHOOK_URL_1")

CSV_SEASON_EFFECTS = "season_effects.csv"

# Наш целевой список категорий (эталонный)
TARGET_CATEGORIES = [
    "Вешалки напольные", "Вешалки настенные", 'Стеллажи', "Обувницы", "Этажерки",
    "Подставки для цветов", "Сушилки для белья", "Швабры", "Столики", "Полки"
]


# =====================================================================================
# ФУНКЦИЯ ДЛЯ ОТПРАВКИ В GOOGLE ТАБЛИЦУ
# =====================================================================================
def send_to_sheet(df: pd.DataFrame, sheet_name: str):
    if df.empty:
        print(f"⚠️ Таблица {sheet_name} пуста, отправка отменена.")
        return False

    df = df.fillna("")
    payload = {"sheet": sheet_name, "data": df.to_dict(orient="records")}

    try:
        # === ИСПРАВЛЕНИЕ ЗДЕСЬ: добавлено allow_redirects=False ===
        resp = requests.post(WEBHOOK_URL, data=json.dumps(payload),
                             headers={"Content-Type": "application/json"},
                             timeout=300, allow_redirects=False)

        if resp.status_code in [200, 302, 303]:
            print(f"✅ Данные успешно доставлены на лист '{sheet_name}'!")
            return True
        else:
            print(f"❌ Ошибка Google Sheets. Статус: {resp.status_code}, Ответ: {resp.text}")
            return False

    except requests.exceptions.ReadTimeout:
        print("⚠️ HTTP-соединение закрыто по таймауту. Всё нормально, скрипт Google доработает в фоне.")
        return True
    except Exception as e:
        print(f"❌ Ошибка сети при отправке в Google: {e}")
        return False


# =====================================================================================
# 1. ПОЛУЧАЕМ АКТУАЛЬНЫЕ ПУТИ КАТЕГОРИЙ
# =====================================================================================
last_day_prev_month = (pd.Timestamp.now().replace(day=1) - pd.DateOffset(days=1)).strftime('%Y-%m-%d')

url_cat = "https://mpstats.io/api/analytics/v1/wb/category/list"
headers_base = {
    "X-Mpstats-TOKEN": TOKEN, # "Cookie": f"mp_auth={mp_auth}",
    "Content-Type": "application/json"
}

CATEGORY_LIST = []

try:
    response_cat = requests.post(url_cat, params={"date": last_day_prev_month}, json={}, headers=headers_base,
                                 timeout=60)
    if response_cat.status_code == 200:
        raw_json = response_cat.json()
        if isinstance(raw_json, dict):
            data_list = raw_json.get("data", [])
        else:
            data_list = raw_json

        df_cat = pd.DataFrame(data_list)

        for i in TARGET_CATEGORIES:
            last_level = df_cat['name'].str.split('/').str[-1]
            search_term = r"Подставк[аи] для цветов" if i == "Подставки для цветов" else i
            condition_main = last_level.str.contains(search_term, case=False, na=False, regex=True)
            condition_exclude = ~last_level.str.contains("Паровые|стулья|Горшки", case=False, na=False, regex=True)

            subset = df_cat[condition_main & condition_exclude]
            if not subset.empty:
                CATEGORY_LIST.append((i, subset.loc[subset['revenue'].idxmax()]['name']))
    else:
        print(f"❌ Ошибка получения категорий: {response_cat.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Ошибка при обработке списка категорий: {e}")
    sys.exit(1)

# =====================================================================================
# 2. СБОР СЕЗОННОСТИ И ОТПРАВКА
# =====================================================================================
BASE_URL = "https://mpstats.io/api/analytics/v1/wb/category/season_effects/annual"
headers_season = {"X-Mpstats-TOKEN": TOKEN, "Content-Type": "application/json"}

all_season_data = []

for company_cat, category_path in CATEGORY_LIST:
    params = {"path": category_path, "period": "day"}

    try:
        response = requests.get(BASE_URL, params=params, headers=headers_season, timeout=30)
        if response.status_code == 200:
            raw_res = response.json()
            if isinstance(raw_res, dict):
                data_list = raw_res.get("data", [])
            else:
                data_list = raw_res

            if data_list:
                df = pd.DataFrame(data_list)

                # === ИСПРАВЛЕНИЕ ДАТЫ: Защита от автоформатирования Google Sheets ===
                if 'date' in df.columns:
                    df['date'] = "'" + df['date'].astype(str)
                # ===================================================================

                df.insert(0, 'mp', 'wb')
                df.insert(1, 'category', category_path)
                df.insert(2, 'company_category', company_cat)
                all_season_data.append(df)
    except Exception as e:
        print(f"  ❌ Ошибка на {company_cat}: {e}")


if all_season_data:
    final_df = pd.concat(all_season_data, ignore_index=True)

    # 1. Отправляем в Google Таблицу (Лист 'season_effects')
    if WEBHOOK_URL:
        send_to_sheet(final_df, "season_effects")
    else:
        print("⚠️ WEBHOOK_URL не настроен, отправка в Google пропущена.")
else:
    print("\n⚠️ Данные не собраны.")
