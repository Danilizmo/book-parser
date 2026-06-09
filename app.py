# -*- coding: utf-8 -*-
import os
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

def clean_price(price_str):
    if not price_str:
        return None
    # Ищем первое число в строке (с учётом пробелов, точек, запятых)
    match = re.search(r'(\d[\d\s]*[.,]?\d*)', price_str)
    if match:
        num_str = re.sub(r'\s', '', match.group(1)).replace(',', '.')
        try:
            return int(float(num_str))
        except:
            return None
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

            # ---------- УЛУЧШЕННЫЙ ПОИСК ЦЕНЫ ----------
            price_raw = ""
            price_selectors = [
                '.product-price',
                '.catalog-card__price',
                '[class*="price"]',
                '.price',
                '[data-price]',
                '.action-price',
                '.current-price',
                '.sale-price',
                '.price-number',
                '.cost',
                '.price-wrap .price'
            ]
            for selector in price_selectors:
                try:
                    price_elem = item.find_element(By.CSS_SELECTOR, selector)
                    price_raw = price_elem.text.strip()
                    if price_raw:
                        # Если цена содержит несколько строк (старая и новая), берём первую или ту, что не зачёркнута
                        lines = price_raw.split('\n')
                        for line in lines:
                            if line and not re.search(r'[₽руб]', line):
                                continue
                            if '<s>' in line or 'old' in line.lower() or 'скидка' in line.lower():
                                continue
                            price_raw = line
                            break
                        else:
                            price_raw = lines[0] if lines else ''
                        break
                except:
                    continue

            # Если селекторы не сработали, пробуем найти любую цену в тексте карточки
            if not price_raw:
                text = item.text
                price_match = re.search(r'(\d[\d\s]*[.,]?\d*)\s*[₽руб]', text)
                if price_match:
                    price_raw = price_match.group(0)

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
            print(f"  [Цена] {title[:40]} → '{price_raw}'")
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
        shared_state['message'] = f"⏹️ Парсинг остановлен. Собрано {len(all_books)} книг."
    else:
        shared_state['message'] = f"✅ Готово! Собрано {len(all_books)} книг за {elapsed:.1f} сек."
    shared_state['running'] = False

# ---------- HTML-шаблон (сокращён для экономии места, но полный) ----------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru | Timergalin Danil</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; transition: background 0.3s, color 0.3s; }
        body.light-theme { background: #f0f2f5; color: #222; }
        body.light-theme .container { background: #fff; }
        body.light-theme .controls, body.light-theme .stats-card, body.light-theme .quote, body.light-theme .log { background: #e9ecef; color: #222; }
        body.light-theme .progress-bar { background: #ddd; }
        body.light-theme th { background: #dee2e6; color: #000; }
        body.light-theme td, body.light-theme th { border-color: #ccc; }
        body.light-theme .log { background: #fff; border: 1px solid #ccc; }
        body.light-theme .log-message { border-bottom: 1px solid #e9ecef; }
        .container { max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); position: relative; }
        h1 { color: #ffd966; text-align: center; margin-top: 0; }
        .settings-top { position: absolute; top: 20px; right: 20px; }
        .settings-top button { background: #607d8b; border-radius: 50%; width: 42px; height: 42px; font-size: 20px; padding: 0; display: flex; align-items: center; justify-content: center; }
        @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
        .toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: #4caf50; color: white; padding: 12px 24px; border-radius: 40px; font-weight: bold; z-index: 2000; animation: slideInRight 0.3s ease forwards; }
        .toast.fade-out { animation: fadeOut 0.3s ease forwards; }
        /* остальные стили такие же, как в предыдущей версии, для краткости опущены, но они есть в полном коде */
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Владелец: Timergalin Danil | Учебный проект</div>
<div class="container">
    <div class="settings-top"><button id="settingsBtn" class="settings-btn">⚙️</button></div>
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="quote">✨ «Читайте больше, живите ярче!» ✨</div>
    <!-- панель управления, вкладки, таблица, логи – аналогично предыдущему -->
    <!-- полный HTML-шаблон идентичен предыдущему рабочему варианту, за исключением обновлённых функций парсинга -->
</div>
<!-- здесь идут модальные окна и скрипты, которые полностью совпадают с предыдущей версией -->
</body>
</html>
"""
# Здесь должен быть полный HTML-шаблон, но в этом ответе я приведу только изменённые функции.
# Чтобы не дублировать 200 строк, просто замените в вашем существующем app.py функции clean_price и parse_page на указанные выше.
