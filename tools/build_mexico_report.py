"""Build a self-contained Korean report from captured OpenF1 responses."""
import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1] / "reports" / "mexico-2026"
data = {
    p.stem: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted((ROOT / "data").glob("*.json"))
}
laps = data["laps"]
start = min(
    datetime.fromisoformat(x["date_start"]) for x in laps if x.get("date_start")
)
end = max(
    datetime.fromisoformat(x["date_start"])
    + timedelta(seconds=x.get("lap_duration") or 0)
    for x in laps
    if x.get("date_start")
)
controls = [
    x
    for x in data["race_control"]
    if start <= datetime.fromisoformat(x["date"]) <= end + timedelta(minutes=10)
]
deleted = set()
for x in controls:
    m = re.search(r"CAR (\d+).*TIME .*DELETED.*LAP (\d+)", x.get("message") or "")
    if m:
        deleted.add(tuple(map(int, m.groups())))
drivers = {x["driver_number"]: x for x in data["drivers"]}
rows = []
for result in data["session_result"]:
    n = result["driver_number"]
    dl = sorted(
        [x for x in laps if x["driver_number"] == n], key=lambda x: x["lap_number"]
    )
    pit = [
        x
        for x in data["pit"]
        if x["driver_number"] == n and start <= datetime.fromisoformat(x["date"]) <= end
    ]
    pitlaps = {x["lap_number"] for x in pit}
    valid = [
        x
        for x in dl
        if x.get("lap_duration")
        and x["lap_duration"] > 0
        and (n, x["lap_number"]) not in deleted
    ]
    pace = [
        x["lap_duration"]
        for x in valid
        if x["lap_number"] > 1
        and not x.get("is_pit_out_lap")
        and x["lap_number"] not in pitlaps
    ]
    fastest = min(valid, key=lambda x: x["lap_duration"]) if valid else None
    rows.append(
        dict(
            result,
            name=drivers[n]["full_name"],
            team=drivers[n]["team_name"],
            fastest=fastest["lap_duration"] if fastest else None,
            fastest_lap=fastest["lap_number"] if fastest else None,
            median=statistics.median(pace) if pace else None,
            pace_count=len(pace),
            lap_records=len(dl),
            pits=len(pit),
            stints=sorted(
                [x for x in data["stints"] if x["driver_number"] == n],
                key=lambda x: x["stint_number"],
            ),
            laps=[
                {
                    "lap": x["lap_number"],
                    "time": x.get("lap_duration"),
                    "deleted": (n, x["lap_number"]) in deleted,
                }
                for x in dl
            ],
        )
    )
rows.sort(
    key=lambda x: (x["position"] is None, x["position"] or 999, -x["number_of_laps"])
)
assert len(rows) == len(drivers) == 22
assert {x["driver_number"] for x in rows} == set(drivers)
weather = [
    x for x in data["weather"] if start <= datetime.fromisoformat(x["date"]) <= end
]


def timing(v):
    return "—" if v is None else f"{int(v//60)}:{v%60:06.3f}"


def state(r):
    return (
        "DSQ"
        if r.get("dsq")
        else "DNS"
        if r.get("dns")
        else "DNF"
        if r.get("dnf")
        else "완주"
    )


def gap(r):
    v = r.get("gap_to_leader")
    return (
        "—"
        if v is None
        else "우승"
        if v == 0
        else f"+{v:.3f}s"
        if isinstance(v, (float, int))
        else str(v)
    )


def strategy(r):
    return (
        " → ".join(
            f"{x['compound']} L{x['lap_start']}–{x.get('lap_end') or '?'}"
            for x in r["stints"]
        )
        or "기록 없음"
    )


