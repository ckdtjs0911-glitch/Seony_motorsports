"""Beginner summary and same-class, time-aligned WEC lap comparisons.

Only measured fields are used; no fuel, tyre or pit-cycle correction is inferred.
"""
import html
import json
import math
import statistics
from collections import Counter, defaultdict


def seconds(value):
    try:
        result = 0.0
        for part in str(value).replace("'", ':').split(':'):
            result = result * 60 + float(part)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def prepare(rows, classification=None):
    """Keep car IDs verbatim, gaps in lap numbering, and observed stint boundaries."""
    groups = defaultdict(list)
    for r in rows:
        groups[r['NUMBER']].append(r)
    results = {r['NUMBER']: r for r in (classification or [])}
    cars = []
    for number, laps in groups.items():
        laps.sort(key=lambda r: int(r['LAP_NUMBER']))
        points, segments = [], []
        previous, segment = None, 0
        for r in laps:
            if previous is None or r['DRIVER_NAME'] != previous['DRIVER_NAME'] or previous.get('pit_in') or r.get('pit_seconds') is not None:
                segment += 1
                segments.append(dict(id=segment, driver=r['DRIVER_NAME'], first=int(r['LAP_NUMBER']), last=int(r['LAP_NUMBER'])))
            segments[-1]['last'] = int(r['LAP_NUMBER'])
            elapsed = seconds(r.get('ELAPSED'))
            lap_time = r.get('seconds')
            if lap_time is None:
                lap_time = seconds(r.get('LAP_TIME'))
            eligible = bool(r.get('pace_eligible')) and not (previous and previous.get('pit_in'))
            if lap_time is not None and lap_time > 0:
                points.append(dict(lap=int(r['LAP_NUMBER']), t=elapsed / 60 if elapsed is not None else None,
                                   seconds=lap_time, driver=r['DRIVER_NAME'], segment=segment,
                                   relative=int(r['LAP_NUMBER']) - segments[-1]['first'] + 1,
                                   eligible=bool(eligible), pit=bool(r.get('pit_in')),
                                   flag=r.get('FLAG_AT_FL') or '미제공'))
            previous = r
        c = results.get(number, {})
        cars.append(dict(number=number, category=c.get('CLASS') or laps[0]['CLASS'],
                         team=c.get('TEAM') or laps[0].get('TEAM', ''),
                         result=c, points=points, segments=segments,
                         pit_entries=sum(bool(r.get('pit_in')) for r in laps),
                         driver_changes=sum(a['DRIVER_NAME'] != b['DRIVER_NAME'] for a, b in zip(laps, laps[1:])),
                         flags=dict(Counter(r.get('FLAG_AT_FL') or '미제공' for r in laps))))
    if classification:
        order = {r['NUMBER']: i for i, r in enumerate(classification)}
        cars.sort(key=lambda c: order.get(c['number'], len(order)))
    return cars


def comparison_stats(car, start=0, end=math.inf, segment=None):
    """Reference calculation used to verify browser selection semantics."""
    points = [p for p in car['points'] if p['t'] is not None and start <= p['t'] <= end
              and (segment is None or p['segment'] == segment)]
    times = [p['seconds'] for p in points if p['eligible']]
    return dict(observed=len(points), n=len(times), median=statistics.median(times) if times else None,
                sd=statistics.pstdev(times) if times else None)


