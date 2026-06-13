#!/usr/bin/env python3
"""
네이버 뉴스 API + 유튜브 프록시 서버 — 김민석 총리
─────────────────────────────────────────
1. 터미널에서 실행: python3 naver_proxy.py
2. 브라우저에서 열기: http://localhost:8766

수집된 기사/영상은 data/ 폴더에 날짜별 JSON 파일로 자동 저장됩니다.
"""
import os, re, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime, timezone, timedelta

CLIENT_ID       = os.environ.get('NAVER_CLIENT_ID',     'YOUR_CLIENT_ID')
CLIENT_SECRET   = os.environ.get('NAVER_CLIENT_SECRET', 'YOUR_CLIENT_SECRET')
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY',     'YOUR_YOUTUBE_API_KEY')
PORT            = int(os.environ.get('PORT', 8766))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
KST      = timezone(timedelta(hours=9))


def today_kst():
    return datetime.now(KST).strftime('%Y-%m-%d')


def date_of_pub(pub_date_str):
    try:
        dt = datetime.strptime(pub_date_str.strip(), '%a, %d %b %Y %H:%M:%S %z')
        return dt.astimezone(KST).strftime('%Y-%m-%d')
    except Exception:
        return today_kst()


def save_items(naver_items=None, youtube_items=None):
    date_str = today_kst()
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, date_str + '.json')

    existing_news = {}
    existing_yt   = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                saved = json.load(f)
                for item in saved.get('items', []):
                    url = item.get('link') or item.get('originallink', '')
                    if url:
                        existing_news[url] = item
                for item in saved.get('youtube', []):
                    vid = item.get('videoId', '')
                    if vid:
                        existing_yt[vid] = item
        except Exception:
            pass

    news_added = 0
    for item in (naver_items or []):
        if date_of_pub(item.get('pubDate', '')) != date_str:
            continue
        url = item.get('link') or item.get('originallink', '')
        if url and url not in existing_news:
            existing_news[url] = item
            news_added += 1

    yt_added = 0
    for item in (youtube_items or []):
        vid = item.get('videoId', '')
        if vid and vid not in existing_yt:
            existing_yt[vid] = item
            yt_added += 1

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(
            {
                'date':    date_str,
                'items':   list(existing_news.values()),
                'youtube': list(existing_yt.values()),
            },
            f, ensure_ascii=False, indent=2
        )

    if news_added or yt_added:
        print(f'[{datetime.now(KST).strftime("%H:%M:%S")}] '
              f'신규 뉴스 {news_added}건 · 유튜브 {yt_added}건 저장 → {path}')


class Handler(BaseHTTPRequestHandler):

        def do_HEAD(self):
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
            
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/news':
            self._live_news()
        elif path == '/api/youtube':
            self._live_youtube()
        elif path == '/api/history':
            self._history()
        elif path == '/api/dates':
            self._available_dates()
        else:
            self._serve_file('index.html')

    def _live_news(self):
        qs    = parse_qs(urlparse(self.path).query)
        query = qs.get('query', ['김민석'])[0]
        url   = ('https://openapi.naver.com/v1/search/news.json'
                 '?query=' + quote(query) + '&display=100&sort=date')
        req = Request(url, headers={
            'X-Naver-Client-Id':     CLIENT_ID,
            'X-Naver-Client-Secret': CLIENT_SECRET,
        })
        try:
            res  = urlopen(req, timeout=10)
            raw  = res.read()
            data = json.loads(raw)
            save_items(naver_items=data.get('items', []))
            self._write(200, raw, 'application/json; charset=utf-8')
        except Exception as e:
            err = json.dumps({'items': [], 'error': str(e)}).encode()
            self._write(500, err, 'application/json; charset=utf-8')

    def _live_youtube(self):
        qs    = parse_qs(urlparse(self.path).query)
        query = qs.get('query', ['김민석 총리'])[0]
        url   = ('https://www.googleapis.com/youtube/v3/search'
                 '?part=snippet&q=' + quote(query) +
                 '&type=video&order=date&maxResults=25'
                 '&key=' + YOUTUBE_API_KEY)
        try:
            res  = urlopen(url, timeout=10)
            raw  = res.read()
            data = json.loads(raw)
            items = []
            for item in data.get('items', []):
                vid = item.get('id', {}).get('videoId', '')
                if not vid:
                    continue
                sn = item.get('snippet', {})
                items.append({
                    'videoId':      vid,
                    'title':        sn.get('title', ''),
                    'channelTitle': sn.get('channelTitle', ''),
                    'publishedAt':  sn.get('publishedAt', ''),
                    'thumbnail':    sn.get('thumbnails', {}).get('medium', {}).get('url', ''),
                })
            save_items(youtube_items=items)
            result = json.dumps({'items': items}).encode()
            self._write(200, result, 'application/json; charset=utf-8')
        except Exception as e:
            err = json.dumps({'items': [], 'error': str(e)}).encode()
            self._write(500, err, 'application/json; charset=utf-8')

    def _history(self):
        qs   = parse_qs(urlparse(self.path).query)
        date = qs.get('date', [''])[0]
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
            self._json({'items': [], 'youtube': [], 'error': 'invalid date'})
            return
        file_path = os.path.join(DATA_DIR, date + '.json')
        if os.path.exists(file_path):
            with open(file_path, encoding='utf-8') as f:
                self._json(json.load(f))
        else:
            self._json({'date': date, 'items': [], 'youtube': []})

    def _available_dates(self):
        dates = []
        if os.path.exists(DATA_DIR):
            for name in sorted(os.listdir(DATA_DIR), reverse=True):
                if re.match(r'^\d{4}-\d{2}-\d{2}\.json$', name):
                    dates.append(name[:-5])
        self._json({'dates': dates})

    def _serve_file(self, name):
        file_path = os.path.join(BASE_DIR, name)
        try:
            with open(file_path, 'rb') as f:
                body = f.read()
            self._write(200, body, 'text/html; charset=utf-8')
        except FileNotFoundError:
            self._write(404, b'Not Found', 'text/plain')

    def _json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self._write(200, body, 'application/json; charset=utf-8')

    def _write(self, code, body, content_type):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    print(f'\n✅  서버 시작됨 (김민석 총리)')
    print(f'   브라우저에서 열기  →  http://localhost:{PORT}')
    print(f'   기사 저장 폴더     →  {DATA_DIR}')
    print(f'   종료: Ctrl+C\n')
    HTTPServer(('', PORT), Handler).serve_forever()
