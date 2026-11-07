"""Collect official public WEC CSVs and render reproducible per-session reports."""
import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = 'https://files.alkamelcloud.com/'
INDEX = BASE + 'wec/manifests/results.json'
ROOT = Path(__file__).resolve().parents[1]


def client():
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
    return session


def get(session, url):
    response = session.get(url, timeout=(15, 90))
    response.raise_for_status()
    return response


def official_url(path):
    url = urljoin(BASE, path)
    if not url.startswith(BASE + 'wec/'):
        raise ValueError('Unexpected official document host/path')
    return quote(url, safe=':/%')


def documents(nodes, parents=()):
    for node in nodes:
        path = parents + (node.get('name') or '',)
        if node.get('url'):
            yield path, node
        yield from documents(node.get('children', []), path)


def discover(manifest, event=None):
    """Group exact FIA WEC sessions; support races and Prologue are excluded."""
    sessions = {}
    for path, node in documents(manifest['folders']):
        raw = node['url']
        match = re.search(r'/([^/]+)/\d+_FIA WEC/(\d{12}_[^/]+)/', raw)
        if not match or (event and event.casefold() not in match[1].casefold()):
            continue
        if node.get('extension', '').lower() != 'csv':
            continue
        key = match[1] + '/' + match[2]
        entry = sessions.setdefault(key, {'event': match[1], 'session': match[2], 'files': []})
        entry['files'].append({'name': node['name'], 'url': official_url(raw)})
    return sessions


def duration(value):
    try:
        parts = str(value).strip().split(':')
        if not 1 <= len(parts) <= 3:
            return None
        result = 0.0
        for part in parts:
            result = result * 60 + float(part)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def parse_csv(content):
    text = content.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text), delimiter=';')
    if not reader.fieldnames:
        raise ValueError('Empty CSV')
    reader.fieldnames = [x.strip() for x in reader.fieldnames]
    required = {'NUMBER', 'LAP_NUMBER', 'LAP_TIME', 'DRIVER_NAME', 'CLASS'}
    if not required.issubset(reader.fieldnames):
        raise ValueError('Unrecognized WEC analysis columns')
    rows = []
    seen = set()
    for raw in reader:
        r = {k: (v or '').strip() for k, v in raw.items() if k}
        if not r['NUMBER'] or not r['LAP_NUMBER'].isdigit():
            raise ValueError('Invalid car/lap identity')
        identity = (r['NUMBER'], int(r['LAP_NUMBER']))
        if identity in seen:
            raise ValueError('Duplicate car/lap identity')
        seen.add(identity)
        r['seconds'] = duration(r['LAP_TIME'])
        r['pit_seconds'] = duration(r.get('PIT_TIME'))
        r['pit_in'] = bool(r.get('CROSSING_FINISH_LINE_IN_PIT'))
        # No inferred fuel/traffic corrections. Missing flags are excluded.
        r['pace_eligible'] = (r['seconds'] is not None and int(r['LAP_NUMBER']) > 1
                              and not r['pit_in'] and r['pit_seconds'] is None
                              and r.get('FLAG_AT_FL') in ('GF', 'FF'))
        rows.append(r)
    if not rows:
        raise ValueError('No lap records')
    return rows


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['CLASS'], row['NUMBER'], row['DRIVER_NAME'])].append(row)
    result = []
    for (category, number, driver), laps in sorted(groups.items()):
        times = [r['seconds'] for r in laps if r['seconds'] is not None]
        pace = [r['seconds'] for r in laps if r['pace_eligible']]
        result.append(dict(category=category, number=number, driver=driver,
                           team=laps[0].get('TEAM', ''), laps=len(laps),
                           best=min(times) if times else None,
                           median=statistics.median(pace) if pace else None,
                           sample=len(pace), pit_in=sum(r['pit_in'] for r in laps)))
    return result


def stints(rows):
    cars = defaultdict(list)
    for row in rows:
        cars[row['NUMBER']].append(row)
    result = []
    for car, laps in sorted(cars.items()):
        current = []
        previous = None
        for row in sorted(laps, key=lambda r: int(r['LAP_NUMBER'])):
            boundary = previous and (row['DRIVER_NAME'] != previous['DRIVER_NAME']
                                     or previous['pit_in'] or row['pit_seconds'] is not None)
            if boundary and current:
                result.append((car, current))
                current = []
            current.append(row)
            previous = row
        if current:
            result.append((car, current))
    return result


def fmt(value):
    return '—' if value is None else f'{int(value // 60)}:{value % 60:06.3f}'


