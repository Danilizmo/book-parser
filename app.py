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
        # Обновляем статистику в реальном времени (для отображения на вкладке)
        prices = [b['Цена (число)'] for b in all_books if b.get('Цена (число)') is not None]
        avg_price = sum(prices)/len(prices) if prices else 0
        min_price = min(prices) if prices else 0
        max_price_val = max(prices) if prices else 0
        shared_state['stats'] = {
            'count': len(all_books),
            'avg_price': round(avg_price, 2),
            'min_price': min_price,
            'max_price': max_price_val,
            'category': categories.get(category_url, category_url),
            'time': round(time.time() - start_time, 1)
        }
        if len(all_books) >= max_books:
            break
        page += 1
        time.sleep(random.uniform(0.8, 1.5))

    driver.quit()
    elapsed = time.time() - start_time

    # Финальная статистика
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

# ---------- HTML-шаблон с вкладками и настройками ----------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru | Timergalin Danil</title>
    <style id="theme-style">
        /* Тёмная тема (по умолчанию) */
        :root {
            --bg-body: #1e1f2c;
            --bg-container: #2d2f3e;
            --bg-controls: #252634;
            --text-color: #eee;
            --accent: #ffd966;
            --border-color: #3c3f54;
            --button-primary: #4caf50;
            --button-danger: #f44336;
            --button-info: #9c27b0;
            --button-save: #2196f3;
            --log-bg: #1e1f2c;
            --log-text: #0f0;
            --table-header: #3c3f54;
        }
        body.light {
            --bg-body: #f0f2f5;
            --bg-container: #ffffff;
            --bg-controls: #e9ecef;
            --text-color: #212529;
            --accent: #e67e22;
            --border-color: #dee2e6;
            --button-primary: #28a745;
            --button-danger: #dc3545;
            --button-info: #6f42c1;
            --button-save: #007bff;
            --log-bg: #f8f9fa;
            --log-text: #000;
            --table-header: #e9ecef;
        }
        * { box-sizing: border-box; }
        body { background: var(--bg-body); font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: var(--text-color); transition: background 0.2s; }
        .container { max-width: 1400px; margin: auto; background: var(--bg-container); border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        h1 { color: var(--accent); text-align: center; margin-top: 0; }
        /* Анимации */
        @keyframes pulse { 0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76,175,80,0.7); } 70% { transform: scale(1.02); box-shadow: 0 0 0 10px rgba(76,175,80,0); } 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76,175,80,0); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes bgFlash { 0% { background-color: var(--bg-container); } 50% { background-color: var(--border-color); } 100% { background-color: var(--bg-container); } }
        .animate-pulse { animation: pulse 1.2s infinite; }
        .stats, .progress-bar, .status, .log { animation: fadeIn 0.4s ease-out; }
        .flash-bg { animation: bgFlash 0.3s ease; }
        .loader { display: inline-block; width: 20px; height: 20px; border: 2px solid var(--text-color); border-radius: 50%; border-top-color: var(--button-primary); animation: spin 0.6s linear infinite; margin-left: 10px; vertical-align: middle; }
        .owner-sign { position: fixed; bottom: 10px; right: 15px; background: rgba(0,0,0,0.6); padding: 4px 12px; border-radius: 20px; font-size: 12px; color: var(--accent); font-family: monospace; backdrop-filter: blur(4px); z-index: 1000; pointer-events: none; font-weight: bold; }
        .controls { display: flex; gap: 20px; flex-wrap: wrap; background: var(--bg-controls); padding: 15px; border-radius: 12px; margin-bottom: 20px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: var(--accent); }
        input, select { background: var(--border-color); border: none; padding: 8px 12px; border-radius: 8px; color: var(--text-color); }
        button { background: var(--button-primary); border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; transition: all 0.2s ease; margin: 5px; }
        button:hover { transform: scale(1.02) translateY(-1px); filter: brightness(1.05); box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
        #stopBtn { background: var(--button-danger); }
        #saveBtn, #exportCsvBtn { background: var(--button-save); }
        .info-btn { background: var(--button-info); }
        .tab-btn { background: var(--border-color); color: var(--text-color); }
        .tab-btn.active { background: var(--button-primary); box-shadow: 0 0 8px var(--button-primary); }
        button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .progress-bar { width: 100%; background: var(--border-color); border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: linear-gradient(90deg, var(--button-primary), #8bc34a); text-align: center; line-height: 25px; color: white; font-weight: bold; font-size: 13px; transition: width 0.2s linear; }
        .stats { background: var(--bg-controls); padding: 12px; border-radius: 10px; margin: 15px 0; border-left: 5px solid var(--accent); transition: 0.3s; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; font-weight: bold; transition: 0.2s; }
        .status.info { background: #0c5460; color: #d1ecf1; }
        .status.success { background: #155724; color: #d4edda; }
        .status.error { background: #721c24; color: #f8d7da; }
        .log { background: var(--log-bg); color: var(--log-text); font-family: monospace; padding: 10px; height: 250px; overflow-y: auto; margin-top: 20px; border-radius: 8px; font-size: 12px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }
        .tab-btn { background: var(--border-color); border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: 0.2s; }
        .tab-content { display: none; }
        .tab-content.active { display: block; animation: fadeIn 0.3s ease; }
        .settings-icon { background: none; font-size: 24px; padding: 0 10px; margin-left: auto; cursor: pointer; background: transparent; box-shadow: none; }
        .settings-icon:hover { transform: rotate(15deg); background: transparent; }
        .table-wrapper { overflow-x: auto; max-height: 500px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; background: var(--bg-container); }
        th, td { border: 1px solid var(--border-color); padding: 10px; text-align: left; }
        th { background: var(--table-header); cursor: pointer; color: var(--accent); position: sticky; top: 0; }
        th:hover { filter: brightness(0.95); }
        td a { color: var(--button-primary); text-decoration: none; }
        .quote { text-align: center; font-style: italic; margin: 20px 0; padding: 10px; background: var(--bg-controls); border-radius: 8px; color: var(--accent); }
        .modal { display: none; position: fixed; z-index: 1001; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.7); backdrop-filter: blur(5px); }
        .modal-content { background: var(--bg-container); margin: 10% auto; padding: 20px; border-radius: 16px; width: 80%; max-width: 500px; color: var(--text-color); box-shadow: 0 5px 15px rgba(0,0,0,0.3); animation: fadeIn 0.3s; }
        .close { color: #aaa; float: right; font-size: 28px; font-weight: bold; cursor: pointer; }
        .close:hover { color: var(--text-color); }
        .settings-group { margin-bottom: 15px; }
        .settings-group label { display: block; margin-bottom: 5px; }
        .settings-group input, .settings-group select { width: 100%; }
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Владелец: Timergalin Danil | Учебный проект</div>
<div class="container">
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="quote">✨ «Читайте больше, живите ярче!» ✨</div>

    <div class="controls">
        <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" placeholder="Введите число" min="1" step="1"></div>
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
            <button id="supportBtn" class="info-btn">🛠️ Техподдержка</button>
        </div>
    </div>

    <div class="tabs">
        <button id="tabParsingBtn" class="tab-btn active">📡 Парсинг</button>
        <button id="tabResultsBtn" class="tab-btn">📊 Результаты</button>
        <button id="tabStatsBtn" class="tab-btn">📈 Статистика</button>
        <button id="settingsBtn" class="settings-icon" title="Настройки">⚙️</button>
    </div>

    <!-- Вкладка Парсинг -->
    <div id="parsingTab" class="tab-content active">
        <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
        <div class="stats" id="statsDiv">📊 Статистика: пока нет данных</div>
        <div class="status info" id="statusDiv">Готов к работе</div>
        <div class="log" id="logDiv">📋 Лог парсинга:\n</div>
    </div>

    <!-- Вкладка Результаты (таблица) -->
    <div id="resultsTab" class="tab-content">
        <div class="table-wrapper">
            <table id="resultsTable">
                <thead><tr><th>№</th><th>Название</th><th>Автор</th><th>Цена</th><th>Ссылка</th></thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
        <div style="margin-top: 15px; text-align: right;">
            <button id="exportCsvBtn" disabled>💾 Экспорт в CSV</button>
        </div>
    </div>

    <!-- Вкладка Статистика -->
    <div id="statsTab" class="tab-content">
        <div class="stats" id="detailedStatsDiv">📊 Детальная статистика появится после парсинга</div>
    </div>
</div>

<!-- Модальное окно "О программе" -->
<div id="aboutModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeAbout">&times;</span>
        <h2>📖 О программе</h2>
        <p><strong>Версия:</strong> 4.0 (веб-версия)</p>
        <p><strong>Автор:</strong> Тимергалин Данил</p>
        <p><strong>Описание:</strong> Программа собирает данные о книгах с сайта book24.ru. Выберите жанр и количество книг, нажмите "Старт" — данные появятся на вкладке "Результаты". Можно сохранить результат в CSV.</p>
        <p><strong>Технологии:</strong> Python, Flask, Selenium, Chrome, HTML/CSS/JS.</p>
        <p><strong>Цель:</strong> Учебный проект для демонстрации возможностей веб-парсинга.</p>
    </div>
</div>

<!-- Модальное окно "Техподдержка" -->
<div id="supportModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeSupport">&times;</span>
        <h2>🛠️ Техническая поддержка</h2>
        <p>По вопросам работы программы обращайтесь:</p>
        <p>📱 Telegram: <a href="https://t.me/timergalin" target="_blank" style="color:var(--button-primary)">@timergalin</a></p>
        <p>💻 GitHub: <a href="https://github.com/timergalin" target="_blank" style="color:var(--button-primary)">github.com/timergalin</a></p>
        <p><small>Обычно отвечаем в течение 24 часов.</small></p>
    </div>
</div>

<!-- Модальное окно настроек -->
<div id="settingsModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeSettings">&times;</span>
        <h2>⚙️ Настройки</h2>
        <div class="settings-group">
            <label>📖 Количество книг по умолчанию (0 или пусто — поле будет пустым):</label>
            <input type="number" id="defaultBookCount" min="0" step="1" placeholder="Например, 300">
        </div>
        <div class="settings-group">
            <label>🎨 Тема оформления:</label>
            <select id="themeSelect">
                <option value="dark">Тёмная (по умолчанию)</option>
                <option value="light">Светлая</option>
            </select>
        </div>
        <button id="saveSettingsBtn">Сохранить настройки</button>
    </div>
</div>

<script>
    // Элементы
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const saveBtn = document.getElementById('saveBtn');
    const exportCsvBtn = document.getElementById('exportCsvBtn');
    const progressFill = document.getElementById('progressFill');
    const statsDiv = document.getElementById('statsDiv');
    const detailedStatsDiv = document.getElementById('detailedStatsDiv');
    const statusDiv = document.getElementById('statusDiv');
    const tableBody = document.getElementById('tableBody');
    const logDiv = document.getElementById('logDiv');
    const aboutBtn = document.getElementById('aboutBtn');
    const supportBtn = document.getElementById('supportBtn');
    const aboutModal = document.getElementById('aboutModal');
    const supportModal = document.getElementById('supportModal');
    const settingsModal = document.getElementById('settingsModal');
    const closeAbout = document.getElementById('closeAbout');
    const closeSupport = document.getElementById('closeSupport');
    const closeSettings = document.getElementById('closeSettings');
    const settingsBtn = document.getElementById('settingsBtn');
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const defaultBookCountInput = document.getElementById('defaultBookCount');
    const themeSelect = document.getElementById('themeSelect');
    const bookCountInput = document.getElementById('bookCount');

    // Вкладки
    const tabParsingBtn = document.getElementById('tabParsingBtn');
    const tabResultsBtn = document.getElementById('tabResultsBtn');
    const tabStatsBtn = document.getElementById('tabStatsBtn');
    const parsingTab = document.getElementById('parsingTab');
    const resultsTab = document.getElementById('resultsTab');
    const statsTab = document.getElementById('statsTab');

    // Переменные
    let currentBooks = [];
    let updateInterval = null;
    let currentStats = null;

    // Загрузка настроек из localStorage
    function loadSettings() {
        const defaultCount = localStorage.getItem('defaultBookCount');
        if (defaultCount !== null && defaultCount !== '0') {
            defaultBookCountInput.value = defaultCount;
            bookCountInput.value = defaultCount;
        } else {
            defaultBookCountInput.value = '';
            bookCountInput.value = '';
        }
        const theme = localStorage.getItem('theme');
        if (theme === 'light') {
            themeSelect.value = 'light';
            document.body.classList.add('light');
        } else {
            themeSelect.value = 'dark';
            document.body.classList.remove('light');
        }
    }

    function saveSettings() {
        let defaultCount = defaultBookCountInput.value.trim();
        if (defaultCount === '' || parseInt(defaultCount) === 0) {
            localStorage.removeItem('defaultBookCount');
            bookCountInput.value = '';
        } else {
            const num = parseInt(defaultCount);
            localStorage.setItem('defaultBookCount', num);
            bookCountInput.value = num;
        }
        const theme = themeSelect.value;
        localStorage.setItem('theme', theme);
        if (theme === 'light') {
            document.body.classList.add('light');
        } else {
            document.body.classList.remove('light');
        }
        settingsModal.style.display = 'none';
    }

    // Открытие/закрытие модальных окон
    settingsBtn.onclick = () => { settingsModal.style.display = 'block'; };
    closeSettings.onclick = () => { settingsModal.style.display = 'none'; };
    saveSettingsBtn.onclick = saveSettings;

    aboutBtn.onclick = () => { aboutModal.style.display = 'block'; };
    supportBtn.onclick = () => { supportModal.style.display = 'block'; };
    closeAbout.onclick = () => { aboutModal.style.display = 'none'; };
    closeSupport.onclick = () => { supportModal.style.display = 'none'; };
    window.onclick = (event) => {
        if (event.target == aboutModal) aboutModal.style.display = 'none';
        if (event.target == supportModal) supportModal.style.display = 'none';
        if (event.target == settingsModal) settingsModal.style.display = 'none';
    };

    // Переключение вкладок
    tabParsingBtn.onclick = () => {
        setActiveTab('parsing');
    };
    tabResultsBtn.onclick = () => {
        setActiveTab('results');
        updateTableDisplay(currentBooks);
    };
    tabStatsBtn.onclick = () => {
        setActiveTab('stats');
        updateDetailedStats(currentStats);
    };

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
        } else if (tab === 'stats') {
            tabStatsBtn.classList.add('active');
            statsTab.classList.add('active');
        }
    }

    function addLog(msg) {
        let p = document.createElement('div');
        p.textContent = msg;
        logDiv.appendChild(p);
        logDiv.scrollTop = logDiv.scrollHeight;
    }

    function updateTableDisplay(books) {
        tableBody.innerHTML = '';
        books.forEach((book, idx) => {
            let row = tableBody.insertRow();
            row.insertCell(0).innerText = idx+1;
            row.insertCell(1).innerText = book['Название'] || '';
            row.insertCell(2).innerText = book['Автор'] || '';
            row.insertCell(3).innerText = book['Цена (строка)'] || '';
            let link = book['Ссылка'] || '';
            let linkCell = row.insertCell(4);
            if(link) {
                let a = document.createElement('a');
                a.href = link;
                a.target = '_blank';
                a.innerText = 'Открыть';
                linkCell.appendChild(a);
            }
        });
        // Сортировка по заголовкам
        document.querySelectorAll('#resultsTable th').forEach(th => {
            th.onclick = () => {
                let col = th.cellIndex;
                let rows = Array.from(tableBody.rows);
                let isNum = col === 0 || col === 3;
                rows.sort((a,b) => {
                    let aVal = a.cells[col].innerText;
                    let bVal = b.cells[col].innerText;
                    if(isNum) {
                        aVal = parseFloat(aVal.replace(/[^\d.-]/g,'')) || 0;
                        bVal = parseFloat(bVal.replace(/[^\d.-]/g,'')) || 0;
                    }
                    return aVal > bVal ? 1 : -1;
                });
                rows.forEach(row => tableBody.appendChild(row));
            };
        });
    }

    function updateDetailedStats(stats) {
        if (!stats || stats.count === 0) {
            detailedStatsDiv.innerHTML = '📊 Детальная статистика появится после парсинга.';
            return;
        }
        detailedStatsDiv.innerHTML = `
            <div class="stats" style="background: var(--bg-controls);">
                <h3>📈 Подробная статистика</h3>
                <p>📚 Всего книг: <strong>${stats.count}</strong></p>
                <p>💰 Средняя цена: <strong>${stats.avg_price} ₽</strong></p>
                <p>📉 Минимальная цена: <strong>${stats.min_price} ₽</strong></p>
                <p>📈 Максимальная цена: <strong>${stats.max_price} ₽</strong></p>
                <p>🎭 Жанр: <strong>${stats.category}</strong></p>
                <p>⏱️ Время парсинга: <strong>${stats.time} сек</strong></p>
            </div>
        `;
    }

    function updateStats(stats) {
        if(stats) {
            let text = `📊 Статистика: ${stats.count} книг | Средняя цена: ${stats.avg_price} ₽ | Мин: ${stats.min_price} ₽ | Макс: ${stats.max_price} ₽ | Жанр: ${stats.category} | Время: ${stats.time} сек`;
            statsDiv.innerHTML = text;
            currentStats = stats;
            // Если вкладка статистики активна, обновить её
            if (statsTab.classList.contains('active')) {
                updateDetailedStats(stats);
            }
        }
    }

    function checkStatus() {
        fetch('/status').then(res => res.json()).then(data => {
            if(data.running){
                if(data.progress_current && data.progress_total){
                    let percent = Math.round((data.progress_current / data.progress_total) * 100);
                    progressFill.style.width = percent+'%';
                    progressFill.innerText = percent+'%';
                }
                if(data.stats) updateStats(data.stats);
                if(data.books && data.books.length !== currentBooks.length){
                    currentBooks = data.books;
                    if (resultsTab.classList.contains('active')) {
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
                    if (resultsTab.classList.contains('active')) updateTableDisplay(currentBooks);
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
                if(data.stats) updateStats(data.stats);
                addLog(data.message || 'Готово');
                startBtn.classList.remove('animate-pulse');
            }
        });
    }

    startBtn.onclick = () => {
        let maxBooks = parseInt(bookCountInput.value);
        if (isNaN(maxBooks) || maxBooks <= 0) {
            addLog('❌ Ошибка: введите корректное количество книг (целое число больше 0)');
            return;
        }
        let categoryUrl = document.getElementById('category').value;
        fetch('/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({max_books:maxBooks, category_url:categoryUrl}) })
        .then(res => res.json()).then(data => {
            if(data.status === 'started'){
                addLog('🚀 Парсинг запущен...');
                progressFill.style.width = '0%';
                progressFill.innerText = '0%';
                currentBooks = [];
                if (resultsTab.classList.contains('active')) updateTableDisplay([]);
                statsDiv.innerHTML = '📊 Статистика: сбор данных...';
                if (statsTab.classList.contains('active')) updateDetailedStats(null);
                statusDiv.innerHTML = 'Запуск...';
                statusDiv.className = 'status info';
                if(updateInterval) clearInterval(updateInterval);
                updateInterval = setInterval(checkStatus, 1000);
                startBtn.classList.add('animate-pulse');
            } else {
                addLog('❌ Ошибка: '+data.message);
            }
        });
    };
    stopBtn.onclick = () => {
        fetch('/stop', { method:'POST' }).then(() => {
            addLog('⏸️ Остановка...');
            stopBtn.disabled = true;
            startBtn.classList.remove('animate-pulse');
        });
    };
    saveBtn.onclick = () => {
        window.location.href = '/download-csv';
    };
    exportCsvBtn.onclick = () => {
        window.location.href = '/download-csv';
    };

    // Инициализация
    loadSettings();
    // Если поле ввода пустое, парсинг не запустится до ввода числа
</script>
</body>
</html>
"""

# ---------- Маршруты ----------
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
    if max_books <= 0:
        return jsonify({'status': 'error', 'message': 'Количество книг должно быть больше 0'})
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
