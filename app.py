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

# ---------- Глобальное состояние ----------
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

# ---------- Функции парсинга ----------
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
                price_elem = item.find_element(By.CSS_SELECTOR, '.product-price, .catalog-card__price, [class*="price"], .price')
                price_raw = price_elem.text.strip().split('\n')[0]
            except:
                # пробуем альтернативный селектор
                try:
                    price_elem = item.find_element(By.CSS_SELECTOR, '[class*="price"]')
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

# ---------- HTML-шаблон ----------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru | Timergalin Danil</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; position: relative; transition: background 0.3s, color 0.3s; }
        body.light-theme { background: #f0f2f5; color: #222; }
        body.light-theme .container { background: #fff; color: #222; }
        body.light-theme .controls, body.light-theme .stats-card, body.light-theme .quote, body.light-theme .log { background: #e9ecef; color: #222; }
        body.light-theme .progress-bar { background: #ddd; }
        body.light-theme th { background: #dee2e6; color: #000; }
        body.light-theme td, body.light-theme th { border-color: #ccc; }
        body.light-theme .status.info { background: #cce5ff; color: #004085; }
        body.light-theme .status.success { background: #d4edda; color: #155724; }
        body.light-theme .status.error { background: #f8d7da; color: #721c24; }
        body.light-theme .log { background: #fff; color: #000; border: 1px solid #ccc; }
        body.light-theme .owner-sign { background: rgba(0,0,0,0.7); color: #ffd966; }
        body.light-theme .stats-card { background: #fff; border: 1px solid #dee2e6; }
        body.light-theme .stats-grid { color: #333; }
        body.light-theme .log-message { border-bottom: 1px solid #e9ecef; }

        .container { max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); transition: background 0.3s; position: relative; }
        h1 { color: #ffd966; text-align: center; margin-top: 0; }
        /* Кнопка настроек в правом верхнем углу */
        .settings-top {
            position: absolute;
            top: 20px;
            right: 20px;
        }
        .settings-top button {
            background: #607d8b;
            border-radius: 50%;
            width: 42px;
            height: 42px;
            font-size: 20px;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        /* Анимации */
        @keyframes pulse {
            0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76,175,80,0.7); }
            70% { transform: scale(1.02); box-shadow: 0 0 0 10px rgba(76,175,80,0); }
            100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76,175,80,0); }
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        @keyframes bgFlash {
            0% { background-color: #2d2f3e; }
            50% { background-color: #3c4058; }
            100% { background-color: #2d2f3e; }
        }
        @keyframes slideInRight {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes fadeOut {
            from { opacity: 1; transform: translateX(0); }
            to { opacity: 0; transform: translateX(100%); }
        }
        .animate-pulse { animation: pulse 1.2s infinite; }
        .progress-bar, .status, .log { animation: fadeIn 0.4s ease-out; }
        .flash-bg { animation: bgFlash 0.3s ease; }
        .loader {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid #fff;
            border-radius: 50%;
            border-top-color: #4caf50;
            animation: spin 0.6s linear infinite;
            margin-left: 10px;
            vertical-align: middle;
        }
        .owner-sign {
            position: fixed;
            bottom: 10px;
            right: 15px;
            background: rgba(0,0,0,0.6);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            color: #ffd966;
            font-family: monospace;
            backdrop-filter: blur(4px);
            z-index: 1000;
            pointer-events: none;
            font-weight: bold;
        }
        .controls { display: flex; gap: 20px; flex-wrap: wrap; background: #252634; padding: 15px; border-radius: 12px; margin-bottom: 20px; align-items: flex-end; justify-content: space-between; }
        .control-group { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        body.light-theme label { color: #0056b3; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; }
        body.light-theme input, body.light-theme select { background: #fff; color: #000; border: 1px solid #ccc; }
        button {
            background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px;
            font-weight: bold; color: white; cursor: pointer; transition: all 0.2s ease; margin: 5px;
        }
        button:hover { transform: scale(1.02) translateY(-1px); filter: brightness(1.05); box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
        #stopBtn { background: #f44336; }
        #saveBtn { background: #2196f3; }
        .info-btn { background: #9c27b0; }
        .tab-btn { background: #3c3f54; }
        .tab-btn.active { background: #4caf50; box-shadow: 0 0 8px #4caf50; }
        button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: linear-gradient(90deg, #4caf50, #8bc34a); text-align: center; line-height: 25px; color: white; font-weight: bold; font-size: 13px; transition: width 0.2s linear; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; font-weight: bold; transition: 0.2s; }
        .status.info { background: #0c5460; color: #d1ecf1; }
        .status.success { background: #155724; color: #d4edda; }
        .status.error { background: #721c24; color: #f8d7da; }
        /* Улучшенный лог */
        .log {
            background: #1e1f2c;
            color: #0f0;
            font-family: 'Fira Code', 'Courier New', monospace;
            padding: 12px;
            height: 280px;
            overflow-y: auto;
            margin-top: 20px;
            border-radius: 12px;
            font-size: 13px;
            box-shadow: inset 0 0 8px rgba(0,0,0,0.3);
            scroll-behavior: smooth;
        }
        .log-message {
            border-bottom: 1px solid #2a2a3a;
            padding: 6px 8px;
            transition: background 0.1s;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .log-message:hover { background: #2a2a3a; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 1px solid #3c3f54; padding-bottom: 10px; }
        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeIn 0.3s ease; }
        .table-wrapper { overflow-x: auto; max-height: 500px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; background: #2d2f3e; }
        th, td { border: 1px solid #3c3f54; padding: 10px; text-align: left; }
        th { background: #3c3f54; cursor: pointer; color: #ffd966; position: sticky; top: 0; user-select: none; }
        th:hover { background: #4a4d6b; }
        td a { color: #66bb6a; text-decoration: none; }
        .quote {
            text-align: center;
            font-style: italic;
            margin: 20px 0;
            padding: 10px;
            background: #252634;
            border-radius: 8px;
            color: #ffd966;
        }
        /* Стили для статистики в виде карточек */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stats-card {
            background: #252634;
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            transition: transform 0.2s;
            border-left: 4px solid #ffd966;
        }
        .stats-card:hover { transform: translateY(-3px); }
        .stats-card .value {
            font-size: 28px;
            font-weight: bold;
            color: #ffd966;
            margin: 10px 0;
        }
        .stats-card .label {
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #aaa;
        }
        body.light-theme .stats-card .label { color: #555; }
        /* Тост уведомление */
        .toast {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%);
            background: #4caf50;
            color: white;
            padding: 12px 24px;
            border-radius: 40px;
            font-weight: bold;
            z-index: 2000;
            animation: slideInRight 0.3s ease forwards;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            font-size: 14px;
        }
        .toast.fade-out {
            animation: fadeOut 0.3s ease forwards;
        }
        /* Модальное окно настроек (компактное) */
        .modal {
            display: none;
            position: fixed;
            z-index: 1001;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0,0,0,0.7);
            backdrop-filter: blur(5px);
        }
        .modal-content {
            background-color: #2d2f3e;
            margin: 8% auto;
            padding: 25px 30px;
            border-radius: 20px;
            width: 90%;
            max-width: 450px;
            color: white;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            animation: fadeIn 0.3s;
        }
        body.light-theme .modal-content { background-color: #fff; color: #222; }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            margin-top: -10px;
        }
        .close:hover { color: white; }
        .settings-group {
            margin-bottom: 20px;
        }
        .settings-group label {
            display: block;
            font-weight: bold;
            margin-bottom: 8px;
            font-size: 16px;
        }
        .settings-group input {
            width: 100%;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid #3c3f54;
        }
        .support-block {
            background: #252634;
            border-radius: 12px;
            padding: 15px;
            margin-top: 20px;
            text-align: center;
        }
        .support-block h4 {
            margin: 0 0 10px 0;
            color: #ffd966;
        }
        .support-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 10px;
        }
        .support-links a {
            color: #66bb6a;
            text-decoration: none;
            font-weight: bold;
        }
        .support-links a:hover { text-decoration: underline; }
        .theme-switch {
            display: flex;
            gap: 15px;
            margin-top: 5px;
        }
        .theme-switch button {
            flex: 1;
            background: #3c3f54;
        }
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Владелец: Timergalin Danil | Учебный проект</div>
<div class="container">
    <div class="settings-top">
        <button id="settingsBtn" class="settings-btn" title="Настройки">⚙️</button>
    </div>
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="quote">✨ «Читайте больше, живите ярче!» ✨</div>

    <div class="controls">
        <div class="control-group">
            <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" value="" placeholder="введите число"></div>
            <div class="form-group"><label>🎭 Жанр:</label>
            <select id="category">
                <option value="https://book24.ru/knigi-bestsellery/">Бестселлеры</option>
                <option value="https://book24.ru/knigi-novinki/">Новинки</option>
                <option value="https://book24.ru/knigi-skoro-v-prodazhe/">Скоро в продаже</option>
                <option value="https://book24.ru/knigi/klassicheskaya-literatura/">Классика</option>
                <option value="https://book24.ru/knigi/detektivy/">Детективы</option>
                <option value="https://book24.ru/knigi/fentezi/">Фэнтези</option>
                <option value="https://book24.ru/knigi/romany/">Романы</option>
                <option value="https://book24.ru/knigi/fantastika/">Фантастика</option>
                <option value="https://book24.ru/knigi/psikhologiya/">Психология</option>
                <option value="https://book24.ru/knigi/biznes-literatura/">Бизнес-литература</option>
                <option value="https://book24.ru/knigi/detskaya-literatura/">Детские книги</option>
                <option value="https://book24.ru/knigi/uchebnaya-literatura/">Учебники</option>
            </select></div>
            <div>
                <button id="startBtn">▶ СТАРТ</button>
                <button id="stopBtn" disabled>⏹️ СТОП</button>
                <button id="saveBtn" disabled>💾 СОХРАНИТЬ CSV</button>
                <button id="aboutBtn" class="info-btn">ℹ️ О программе</button>
                <button id="siteBtn" class="info-btn">🌐 Официальный сайт</button>
            </div>
        </div>
    </div>

    <div class="tabs">
        <button id="tabParsingBtn" class="tab-btn active">📡 Парсинг</button>
        <button id="tabResultsBtn" class="tab-btn">📊 Результаты</button>
        <button id="tabStatsBtn" class="tab-btn">📈 Статистика</button>
    </div>

    <!-- Вкладка Парсинг -->
    <div id="parsingTab" class="tab-content active">
        <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
        <div class="status info" id="statusDiv">Готов к работе</div>
        <div class="log" id="logDiv">📋 Лог парсинга:\n</div>
    </div>

    <!-- Вкладка Результаты (таблица) -->
    <div id="resultsTab" class="tab-content">
        <div class="table-wrapper">
            <table id="resultsTable">
                <thead>
                    <th data-sort="number">№</th>
                    <th data-sort="string">Название</th>
                    <th data-sort="string">Автор</th>
                    <th data-sort="number">Цена</th>
                    <th data-sort="string">Ссылка</th>
                </thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button id="exportCsvBtn" disabled>💾 Экспорт в CSV</button>
        </div>
    </div>

    <!-- Вкладка Статистика -->
    <div id="statsTab" class="tab-content">
        <div class="stats-grid">
            <div class="stats-card"><div class="label">📚 Всего книг</div><div class="value" id="statCount">0</div></div>
            <div class="stats-card"><div class="label">💰 Средняя цена</div><div class="value" id="statAvg">0 ₽</div></div>
            <div class="stats-card"><div class="label">⬇️ Мин. цена</div><div class="value" id="statMin">0 ₽</div></div>
            <div class="stats-card"><div class="label">⬆️ Макс. цена</div><div class="value" id="statMax">0 ₽</div></div>
            <div class="stats-card"><div class="label">🎭 Жанр</div><div class="value" id="statGenre">—</div></div>
            <div class="stats-card"><div class="label">⏱️ Время</div><div class="value" id="statTime">0 сек</div></div>
        </div>
    </div>
</div>

<!-- Модальное окно "О программе" -->
<div id="aboutModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeAbout">&times;</span>
        <h2>📖 О программе</h2>
        <p><strong>Версия:</strong> 4.0 (веб-версия)</p>
        <p><strong>Автор:</strong> Тимергалин Данил</p>
        <p><strong>Описание:</strong> Программа собирает данные о книгах с сайта book24.ru.</p>
        <p><strong>Технологии:</strong> Python, Flask, Selenium, Chrome.</p>
        <p><strong>Цель:</strong> Учебный проект.</p>
    </div>
</div>

<!-- Модальное окно Настройки (включает техподдержку) -->
<div id="settingsModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeSettings">&times;</span>
        <h2>⚙️ Настройки</h2>
        <div class="settings-group">
            <label>📖 Количество книг по умолчанию:</label>
            <input type="number" id="defaultBookCount" placeholder="например, 300">
        </div>
        <div class="settings-group">
            <label>🎨 Тема оформления:</label>
            <div class="theme-switch">
                <button id="themeLightBtn" class="info-btn">Светлая</button>
                <button id="themeDarkBtn" class="info-btn">Тёмная</button>
            </div>
        </div>
        <div class="support-block">
            <h4>🛠️ Техническая поддержка</h4>
            <p>📱 Telegram: <a href="https://t.me/timergalin" target="_blank">@timergalin</a></p>
            <p>💻 GitHub: <a href="https://github.com/timergalin" target="_blank">github.com/timergalin</a></p>
            <p><small>Обращайтесь, поможем!</small></p>
        </div>
        <button id="saveSettingsBtn" style="background:#4caf50; width:100%; margin-top:15px;">Сохранить настройки</button>
    </div>
</div>

<script>
    let currentBooks = [];
    let updateInterval = null;
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const saveBtn = document.getElementById('saveBtn');
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const progressFill = document.getElementById('progressFill');
    const statusDiv = document.getElementById('statusDiv');
    const logDiv = document.getElementById('logDiv');
    const aboutBtn = document.getElementById('aboutBtn');
    const siteBtn = document.getElementById('siteBtn');
    const settingsBtn = document.getElementById('settingsBtn');
    const aboutModal = document.getElementById('aboutModal');
    const settingsModal = document.getElementById('settingsModal');
    const closeAbout = document.getElementById('closeAbout');
    const closeSettings = document.getElementById('closeSettings');
    const tabParsingBtn = document.getElementById('tabParsingBtn');
    const tabResultsBtn = document.getElementById('tabResultsBtn');
    const tabStatsBtn = document.getElementById('tabStatsBtn');
    const parsingTab = document.getElementById('parsingTab');
    const resultsTab = document.getElementById('resultsTab');
    const statsTab = document.getElementById('statsTab');
    const bookCountInput = document.getElementById('bookCount');
    const defaultBookCountInput = document.getElementById('defaultBookCount');
    const themeLightBtn = document.getElementById('themeLightBtn');
    const themeDarkBtn = document.getElementById('themeDarkBtn');
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');

    const statCount = document.getElementById('statCount');
    const statAvg = document.getElementById('statAvg');
    const statMin = document.getElementById('statMin');
    const statMax = document.getElementById('statMax');
    const statGenre = document.getElementById('statGenre');
    const statTime = document.getElementById('statTime');

    function showToast(message, isError = false) {
        let toast = document.createElement('div');
        toast.className = 'toast';
        toast.style.background = isError ? '#f44336' : '#4caf50';
        toast.innerText = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => { toast.remove(); }, 300);
        }, 2500);
    }

    function addLog(msg) {
        let p = document.createElement('div');
        p.className = 'log-message';
        p.textContent = msg;
        logDiv.appendChild(p);
        logDiv.scrollTop = logDiv.scrollHeight;
    }

    function setActiveTab(tab) {
        tabParsingBtn.classList.remove('active');
        tabResultsBtn.classList.remove('active');
        tabStatsBtn.classList.remove('active');
        parsingTab.classList.remove('active');
        resultsTab.classList.remove('active');
        statsTab.classList.remove('active');
        if (tab === 'parsing') {
            tabParsingBtn.classList.add('active');
            parsingTab.classList.add('active');
        } else if (tab === 'results') {
            tabResultsBtn.classList.add('active');
            resultsTab.classList.add('active');
            updateTableDisplay(currentBooks);
        } else if (tab === 'stats') {
            tabStatsBtn.classList.add('active');
            statsTab.classList.add('active');
            fetchAndUpdateStats();
        }
    }
    tabParsingBtn.onclick = () => setActiveTab('parsing');
    tabResultsBtn.onclick = () => setActiveTab('results');
    tabStatsBtn.onclick = () => setActiveTab('stats');

    function fetchAndUpdateStats() {
        fetch('/status').then(res => res.json()).then(data => {
            if (data.stats) {
                let s = data.stats;
                statCount.innerText = s.count;
                statAvg.innerText = s.avg_price + ' ₽';
                statMin.innerText = s.min_price + ' ₽';
                statMax.innerText = s.max_price + ' ₽';
                statGenre.innerText = s.category;
                statTime.innerText = s.time + ' сек';
            } else {
                statCount.innerText = '0';
                statAvg.innerText = '0 ₽';
                statMin.innerText = '0 ₽';
                statMax.innerText = '0 ₽';
                statGenre.innerText = '—';
                statTime.innerText = '0 сек';
            }
        });
    }

    aboutBtn.onclick = () => { aboutModal.style.display = 'block'; };
    siteBtn.onclick = () => { window.open('https://book24.ru', '_blank'); };
    settingsBtn.onclick = () => { settingsModal.style.display = 'block'; };
    closeAbout.onclick = () => { aboutModal.style.display = 'none'; };
    closeSettings.onclick = () => { settingsModal.style.display = 'none'; };
    window.onclick = (event) => {
        if (event.target == aboutModal) aboutModal.style.display = 'none';
        if (event.target == settingsModal) settingsModal.style.display = 'none';
    };

    function updateTableDisplay(books) {
        const tbody = document.getElementById('tableBody');
        tbody.innerHTML = '';
        books.forEach((book, idx) => {
            let row = tbody.insertRow();
            row.insertCell(0).innerText = idx+1;
            row.insertCell(1).innerText = book['Название'] || '';
            row.insertCell(2).innerText = book['Автор'] || '';
            let price = book['Цена (строка)'] || (book['Цена (число)'] ? book['Цена (число)'] + ' ₽' : '—');
            row.insertCell(3).innerText = price;
            let link = book['Ссылка'] || '';
            let linkCell = row.insertCell(4);
            if(link) {
                let a = document.createElement('a');
                a.href = link;
                a.target = '_blank';
                a.innerText = 'Открыть';
                linkCell.appendChild(a);
            } else {
                linkCell.innerText = '—';
            }
        });
        const headers = document.querySelectorAll('#resultsTable th');
        headers.forEach(th => {
            th.onclick = () => {
                const colIndex = th.cellIndex;
                const isNumber = th.getAttribute('data-sort') === 'number';
                const rows = Array.from(tbody.rows);
                rows.sort((a, b) => {
                    let aVal = a.cells[colIndex].innerText;
                    let bVal = b.cells[colIndex].innerText;
                    if (isNumber) {
                        aVal = parseFloat(aVal.replace(/[^\d.-]/g, '')) || 0;
                        bVal = parseFloat(bVal.replace(/[^\d.-]/g, '')) || 0;
                    }
                    if (aVal < bVal) return -1;
                    if (aVal > bVal) return 1;
                    return 0;
                });
                rows.forEach(row => tbody.appendChild(row));
            };
        });
    }

    function checkStatus() {
        fetch('/status').then(res => res.json()).then(data => {
            if(data.running){
                if(data.progress_current && data.progress_total){
                    let percent = Math.round((data.progress_current / data.progress_total) * 100);
                    progressFill.style.width = percent+'%';
                    progressFill.innerText = percent+'%';
                }
                if(data.books && data.books.length !== currentBooks.length){
                    currentBooks = data.books;
                    if(document.getElementById('resultsTab').classList.contains('active')) {
                        updateTableDisplay(currentBooks);
                    }
                    document.querySelector('.table-wrapper').classList.add('flash-bg');
                    setTimeout(() => document.querySelector('.table-wrapper').classList.remove('flash-bg'), 300);
                }
                statusDiv.innerHTML = '⏳ Сбор данных...';
                statusDiv.className = 'status info';
                startBtn.disabled = true;
                stopBtn.disabled = false;
                saveBtn.disabled = true;
                exportCsvBtn.disabled = true;
            } else {
                if(updateInterval) clearInterval(updateInterval);
                updateInterval = null;
                startBtn.disabled = false;
                stopBtn.disabled = true;
                if(data.books && data.books.length > 0){
                    currentBooks = data.books;
                    if(document.getElementById('resultsTab').classList.contains('active')) {
                        updateTableDisplay(currentBooks);
                    }
                    saveBtn.disabled = false;
                    exportCsvBtn.disabled = false;
                    statusDiv.innerHTML = data.message || 'Завершено';
                    statusDiv.className = 'status success';
                } else {
                    statusDiv.innerHTML = data.message || 'Нет результатов';
                    statusDiv.className = 'status error';
                    saveBtn.disabled = true;
                    exportCsvBtn.disabled = true;
                }
                if(data.stats && document.getElementById('statsTab').classList.contains('active')) {
                    let s = data.stats;
                    statCount.innerText = s.count;
                    statAvg.innerText = s.avg_price + ' ₽';
                    statMin.innerText = s.min_price + ' ₽';
                    statMax.innerText = s.max_price + ' ₽';
                    statGenre.innerText = s.category;
                    statTime.innerText = s.time + ' сек';
                }
                addLog(data.message || 'Готово');
                startBtn.classList.remove('animate-pulse');
            }
        });
    }

    startBtn.onclick = () => {
        let maxBooks = parseInt(bookCountInput.value);
        if (isNaN(maxBooks) || maxBooks <= 0) {
            showToast('❌ Введите корректное количество книг (целое число > 0)', true);
            return;
        }
        let categoryUrl = document.getElementById('category').value;
        fetch('/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({max_books:maxBooks, category_url:categoryUrl}) })
        .then(res => res.json()).then(data => {
            if(data.status === 'started'){
                addLog('🚀 Парсинг запущен...');
                showToast('🚀 Парсинг запущен');
                progressFill.style.width = '0%';
                progressFill.innerText = '0%';
                currentBooks = [];
                if(document.getElementById('resultsTab').classList.contains('active')) updateTableDisplay([]);
                statusDiv.innerHTML = 'Запуск...';
                statusDiv.className = 'status info';
                if(updateInterval) clearInterval(updateInterval);
                updateInterval = setInterval(checkStatus, 1000);
                startBtn.classList.add('animate-pulse');
            } else {
                showToast('❌ Ошибка: '+data.message, true);
            }
        });
    };
    stopBtn.onclick = () => {
        fetch('/stop', { method:'POST' }).then(() => {
            addLog('⏸️ Остановка...');
            showToast('⏸️ Парсинг остановлен');
            stopBtn.disabled = true;
            startBtn.classList.remove('animate-pulse');
        });
    };
    saveBtn.onclick = () => { window.location.href = '/download-csv'; };
    exportCsvBtn.onclick = () => { window.location.href = '/download-csv'; };

    function loadSettings() {
        let defaultCount = localStorage.getItem('defaultBookCount');
        if (defaultCount !== null && defaultCount !== '') {
            defaultBookCountInput.value = defaultCount;
            bookCountInput.value = defaultCount;
        } else {
            defaultBookCountInput.value = '';
            bookCountInput.value = '';
        }
        let theme = localStorage.getItem('theme');
        if (theme === 'light') {
            document.body.classList.add('light-theme');
        } else {
            document.body.classList.remove('light-theme');
        }
    }
    function saveSettings() {
        let defCount = defaultBookCountInput.value.trim();
        if (defCount === '') {
            localStorage.removeItem('defaultBookCount');
            bookCountInput.value = '';
        } else {
            let num = parseInt(defCount);
            if (!isNaN(num) && num > 0) {
                localStorage.setItem('defaultBookCount', num);
                bookCountInput.value = num;
            } else {
                showToast('Введите корректное положительное число', true);
                return;
            }
        }
        localStorage.setItem('theme', document.body.classList.contains('light-theme') ? 'light' : 'dark');
        settingsModal.style.display = 'none';
        showToast('✅ Настройки сохранены');
    }
    themeLightBtn.onclick = () => {
        document.body.classList.add('light-theme');
        localStorage.setItem('theme', 'light');
    };
    themeDarkBtn.onclick = () => {
        document.body.classList.remove('light-theme');
        localStorage.setItem('theme', 'dark');
    };
    saveSettingsBtn.onclick = saveSettings;

    loadSettings();
</script>
</body>
</html>
"""

# ---------- Маршруты Flask ----------
@app.route('/')
def index():
    return render_template_string(MAIN_TEMPLATE)

@app.route('/start', methods=['POST'])
def start():
    if shared_state['running']:
        return jsonify({'status': 'error', 'message': 'Парсинг уже запущен'})
    data = request.get_json()
    max_books = data.get('max_books', 500)
    category_url = data.get('category_url')
    if not category_url:
        return jsonify({'status': 'error', 'message': 'Не указана категория'})
    thread = threading.Thread(target=run_parser_task, args=(max_books, category_url))
    thread.start()
    return jsonify({'status': 'started'})

@app.route('/stop', methods=['POST'])
def stop():
    shared_state['stop_flag'] = True
    return jsonify({'status': 'stopped'})

@app.route('/status')
def status():
    return jsonify({
        'running': shared_state['running'],
        'books': shared_state['books'],
        'progress_current': shared_state['progress_current'],
        'progress_total': shared_state['progress_total'],
        'stats': shared_state['stats'],
        'message': shared_state['message']
    })

@app.route('/download-csv')
def download_csv():
    books = shared_state.get('books', [])
    if not books:
        return "Нет данных для сохранения", 404
    output = io.StringIO()
    fieldnames = ['Название', 'Автор', 'Цена (число)', 'Цена (строка)', 'Ссылка']
    writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=';')
    writer.writeheader()
    writer.writerows(books)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'books_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
