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
    "https://book24.ru/knigi/detektivy/": "Детективы"
}

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
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.product-card, .catalog-card'))
        )
    except Exception as e:
        print(f"⚠️ Страница {page_num}: {e}")
        return books
    
    items = driver.find_elements(By.CSS_SELECTOR, '.product-card, .catalog-card')
    print(f"📄 Страница {page_num}: {len(items)} карточек")
    
    for item in items:
        try:
            title = ""
            try:
                title_elem = item.find_element(By.CSS_SELECTOR, 'a[title], .product-title')
                title = title_elem.text.strip()
                if not title:
                    title = title_elem.get_attribute('title') or ""
            except:
                continue
            
            author = ""
            try:
                author_elem = item.find_element(By.CSS_SELECTOR, '.product-author')
                author = author_elem.text.strip()
            except:
                pass
            
            price_raw = ""
            try:
                price_elem = item.find_element(By.CSS_SELECTOR, '.product-price')
                price_raw = price_elem.text.strip().split('\n')[0]
            except:
                pass
            
            price_num = clean_price(price_raw)
            
            link = ""
            try:
                link_elem = item.find_element(By.CSS_SELECTOR, 'a')
                link = link_elem.get_attribute('href')
            except:
                pass
            
            if title:
                books.append({
                    'Название': title,
                    'Автор': author,
                    'Цена (число)': price_num,
                    'Цена (строка)': price_raw,
                    'Ссылка': link
                })
        except:
            continue
    
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
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=options)
    
    all_books = []
    
    try:
        print(f"🌐 Загрузка: {category_url}")
        driver.get(category_url)
        time.sleep(3)
        
        books_on_page = parse_page(driver, 1)
        
        if books_on_page:
            max_books = min(max_books, len(books_on_page))
            all_books = books_on_page[:max_books]
            shared_state['books'] = all_books
            shared_state['progress_current'] = len(all_books)
            print(f"✅ Собрано {len(all_books)} книг")
        else:
            print("❌ Не найдено книг")
            # Сохраняем HTML для отладки
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source[:100000])
            print("💾 Сохранён debug.html")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        shared_state['message'] = str(e)
    
    driver.quit()
    
    prices = [b['Цена (число)'] for b in all_books if b.get('Цена (число)')]
    shared_state['stats'] = {
        'count': len(all_books),
        'avg_price': round(sum(prices)/len(prices), 2) if prices else 0,
        'min_price': min(prices) if prices else 0,
        'max_price': max(prices) if prices else 0,
        'category': categories.get(category_url, ''),
        'time': round(time.time() - start_time, 1)
    }
    
    if len(all_books) == 0:
        shared_state['message'] = "❌ Книги не найдены. Скачан debug.html для анализа"
    else:
        shared_state['message'] = f"✅ Собрано {len(all_books)} книг"
    
    shared_state['running'] = False