def page(title, body):
    return ('<!doctype html><html lang="ko"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>body{{font:16px system-ui;max-width:1200px;'
            'margin:32px auto;padding:0 16px;background:#101827;color:#edf2ff}'
            'a{color:#82d6ff}table{border-collapse:collapse;width:100%}td,th{padding:9px;'
            'border-bottom:1px solid #40506c;text-align:left}section{overflow:auto}select,input{padding:8px}'
            'svg{background:#18243b;max-width:100%;height:auto}button{padding:8px}</style>'
            f'<h1>{html.escape(title)}</h1>{body}</html>')


def render(entry, rows, sources, classification=None):
    esc = html.escape
    summaries = summarize(rows)
    body = '<a href="../../index.html">WEC 목록</a> · <a href="laps.json">랩 JSON</a><p>'
    body += '공식 CSV 관측 기록. 순위·최종 결과를 추정하지 않습니다. 중앙값은 첫 랩·피트 진입·피트 시간 기록 랩을 제외하고 GF/FF 랩만 사용합니다. '
    body += '플래그는 결승선 통과 시점 정보이며 랩 전체의 그린 상태를 보장하지 않습니다. 연료·트래픽·타이어 보정 없음. '
    body += '피트 진입 수는 완료된 정차 횟수와 다르며 첫 출차의 PIT_TIME도 정차로 세지 않습니다.</p>'
    body += '<p>출처: ' + ' · '.join(f'<a href="{esc(s["url"], quote=True)}">{esc(s["name"])}</a>' for s in sources) + '</p>'
    if classification:
        columns = ['POS', 'NUMBER', 'CLASS', 'TEAM', 'LAPS', 'TIME', 'GAP_FIRST']
        body += '<h2>공식 CSV 세션 결과</h2><p>기록 파일의 현재 순위입니다. 잠정/확정 여부는 원본 문서를 확인하세요. TIME은 세션별 공식 값 그대로 표시합니다.</p><section><table><thead><tr>'
        body += ''.join('<th>'+esc(c)+'</th>' for c in columns)+'</tr></thead><tbody>'
        for result in classification:
            body += '<tr>'+''.join('<td>'+esc(result.get(c, ''))+'</td>' for c in columns)+'</tr>'
        body += '</tbody></table></section>'
    body += '<label>클래스/차량/드라이버 검색 <input id="search" type="search"></label><section><table><thead><tr>'
    body += ''.join(f'<th>{x}</th>' for x in ['클래스','차량','드라이버','팀','관측 랩','최속','중앙값','표본','피트 진입']) + '</tr></thead><tbody>'
    for s in summaries:
        vals = [s['category'],s['number'],s['driver'],s['team'],s['laps'],fmt(s['best']),fmt(s['median']),s['sample'],s['pit_in']]
        body += '<tr>' + ''.join('<td>'+esc(str(v))+'</td>' for v in vals) + '</tr>'
    body += '</tbody></table></section><h2>관측 주행 구간</h2><p>드라이버 교대 또는 CSV 피트 경계로 나눈 구간입니다. 공식 타이어 스틴트가 아닙니다.</p><section><table><thead><tr><th>차량</th><th>드라이버</th><th>랩 범위</th><th>유효 표본</th><th>중앙값</th></tr></thead><tbody>'
    for car, stint in stints(rows):
        times = [r['seconds'] for r in stint if r['pace_eligible']]
        values = [car, stint[0]['DRIVER_NAME'], stint[0]['LAP_NUMBER']+'–'+stint[-1]['LAP_NUMBER'], len(times), fmt(statistics.median(times) if times else None)]
        body += '<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in values)+'</tr>'
    body += '</tbody></table></section><h2>차량별 랩타임</h2><p>가로: 랩 번호 · 세로: 랩타임(초), 아래쪽이 빠른 랩</p><select id="car">' 
    for car in sorted({r['NUMBER'] for r in rows}):
        body += f'<option value="{esc(car, quote=True)}">#{esc(car)}</option>'
    body += '</select><div id="chart"></div><p>점에 포커스하거나 마우스를 올리면 드라이버·랩타임 표시. 피트 랩은 주황색.</p>'
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    body += '<script>const laps='+data+''';
const ns='http://www.w3.org/2000/svg';
function draw(){const rows=laps.filter(r=>r.NUMBER===document.querySelector('#car').value&&r.seconds!==null);
const box=document.querySelector('#chart');box.replaceChildren();if(!rows.length)return;
const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 330');
const maxLap=Math.max(...rows.map(r=>Number(r.LAP_NUMBER)),1),lo=Math.min(...rows.map(r=>r.seconds)),hi=Math.max(...rows.map(r=>r.seconds));
for(const [x,y,text] of [[30,315,'Lap 0'],[900,315,'Lap '+maxLap],[1,25,hi.toFixed(1)+'s'],[1,290,lo.toFixed(1)+'s']]){const t=document.createElementNS(ns,'text');t.setAttribute('x',x);t.setAttribute('y',y);t.setAttribute('fill','#edf2ff');t.textContent=text;svg.append(t)}
for(const r of rows){const c=document.createElementNS(ns,'circle');c.setAttribute('cx',30+940*Number(r.LAP_NUMBER)/maxLap);c.setAttribute('cy',290-260*(r.seconds-lo)/(hi-lo||1));c.setAttribute('r',4);c.setAttribute('fill',r.pit_in||r.pit_seconds?'#ffad60':'#82d6ff');c.setAttribute('tabindex','0');const label=`${r.DRIVER_NAME} / Lap ${r.LAP_NUMBER}: ${r.LAP_TIME}`;c.setAttribute('aria-label',label);const t=document.createElementNS(ns,'title');t.textContent=label;c.append(t);svg.append(c)}box.append(svg)}
document.querySelector('#car').addEventListener('change',draw);draw();
document.querySelector('#search').addEventListener('input',e=>{for(const r of document.querySelectorAll('tbody tr'))r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())});</script>'''
    return page(entry['event']+' · '+entry['session'], body)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(value, encoding='utf-8')
    temp.replace(path)