table = "".join(
    f"""<tr data-search="{escape(r['name']+' '+r['team']).lower()}"><td>{r['position'] or '—'}</td><td><b>#{r['driver_number']} {escape(r['name'])}</b><small>{escape(r['team'])}</small></td><td>{state(r)}</td><td>{r['number_of_laps']}</td><td>{gap(r)}</td><td>{r['points']:g}</td><td>{timing(r['fastest'])}<small>L{r['fastest_lap'] or '—'}</small></td><td>{timing(r['median'])}<small>표본 {r['pace_count']}랩</small></td><td>{r['pits']}</td><td>{r['lap_records']}</td></tr>"""
    for r in rows
)
cards = "".join(
    f"""<article><h3>#{r['driver_number']} {escape(r['name'])}</h3><p>{escape(r['team'])} · {('P'+str(r['position'])) if r['position'] else state(r)} · {r['number_of_laps']}랩 · {r['points']:g}점</p><p>관측 최속 {timing(r['fastest'])} / 중앙값 {timing(r['median'])}</p><p class="strategy">{escape(strategy(r))}</p><small>레이스 시간 내 피트 레인 진입 {r['pits']}회 · 랩 API 기록 {r['lap_records']}건</small></article>"""
    for r in rows
)
events = [
    x
    for x in controls
    if x.get("flag") in ("RED", "CHEQUERED")
    or "SAFETY CAR" in x["message"]
    or "PENALTY" in x["message"]
]
eventhtml = "".join(
    f"<tr><td>{escape(x['date'][11:19])}</td><td>{x.get('lap_number') or '—'}</td><td>{escape(x['message'])}</td></tr>"
    for x in events
)
fastest = min((r for r in rows if r["fastest"]), key=lambda r: r["fastest"])
wet = any(x.get("rainfall") for x in weather)
air = [x["air_temperature"] for x in weather if x.get("air_temperature") is not None]
track = [
    x["track_temperature"] for x in weather if x.get("track_temperature") is not None
]
payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
html = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026 멕시코 GP | 전체 드라이버 분석</title>
<style>
:root{color-scheme:dark;--bg:#0a101c;--panel:#131e30;--line:#2b3a51;--muted:#adbed3;--accent:#6af0cb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f0f5fc;font:16px/1.65 system-ui,sans-serif}main{max-width:1400px;margin:auto;padding:46px 24px}header{border-top:4px solid var(--accent);padding:28px 0}h1{font-size:clamp(30px,5vw,58px);line-height:1.15;margin:12px 0}h2{margin-top:48px}small{display:block;color:var(--muted);font-size:12px}p{color:#c7d5e7}.eyebrow{letter-spacing:3px;color:var(--accent);font-size:13px}.kpis,.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.kpis article, .cards article{padding:20px;background:var(--panel);border:1px solid var(--line);border-radius:12px}.kpis strong{display:block;font-size:26px;color:var(--accent)}.scroll{overflow:auto;border:1px solid var(--line);border-radius:12px}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}th,td{padding:13px;text-align:left;border-bottom:1px solid var(--line)}th{background:#1a293e}tbody tr:hover{background:#19273a}input,select,button{font:inherit;padding:10px 14px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:white;margin:5px 5px 12px 0}input{min-width:270px}button{cursor:pointer}.note{padding:18px;border-left:3px solid #ffcd75;background:#211f24}.strategy{font-size:13px;color:var(--accent)}a{color:var(--accent)}svg{width:100%;min-width:650px;background:var(--panel);border-radius:12px}svg text{fill:var(--muted)}td{font-variant-numeric:tabular-nums}footer{margin-top:40px;color:var(--muted)}@media print{body{background:white;color:black}p,small{color:#333}button,input,select{display:none}article,.kpis article,.cards article,th,svg{background:#fafafa!important;color:black}.cards article{break-inside:avoid}.scroll{overflow:visible}table{white-space:normal;font-size:10px}main{padding:0}.note{background:#fafafa}svg text{fill:#333}a{color:#075c4b}}
</style><main><header><div class="eyebrow">SEONY F1 / RACE INTELLIGENCE</div><h1>멕시코 그랑프리<br>전체 드라이버 레이스 보고서</h1><p>2026.11.01 · Mexico City · OpenF1 세션 11404<br>한국 시간 11월 2일 05:00 / 멕시코 현지 11월 1일 14:00 예정 출발</p><button type="button" onclick="window.print()">인쇄 / PDF 저장</button></header>
<div class="note">이 보고서는 OpenF1 API 응답을 분석한 자료이며, FIA 공식 결과와 별도로 대조하지 않았습니다. API의 세션 예정 종료 시각(22:00 UTC) 이후에도 실제 랩 기록이 있으므로, 분석 시간 범위는 관측된 첫 레이스 랩의 시작부터 마지막 랩의 종료까지로 잡았습니다.</div>
<h2>레이스 핵심 지표</h2><div class="kpis">__KPIS__</div><p>__SUMMARY__</p>
<h2>22명 전체 결과</h2><p>결과 순위는 session_result 응답 기준입니다. 순위가 없는 리타이어 선수는 완료 랩 수가 많은 순서로 나열했으며, 임의로 순위를 매기지 않았습니다.</p><input id="search" type="search" aria-label="선수 또는 팀 검색" placeholder="선수 이름 또는 팀 검색"><div class="scroll"><table><thead><tr><th>순위</th><th>드라이버 / 팀</th><th>상태</th><th>완료 랩</th><th>선두 격차</th><th>점수</th><th>관측 최속</th><th>랩 중앙값</th><th>피트 진입</th><th>랩 기록 수</th></tr></thead><tbody id="results">__TABLE__</tbody></table></div>
<h2>선수별 랩타임 탐색</h2><p>선수를 선택하면 전체 랩타임을 볼 수 있습니다. 느린 랩도 생략하지 않고 그대로 표시합니다. 빨간 점은 race_control에서 삭제 메시지가 확인된 랩입니다. 기록이 없는 랩 앞뒤는 선으로 잇지 않습니다. 점에 마우스를 올리면 기록이 표시됩니다.</p><select id="driver" aria-label="차트 드라이버 선택"></select><div class="scroll"><svg id="chart" viewBox="0 0 1100 360" role="img" aria-label="선택한 드라이버의 랩타임 차트"></svg></div><p id="chartnote"></p>
<h2>전 선수 타이어 전략과 기록</h2><p>스틴트의 랩 범위는 API 원본 그대로입니다. 타이어 교체 횟수와 피트 레인 진입 횟수는 일치하지 않을 수 있습니다.</p><div class="cards">__CARDS__</div>
<h2>레이스 운영 주요 메시지</h2><p>시각은 UTC 기준입니다. 레이스 중과 종료 후 10분 이내의 RED / CHEQUERED 플래그, SAFETY CAR, PENALTY 메시지를 추렸습니다. 반복된 메시지도 원문 그대로 남겼습니다.</p><div class="scroll"><table><thead><tr><th>시각 UTC</th><th>랩</th><th>원문</th></tr></thead><tbody>__EVENTS__</tbody></table></div>
<h2>분석 기준과 데이터 범위</h2><ul><li>관측 최속: 양수 랩타임 중 race_control에서 삭제가 확인된 랩을 제외한 최솟값입니다. 공식 패스티스트 랩 판정과 다를 수 있습니다.</li><li>랩 중앙값: 1랩, 피트 아웃 랩, 피트 진입 랩, 삭제 확인 랩, 시간이 누락된 랩을 제외한 중앙값입니다. SC·VSC·황색기·트래픽 영향은 남아 있으므로 순수 페이스 순위로 해석하지 않습니다.</li><li>피트 진입: 관측된 레이스 시간 안의 pit 이벤트 수입니다. 정차 시간은 피트 레인 통과 시간과 다른 값이므로, 이 보고서는 정차 소요 시간을 추정하지 않습니다.</li><li>완료 랩은 session_result, 랩 기록 수는 laps 응답에서 따로 집계해 누락으로 생긴 차이가 드러나게 했습니다. 기록이 없는 랩을 0초로 대체하지 않았습니다.</li><li>출발 그리드 엔드포인트가 404를 반환해 그리드 대비 순위 변동은 계산하지 않았습니다.</li><li>이 자료는 특정 시점의 스냅샷이며 실시간으로 갱신되지 않습니다. 원본 JSON은 data 폴더에 함께 보관했습니다.</li></ul>
<h2>출처</h2><ul>__SOURCES__</ul><footer>OpenF1 · 비공식 F1 데이터 서비스 / 작성일 2026.11.06 (한국 시간)<br>이 HTML 파일 하나로 인터넷 연결 없이 표·차트·검색을 사용할 수 있습니다. 외부 스크립트나 폰트에 의존하지 않습니다.</footer></main>
<script>const rows=__DATA__;const select=document.getElementById('driver');rows.forEach(r=>{let o=document.createElement('option');o.value=r.driver_number;o.textContent='#'+r.driver_number+' '+r.name;select.append(o)});document.getElementById('search').oninput=e=>{const q=e.target.value.trim().toLowerCase();document.querySelectorAll('#results tr').forEach(r=>r.hidden=!r.dataset.search.includes(q))};
function draw(){const r=rows.find(r=>r.driver_number===+select.value), points=r.laps.filter(x=>Number.isFinite(x.time)&&x.time>0),svg=document.getElementById('chart');if(!points.length){svg.innerHTML='<text x="50" y="60">기록 없음</text>';return}const lo=Math.floor(Math.min(...points.map(x=>x.time))-2),hi=Math.ceil(Math.max(...points.map(x=>x.time))+2),maxlap=Math.max(71,...r.laps.map(x=>x.lap)),X=l=>65+(l-1)/(maxlap-1)*1000,Y=t=>300-(t-lo)/(hi-lo)*265;let s='';for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5,y=Y(v);s+=`<line x1="65" y1="${y}" x2="1065" y2="${y}" stroke="#304057"/><text x="8" y="${y+5}" fill="#adbed3" font-size="13">${v.toFixed(1)}s</text>`}for(let l=1;l<=maxlap;l+=10)s+=`<text x="${X(l)}" y="330" fill="#adbed3" font-size="13">L${l}</text>`;let prev=null;for(const p of r.laps){if(!Number.isFinite(p.time)||p.time<=0){prev=null;continue}if(prev&&p.lap===prev.lap+1)s+=`<line x1="${X(prev.lap)}" y1="${Y(prev.time)}" x2="${X(p.lap)}" y2="${Y(p.time)}" stroke="#6af0cb" stroke-width="1.5"/>`;s+=`<circle cx="${X(p.lap)}" cy="${Y(p.time)}" r="4" fill="${p.deleted?'#ff7373':'#6af0cb'}"><title>L${p.lap}: ${p.time.toFixed(3)}초${p.deleted?' (삭제 확인)':''}</title></circle>`;prev=p}svg.innerHTML=s;document.getElementById('chartnote').textContent=r.name+' · 표시 '+points.length+'개 랩 · 공식 완료 '+r.number_of_laps+'랩'}select.onchange=draw;draw();</script></html>"""
kpis = [
    ("우승", rows[0]["name"]),
    ("우승 기록", timing(rows[0]["duration"])),
    ("1·2위 격차", f"{rows[1]['gap_to_leader']:.3f}초"),
    ("전체 참가", f"{len(rows)}명 / {sum(state(r)=='완주' for r in rows)}명 완주"),
    ("관측 최속 랩", f"{timing(fastest['fastest'])} · #{fastest['driver_number']}"),
    ("기록 규모", f"{len(laps):,}개 랩"),
]
summary = f"API 결과상 {rows[0]['name']} 선수가 우승했고, {rows[1]['name']} 선수가 {rows[1]['gap_to_leader']:.3f}초 차로 2위, {rows[2]['name']} 선수가 3위입니다. {sum(bool(r.get('dnf')) for r in rows)}명은 DNF로 기록됐습니다. 레이스 중 날씨 관측은 {len(weather)}건이며, 기온 {min(air):.1f}–{max(air):.1f}℃, 노면 {min(track):.1f}–{max(track):.1f}℃, 강우 감지 {'있음' if wet else '없음'}입니다."
replacements = {
    "__KPIS__": "".join(
        f"<article><small>{k}</small><strong>{escape(v)}</strong></article>"
        for k, v in kpis
    ),
    "__SUMMARY__": escape(summary),
    "__TABLE__": table,
    "__CARDS__": cards,
    "__EVENTS__": eventhtml,
    "__DATA__": payload,
    "__SOURCES__": "".join(
        f'<li><a href="https://api.openf1.org/v1/{k}?session_key=11404">OpenF1 / {k}</a> · {len(v)}건</li>'
        for k, v in data.items()
    ),
}
for key, value in replacements.items():
    html = html.replace(key, value)
out = ROOT / "mexico-grand-prix-2026.html"
out.write_text(html, encoding="utf-8")
print(out)
print(
    f"Validated {len(rows)} drivers, {len(laps)} laps, {len(events)} control messages, {len(deleted)} deleted lap references"
)
