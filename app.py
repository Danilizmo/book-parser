# -*- coding: utf-8 -*-
import csv
import io
import random
import re
import threading
import time
from datetime import datetime

from flask import Flask, render_template_string, request, jsonify, send_file
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)
CORS(app)

# --------------------------------------------------------------
# Глобальное состояние парсинга
# --------------------------------------------------------------
shared_state = {
    'running': False,
    'books': [],
    'progress_current': 0,
    'progress_total': 0,
    'stats': None,
    'message': '',
    'stop_flag': False
}

categories = {
    "https://book24.ru/knigi-bestsellery/": "Бестселлеры",
    "https://book24.ru/knigi-novinki/": "Новинки",
    "https://book24.ru/knigi-skoro-v-prodazhe/": "Скоро в продаже",
    "https://book24.ru/knigi/klassicheskaya-literatura/": "Классика",
    "https://book24.ru/knigi/detektivy/": "Детективы",
    "https://book24.ru/knigi/fentezi/": "Фэнтези",
    "https://book24.ru/knigi/romany/": "Романы",
    "https://book24.ru/knigi/fantastika/": "Фантастика",
    "https://book24.ru/knigi/psikhologiya/": "Психология",
    "https://book24.ru/knigi/biznes-literatura/": "Бизнес-литература",
    "https://book24.ru/knigi/detskaya-literatura/": "Детские книги",
    "https://book24.ru/knigi/uchebnaya-literatura/": "Учебники"
}

# --------------------------------------------------------------
# Функции парсинга (адаптированы под Chrome)
# --------------------------------------------------------------
def clean_price(price_str):
    if not price_str:
        return None
    match = re.search(r'(\d[\d\s]*)', price_str)
    if match:
        return int(re.sub(r'\s', '', match.group(1)))
    return None

def parse_page(driver, page_num):
    books = []
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.product-card, .catalog-card, [data-product-id]'))
        )
    except Exception as e:
        print(f"⚠️ Страница {page_num}: не дождались карточек – {e}")
        return books
    time.sleep(random.uniform(0.6, 1.2))
    items = driver.find_elements(By.CSS_SELECTOR, '.product-card, .catalog-card, [data-product-id]')
    print(f"📄 Страница {page_num}: найдено {len(items)} карточек")
    for item in items:
        try:
            title = ""
            title_elem = item.find_element(By.CSS_SELECTOR, 'a[title], .product-title, .catalog-card__title, h3')
            title = title_elem.text.strip()
            if not title:
                title = title_elem.get_attribute('title') or ""
            author = ""
            try:
                author_elem = item.find_element(By.CSS_SELECTOR, '.product-author, .catalog-card__author, [class*="author"]')
                author = author_elem.text.strip()
            except:
                pass
            price_raw = ""
            try:
                price_elem = item.find_element(By.CSS_SELECTOR, '.product-price, .catalog-card__price, [class*="price"]')
                price_raw = price_elem.text.strip().split('\n')[0]
            except:
                pass
            price_num = clean_price(price_raw)
            link = ""
            try:
                link_elem = item.find_element(By.CSS_SELECTOR, 'a')
                link = link_elem.get_attribute('href')
                if link and not link.startswith('http'):
                    link = 'https://book24.ru' + link
            except:
                pass
            books.append({
                'Название': title,
                'Автор': author,
                'Цена (число)': price_num,
                'Цена (строка)': price_raw,
                'Ссылка': link
            })
        except Exception as e:
            print(f"❌ Ошибка в карточке: {e}")
    return books

