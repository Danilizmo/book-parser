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
    "https://book24.ru/knigi/klassicheskaya-literatura/": "Классика",
    "https://book24.ru/knigi/detektivy/": "Детективы",
}

def clean_price(price_str):
    if not price_str:
        return None
    match = re.search(r'(\d[\d\s]*)', price_str)
    if match:
        return int(re.sub(r'\s', '', match.group(1)))
    return None

def parse_page(driver, page_num, log_func):
    books = []
    
    # ДИАГНОСТИКА: сохраняем HTML для отладки
    try:
        page_source = driver.page_source
        with open(f"debug_page_{page_num}.html", "w", encoding="utf-8") as f:
            f.write(page_source[:50000])  # сохраняем первые 50к символов
        log_func(f"🔍 HTML страницы {page_num} сохранён в debug_page_{page_num}.html")
    except Exception as e:
        log_func(f"⚠️ Не удалось сохранить HTML: {e}")
    
    # ПРОВЕРЯЕМ РАЗНЫЕ СЕЛЕКТОРЫ
    selectors_to_try = [
        '.product-card',
        '.catalog-card', 
        '[data-product-id]',
        '.product-item',
        '.book-item',
        '.card',
        'div[class*="product"]',
        'div[class*="book"]'
    ]
    
    items = []
    for selector in selectors_to_try:
        found = driver.find_elements(By.CSS_SELECTOR, selector)
        if found:
            items = found
            log_func(f"✅ Нашёл карточки по селектору: {selector} (найдено {len(found)})")
            break
    
    if not items:
        log_func(f"❌ НЕ НАЙДЕНО карточек ни одним из селекторов!")
        # Показываем первые 10 div'ов для анализа
        all_divs = driver.find_elements(By.CSS_SELECTOR, 'div')
        log_func(f"📊 Всего div на странице: {len(all_divs)}")
        for i, div in enumerate(all_divs[:10]):
            class_name = div.get_attribute('class') or 'нет класса'
            log_func(f"  div {i+1}: class='{class_name[:50]}'")
        return books
    
    log_func(f"📄 Страница {page_num}: найдено {len(items)} карточек (всего)")
    
    for item in items:
        try:
            # Получаем HTML карточки для диагностики
            item_html = item.get_attribute('outerHTML')[:500]
            
            # Поиск названия
            title = ""
            title_selectors = ['a[title]', '.product-title', '.catalog-card__title', 'h3', 'a', '[class*="title"]']
            for sel in title_selectors:
                try:
                    elem = item.find_element(By.CSS_SELECTOR, sel)
                    title = elem.text.strip() or elem.get_attribute('title') or ""
                    if title:
                        break
                except:
                    continue
            
            # Поиск цены
            price_raw = ""
            price_selectors = ['.product-price', '.catalog-card__price', '[class*="price"]', '[class*="Price"]', '.price']
            for sel in price_selectors:
                try:
                    elem = item.find_element(By.CSS_SELECTOR, sel)
                    price_raw = elem.text.strip().split('\n')[0]
                    if price_raw:
                        break
                except:
                    continue
            
            price_num = clean_price(price_raw)
            
            # Поиск ссылки
            link = ""
            try:
                link_elem = item.find_element(By.CSS_SELECTOR, 'a')
                link = link_elem.get_attribute('href')
                if link and not link.startswith('http'):
                    link = 'https://book24.ru' + link
            except:
                pass
            
            if title:
                books.append({
                    'Название': title,
                    'Автор': 'не найден',
                    'Цена (число)': price_num,
                    'Цена (строка)': price_raw,
                    'Ссылка': link
                })
                log_func(f"  ✅ Найдена книга: {title[:40]} | цена: {price_raw}")
            else:
                log_func(f"  ⚠️ Карточка без названия, пропускаем")
                
        except Exception as e:
            log_func(f"❌ Ошибка в карточке: {e}")
    
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
    
    def log(msg):
        print(msg)
    
    log(f"🚀 Старт парсинга: {max_books} книг")
    log(f"🔗 URL категории: {category_url}")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # Пробуем загрузить первую страницу
    try:
        log(f"🌐 Загрузка {category_url}")
        driver.get(category_url)
        time.sleep(5)  # Ждём загрузки
        
        # Проверяем заголовок страницы
        title = driver.title
        log(f"📄 Заголовок страницы: {title}")
        
        # Проверяем, не перенаправило ли на капчу
        if "captcha" in driver.current_url.lower() or "blocked" in driver.current_url.lower():
            log(f"❌ Страница перенаправила на капчу/блокировку: {driver.current_url}")
            shared_state['message'] = "Сайт заблокировал запрос. Попробуйте позже."
            shared_state['running'] = False
            driver.quit()
            return
        
        books_on_page = parse_page(driver, 1, log)
        
        if books_on_page:
            log(f"✅ Найдено {len(books_on_page)} книг на первой странице!")
            # Берём столько книг, сколько запросил пользователь
            total_to_take = min(max_books, len(books_on_page))
            shared_state['books'] = books_on_page[:total_to_take]
            shared_state['progress_current'] = total_to_take
            log(f"📚 Взято {total_to_take} книг")
        else:
            log(f"❌ Не найдено книг на первой странице!")
            # Проверяем, что вообще есть на странице
            body_text = driver.find_element(By.TAG_NAME, 'body').text[:500]
            log(f"📄 Текст страницы (первые 500 символов): {body_text}")
            
    except Exception as e:
        log(f"❌ Критическая ошибка: {e}")
        shared_state['message'] = f"Ошибка: {str(e)[:200]}"
    
    driver.quit()
    elapsed = time.time() - start_time
    
    # Статистика
    all_books = shared_state['books']
    prices = [b['Цена (число)'] for b in all_books if b.get('Цена (число)'] is not None]
    avg_price = sum(prices)/len(prices) if prices else 0
    min_price = min(prices) if prices else 0
    max_price_val = max(prices) if prices else 0
    
    shared_state['stats'] = {
        'count': len(all_books),
        'avg_price': round(avg_price, 2),
        'min_price': min_price,
        'max_price': max_price_val,
        'category': categories.get(category_url, 'Неизвестно'),
        'time': round(elapsed, 1)
    }
    
    if shared_state['stop_flag']:
        shared_state['message'] = f"⏹️ Парсинг остановлен. Собрано {len(all_books)} книг."
    elif len(all_books) == 0:
        shared_state['message'] = f"❌ Не удалось найти книги. Проверьте файлы debug_page_*.html"
    else:
        shared_state['message'] = f"✅ Готово! Собрано {len(all_books)} книг за {elapsed:.1f} сек."
    
    shared_state['running'] = False

