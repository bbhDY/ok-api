#!/usr/bin/env python3
import json
import urllib.request
import os
import urllib.parse
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

MIRRORS = [
    'https://scu.ixgukkejj.cc',
    'https://zju.ixgukkejj.cc',
    'https://bnu.ixgukkejj.cc',
    'https://pku.ixgukkejj.cc',
]

CATEGORIES = [
    {'type_id': 24, 'type_name': '短剧', 'route': 'ai-duanju'},
    {'type_id': 25, 'type_name': '漫剧', 'route': 'ai-manju'},
    {'type_id': 26, 'type_name': 'AI换脸', 'route': 'ai-huanlian'},
    {'type_id': 27, 'type_name': 'AI魔改', 'route': 'ai-mogai'},
]
CATE_BY_ID = {str(c['type_id']): c for c in CATEGORIES}

def fetch_json(path, method='GET', payload=None, timeout=8):
    last_err = None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    for base in MIRRORS:
        try:
            req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            last_err = e
    raise RuntimeError(f'All mirrors failed for {path}: {last_err}')

def format_item(v, play_from='', play_url=''):
    vid = v.get('id')
    cid = v.get('cate_id', 24)
    cname = CATE_BY_ID.get(str(cid), {}).get('type_name', '短剧')
    ep_cnt = v.get('episode_count') or v.get('total_episodes') or 1
    remarks = f'全{ep_cnt}集' if v.get('is_finished') else f'更新至{ep_cnt}集'
    return {
        'vod_id': vid,
        'vod_name': v.get('title', ''),
        'type_id': cid,
        'type_name': cname,
        'vod_en': '',
        'vod_time': v.get('created_at', '') or '',
        'vod_remarks': remarks,
        'vod_pic': v.get('cover', ''),
        'vod_blurb': v.get('description', '') or v.get('desc', '') or '',
        'vod_content': v.get('description', '') or v.get('desc', '') or '',
        'vod_play_from': play_from or '黄果短剧',
        'vod_play_url': play_url,
    }

def get_detail(vid):
    res = fetch_json(f'/api/videos/{vid}')
    d = res.get('data', {})
    if not d:
        return None
    episodes = d.get('episodes') or [{'ep_num': 1, 'title': '第1集'}]
    def get_ep_url(ep):
        ep_num = ep.get('ep_num', 1)
        ep_title = f'第{ep_num}集'
        try:
            p = fetch_json(f'/api/videos/{vid}/episodes/{ep_num}/playback', method='POST', payload={})
            m3u8 = p.get('data', {}).get('streams', {}).get('main', '')
            if m3u8:
                return (ep_num, f'{ep_title}${m3u8}')
        except Exception:
            pass
        return (ep_num, '')

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(get_ep_url, episodes))
    results.sort(key=lambda x: x[0])
    play_parts = [r[1] for r in results if r[1]]
    play_url = '#'.join(play_parts)
    return format_item(d, '黄果短剧', play_url)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/health'):
            self.send_json({'ok': True, 'endpoints': ['/oktv.json', '/huangguo.json', '/api.php/provide/vod']})
            return

        if parsed.path in ('/huangguo.json', '/hg.json'):
            with open(os.path.join(BASE_DIR, 'huangguo.json'), 'r', encoding='utf-8') as f:
                raw = f.read()
            host = self.headers.get('X-Forwarded-Host') or self.headers.get('Host')
            if host:
                proto = self.headers.get('X-Forwarded-Proto', 'https')
                raw = raw.replace('http://107.174.127.147:18080', f'{proto}://{host}')
            self.send_json(json.loads(raw))
            return

        if parsed.path == '/oktv.json':
            try:
                with open(os.path.join(BASE_DIR, 'oktv.json'), 'rb') as f:
                    raw = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(raw)
            except Exception as e:
                self.send_json({'error': str(e)}, 500)
            return

        if not parsed.path.startswith('/api.php/provide/vod'):
            self.send_json({'code': 0, 'msg': 'not found'}, 404)
            return

        qs = urllib.parse.parse_qs(parsed.query)
        ac = qs.get('ac', ['list'])[0]
        t = qs.get('t', [''])[0]
        pg = int(qs.get('pg', ['1'])[0] or 1)
        wd = qs.get('wd', [''])[0]
        ids = qs.get('ids', [''])[0]

        try:
            items = []
            total = 0
            pagecount = 1
            if ids:
                id_list = [x.strip() for x in ids.split(',') if x.strip()]
                with ThreadPoolExecutor(max_workers=4) as ex:
                    details = list(ex.map(get_detail, id_list))
                items = [x for x in details if x]
                total = len(items)
            elif wd:
                q = urllib.parse.quote(wd)
                res = fetch_json(f'/api/search?q={q}&page={pg}')
                raw_items = res.get('data', {}).get('items', [])
                items = [format_item(v) for v in raw_items]
                total = res.get('data', {}).get('total', len(items))
                pagecount = max(1, (total + 19) // 20)
            elif t and t in CATE_BY_ID:
                route = CATE_BY_ID[t]['route']
                res = fetch_json(f'/api/videos/category/{route}?page={pg}')
                raw_items = res.get('data', {}).get('items', [])
                items = [format_item(v) for v in raw_items]
                total = res.get('data', {}).get('total', len(items) * 10)
                pagecount = max(1, (total + 19) // 20)
            else:
                res = fetch_json(f'/api/videos?page={pg}')
                raw_items = res.get('data', {}).get('items', [])
                items = [format_item(v) for v in raw_items]
                total = res.get('data', {}).get('total', 1000)
                pagecount = max(1, (total + 19) // 20)

            classes = [{'type_id': c['type_id'], 'type_name': c['type_name']} for c in CATEGORIES]
            self.send_json({
                'code': 1,
                'msg': '数据列表',
                'page': pg,
                'pagecount': pagecount,
                'limit': '20',
                'total': total,
                'list': items,
                'class': classes,
            })
        except Exception as e:
            self.send_json({'code': 0, 'msg': str(e), 'list': []}, 500)

if __name__ == '__main__':
    srv = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '3000'))), Handler)
    srv.serve_forever()
