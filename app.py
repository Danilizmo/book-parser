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

# ---------- HTML-шаблон главной страницы ----------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru | Timergalin Danil</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; position: relative; }
        .container { max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        h1 { color: #ffd966; text-align: center; margin-top: 0; }
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
        .animate-pulse { animation: pulse 1.2s infinite; }
        .stats, .progress-bar, .status, .log { animation: fadeIn 0.4s ease-out; }
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
        .controls { display: flex; gap: 20px; flex-wrap: wrap; background: #252634; padding: 15px; border-radius: 12px; margin-bottom: 20px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; }
        button { background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; transition: all 0.2s ease; margin: 5px; }
        button:hover { transform: translateY(-2px); filter: brightness(1.05); }
        #stopBtn { background: #f44336; }
        #saveBtn { background: #2196f3; }
        .info-btn { background: #9c27b0; }
        button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: linear-gradient(90deg, #4caf50, #8bc34a); text-align: center; line-height: 25px; color: white; font-weight: bold; font-size: 13px; transition: width 0.2s linear; }
        .stats { background: #252634; padding: 12px; border-radius: 10px; margin: 15px 0; border-left: 5px solid #ffd966; transition: 0.3s; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; font-weight: bold; transition: 0.2s; }
        .status.info { background: #0c5460; color: #d1ecf1; }
        .status.success { background: #155724; color: #d4edda; }
        .status.error { background: #721c24; color: #f8d7da; }
        .log { background: #1e1f2c; color: #0f0; font-family: monospace; padding: 10px; height: 200px; overflow-y: auto; margin-top: 20px; border-radius: 8px; font-size: 12px; }
        .table-wrapper { overflow-x: auto; max-height: 400px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; background: #2d2f3e; }
        th, td { border: 1px solid #3c3f54; padding: 10px; text-align: left; }
        th { background: #3c3f54; cursor: pointer; color: #ffd966; position: sticky; top: 0; }
        th:hover { background: #4a4d6b; }
        td a { color: #66bb6a; text-decoration: none; }
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
            margin: 10% auto;
            padding: 20px;
            border-radius: 16px;
            width: 80%;
            max-width: 500px;
            color: white;
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
            animation: fadeIn 0.3s;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover { color: white; }
        .quote {
            text-align: center;
            font-style: italic;
            margin: 20px 0;
            padding: 10px;
            background: #252634;
            border-radius: 8px;
            color: #ffd966;
        }
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Владелец: Timergalin Danil | Учебный проект</div>
<div class="container">
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="quote">«Книги — это мосты между мирами» ✨</div>
    <div class="controls">
        <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" value="500" min="1" max="2000"></div>
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
            <button id="resultsBtn" class="info-btn">📋 Открыть полную таблицу</button>
            <button id="aboutBtn" class="info-btn">ℹ️ О программе</button>
            <button id="supportBtn" class="info-btn">🛠️ Техподдержка</button>
        </div>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
    <div class="stats" id="statsDiv">📊 Статистика: пока нет данных</div>
    <div class="status info" id="statusDiv">Готов к работе</div>
    <div class="table-wrapper"><table id="resultsTable"><thead><tr><th>№</th><th>Название</th><th>Автор</th><th>Цена</th><th>Ссылка</th></tr></thead><tbody id="tableBody"></tbody></table></div>
    <div class="log" id="logDiv">📋 Лог парсинга:\n</div>
</div>

<!-- Модальное окно "О программе" -->
<div id="aboutModal" class="modal">
    <div class="modal-content">
        <span class="close" id="closeAbout">&times;</span>
        <h2>📖 О программе</h2>
        <p><strong>Версия:</strong> 3.0 (веб-версия)</p>
        <p><strong>Автор:</strong> Тимергалин Данил</p>
        <p><strong>Описание:</strong> Программа собирает данные о книгах с сайта book24.ru. Выберите жанр и количество книг, нажмите "Старт" — данные появятся в таблице. Можно сохранить результат в CSV.</p>
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
        <p>📧 Email: <a href="mailto:timergalin.d@example.com" style="color:#4caf50">timergalin.d@example.com</a></p>
        <p>📱 Telegram: <a href="https://t.me/timergalin" target="_blank" style="color:#4caf50">@timergalin</a></p>
        <p>💬 GitHub: <a href="https://github.com/timergalin" target="_blank" style="color:#4caf50">github.com/timergalin</a></p>
        <p><small>Обычно отвечаем в течение 24 часов.</small></p>
    </div>
</div>

<script>
    let currentBooks = [];
    let updateInterval = null;
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const saveBtn = document.getElementById('saveBtn');
    const resultsBtn = document.getElementById('resultsBtn');
    const aboutBtn = document.getElementById('aboutBtn');
    const supportBtn = document.getElementById('supportBtn');
    const progressFill = document.getElementById('progressFill');
    const statsDiv = document.getElementById('statsDiv');
    const statusDiv = document.getElementById('statusDiv');
    const tableBody = document.getElementById('tableBody');
    const logDiv = document.getElementById('logDiv');

    // Модальные окна
    const aboutModal = document.getElementById('aboutModal');
    const supportModal = document.getElementById('supportModal');
    const closeAbout = document.getElementById('closeAbout');
    const closeSupport = document.getElementById('closeSupport');

    aboutBtn.onclick = () => { aboutModal.style.display = 'block'; };
    supportBtn.onclick = () => { supportModal.style.display = 'block'; };
    closeAbout.onclick = () => { aboutModal.style.display = 'none'; };
    closeSupport.onclick = () => { supportModal.style.display = 'none'; };
    window.onclick = (event) => {
        if (event.target == aboutModal) aboutModal.style.display = 'none';
        if (event.target == supportModal) supportModal.style.display = 'none';
    };

    // Открыть полную таблицу в новом окне
    resultsBtn.onclick = () => {
        window.open('/results', '_blank');
    };

    function addLog(msg) {
        let p = document.createElement('div');
        p.textContent = msg;
        logDiv.appendChild(p);
        logDiv.scrollTop = logDiv.scrollHeight;
    }
    function updateTable(books) {
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
        document.querySelectorAll('th').forEach(th => {
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
    function updateStats(stats) {
        if(stats) statsDiv.innerHTML = `📊 Статистика: ${stats.count} книг | Средняя цена: ${stats.avg_price} ₽ | Мин: ${stats.min_price} ₽ | Макс: ${stats.max_price} ₽ | Жанр: ${stats.category} | Время: ${stats.time} сек`;
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
                    updateTable(data.books);
                    document.querySelector('.table-wrapper').classList.add('flash-bg');
                    setTimeout(() => document.querySelector('.table-wrapper').classList.remove('flash-bg'), 300);
                }
                statusDiv.className = 'status info';
                statusDiv.innerText = '⏳ Сбор данных... <span class="loader"></span>';
                startBtn.disabled = true;
                stopBtn.disabled = false;
                saveBtn.disabled = true;
            } else {
                if(updateInterval) clearInterval(updateInterval);
                updateInterval = null;
                startBtn.disabled = false;
                stopBtn.disabled = true;
                if(data.books && data.books.length > 0){
                    currentBooks = data.books;
                    updateTable(data.books);
                    saveBtn.disabled = false;
                    statusDiv.className = 'status success';
                    statusDiv.innerText = data.message || 'Завершено';
                } else {
                    statusDiv.className = 'status error';
                    statusDiv.innerText = data.message || 'Нет результатов';
                }
                if(data.stats) updateStats(data.stats);
                addLog(data.message || 'Готово');
                startBtn.classList.remove('animate-pulse');
            }
        });
    }

    startBtn.onclick = () => {
        let maxBooks = parseInt(document.getElementById('bookCount').value);
        let categoryUrl = document.getElementById('category').value;
        fetch('/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({max_books:maxBooks, category_url:categoryUrl}) })
        .then(res => res.json()).then(data => {
            if(data.status === 'started'){
                addLog('🚀 Парсинг запущен...');
                progressFill.style.width = '0%';
                progressFill.innerText = '0%';
                tableBody.innerHTML = '';
                currentBooks = [];
                statsDiv.innerHTML = '📊 Статистика: сбор данных...';
                statusDiv.className = 'status info';
                statusDiv.innerText = 'Запуск...';
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
</script>
</body>
</html>
"""

# ---------- Маршрут для отдельной страницы с полной таблицей ----------
@app.route('/results')
def results():
    books = shared_state.get('books', [])
    stats = shared_state.get('stats', {})
    # Генерируем HTML для отдельной страницы
    rows = ""
    for idx, book in enumerate(books, 1):
        rows += f"""
        <tr>
            <td>{idx}</td>
            <td>{book.get('Название', '')}</td>
            <td>{book.get('Автор', '')}</td>
            <td>{book.get('Цена (строка)', '')}</td>
            <td><a href="{book.get('Ссылка', '#')}" target="_blank">Открыть</a></td>
        </tr>
        """
    stats_html = ""
    if stats:
        stats_html = f"""
        <div style="background:#252634; padding:15px; border-radius:10px; margin:20px 0; border-left:5px solid #ffd966;">
            📊 Статистика: {stats.get('count',0)} книг | Средняя цена: {stats.get('avg_price',0)} ₽ |
            Мин: {stats.get('min_price',0)} ₽ | Макс: {stats.get('max_price',0)} ₽ | Жанр: {stats.get('category','')} | Время: {stats.get('time',0)} сек
        </div>
        """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Полная таблица результатов - Парсер book24.ru</title>
        <style>
            body {{ background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 20px; color: #eee; }}
            h1 {{ color: #ffd966; text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; background: #2d2f3e; }}
            th, td {{ border: 1px solid #3c3f54; padding: 10px; text-align: left; }}
            th {{ background: #3c3f54; color: #ffd966; position: sticky; top: 0; }}
            a {{ color: #66bb6a; }}
            .container {{ max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; }}
            button {{ background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Полная таблица собранных книг</h1>
            {stats_html}
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr><th>№</th><th>Название</th><th>Автор</th><th>Цена</th><th>Ссылка</th></tr>
                    </thead>
                    <tbody>
                        {rows if rows else "<tr><td colspan='5'>Нет данных. Запустите парсинг на главной странице.</td></tr>"}
                    </tbody>
                </table>
            </div>
            <button onclick="window.close()">Закрыть окно</button>
        </div>
    </body>
    </html>
    """
    return html

# ---------- Маршруты API ----------
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

# ---------- Точка входа ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