# -------------------- HTML-шаблон (упрощённый, но рабочий) --------------------
MAIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📚 Парсер книг book24.ru</title>
    <style>
        * { box-sizing: border-box; }
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; }
        .container { max-width: 1200px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; }
        h1 { color: #ffd966; text-align: center; }
        .controls { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; align-items: flex-end; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; }
        button { background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; }
        #stopBtn { background: #f44336; }
        #saveBtn { background: #2196f3; }
        button:disabled { opacity: 0.6; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: #4caf50; text-align: center; line-height: 25px; color: white; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 15px 0; }
        .status.info { background: #0c5460; }
        .status.success { background: #155724; }
        .status.error { background: #721c24; }
        .log { background: #1e1f2c; color: #0f0; font-family: monospace; padding: 10px; height: 300px; overflow-y: auto; border-radius: 8px; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #3c3f54; padding: 10px; text-align: left; }
        th { background: #3c3f54; color: #ffd966; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }
        .stats-card { background: #252634; padding: 15px; border-radius: 12px; text-align: center; }
        .stats-card .value { font-size: 24px; font-weight: bold; color: #ffd966; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab-btn { background: #3c3f54; }
        .tab-btn.active { background: #4caf50; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .owner-sign { position: fixed; bottom: 10px; right: 15px; background: rgba(0,0,0,0.6); padding: 4px 12px; border-radius: 20px; font-size: 12px; }
    </style>
</head>
<body>
<div class="owner-sign">👨‍💻 Timergalin Danil</div>
<div class="container">
    <h1>📚 Парсер книг book24.ru</h1>
    
    <div class="controls">
        <div class="form-group"><label>📖 Количество книг:</label><input type="number" id="bookCount" placeholder="введите число"></div>
        <div class="form-group"><label>🎭 Жанр:</label>
        <select id="category">
            <option value="https://book24.ru/knigi-bestsellery/">Бестселлеры</option>
            <option value="https://book24.ru/knigi-novinki/">Новинки</option>
            <option value="https://book24.ru/knigi/klassicheskaya-literatura/">Классика</option>
            <option value="https://book24.ru/knigi/detektivy/">Детективы</option>
        </select></div>
        <div>
            <button id="startBtn">▶ СТАРТ</button>
            <button id="stopBtn" disabled>⏹️ СТОП</button>
            <button id="saveBtn" disabled>💾 СОХРАНИТЬ CSV</button>
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
        <div class="table-wrapper" style="overflow-x:auto">
            <table id="resultsTable"><thead><tr><th>№</th><th>Название</th><th>Цена</th><th>Ссылка</th></tr></thead><tbody id="tableBody"></tbody></table>
        </div>
    </div>

    <div id="statsTab" class="tab-content">
        <div class="stats-grid" id="statsGrid"></div>
    </div>
</div>

<script>
    let currentBooks = [], updateInterval = null;
    const startBtn = document.getElementById('startBtn'), stopBtn = document.getElementById('stopBtn'), saveBtn = document.getElementById('saveBtn');
    const progressFill = document.getElementById('progressFill'), statusDiv = document.getElementById('statusDiv'), logDiv = document.getElementById('logDiv');
    const tabParsingBtn = document.getElementById('tabParsingBtn'), tabResultsBtn = document.getElementById('tabResultsBtn'), tabStatsBtn = document.getElementById('tabStatsBtn');
    const parsingTab = document.getElementById('parsingTab'), resultsTab = document.getElementById('resultsTab'), statsTab = document.getElementById('statsTab');
    const bookCountInput = document.getElementById('bookCount'), categorySelect = document.getElementById('category');
    const tableBody = document.getElementById('tableBody'), statsGrid = document.getElementById('statsGrid');

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
    
    function fetchStats(){ fetch('/status').then(r=>r.json()).then(d=>{ if(d.stats){ statsGrid.innerHTML = `<div class="stats-card"><div class="label">📚 Книг</div><div class="value">${d.stats.count}</div></div><div class="stats-card"><div class="label">💰 Средняя цена</div><div class="value">${d.stats.avg_price} ₽</div></div><div class="stats-card"><div class="label">⏱️ Время</div><div class="value">${d.stats.time} сек</div></div>`; } }); }
    
    function updateTableDisplay(books){
        tableBody.innerHTML='';
        books.forEach((b,i)=>{ let r=tableBody.insertRow(); r.insertCell(0).innerText=i+1; r.insertCell(1).innerText=b['Название']||''; r.insertCell(2).innerText=b['Цена (строка)']||'—'; let l=b['Ссылка']||''; let lc=r.insertCell(3); if(l){ let a=document.createElement('a'); a.href=l; a.target='_blank'; a.innerText='Открыть'; lc.appendChild(a); } else lc.innerText='—'; });
    }
    
    function checkStatus(){
        fetch('/status').then(r=>r.json()).then(d=>{
            if(d.running){
                if(d.progress_current && d.progress_total){ let p=Math.round(d.progress_current/d.progress_total*100); progressFill.style.width=p+'%'; progressFill.innerText=p+'%'; }
                if(d.books && d.books.length!==currentBooks.length){ currentBooks=d.books; if(resultsTab.classList.contains('active')) updateTableDisplay(currentBooks); }
                statusDiv.innerText='⏳ Сбор данных...'; statusDiv.className='status info';
                startBtn.disabled=true; stopBtn.disabled=false; saveBtn.disabled=true;
            }else{
                if(updateInterval) clearInterval(updateInterval); updateInterval=null;
                startBtn.disabled=false; stopBtn.disabled=true;
                if(d.books && d.books.length>0){ currentBooks=d.books; if(resultsTab.classList.contains('active')) updateTableDisplay(currentBooks); saveBtn.disabled=false; statusDiv.innerText=d.message||'Завершено'; statusDiv.className='status success'; }
                else{ statusDiv.innerText=d.message||'Нет результатов'; statusDiv.className='status error'; saveBtn.disabled=true; }
                if(d.stats && statsTab.classList.contains('active')){ statsGrid.innerHTML = `<div class="stats-card"><div class="label">📚 Книг</div><div class="value">${d.stats.count}</div></div><div class="stats-card"><div class="label">💰 Средняя цена</div><div class="value">${d.stats.avg_price} ₽</div></div><div class="stats-card"><div class="label">⏱️ Время</div><div class="value">${d.stats.time} сек</div></div>`; }
                addLog(d.message||'Готово');
            }
        });
    }
    
    startBtn.onclick=()=>{
        let maxBooks=parseInt(bookCountInput.value);
        if(isNaN(maxBooks) || maxBooks<=0){ addLog('❌ Введите количество книг (целое >0)'); return; }
        fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_books:maxBooks, category_url:categorySelect.value})})
        .then(r=>r.json()).then(d=>{ if(d.status==='started'){ addLog('🚀 Парсинг запущен...'); progressFill.style.width='0%'; progressFill.innerText='0%'; currentBooks=[]; if(resultsTab.classList.contains('active')) updateTableDisplay([]); if(updateInterval) clearInterval(updateInterval); updateInterval=setInterval(checkStatus,1000); } else addLog('❌ '+d.message); });
    };
    stopBtn.onclick=()=>{ fetch('/stop',{method:'POST'}).then(()=>{ addLog('⏸️ Остановка'); stopBtn.disabled=true; }); };
    saveBtn.onclick=()=>{ window.location.href='/download-csv'; };
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(MAIN_TEMPLATE)

@app.route('/start', methods=['POST'])
def start():
    global shared_state
    if shared_state['running']:
        return jsonify({'status': 'error', 'message': 'Парсинг уже запущен'})
    data = request.get_json()
    max_books = data.get('max_books')
    if not max_books or max_books <= 0:
        return jsonify({'status': 'error', 'message': 'Введите корректное количество книг'})
    category_url = data.get('category_url')
    if not category_url:
        return jsonify({'status': 'error', 'message': 'Не указана категория'})
    shared_state['stop_flag'] = False
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
        return "Нет данных", 404
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['Название', 'Автор', 'Цена (строка)', 'Ссылка'], delimiter=';')
    writer.writeheader()
    writer.writerows(books)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name=f'books_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
