import requests
import os
import json
import time
import sys
from requests.exceptions import ReadTimeout
from dotenv import load_dotenv
import numpy as np
import pandas as pd

start_time = time.time()
load_dotenv()

TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
mp_auth = os.getenv("mp_auth")

FINAL_COLUMNS = [
    'mp', 'category', 'company_category', 'start_date', 'end_date', 'seller_name', 'inn', 'rating', 'items',
    'items_with_sells', 'items_with_sells_percent', 'sales', 'sales_per', 'sellers', 'sellers_with_sells',
    'brands', 'brands_with_sells', 'brands_with_sells_percent', 'revenue', 'revenue_per', 'revenue_estimated',
    'sales_estimated', 'revenue_per_items_with_sells_average', 'average_order_value', 'avg_price', 'comments',
    'balance', 'balance_price', 'index_card_power', 'index_sprosa', 'index_price', 'index_konkurent', 'index_total',
    'top_1/range', 'top_1/price_score', 'top_2/range', 'top_2/price_score', 'top_3/range', 'top_3/price_score'
]

MARKETPLACES = {
    "wb": {
        "endpoints": {
            "category": {"url": "https://mpstats.io/api/analytics/v1/wb/category/list", "method": "POST"},
            "trends": {"url": "https://mpstats.io/api/analytics/v1/wb/category/trends", "method": "POST"},
            "sellers": {"url": "https://mpstats.io/api/analytics/v1/wb/category/sellers", "method": "POST"},
            "segmentation": {"url": "https://mpstats.io/api/analytics/v1/wb/category/price_segmentation",
                             "method": "POST"}
        },
        "headers": {
            "X-Mpstats-TOKEN": TOKEN, # "Cookie": f"mp_auth={mp_auth}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        "calc_rev_col": "revenue_estimated",
        "calc_sales_col": "sales_estimated",
        "cat_path_col": "name",
        "categories": [
            "Вешалки напольные", "Вешалки настенные", 'Стеллажи', "Обувницы", "Этажерки",
            "Подставки для цветов", "Сушилки для белья", "Швабры", "Столики", "Полки"
        ]
    },
    "oz": {
        "endpoints": {
            "category": {"url": "https://mpstats.io/api/analytics/v1/oz/category/list", "method": "POST"},
            "trends": {"url": "https://mpstats.io/api/analytics/v1/oz/category/trends", "method": "POST"},
            "sellers": {"url": "https://mpstats.io/api/analytics/v1/oz/category/sellers", "method": "POST"}
        },
        "headers": {
            "X-Mpstats-TOKEN": TOKEN, # "Cookie": f"mp_auth={mp_auth}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        "calc_rev_col": "revenue",
        "calc_sales_col": "sales",
        "cat_path_col": "name",
        "categories": [
            "Вешалки настенные", "Вешалки", "Швабры", "Обувницы", "Столы",
            "Стеллажи", "Подставки и крепления для растений", "Сушилки для белья", "Полки"
        ]
    },
    "ym": {
        "endpoints": {
            "category": {"url": "https://mpstats.io/api/ym/rubricator", "method": "POST"},
            "trends": {"url": "https://mpstats.io/api/ym/get/category/trends", "method": "GET"},
            "sellers": {"url": "https://mpstats.io/api/ym/get/category/sellers", "method": "GET"}
        },
        "headers": {
            "X-Mpstats-TOKEN": TOKEN, # "Cookie": f"mp_auth={mp_auth}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        "calc_rev_col": "revenue",
        "calc_sales_col": "sales",
        "cat_path_col": "category_name",
        "categories": [
            "Вешалки напольные", "Вешалки настенные", 'Стеллажи', "Обувницы",
            "Подставки для цветов", "Сушилки для белья", "Швабры", "Столики", "Полки"
        ]
    }
}

new_data_frames = []


def send_to_sheet(df: pd.DataFrame, sheet_name: str):
    if df.empty: return False
    df = df.fillna("")
    payload = {"sheet": sheet_name, "data": df.to_dict(orient="records")}
    try:
        resp = requests.post(WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"},
                             timeout=300, allow_redirects=False)
        if resp.status_code in [200, 302, 303]:
            print("✅ Данные успешно доставлены и обработаны Google Таблицей!")
            return True
        else:
            print(f"❌ Ошибка сервера. Статус: {resp.status_code}, Ответ: {resp.text}")
            return False
    except ReadTimeout:
        print("⚠️ HTTP-соединение закрыто по таймауту (300 сек). Всё нормально, скрипт Google доработает в фоне.")
        return True
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")
        return False


if not WEBHOOK_URL: raise ValueError("❌ Секрет WEBHOOK_URL не найден!")

# === ЖЕСТКИЕ ДАТЫ ДЛЯ ЭКОНОМИИ ЛИМИТОВ ===
first_day_prev_month = (pd.Timestamp.now().replace(day=1) - pd.DateOffset(months=1)).strftime('%Y-%m-%d')
last_day_prev_month = (pd.Timestamp.now().replace(day=1) - pd.DateOffset(days=1)).strftime('%Y-%m-%d')

params_c = {"date": last_day_prev_month}

# =====================================================================================
# ГЛАВНЫЙ ЦИКЛ ПО МАРКЕТПЛЕЙСАМ
# =====================================================================================
for mp_name, mp_config in MARKETPLACES.items():
    ep_cat, ep_trends, ep_sellers = mp_config['endpoints']['category'], mp_config['endpoints']['trends'], \
        mp_config['endpoints']['sellers']
    headers, calc_rev_col, calc_sales_col, cat_path_col = mp_config['headers'], mp_config['calc_rev_col'], mp_config[
        'calc_sales_col'], mp_config['cat_path_col']

    session = requests.Session()
    session.headers.update(headers)

    CATEGORY_LIST = []
    all_trends_frames, all_sellers_frames, periods_for_details = [], [], []

    # 1. КАТЕГОРИИ
    response = session.request(ep_cat['method'], ep_cat['url'], params=params_c, json={}, headers=headers, timeout=60)

    if response.status_code == 200:
        data_list = response.json().get("data", response.json()) if isinstance(response.json(),
                                                                               dict) else response.json()
        df_cat = pd.DataFrame(data_list)
        for i in mp_config['categories']:
            last_level = df_cat[cat_path_col].str.split('/').str[-1]
            # === ИЗМЕНЕНИЕ: Гибкий поиск с регулярным выражением ===
            search_term = r"Подставк[аи] для цветов" if i == "Подставки для цветов" else i
            condition_main = last_level.str.contains(search_term, case=False, na=False, regex=True)
            condition_exclude = ~last_level.str.contains("Паровые|стулья|Горшки", case=False, na=False, regex=True)
            subset = df_cat[condition_main & condition_exclude]
            if not subset.empty:
                CATEGORY_LIST.append((i, subset.loc[subset['revenue'].idxmax()][cat_path_col]))
    else:
        continue

    # 2. ТРЕНДЫ
    for company_cat, category_path in CATEGORY_LIST:
        # === СПАСЕНИЕ ЛИМИТОВ: Строго params, никаких json payload ===
        params_t = {
            "path": category_path,
            "view": "itemsInCategory",
            "trends_by": "month",
            "d1": first_day_prev_month,
            "d2": last_day_prev_month
        }

        response = session.request(ep_trends['method'], ep_trends['url'], params=params_t, json={}, headers=headers,
                                   timeout=30)

        if response.status_code == 200:
            data_list = response.json().get("data", response.json()) if isinstance(response.json(),
                                                                                   dict) else response.json()
            if data_list:
                df = pd.DataFrame(data_list)
                df['company_category'] = company_cat
                df['category'] = category_path
                df['mp'] = mp_name

                target_row = df[df['date'] == first_day_prev_month]

                if not target_row.empty:
                    last_month_row = target_row.copy()
                    row = last_month_row.iloc[0]

                    last_month_row['start_date'] = str(row['date'])
                    last_month_row['end_date'] = str(row['end_date'])

                    all_trends_frames.append(last_month_row)

                    periods_for_details.append((company_cat, category_path, row['date'], row['end_date'],
                                                row.get(calc_rev_col, 0), row.get('revenue', 0),
                                                row.get(calc_sales_col, 0), row.get('sales', 0)))

    # 3. ПРОДАВЦЫ
    for company_cat, cat, d_from, d_to, total_calc_rev, total_rev, total_calc_sales, total_sales in periods_for_details:

        def process_sellers(data_s, cat_name):
            df_s = pd.DataFrame(data_s)
            for c in [calc_rev_col, calc_sales_col, 'revenue', 'sales']:
                if c not in df_s.columns: df_s[c] = 0

            df_s = df_s.sort_values(by=calc_rev_col, ascending=False).reset_index(drop=True)
            df_s['cum_rev'] = df_s[calc_rev_col].cumsum()
            target_rev = total_calc_rev * 0.5
            if target_rev > 0 and df_s['cum_rev'].max() >= target_rev:
                df_s = df_s.iloc[:(df_s['cum_rev'] >= target_rev).idxmax() + 1]
            df_s.drop(columns=['cum_rev'], inplace=True, errors='ignore')

            df_s['revenue_per'] = round((df_s['revenue'] / total_rev) * 100, 2) if total_rev > 0 else 0
            df_s['sales_per'] = round((df_s['sales'] / total_sales) * 100, 2) if total_sales > 0 else 0

            for idx_col, base_val in [('index_card_power', 'comments'), ('index_sprosa', calc_sales_col),
                                      ('index_price', 'revenue_per_items_with_sells_average'),
                                      ('index_konkurent', 'items_with_sells')]:
                base = (df_s.get(base_val, 0) * df_s[calc_rev_col]).sum() / total_calc_rev if total_calc_rev > 0 else 0
                df_s[idx_col] = round(df_s.get(base_val, 0) / base, 2) if base > 0 else 0

            df_s['index_total'] = (
                    0.4 * df_s['index_price'] + 0.3 * df_s['index_sprosa'] + 0.2 * df_s['index_konkurent'] + 0.1 *
                    df_s['index_card_power']).round(2)

            df_s['mp'], df_s['company_category'], df_s['category'] = mp_name, company_cat, cat_name
            df_s['start_date'] = str(d_from)
            df_s['end_date'] = str(d_to)

            all_sellers_frames.append(df_s)


        payload_s = {"path": cat, "d1": d_from, "d2": d_to, "fbs": 0}
        res_s = session.request(ep_sellers['method'], ep_sellers['url'], params=payload_s, json={}, headers=headers,
                                timeout=30)

        data_found = False

        if res_s.status_code == 200:
            data_s = res_s.json().get("data", res_s.json()) if isinstance(res_s.json(), dict) else res_s.json()
            if data_s and len(data_s) > 0:
                process_sellers(data_s, cat)
                data_found = True

        # ПЛАН Б
        if not data_found:
            payload_cb = {"date": d_from}
            res_c = session.request(ep_cat['method'], ep_cat['url'], params=payload_cb, json={}, headers=headers,
                                    timeout=30)

            if res_c.status_code == 200:
                data_c = res_c.json().get("data", res_c.json()) if isinstance(res_c.json(), dict) else res_c.json()
                if data_c:
                    df_c = pd.DataFrame(data_c)
                    search_term = r"Подставк[аи] для цветов" if company_cat == "Подставки для цветов" else company_cat
                    subset = df_c[df_c[cat_path_col].str.contains(search_term, case=False, na=False, regex=True)]
                    if not subset.empty:
                        new_cat = subset.loc[subset['revenue'].idxmax()][cat_path_col]

                        payload_new_s = {"path": new_cat, "d1": d_from, "d2": d_to, "fbs": 0}
                        res_new_s = session.request(ep_sellers['method'], ep_sellers['url'], params=payload_new_s,
                                                    json={}, headers=headers, timeout=30)

                        if res_new_s.status_code == 200:
                            data_new_s = res_new_s.json().get("data", res_new_s.json()) if isinstance(res_new_s.json(),
                                                                                                      dict) else res_new_s.json()
                            if data_new_s and len(data_new_s) > 0:
                                process_sellers(data_new_s, new_cat)

                                # Синхронизация категории в трендах
                                for t_df in all_trends_frames:
                                    if t_df['company_category'].iloc[0] == company_cat and t_df['category'].iloc[
                                        0] == cat:
                                        t_df['category'] = new_cat

    # 4. СБОРКА ТАБЛИЦ ДЛЯ ТЕКУЩЕГО МП
    if all_trends_frames:
        trends_df = pd.concat(all_trends_frames, ignore_index=True)
        trends_df['seller_name'] = 'total'
        trends_df.rename(columns={'product_revenue': 'revenue_per_items_with_sells_average'}, inplace=True)
        trends_df['items_with_sells_percent'] = round(
            (trends_df.get('items_with_sells', 0) / trends_df.get('items', 1)) * 100, 2)
        trends_df['brands_with_sells_percent'] = round(
            (trends_df.get('brands_with_sells', 0) / trends_df.get('brands', 1)) * 100, 2)
        trends_df['revenue_per'], trends_df['sales_per'] = 100.0, 100.0

        for col in FINAL_COLUMNS:
            if col not in trends_df.columns: trends_df[col] = np.nan
        new_data_frames.append(trends_df[FINAL_COLUMNS])

    if all_sellers_frames:
        sellers_df = pd.concat(all_sellers_frames, ignore_index=True)
        sellers_df = sellers_df.loc[:, ~sellers_df.columns.str.startswith('graph')]
        sellers_df.rename(columns={'name': 'seller_name'}, inplace=True)

        for col in FINAL_COLUMNS:
            if col not in sellers_df.columns: sellers_df[col] = np.nan
        new_data_frames.append(sellers_df[FINAL_COLUMNS])

# =====================================================================================
# 5. ОТПРАВКА И СБОР ЦЕНОВЫХ СЕГМЕНТОВ В КОНЦЕ
# =====================================================================================
if new_data_frames:
    df_new = pd.concat(new_data_frames, ignore_index=True)


    def normalize_score(series):
        if series.max() == series.min(): return pd.Series(0, index=series.index)
        return (series - series.min()) / (series.max() - series.min())


    if 'wb' in df_new['mp'].values:
        wb_recent = df_new[(df_new['mp'] == 'wb') & (df_new['seller_name'] != 'total')]
        unique_combinations = wb_recent[['category', 'start_date', 'end_date']].drop_duplicates()

        seg_results = []
        ep_seg = MARKETPLACES['wb']['endpoints'].get('segmentation')
        headers_wb = MARKETPLACES['wb']['headers']

        if ep_seg and not unique_combinations.empty:
            print("📊 Расчет ценовых сегментов (WB Топ-3)...")
            for _, row in unique_combinations.iterrows():
                cat_path, d1, d2 = row['category'], row['start_date'], row['end_date']

                try:
                    seg_params = {"path": cat_path, "d1": d1, "d2": d2, "fbs": 0, "minPrice": 500, "maxPrice": 4000}
                    res_seg = requests.request(ep_seg['method'], ep_seg['url'], params=seg_params, json={},
                                               headers=headers_wb, timeout=30)

                    if res_seg.status_code == 200:
                        raw = res_seg.json()
                        data_seg = raw.get("data", raw) if isinstance(raw, dict) else raw

                        if data_seg:
                            df_seg = pd.DataFrame(data_seg)
                            for c in ['lost_profit', 'revenue', 'revenue_estimated', 'items_with_sells',
                                      'sales_estimated', 'items']:
                                if c in df_seg.columns:
                                    df_seg[c] = pd.to_numeric(df_seg[c], errors='coerce').fillna(0)

                            df_seg['lost_revenue'] = (df_seg.get('lost_profit', 0) / df_seg['revenue']).replace(
                                [np.inf, -np.inf], 0).fillna(0)
                            df_seg['efficiency_items'] = (
                                        df_seg['revenue_estimated'] / df_seg['items_with_sells']).replace(
                                [np.inf, -np.inf], 0).fillna(0)
                            df_seg['average_check'] = (df_seg['revenue_estimated'] / df_seg['sales_estimated']).replace(
                                [np.inf, -np.inf], 0).fillna(0)
                            df_seg['pocket_weight'] = (
                                        df_seg['revenue_estimated'] / df_seg['revenue_estimated'].sum()).fillna(0)

                            eff_norm = normalize_score(df_seg['efficiency_items'])
                            lost_norm = normalize_score(df_seg['lost_revenue'])
                            aver_norm = normalize_score(df_seg['average_check'])
                            weight_norm = normalize_score(df_seg['pocket_weight'])

                            score = eff_norm * 0.30 + lost_norm * 0.15 + aver_norm * 0.15 + weight_norm * 0.40
                            df_seg['price_score'] = score.round(3)

                            if not df_seg.empty and 'price_score' in df_seg.columns:
                                top_segments = df_seg.sort_values(by='price_score', ascending=False).head(3)

                                seg_dict = {
                                    'mp': 'wb',
                                    'category': cat_path,
                                    'start_date': d1,
                                    'end_date': d2
                                }

                                for i, (_, row_seg) in enumerate(top_segments.iterrows(), start=1):
                                    seg_dict[f'top_{i}/range'] = row_seg.get('range', '')
                                    seg_dict[f'top_{i}/price_score'] = row_seg['price_score']

                                for i in range(len(top_segments) + 1, 4):
                                    seg_dict[f'top_{i}/range'] = ""
                                    seg_dict[f'top_{i}/price_score'] = np.nan

                                seg_results.append(seg_dict)

                except Exception as e:
                    print(f"⚠️ Ошибка сегментации {cat_path}: {e}")

        if seg_results:
            df_seg_scores = pd.DataFrame(seg_results)
            metrics_cols = ['top_1/range', 'top_1/price_score', 'top_2/range', 'top_2/price_score', 'top_3/range',
                            'top_3/price_score']
            df_new.drop(columns=[c for c in metrics_cols if c in df_new.columns], inplace=True)
            df_new = pd.merge(df_new, df_seg_scores, on=['mp', 'category', 'start_date', 'end_date'], how='left')

    df_new.loc[(df_new['mp'] == 'oz') & (df_new[
                                             'company_category'] == 'Подставки и крепления для растений'), 'company_category'] = 'Подставки для цветов'
    df_new.loc[(df_new['mp'] == 'oz') & (df_new['company_category'] == 'Столы'), 'company_category'] = 'Столики'

    df_new = df_new.reindex(columns=FINAL_COLUMNS)

    is_success = send_to_sheet(df_new, "mpstats_general")
    if not is_success: sys.exit(1)

else:
    print("⚠️ Новых данных за прошлый месяц не найдено.")
print(f"⏱ Время выполнения: {round((time.time() - start_time), 2)} сек.")
