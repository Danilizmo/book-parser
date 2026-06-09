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

            # ----- ИСПРАВЛЕННЫЙ ПОИСК ЦЕНЫ -----
            price_raw = ""
            try:
                # Пробуем стандартный селектор цены
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

# ---------- HTML-шаблон (рабочий, с тёмной темой, без авто-подстановки количества) ----------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru | Timergalin Danil</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; transition: background 0.3s; }
        body.light-theme { background: #f0f2f5; color: #222; }
        body.light-theme .container { background: #fff; }
        body.light-theme .controls, body.light-theme .stats-card, body.light-theme .quote, body.light-theme .log { background: #e9ecef; color: #222; }
        body.light-theme .progress-bar { background: #ddd; }
        body.light-theme th { background: #dee2e6; color: #000; }
        body.light-theme td, body.light-theme th { border-color: #ccc; }
        body.light-theme .log { background: #fff; border: 1px solid #ccc; }
        .container { max-width: 1400px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); position: relative; }
        h1 { color: #ffd966; text-align: center; margin-top: 0; }
        .settings-top { position: absolute; top: 20px; right: 20px; }
        .settings-top button { background: #607d8b; border-radius: 50%; width: 42px; height: 42px; font-size: 20px; border: none; color: white; cursor: pointer; display: flex; align-items: center; justify-content: center; }
        @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
        .toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: #4caf50; color: white; padding: 12px 24px; border-radius: 40px; font-weight: bold; z-index: 2000; animation: slideInRight 0.3s ease forwards; }
        .toast.fade-out { animation: fadeOut 0.3s ease forwards; }
        .owner-sign { position: fixed; bottom: 10px; right: 15px; background: rgba(0,0,0,0.6); padding: 4px 12px; border-radius: 20px; font-size: 12px; color: #ffd966; font-family: monospace; backdrop-filter: blur(4px); z-index: 1000; pointer-events: none; }
        .controls { display: flex; gap: 20px; flex-wrap: wrap; background: #252634; padding: 15px; border-radius: 12px; margin-bottom: 20px; align-items: flex-end; justify-content: space-between; }
        .control-group { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        body.light-theme label { color: #0056b3; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; font-size: 14px; }
        body.light-theme input, body.light-theme select { background: #fff; color: #000; border: 1px solid #ccc; }
        button { background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; transition: 0.2s; margin: 5px; }
        button:hover { transform: scale(1.02); filter: brightness(1.05); }
        #stopBtn { background: #f44336; }
        #saveBtn { background: #2196f3; }
        .info-btn { background: #9c27b0; }
        .tab-btn { background: #3c3f54; }
        .tab-btn.active { background: #4caf50; }
        button:disabled { opacity: 0.6; cursor: not-allowed; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: linear-gradient(90deg, #4caf50, #8bc34a); text-align: center; line-height: 25px; color: white; font-weight: bold; font-size: 13px; transition: width 0.2s; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; font-weight: bold; }
        .status.info { background: #0c5460; color: #d1ecf1; }
        .status.success { background: #155724; color: #d4edda; }
        .status.error { background: #721c24; color: #f8d7da; }
        .log { background: #1e1f2c; color: #0f0; font-family: monospace; padding: 10px; height: 250px; overflow-y: auto; margin-top: 20px; border-radius: 8px; font-size: 12px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 1px solid #3c3f54; padding-bottom: 10px; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .table-wrapper { overflow-x: auto; max-height: 500px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; background: #2d2f3e; }
        th, td { border: 1px solid #3c3f54; padding: 10px; text-align: left; }
        th { background: #3c3f54; cursor: pointer; color: #ffd966; position: sticky; top: 0; }
        th:hover { background: #4a4d6b; }
        td a { color: #66bb6a; text-decoration: none; }
        .quote { text-align: center; font-style: italic; margin: 20px 0; padding: 10px; background: #252634; border-radius: 8px; color: #ffd966; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
        .stats-card { background: #252634; border-radius: 12px; padding: 15px; text-align: center; border-left: 4px solid #ffd966; }
        .stats-card .value { font-size: 28px; font-weight: bold; color: #ffd966; margin: 10px 0; }
        .stats-card .label { font-size: 14px; text-transform: uppercase; color: #aaa; }
        .modal { display: none; position: fixed; z-index: 1001; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); backdrop-filter: blur(5px); }
        .modal-content { background: #2d2f3e; margin: 10% auto; padding: 20px; border-radius: 16px; width: 90%; max-width: 450px; color: white; }
        body.light-theme .modal-content { background: #fff; color: #222; }
        .close { float: right; font-size: 28px; cursor: pointer; color: #aaa; }
        .close:hover { color: white; }
        .settings-group { margin-bottom: 20px; }
        .settings-group label { display: block; margin-bottom: 8px; font-weight: bold; }
        .settings-group input { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #3c3f54; background: #3c3f54; color: white; }
        body.light-theme .settings-group input { background: #fff; color: #000; border: 1px solid #ccc; }
        .theme-switch { display: flex; gap: 15px; }
        .theme-switch button { flex: 1; background: #3c3f54; }
        .red-close-btn { background: #f44336; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; width: 100%; margin-top: 15px; }
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Владелец: Timergalin Danil</div>
<div class="container">
    <div class="settings-top"><button id="settingsBtn">⚙️</button></div>
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="quote">✨ «Читайте больше, живите ярче!» ✨</div>

    <div class="controls">
        <div class="control-group">
            <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" placeholder="введите число"></div>
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

    <div id="parsingTab" class="tab-content active">
        <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
        <div class="status info" id="statusDiv">Готов к работе</div>
        <div class="log" id="logDiv">📋 Лог парсинга:\n</div>
    </div>

    <div id="resultsTab" class="tab-content">
        <div class="table-wrapper">
            <table id="resultsTable">
                <thead><tr><th data-sort="number">№</th><th>Название</th><th>Автор</th><th data-sort="number">Цена</th><th>Ссылка</th></tr></thead>
                <tbody id="tableBody"></tbody>
            </table>
        </div>
        <div style="margin-top:15px; text-align:right;"><button id="exportCsvBtn" disabled>💾 Экспорт в CSV</button></div>
    </div>

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

<div id="aboutModal" class="modal">
    <div class="modal-content"><span class="close" id="closeAbout">&times;</span><h2>📖 О программе</h2><p><strong>Версия:</strong> 4.0</p><p><strong>Автор:</strong> Тимергалин Данил</p><p><strong>Описание:</strong> Парсер книг book24.ru.</p><p><strong>Технологии:</strong> Python, Flask, Selenium.</p><button id="aboutCloseBtn" class="red-close-btn">Закрыть</button></div>
</div>

<div id="settingsModal" class="modal">
    <div class="modal-content"><span class="close" id="closeSettings">&times;</span><h2>⚙️ Настройки</h2>
        <div class="settings-group"><label>📖 Количество книг по умолчанию:</label><input type="number" id="defaultBookCount" placeholder="оставьте пустым"></div>
        <div class="settings-group"><label>🎨 Тема:</label><div class="theme-switch"><button id="themeLightBtn">Светлая</button><button id="themeDarkBtn">Тёмная</button></div></div>
        <button id="openSupportBtn" class="info-btn" style="width:100%; margin-bottom:10px;">🛠️ Техподдержка</button>
        <button id="saveSettingsBtn" style="background:#4caf50; width:100%;">Сохранить</button>
    </div>
</div>

<div id="supportModal" class="modal">
    <div class="modal-content"><span class="close" id="closeSupport">&times;</span><h3>🛠️ Техподдержка</h3>
        <p>📱 Telegram: <a href="https://t.me/timergalin" target="_blank">@timergalin</a></p>
        <p>💻 GitHub: <a href="https://github.com/timergalin" target="_blank">github.com/timergalin</a></p>
        <button id="supportCloseBtn" class="red-close-btn">Закрыть</button>
    </div>
</div>

<script>
    let currentBooks = [], updateInterval = null;
    const startBtn = document.getElementById('startBtn'), stopBtn = document.getElementById('stopBtn'), saveBtn = document.getElementById('saveBtn'), exportCsvBtn = document.getElementById('exportCsvBtn');
    const progressFill = document.getElementById('progressFill'), statusDiv = document.getElementById('statusDiv'), logDiv = document.getElementById('logDiv');
    const aboutBtn = document.getElementById('aboutBtn'), siteBtn = document.getElementById('siteBtn'), settingsBtn = document.getElementById('settingsBtn');
    const aboutModal = document.getElementById('aboutModal'), settingsModal = document.getElementById('settingsModal'), supportModal = document.getElementById('supportModal');
    const closeAbout = document.getElementById('closeAbout'), closeSettings = document.getElementById('closeSettings'), closeSupport = document.getElementById('closeSupport');
    const aboutCloseBtn = document.getElementById('aboutCloseBtn'), supportCloseBtn = document.getElementById('supportCloseBtn'), openSupportBtn = document.getElementById('openSupportBtn');
    const tabParsingBtn = document.getElementById('tabParsingBtn'), tabResultsBtn = document.getElementById('tabResultsBtn'), tabStatsBtn = document.getElementById('tabStatsBtn');
    const parsingTab = document.getElementById('parsingTab'), resultsTab = document.getElementById('resultsTab'), statsTab = document.getElementById('statsTab');
    const bookCountInput = document.getElementById('bookCount'), defaultBookCountInput = document.getElementById('defaultBookCount');
    const themeLightBtn = document.getElementById('themeLightBtn'), themeDarkBtn = document.getElementById('themeDarkBtn'), saveSettingsBtn = document.getElementById('saveSettingsBtn');
    const statCount = document.getElementById('statCount'), statAvg = document.getElementById('statAvg'), statMin = document.getElementById('statMin'), statMax = document.getElementById('statMax'), statGenre = document.getElementById('statGenre'), statTime = document.getElementById('statTime');
    const tableBody = document.getElementById('tableBody');

    function showToast(msg, isErr=false){ let t=document.createElement('div'); t.className='toast'; t.style.background=isErr?'#f44336':'#4caf50'; t.innerText=msg; document.body.appendChild(t); setTimeout(()=>{ t.classList.add('fade-out'); setTimeout(()=>t.remove(),300); },2500); }
    function addLog(msg){ let p=document.createElement('div'); p.textContent=msg; logDiv.appendChild(p); logDiv.scrollTop=logDiv.scrollHeight; }
    function setActiveTab(tab){
        [tabParsingBtn,tabResultsBtn,tabStatsBtn].forEach(btn=>btn.classList.remove('active'));
        [parsingTab,resultsTab,statsTab].forEach(t=>t.classList.remove('active'));
        if(tab==='parsing'){ tabParsingBtn.classList.add('active'); parsingTab.classList.add('active'); }
        else if(tab==='results'){ tabResultsBtn.classList.add('active'); resultsTab.classList.add('active'); updateTableDisplay(currentBooks); }
        else if(tab==='stats'){ tabStatsBtn.classList.add('active'); statsTab.classList.add('active'); fetchStats(); }
    }
    tabParsingBtn.onclick=()=>setActiveTab('parsing');
    tabResultsBtn.onclick=()=>setActiveTab('results');
    tabStatsBtn.onclick=()=>setActiveTab('stats');
    function fetchStats(){ fetch('/status').then(r=>r.json()).then(d=>{ if(d.stats){ let s=d.stats; statCount.innerText=s.count; statAvg.innerText=s.avg_price+' ₽'; statMin.innerText=s.min_price+' ₽'; statMax.innerText=s.max_price+' ₽'; statGenre.innerText=s.category; statTime.innerText=s.time+' сек'; } }); }
    function updateTableDisplay(books){
        tableBody.innerHTML='';
        books.forEach((b,i)=>{ let r=tableBody.insertRow(); r.insertCell(0).innerText=i+1; r.insertCell(1).innerText=b['Название']||''; r.insertCell(2).innerText=b['Автор']||''; let price=b['Цена (строка)']||(b['Цена (число)']?b['Цена (число)']+' ₽':'—'); r.insertCell(3).innerText=price; let l=b['Ссылка']||''; let lc=r.insertCell(4); if(l){ let a=document.createElement('a'); a.href=l; a.target='_blank'; a.innerText='Открыть'; lc.appendChild(a); } else lc.innerText='—'; });
        document.querySelectorAll('#resultsTable th').forEach(th=>{ th.onclick=()=>{ let col=th.cellIndex, isNum=th.getAttribute('data-sort')==='number'; let rows=Array.from(tableBody.rows); rows.sort((a,b)=>{ let av=a.cells[col].innerText, bv=b.cells[col].innerText; if(isNum){ av=parseFloat(av.replace(/[^\d.-]/g,''))||0; bv=parseFloat(bv.replace(/[^\d.-]/g,''))||0; } return av<bv?-1:av>bv?1:0; }); rows.forEach(r=>tableBody.appendChild(r)); }; });
    }
    function checkStatus(){
        fetch('/status').then(r=>r.json()).then(d=>{
            if(d.running){
                if(d.progress_current && d.progress_total){ let p=Math.round(d.progress_current/d.progress_total*100); progressFill.style.width=p+'%'; progressFill.innerText=p+'%'; }
                if(d.books && d.books.length!==currentBooks.length){ currentBooks=d.books; if(resultsTab.classList.contains('active')) updateTableDisplay(currentBooks); }
                statusDiv.innerText='⏳ Сбор данных...'; statusDiv.className='status info';
                startBtn.disabled=true; stopBtn.disabled=false; saveBtn.disabled=true; exportCsvBtn.disabled=true;
            }else{
                if(updateInterval) clearInterval(updateInterval); updateInterval=null;
                startBtn.disabled=false; stopBtn.disabled=true;
                if(d.books && d.books.length>0){ currentBooks=d.books; if(resultsTab.classList.contains('active')) updateTableDisplay(currentBooks); saveBtn.disabled=false; exportCsvBtn.disabled=false; statusDiv.innerText=d.message||'Завершено'; statusDiv.className='status success'; }
                else{ statusDiv.innerText=d.message||'Нет результатов'; statusDiv.className='status error'; saveBtn.disabled=true; exportCsvBtn.disabled=true; }
                if(d.stats && statsTab.classList.contains('active')){ let s=d.stats; statCount.innerText=s.count; statAvg.innerText=s.avg_price+' ₽'; statMin.innerText=s.min_price+' ₽'; statMax.innerText=s.max_price+' ₽'; statGenre.innerText=s.category; statTime.innerText=s.time+' сек'; }
                addLog(d.message||'Готово'); startBtn.classList.remove('animate-pulse');
            }
        });
    }
    startBtn.onclick=()=>{
        let maxBooks=parseInt(bookCountInput.value);
        if(isNaN(maxBooks) || maxBooks<=0){ showToast('❌ Введите количество книг (целое >0)',true); return; }
        fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_books:maxBooks, category_url:document.getElementById('category').value})})
        .then(r=>r.json()).then(d=>{ if(d.status==='started'){ addLog('🚀 Парсинг запущен...'); showToast('Парсинг запущен'); progressFill.style.width='0%'; progressFill.innerText='0%'; currentBooks=[]; if(resultsTab.classList.contains('active')) updateTableDisplay([]); if(updateInterval) clearInterval(updateInterval); updateInterval=setInterval(checkStatus,1000); startBtn.classList.add('animate-pulse'); } else showToast('❌ '+d.message,true); });
    };
    stopBtn.onclick=()=>{ fetch('/stop',{method:'POST'}).then(()=>{ addLog('⏸️ Остановка'); showToast('Парсинг остановлен'); stopBtn.disabled=true; startBtn.classList.remove('animate-pulse'); }); };
    saveBtn.onclick=()=>{ window.location.href='/download-csv'; };
    exportCsvBtn.onclick=()=>{ window.location.href='/download-csv'; };
    aboutBtn.onclick=()=>{ aboutModal.style.display='block'; };
    siteBtn.onclick=()=>{ window.open('https://book24.ru','_blank'); };
    settingsBtn.onclick=()=>{ settingsModal.style.display='block'; };
    openSupportBtn.onclick=()=>{ settingsModal.style.display='none'; supportModal.style.display='block'; };
    closeAbout.onclick=closeAbout2=()=>{ aboutModal.style.display='none'; };
    aboutCloseBtn.onclick=()=>{ aboutModal.style.display='none'; };
    closeSettings.onclick=()=>{ settingsModal.style.display='none'; };
    closeSupport.onclick=()=>{ supportModal.style.display='none'; };
    supportCloseBtn.onclick=()=>{ supportModal.style.display='none'; };
    window.onclick=e=>{ if(e.target==aboutModal) aboutModal.style.display='none'; if(e.target==settingsModal) settingsModal.style.display='none'; if(e.target==supportModal) supportModal.style.display='none'; };
    function loadSettings(){ let def=localStorage.getItem('defaultBookCount'); if(def && def!==''){ defaultBookCountInput.value=def; bookCountInput.value=def; } else{ defaultBookCountInput.value=''; bookCountInput.value=''; } let theme=localStorage.getItem('theme'); if(theme==='light') document.body.classList.add('light-theme'); else document.body.classList.remove('light-theme'); }
    function saveSettings(){ let def=defaultBookCountInput.value.trim(); if(def===''){ localStorage.removeItem('defaultBookCount'); bookCountInput.value=''; }else{ let num=parseInt(def); if(!isNaN(num) && num>0){ localStorage.setItem('defaultBookCount',num); bookCountInput.value=num; }else{ showToast('Введите положительное число',true); return; } } localStorage.setItem('theme',document.body.classList.contains('light-theme')?'light':'dark'); settingsModal.style.display='none'; showToast('Настройки сохранены'); }
    themeLightBtn.onclick=()=>{ document.body.classList.add('light-theme'); localStorage.setItem('theme','light'); };
    themeDarkBtn.onclick=()=>{ document.body.classList.remove('light-theme'); localStorage.setItem('theme','dark'); };
    saveSettingsBtn.onclick=saveSettings;
    loadSettings();
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
    max_books = data.get('max_books')
    if not max_books or max_books <= 0:
        return jsonify({'status': 'error', 'message': 'Введите корректное количество книг'})
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