def build_index(output):
    links = []
    for file in sorted(output.glob('*/*/report.html'), reverse=True):
        label = ' / '.join(file.relative_to(output).parts[:-1])
        links.append(f'<li><a href="{html.escape(file.relative_to(output).as_posix(), quote=True)}">{html.escape(label)}</a></li>')
    write(output/'index.html', page('WEC 세션 리포트', '<a href="../index.html">F1 · WEC</a><ul>'+''.join(links)+'</ul>'))


def run(year, output, event=None):
    http = client()
    index = get(http, INDEX).json()
    season = next((s for s in index['seasons'] if s['name'] == str(year)), None)
    if not season:
        raise ValueError(f'No official season: {year}')
    entries = discover(get(http, official_url(season['manifestUrl'])).json(), event)
    if not entries:
        raise ValueError('No FIA WEC sessions found')
    count = 0
    for key, entry in entries.items():
        candidates = [s for s in entry['files'] if re.search(r'^\d+_Analysis_', s['url'].rsplit('/',1)[-1], re.I)]
        if not candidates:
            continue
        # Hourly snapshots: choose the last numeric hour; prefer a final unsuffixed file.
        def rank(source):
            name = source['name']
            m = re.search(r'Hour\s*(\d+)',name,re.I)
            return (0, int(m[1])) if m else (1, 0)
        source = max(candidates, key=rank)
        content = get(http, source['url']).content
        rows = parse_csv(content)
        destination = output/str(year)/hashlib.sha256(key.encode()).hexdigest()[:16]
        classification = None
        classifications = [s for s in entry['files'] if re.match(r'^Classification_', s['name'], re.I)]
        classification_content = None
        if classifications:
            classification_content = get(http, max(classifications, key=rank)['url']).content
            reader = csv.DictReader(io.StringIO(classification_content.decode('utf-8-sig')), delimiter=';')
            reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
            if not {'POS', 'NUMBER', 'CLASS'}.issubset(reader.fieldnames):
                raise ValueError('Unrecognized WEC classification columns')
            classification = [{k: (v or '').strip() for k,v in r.items() if k} for r in reader]
            if not classification:
                raise ValueError('Empty WEC classification')
        report = render(entry, rows, entry['files'], classification)
        if classification_content:
            write(destination/'classification.csv', classification_content.decode('utf-8-sig'))
        write(destination/'analysis.csv', content.decode('utf-8-sig'))
        write(destination/'laps.json', json.dumps(rows, ensure_ascii=False, indent=2))
        write(destination/'source.json', json.dumps(dict(entry, analysis=source, sha256=hashlib.sha256(content).hexdigest()),ensure_ascii=False,indent=2))
        write(destination/'report.html', report)
        count += 1
    if not count:
        raise ValueError('No supported lap analysis CSVs; existing reports preserved')
    build_index(output)
    print(f'WEC: {count} sessions generated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument('--event', help='Official event path substring, e.g. MONZA')
    parser.add_argument('--output', type=Path, default=ROOT/'reports/wec')
    args = parser.parse_args()
    run(args.year, args.output, args.event)