# --- HTML ---
HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>📚 Парсер book24.ru</title>
    <style>
        body { background: #1e1f2c; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; color: #eee; }
        .container { max-width: 1200px; margin: auto; background: #2d2f3e; border-radius: 16px; padding: 20px; }
        h1 { color: #ffd966; text-align: center; }
        .controls { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; }
        .form-group { display: flex; flex-direction: column; gap: 5px; }
        label { font-weight: bold; color: #ffd966; }
        input, select { background: #3c3f54; border: none; padding: 8px 12px; border-radius: 8px; color: white; }
        button { background: #4caf50; border: none; padding: 8px 20px; border-radius: 8px; font-weight: bold; color: white; cursor: pointer; }
        #stopBtn { background: #f44336; }
        .progress-bar { width: 100%; background: #3c3f54; border-radius: 10px; margin: 15px 0; overflow: hidden; }
        .progress-fill { width: 0%; height: 25px; background: #4caf50; text-align: center; line-height: 25px; }
        .log { background: #1e1f2c; color: #0f0; font-family: monospace; padding: 10px; height: 200px; overflow-y: auto; border-radius: 8px; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #3c3f54; padding: 8px; text-align: left; }
        th { background: #3c3f54; color: #ffd966; }
        td a { color: #66bb6a; }
        .status { padding: 10px; border-radius: 8px; text-align: center; margin: 10px 0; }
        .status.info { background: #0c5460; }
        .status.success { background: #155724; }
        .status.error { background: #721c24; }
    </style>
</head>
<body>
<div class="container">
    <h1>📚 Парсер книг book24.ru</h1>
    <div class="controls">
        <div class="form-group"><label>📖 Книг:</label><input type="number" id="bookCount" value="30"></div>
        <div class="form-group"><label>🎭 Жанр:</label>
        <select id="category">
            <option value="https://book24.ru/knigi-bestsellery/">Бестселлеры</option>
            <option value="https://book24.ru/knigi-novinki/">Новинки</option>
            <option value="https://book24.ru/knigi/klassicheskaya-literatura/">Классика</option>
            <option value="https://book24.ru/knigi/detektivy/">Детективы</option>
        </select></div>
        <div><button id="startBtn">▶ СТАРТ</button><button id="stopBtn" disabled>⏹️ СТОП</button></div>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill">0%</div></div>
    <div class="status info" id="statusDiv">Готов</div>
    <div class="log" id="logDiv">📋 Лог:\n</div>
    <div id="results"></div>
</div>
<script>
    let interval = null;
    const startBtn = document.getElementById('startBtn'), stopBtn = document.getElementById('stopBtn');
    const progressFill = document.getElementById('progressFill'), statusDiv = document.getElementById('statusDiv');
    const logDiv = document.getElementById('logDiv'), resultsDiv = document.getElementById('results');
    
    function addLog(msg){ let p=document.createElement('div'); p.textContent=msg; logDiv.appendChild(p); logDiv.scrollTop=logDiv.scrollHeight; }
    
    function checkStatus(){
        fetch('/status').then(r=>r.json()).then(d=>{
            if(d.running){
                if(d.progress_current && d.progress_total){
                    let p = Math.round(d.progress_current/d.progress_total*100);
                    progressFill.style.width = p+'%'; progressFill.innerText = p+'%';
                }
                statusDiv.innerText = '⏳ Сбор данных...'; statusDiv.className = 'status info';
                startBtn.disabled = true; stopBtn.disabled = false;
            } else {
                if(interval) clearInterval(interval); interval = null;
                startBtn.disabled = false; stopBtn.disabled = true;
                if(d.books && d.books.length > 0){
                    statusDiv.innerText = d.message; statusDiv.className = 'status success';
                    let html = '<table><thead><tr><th>№</th><th>Название</th><th>Автор</th><th>Цена</th><th>Ссылка</th></tr></thead><tbody>';
                    d.books.forEach((b,i)=>{ html += `<tr><td>${i+1}</td><td>${b['Название']||''}</td><td>${b['Автор']||''}</td><td>${b['Цена (строка)']||'—'}</td><td>${b['Ссылка']?`<a href="${b['Ссылка']}" target="_blank">Открыть</a>`:'—'}</td></tr>`; });
                    html += '</tbody></table>';
                    resultsDiv.innerHTML = html;
                } else {
                    statusDiv.innerText = d.message || 'Нет результатов'; statusDiv.className = 'status error';
                }
                addLog(d.message || 'Готово');
            }
        });
    }
    
    startBtn.onclick = () => {
        let maxBooks = parseInt(document.getElementById('bookCount').value);
        let categoryUrl = document.getElementById('category').value;
        fetch('/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({max_books:maxBooks, category_url:categoryUrl}) })
        .then(r=>r.json()).then(d=>{ if(d.status==='started'){ addLog('🚀 Старт'); progressFill.style.width='0%'; resultsDiv.innerHTML=''; if(interval) clearInterval(interval); interval = setInterval(checkStatus, 1000); } else addLog('❌ '+d.message); });
    };
    stopBtn.onclick = () => { fetch('/stop',{method:'POST'}).then(()=>{ addLog('⏸️ Стоп'); stopBtn.disabled=true; }); };
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/start', methods=['POST'])
def start():
    global shared_state
    if shared_state['running']:
        return jsonify({'status': 'error', 'message': 'Уже запущено'})
    data = request.get_json()
    max_books = data.get('max_books', 30)
    category_url = data.get('category_url')
    if not category_url:
        return jsonify({'status': 'error', 'message': 'Нет категории'})
    shared_state['stop_flag'] = False
    threading.Thread(target=run_parser_task, args=(max_books, category_url)).start()
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
    writer = csv.DictWriter(output, fieldnames=['Название','Автор','Цена (строка)','Ссылка'], delimiter=';')
    writer.writeheader()
    writer.writerows(books)
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name=f'books_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