def render(entry, rows, classification=None, context=None):
    esc = html.escape
    context = context or {}
    cars = prepare(rows, classification)
    categories = sorted({c['category'] for c in cars} | {r['CLASS'] for r in (classification or [])})
    race = entry['session'].split('_', 1)[-1].casefold() == 'race'
    leaders = []
    for category in categories:
        ranked = [r for r in (classification or []) if r['CLASS'] == category and (not race or r.get('STATUS') == 'Classified')]
        if not ranked:
            continue
        first = ranked[0]
        if race:
            detail = f"분류 {esc(first.get('LAPS', '—'))}랩 · 총 시간 {esc(first.get('TIME', first.get('TOTAL_TIME', '—')))}"
            if len(ranked) > 1:
                second = ranked[1]
                try:
                    lapgap = int(first['LAPS']) - int(second['LAPS'])
                except (ValueError, KeyError):
                    lapgap = None
                a, b = seconds(first.get('TIME', first.get('TOTAL_TIME'))), seconds(second.get('TIME', second.get('TOTAL_TIME')))
                gap = f'{lapgap}랩' if lapgap and lapgap > 0 else f'{b-a:.3f}초' if lapgap == 0 and a is not None and b is not None and b >= a else '미확인'
                detail += f" · 클래스 두 번째 Classified 행 #{esc(second['NUMBER'])}와 {gap}"
        else:
            detail = f"공식 세션 최속 {esc(first.get('TIME', '—'))} · 관측 세션 랩 {esc(first.get('LAPS', '—'))}"
        leaders.append(f'<article><h3>{esc(category)} · #{esc(first["NUMBER"])} {esc(first.get("TEAM", ""))}</h3><p>{detail}</p></article>')
    intro = ('이번 결승은 한 바퀴의 최속보다 정해진 경기 동안의 거리와 공식 분류가 승부를 정합니다.' if race else
             '이번 예선·하이퍼폴은 같은 클래스의 유효 최속과 해당 단계의 진출·출발 위치 경쟁을 먼저 봅니다.' if any(x in entry['session'].lower() for x in ['qualifying', 'hyperpole']) else
             '이번 연습은 한 랩 최고 기록과 연속 주행의 반복성을 나눠 봅니다. 연습 순위로 결승 승부를 확정하지 않습니다.')
    status = context.get('classification_status', '제공된 공식 분류 CSV 기준 · 잠정/최종은 원문 확인')
    payload = json.dumps(cars, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    controls = ''.join(f'<option value="{esc(c, quote=True)}">{esc(c)}</option>' for c in categories)
    penalty = '<ul>' + ''.join('<li>'+esc(n)+'</li>' for n in context.get('penalty_notes', [])) + '</ul>' if context.get('penalty_notes') else '<p>이 요약에는 개별 판정문을 대조한 페널티 목록이 없습니다. 아래 분류의 상태와 출처를 확인하세요.</p>'
    return '<!-- WEC-INSIGHTS-BEGIN -->' + f'''<section id="wec-intro" class="wec-insights">
<div class="eyebrow">CHAPTER 00</div><h2>처음 보는 WEC · 이 세션을 읽는 순서</h2>
<p><strong>여러 종류의 차가 같은 트랙에서 달리고, 여러 드라이버가 한 대를 교대해 운전합니다.</strong> 다른 종류의 차를 추월하는 장면과 같은 클래스 안에서 순위를 다투는 장면을 구분하면 이해하기 쉽습니다.</p>
<p>{intro} <strong>클래스 → 차량 번호·팀 → 같은 시간대의 연속 랩 → 피트·교대 → 공식 결과</strong> 순서로 보세요.</p>
<p class="wec-note">자료 범위: {len(classification or [])}개 분류 행 / {len(rows):,}개 관측 랩 · {esc(status)}. 클래스 첫 행은 원본의 순서를 따른 표시이며, 별도의 공식 클래스 순위 필드가 없는 경우 계산한 표시 순서입니다.</p>
<div class="wec-cards">{''.join(leaders)}</div>
<h3>이번 자료에서 확인할 수 있는 기록 포인트</h3>
<div class="wec-table"><table><thead><tr><th>기록 포인트</th><th>이 보고서에서 보는 방법</th><th>해석 범위</th></tr></thead><tbody>
<tr><td>클래스·분류 랩·공식 상태</td><td>위 클래스 요약과 아래 공식 분류</td><td>전체/클래스, 관측 랩/분류 랩을 구별합니다.</td></tr>
<tr><td>차량별 연속 랩</td><td>아래 같은 클래스 두 차량의 시간대·주행 구간 비교</td><td>중앙값·표본 수·표준편차를 함께 봅니다. 낮은 랩타임이 빠른 기록입니다.</td></tr>
<tr><td>격차</td><td>위 클래스 선두 비교와 공식 표의 GAP_FIRST</td><td>GAP_FIRST는 전체 선두 기준입니다. 피트 사이클을 보정한 실질 격차를 뜻하지 않습니다.</td></tr>
<tr><td>피트·드라이버 교대</td><td>선택 구간의 관측 드라이버, 피트 진입 표시와 교대 횟수</td><td>완료 정차 횟수·작업 시간·타이어 스틴트와 같지 않습니다.</td></tr>
<tr><td>플래그·페널티</td><td>선택 구간의 결승선 플래그 코드와 확인된 원문 메모</td><td>플래그 한 값으로 랩 전체의 상태나 SC/FCY의 손익을 확정하지 않습니다.</td></tr>
</tbody></table></div>
<h3>WEC에 맞춘 차량별 랩타임 비교</h3><p>기본은 <strong>같은 클래스·같은 세션 경과 시간</strong>입니다. 각 차량의 랩 번호가 달라도 같은 시간대에 달린 기록을 비교합니다. 특정 주행 구간을 고르면 교대와 피트 경계를 구별할 수 있습니다.</p>
<div class="wec-controls">
<label>클래스 <select id="wec-category">{controls}</select></label>
<label>차량 A <select id="wec-a"></select></label><label>차량 B <select id="wec-b"></select></label>
<label>A 관측 주행 구간 <select id="wec-seg-a"></select></label><label>B 관측 주행 구간 <select id="wec-seg-b"></select></label>
<label>시작 경과 분 <input id="wec-start" type="number" min="0" step="1" value="0"></label><label>종료 경과 분 <input id="wec-end" type="number" min="0" step="1" value="60"></label>
<label>가로축 <select id="wec-axis"><option value="time">같은 경과 시간(분)</option><option value="relative">주행 구간 안의 랩 순서</option></select></label>
<label>표시 랩 <select id="wec-sample"><option value="eligible">참고 페이스 표본</option><option value="all">모든 관측 랩</option></select></label>
<label><input id="wec-smooth" type="checkbox" checked> 연속 5랩 중앙값 선 표시</label><button id="wec-full-time" type="button">전체 시간 범위</button></div>
<p id="wec-comparison-status" role="status"></p><div id="wec-comparison-chart"></div><div id="wec-comparison-stats"></div>
<p class="wec-note">점은 관측 랩, 선은 같은 주행 구간에서 랩 번호가 연속된 참고 표본 5개의 중앙값입니다. 피트·교대·제외 랩·결측 랩을 건너 연결하지 않습니다. 선택 시간 범위는 각 랩의 결승선 통과 경과 시간 기준입니다. ELAPSED가 없으면 시간 비교에서 제외합니다.</p>
<p class="wec-note">참고 표본은 첫 랩·피트 진입·PIT_TIME 및 그 다음 출차 랩·자료에서 제외된 랩을 빼고 결승선 GF/FF 기록을 사용합니다. 전체 삭제 랩·중립화 구간을 전수 대조한 그린 페이스가 아닙니다. 타이어 열화·연료량·트래픽·작전 의도는 이 차트만으로 확정할 수 없습니다.</p>
<h3>확인된 판정과 아직 모르는 것</h3>{penalty}
<p>실제 급유량·타이어 교체·피트의 트랙 대비 총 손실·SC/FCY 전후 전략 손익은 추가 자료가 없으면 <strong>미확인</strong>으로 남깁니다. 데이터가 없는 항목에 가상의 수치를 채우지 않습니다.</p>
<script id="wec-insights-data" type="application/json">{payload}</script><style>{STYLE}</style><script>{SCRIPT}</script></section><!-- WEC-INSIGHTS-END -->'''


STYLE = '''
.wec-insights{border:1px solid #375666;border-radius:14px;padding:24px!important;overflow:visible!important;margin:28px 0;background:#102536;color:#e7f1f5;line-height:1.8}.wec-insights .eyebrow{color:#67e8ce;letter-spacing:.12em;font-size:13px}.wec-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.wec-cards article{padding:16px;border:1px solid #375666;border-radius:10px}.wec-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.wec-controls label{display:flex;flex-direction:column;gap:6px;font-size:14px}.wec-controls select,.wec-controls input[type=number]{width:100%;max-width:100%;min-width:0;background:#081521;color:#e7f1f5;border:1px solid #48627e;padding:10px;border-radius:6px;font:inherit}.wec-controls input[type=checkbox]{align-self:flex-start}.wec-note{font-size:13px;color:#b8cbd5}.wec-table{max-width:100%;overflow-x:auto}.wec-insights table{min-width:620px;width:100%;font-size:14px}.wec-insights svg{display:block;width:100%;height:auto;background:#081521}.wec-insights svg text{fill:#e7f1f5;font:16px system-ui}.wec-insights circle:focus{outline:none;stroke:white;stroke-width:3}.wec-insights :focus-visible{outline:2px solid #67e8ce;outline-offset:3px}.wec-legend{display:flex;flex-wrap:wrap;gap:18px;font-weight:bold}.wec-insights h3{margin-top:28px}@media(max-width:500px){.wec-insights{padding:16px!important}.wec-controls,.wec-cards{grid-template-columns:1fr}}@media print{.wec-insights{background:white;color:black;border-color:#aaa}.wec-insights .wec-note{color:#333}.wec-controls{display:none!important}.wec-insights article{break-inside:avoid}.wec-insights table{min-width:0}.wec-insights svg{background:white}.wec-insights svg text{fill:black}.wec-table{overflow:visible}}
'''

SCRIPT = r'''
const wiCars=JSON.parse(document.querySelector('#wec-insights-data').textContent);
const wiQ=s=>document.querySelector(s),wiEsc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const wiMedian=a=>{const b=[...a].sort((x,y)=>x-y);return b.length?(b[Math.floor((b.length-1)/2)]+b[Math.floor(b.length/2)])/2:null};
const wiFmt=n=>n==null?'—':`${Math.floor(n/60)}:${(n%60).toFixed(3).padStart(6,'0')}`;
function wiSegments(which){const car=wiCars.find(c=>c.number===wiQ('#wec-'+which).value),box=wiQ('#wec-seg-'+which);box.replaceChildren(new Option('전체 구간',''));if(car)for(const s of car.segments)box.add(new Option(`${s.id} · ${s.driver} · Lap ${s.first}–${s.last}`,String(s.id)));}
function wiClass(){const c=wiCars.filter(c=>c.category===wiQ('#wec-category').value);for(const which of ['a','b']){const s=wiQ('#wec-'+which);s.replaceChildren();for(const car of c)s.add(new Option(`#${car.number} ${car.team}`,car.number));}if(c.length>1)wiQ('#wec-b').selectedIndex=1;wiSegments('a');wiSegments('b');wiDraw();}
function wiDraw(){
 const a=wiCars.find(c=>c.number===wiQ('#wec-a').value),b=wiCars.find(c=>c.number===wiQ('#wec-b').value),box=wiQ('#wec-comparison-chart');
 if(!a||!b){box.textContent='이 클래스에 비교 가능한 차량 기록이 없습니다.';return;}
 let start=Number(wiQ('#wec-start').value),end=Number(wiQ('#wec-end').value);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<start){box.textContent='종료 경과 분을 시작보다 같거나 크게 입력하세요.';wiQ('#wec-comparison-stats').replaceChildren();wiQ('#wec-comparison-status').textContent='시간 범위를 확인하세요.';return;}
 const relative=wiQ('#wec-axis').value==='relative',all=wiQ('#wec-sample').value==='all';
 if(relative&&(!wiQ('#wec-seg-a').value||!wiQ('#wec-seg-b').value)){box.textContent='구간 안의 랩 순서를 비교하려면 A와 B의 관측 주행 구간을 하나씩 선택하세요.';wiQ('#wec-comparison-stats').replaceChildren();wiQ('#wec-comparison-status').textContent='두 주행 구간을 선택하세요.';return;}
 const info=[a,b].map((c,i)=>{const segment=wiQ(i?'#wec-seg-b':'#wec-seg-a').value,rows=c.points.filter(p=>p.t!=null&&p.t>=start&&p.t<=end&&(!segment||String(p.segment)===segment)),eligible=rows.filter(p=>p.eligible),values=eligible.map(p=>p.seconds),median=wiMedian(values),mean=values.reduce((s,n)=>s+n,0)/(values.length||1),sd=values.length?Math.sqrt(values.reduce((s,n)=>s+(n-mean)**2,0)/values.length):null;
 return {car:c,rows,eligible,median,sd,shown:all?rows:eligible};});
 const data=info.flatMap(d=>d.shown),missing=[a,b].reduce((s,c)=>s+c.points.filter(p=>p.t==null).length,0);
 let status=`${a.category} · ${start}–${end}분 · 같은 클래스 #${a.number} / #${b.number} · ELAPSED 없는 관측 랩 ${missing}개 제외.`;
 if(a.number===b.number)status+=' 같은 차량을 선택했습니다.';
 if(info.every(d=>d.median!=null)&&a.number!==b.number){const delta=info[1].median-info[0].median;status+=` 선택 표본 중앙값 B−A=${delta>=0?'+':''}${delta.toFixed(3)}초. 서로 다른 실제 조건과 표본 수를 보정한 성능 차이는 아닙니다.`;}
 wiQ('#wec-comparison-status').textContent=status;
 wiQ('#wec-comparison-stats').innerHTML='<div class="wec-table"><table><thead><tr><th>차량</th><th>관측 / 표본 n</th><th>중앙값</th><th>표준편차</th><th>선택 범위 드라이버</th><th>선택 범위 피트 진입 표시</th><th>차량 전체 관측 교대</th><th>선택 범위 결승선 플래그</th></tr></thead><tbody>'+info.map(d=>{const flags={};for(const p of d.rows)flags[p.flag]=(flags[p.flag]||0)+1;return `<tr><td>#${wiEsc(d.car.number)} ${wiEsc(d.car.team)}</td><td>${d.rows.length} / ${d.eligible.length}</td><td>${wiFmt(d.median)}</td><td>${d.sd==null?'—':d.sd.toFixed(3)+'초'}</td><td>${[...new Set(d.rows.map(p=>p.driver))].map(wiEsc).join(' / ')||'—'}</td><td>${d.rows.filter(p=>p.pit).length}</td><td>${d.car.driver_changes}</td><td>${Object.entries(flags).map(([f,n])=>wiEsc(f)+': '+n).join(', ')||'—'}</td></tr>`}).join('')+'</tbody></table></div>';
 if(!data.length){box.textContent='선택 조건의 표시 가능한 랩이 없습니다. 시간 범위나 표본 조건을 바꾸세요.';return;}
 const xval=p=>relative?p.relative:p.t,xlo=relative?1:start,xhi=relative?Math.max(...data.map(xval),2):Math.max(end,start+1),lo=Math.min(...data.map(p=>p.seconds)),hi=Math.max(...data.map(p=>p.seconds)),pad=Math.max((hi-lo)*.08,.2),ylo=lo-pad,yhi=hi+pad,x=n=>85+640*(n-xlo)/(xhi-xlo||1),y=n=>300-255*(n-ylo)/(yhi-ylo);
 let svg='<svg viewBox="0 0 780 355" role="img" aria-label="같은 클래스 두 차량의 연속 랩타임 비교"><path d="M85 30V300H735" stroke="currentColor" fill="none"/>';
 for(let k=0;k<=4;k++){let v=ylo+(yhi-ylo)*k/4;svg+=`<text x="2" y="${y(v)+5}">${wiFmt(v)}</text>`;}
 for(let k=0;k<=4;k++){let v=xlo+(xhi-xlo)*k/4;svg+=`<text x="${x(v)-10}" y="330">${v.toFixed(relative?0:1)}</text>`;}
 info.forEach((d,i)=>{const color=i?'#ffb268':'#67e8ce',rolling=[];for(const p of d.shown){const label=`${i?'B':'A'} #${d.car.number} / Lap ${p.lap} / ${p.t.toFixed(2)}분 / ${p.driver} / ${wiFmt(p.seconds)} / 구간 ${p.segment} / ${p.eligible?'참고 표본':'표본 제외'} / ${p.flag}`;svg+=`<circle cx="${x(xval(p))}" cy="${y(p.seconds)}" r="${i?4.5:3.5}" fill="${color}" ${i?'stroke="#081521"':''} tabindex="0" aria-label="${wiEsc(label)}"><title>${wiEsc(label)}</title></circle>`;}
 if(wiQ('#wec-smooth').checked){for(let j=4;j<d.eligible.length;j++){const window=d.eligible.slice(j-4,j+1),p=window[4];if(window.every((r,k)=>r.segment===p.segment&&(k===0||r.lap===window[k-1].lap+1)))rolling.push({x:x(xval(p)),y:y(wiMedian(window.map(r=>r.seconds))),lap:p.lap,segment:p.segment});}for(let j=1;j<rolling.length;j++){const p=rolling[j-1],q=rolling[j];if(p.segment===q.segment&&q.lap===p.lap+1)svg+=`<path d="M${p.x} ${p.y}L${q.x} ${q.y}" fill="none" stroke="${color}" stroke-width="3" ${i?'stroke-dasharray="7 4"':''}/>`;}}});
 box.innerHTML=svg+'</svg><div class="wec-legend"><span style="color:#67e8ce">A #'+wiEsc(a.number)+' · 점</span><span style="color:#ffb268">B #'+wiEsc(b.number)+' · 원 테두리 / 점선</span></div><p class="wec-note">가로: '+(relative?'선택 주행 구간 안의 랩 순서':'세션 경과 시간(분)')+' · 세로: 랩타임(분:초), 아래쪽이 빠릅니다. 전체 레이스의 현재 순위나 피트 사이클 보정 격차가 아닙니다.</p>';
}
wiQ('#wec-category').addEventListener('change',wiClass);for(const which of ['a','b'])wiQ('#wec-'+which).addEventListener('change',()=>{wiSegments(which);wiDraw()});for(const selector of ['#wec-seg-a','#wec-seg-b','#wec-axis','#wec-sample','#wec-smooth'])wiQ(selector).addEventListener('change',wiDraw);for(const selector of ['#wec-start','#wec-end'])wiQ(selector).addEventListener('input',wiDraw);
const wiMax=Math.ceil(Math.max(0,...wiCars.flatMap(c=>c.points.filter(p=>p.t!=null).map(p=>p.t))));wiQ('#wec-start').max=wiMax;wiQ('#wec-end').max=wiMax;wiQ('#wec-end').value=Math.min(60,wiMax);wiClass();
wiQ('#wec-full-time').addEventListener('click',()=>{wiQ('#wec-start').value=0;wiQ('#wec-end').value=wiMax;wiDraw()});
'''