def run_parser_task(max_books, category_url):
    global shared_state
    start_time = time.time()
    shared_state['running'] = True
    shared_state['stop_flag'] = False
    shared_state['books'] = []
    shared_state['progress_current'] = 0
    shared_state['progress_total'] = max_books
    shared_state['message'] = ''
    shared_state['stats'] = None

    # Настройка Chrome для сервера
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)

    page = 1
    all_books = []
    max_pages = 100

    while page <= max_pages and len(all_books) < max_books and not shared_state['stop_flag']:
        url = f"{category_url}?page={page}" if page > 1 else category_url
        print(f"🌐 Загрузка страницы {page}...")
        driver.get(url)
        books_on_page = parse_page(driver, page)
        if not books_on_page:
            break
        if len(all_books) + len(books_on_page) > max_books:
            remaining = max_books - len(all_books)
            all_books.extend(books_on_page[:remaining])
        else:
            all_books.extend(books_on_page)
        shared_state['books'] = all_books.copy()
        shared_state['progress_current'] = len(all_books)
        if len(all_books) >= max_books:
            break
        page += 1
        time.sleep(random.uniform(0.8, 1.5))

    driver.quit()
    elapsed = time.time() - start_time

    # Статистика
    prices = [b['Цена (число)'] for b in all_books if b.get('Цена (число)') is not None]
    avg_price = sum(prices)/len(prices) if prices else 0
    min_price = min(prices) if prices else 0
    max_price_val = max(prices) if prices else 0
    category_name = categories.get(category_url, category_url)
    shared_state['stats'] = {
        'count': len(all_books),
        'avg_price': round(avg_price, 2),
        'min_price': min_price,
        'max_price': max_price_val,
        'category': category_name,
        'time': round(elapsed, 1)
    }
    if shared_state['stop_flag']:
        shared_state['message'] = f"Парсинг остановлен. Собрано {len(all_books)} книг."
    else:
        shared_state['message'] = f"Готово! Собрано {len(all_books)} книг за {elapsed:.1f} сек."
    shared_state['running'] = False

# --------------------------------------------------------------
# HTML + CSS + JS (можно взять из предыдущего кода, он не менялся)
# --------------------------------------------------------------
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru (Веб-версия)</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; color: #eee; }
        .container { max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); overflow: hidden; padding: 20px; }
        h1 { color: #ffd966; text-align: center; margin-top: 0; }
        .controls { display: flex; gap: 20px; flex-wrap: wrap; background: #252634; padding: 15px; border-radius: 12px; margin-bottom: 20px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; }
        button { background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; transition: 0.2s; }
        button:hover { filter: brightness(1.1); }
        #stopBtn { background: #f44336; }
        #saveBtn { background: #2196f3; }
        button:disabled { opacity: 0.6; cursor: not-allowed; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: linear-gradient(90deg, #4caf50, #8bc34a); text-align: center; line-height: 25px; color: white; font-weight: bold; font-size: 13px; transition: width 0.3s; }
        .stats { background: #252634; padding: 12px; border-radius: 10px; margin: 15px 0; border-left: 5px solid #ffd966; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; font-weight: bold; }
        .status.info { background: #0c5460; color: #d1ecf1; }
        .status.success { background: #155724; color: #d4edda; }
        .status.error { background: #721c24; color: #f8d7da; }
        .log { background: #1e1f2c; color: #0f0; font-family: monospace; padding: 10px; height: 200px; overflow-y: auto; margin-top: 20px; border-radius: 8px; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background: #2d2f3e; }
        th, td { border: 1px solid #3c3f54; padding: 10px; text-align: left; }
        th { background: #3c3f54; cursor: pointer; color: #ffd966; }
        td a { color: #66bb6a; text-decoration: none; }
        .table-wrapper { overflow-x: auto; }
    </style>
</head>
<body>
<div class="container">
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="controls">
        <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" value="10" min="1" max="2000"></div>
        <div class="form-group"><label>🎭 Жанр:</label>
        <select id="category">... (все категории) ...</select></div>
        <div><button id="startBtn">▶ СТАРТ</button><button id="stopBtn" disabled>⏹️ СТОП</button><button id="saveBtn" disabled>💾 СОХРАНИТЬ CSV</button></div>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
    <div class="stats" id="statsDiv">📊 Статистика: пока нет данных</div>
    <div class="status info" id="statusDiv">Готов к работе</div>
    <div class="table-wrapper"><table id="resultsTable"><thead><tr><th>№</th><th>Название</th><th>Автор</th><th>Цена</th><th>Ссылка</th></tr></thead><tbody id="tableBody"></tbody></table></div>
    <div class="log" id="logDiv">📋 Лог парсинга:\n</div>
</div>
<script> ... (JS код такой же, как в предыдущей версии, но для краткости оставлю предыдущий рабочий JS) ... </script>
</body>
</html>
"""

# Остальной Flask код (маршруты) – без изменений
# ...

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8000)
