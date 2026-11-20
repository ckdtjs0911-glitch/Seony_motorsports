"""Create stage/day/rally guide reports from the official site's public timing feed."""
import json,sys,hashlib,statistics,zipfile
from pathlib import Path
from collections import defaultdict,Counter
from html import escape as e

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from wrc_insights import render as render_intro
CSS=(ROOT/"tools/wrc_report.css").read_text(encoding="utf-8")
STATE=ROOT/".session-monitor/wrc"
RAW=STATE/'snapshots/2026/sardegna'
OUT=ROOT/'reports/wrc/session-guides/2026/sardegna'
MANIFEST=json.loads((STATE/'sources.json').read_text(encoding='utf-8'))
SOURCE={s['name']:s for s in MANIFEST}
OFFICIAL='https://www.wrc.com/en/events/wrc-rally-italia-sardegna-2026/results-wrc-rally-italia-sardegna-2026?page=results&tab=overall'
ARTICLE='https://www.wrc.com/en/news/evans-crowned-2026-wrc-champion-in-sardinia-thriller'
load=lambda n:json.loads((RAW/(n+'.json')).read_text(encoding='utf-8'))

def fmt(ms,places=1):
    if ms is None:return '—'
    if ms<0:return '-'+fmt(-ms,places)
    value=ms/1000;h=int(value//3600);m=int(value%3600//60);s=value%60
    return (f'{h}:{m:02}:' if h else f'{m}:')+f'{s:0{3+places}.{places}f}'

def table(headers,rows,attrs=None):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr'+(attrs[i] if attrs else '')+'>'+''.join('<td>'+str(v)+'</td>' for v in r)+'</tr>' for i,r in enumerate(rows))+'</tbody></table></div>'

def section(i,title,body):return f'<section id="s{i}"><div class="eyebrow">CHAPTER {i:02}</div><h2>{title}</h2>{body}</section>'

JS=r'''
const pristine='<!DOCTYPE html>\n'+document.documentElement.outerHTML,$=s=>document.querySelector(s),D=JSON.parse($('#chart-data').textContent);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function filters(){const group=$('#group').value,q=$('#search').value.trim().toLowerCase();document.querySelectorAll('tr[data-group]').forEach(r=>r.hidden=!!((group&&r.dataset.group!==group)||(q&&!r.textContent.toLowerCase().includes(q))));$('#filter-status').textContent='필터를 적용했습니다. 표의 순위는 원본 전체 순위를 유지합니다.';}
$('#group').addEventListener('change',filters);$('#search').addEventListener('input',filters);
$('#save').addEventListener('click',()=>{const u=URL.createObjectURL(new Blob([pristine],{type:'text/html;charset=utf-8'})),a=document.createElement('a');a.href=u;a.download=document.body.dataset.file;a.click();setTimeout(()=>URL.revokeObjectURL(u),1200)});$('#print').addEventListener('click',()=>print());
$('#copy').addEventListener('click',async()=>{try{await Promise.race([navigator.clipboard.writeText($('#note').value),new Promise((_,reject)=>setTimeout(reject,1000))]);$('#copy-status').textContent='복사했습니다.'}catch{$('#note').select();$('#copy-status').textContent='선택된 노트를 Ctrl+C로 복사하세요.'}});
function draw(){if(!$('#crew'))return;const points=D[$('#crew').value]||[],valid=points.filter(p=>p[1]!=null);if(!valid.length){$('#chart').textContent='선택 범위의 누적 격차 기록이 없습니다.';return;}const max=Math.max(...valid.map(p=>p[1]),1),last=Math.max(...points.map(p=>p[0]),1);let svg=`<svg viewBox="0 0 740 320" role="img" aria-label="SS별 공식 누적 선두 격차"><path d="M70 25V265H710" fill="none" stroke="currentColor"/><text x="0" y="30">${(max/1000).toFixed(1)}s</text><text x="5" y="265">0s</text><text x="70" y="303">SS1</text><text x="640" y="303">SS${last}</text>`;for(const p of valid){const x=70+630*p[0]/last,y=265-225*p[1]/max;svg+=`<circle cx="${x}" cy="${y}" r="5" fill="#c6ed70" tabindex="0"><title>SS${p[0]}: +${(p[1]/1000).toFixed(1)}초 / 종합 ${p[2]}위</title></circle>`;}$('#chart').innerHTML=svg+'</svg>';}
if($('#crew'))$('#crew').addEventListener('change',draw);draw();
'''

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    entries=load('entries');byid={r['entryId']:r for r in entries};it=load('itinerary')
    stages={};days=[]
    for leg in it['itineraryLegs']:
        numbers=[]
        for sec in leg['itinerarySections']:
            for s in sec['stages']:
                stages[s['number']]=dict(s,date=leg['legDate']);numbers.append(s['number'])
        days.append(dict(date=leg['legDate'],numbers=numbers,status=leg['status']))
    assert sorted(stages)==list(range(1,18))
    assert all(s['status'] in ['Completed','Interrupted','Cancelled'] for s in stages.values())
    ss={n:load(f'SS{n:02}-stage') for n in stages};overall={n:load(f'SS{n:02}-overall') for n in stages}
    finals=load('final-results');finalby={r['entryId']:r for r in finals}
    group=lambda eid:byid[eid]['group']['name']
    crew=lambda eid:byid[eid]['driver']['fullName']+' / '+byid[eid]['codriver']['fullName']
    car=lambda eid:byid[eid]['identifier']
    def rowattrs(r):return ' data-group="'+e(group(r['entryId']),quote=True)+'"'
    def timed_table(rows,stage=False,distance=None,daily=False):
        cells=[]
        for r in rows:
            eid=r['entryId'];ent=byid[eid];common=[r.get('position') or '—',e(car(eid)),e(crew(eid)),e(ent['vehicleModel']),e(group(eid))]
            if stage:
                t=r.get('elapsedDurationMs');gap=r.get('diffFirstMs');common+=[fmt(t,3),fmt(gap,3),f'{t/1000/distance:.3f}' if t is not None and distance else '—',f'{gap/1000/distance:.3f}' if gap is not None and distance else '—',e(r['status']),e(r['source'])]
            else:
                common+=[fmt(r['stageTimeMs']),fmt(r['penaltyTimeMs']),fmt(r['totalTimeMs']),fmt(r['diffFirstMs'])]
                if daily:common += [fmt(r['stageTimeMs']+r['penaltyTimeMs']),fmt(r['totalTimeMs']-r['stageTimeMs']-r['penaltyTimeMs'])]
            cells.append(common)
        headers=['원본 순위','번호','드라이버 / 코드라이버','차량','그룹']
        headers+=['SS 시간','SS 선두 격차','주행 초/km','격차 초/km','크루 상태','시간 출처'] if stage else ['구간 합계','페널티','누적 총 시간','누적 선두 격차']
        if daily:headers += ['합계+페널티(독립 계산)','원본 total−독립 계산']
        return table(headers,cells,[rowattrs(r) for r in rows])
    reports=[]
    definitions=[('shakedown','셰이크다운 관측 요약','shakedown',0)]+[(f'SS{n:02}',f'SS{n} · {s["name"]}','stage',n) for n,s in stages.items()]+[(f'day{i}',f'{d["date"]} 일일 요약','day',i) for i,d in enumerate(days,1)]+[('rally-final','대회 종합 요약','final',17)]
    for ident,title,kind,number in definitions:
        current=number if kind=='stage' else max(days[number-1]['numbers']) if kind=='day' else 17 if kind=='final' else 0
        stage=stages.get(current);stage_status=stage['status'] if stage else '공식 런 기록(별도 최종 순위 미확인)'
        sources=['entries','event','itinerary'];graph={};detail='';operations='';more='';summary=''
        if kind=='stage':
            sources += [f'SS{number:02}-stage',f'SS{number:02}-overall']
            records=ss[number];agg=overall[number];valid=[r for r in records if r['status']=='Completed' and r['elapsedDurationMs'] is not None]
            first=valid[0];lead=agg[0];dist=stage['distance'];types=Counter(r['source'] for r in records)
            status_text='중단(Interrupted)' if stage_status=='Interrupted' else '완료(Completed)' if stage_status=='Completed' else stage_status
            summary=f'<p><strong>{e(stage["name"])} · {dist:.2f}km · {e(stage["date"])} · 비포장(Gravel)</strong><br>공식 일정의 구간 상태는 <strong>{e(status_text)}</strong>입니다. 구간 기록 {len(records)}개, 유효 Completed 시간 {len(valid)}개, 해당 SS 뒤 누적 분류 {len(agg)}개를 확보했습니다.</p>'
            summary+=f'<p>시간이 있는 Completed 행 중 첫 행은 #{e(car(first["entryId"]))} {e(crew(first["entryId"]))}, {fmt(first["elapsedDurationMs"],3)}입니다. 이 SS 뒤 종합 선두는 #{e(car(lead["entryId"]))} {e(crew(lead["entryId"]))}, 누적 {fmt(lead["totalTimeMs"])}입니다. 구간 첫 행과 종합 선두는 다른 개념입니다.</p>'
            if stage_status=='Interrupted':summary+='<p><strong>이 구간을 모든 크루가 정상 완주한 SS로 부르지 않습니다.</strong> 중단 상태와 Default·Notional·Assessed 등의 시간 출처를 함께 보세요. 아래 첫 행을 중단 상황을 무시한 단순 “정상 SS 우승”으로 바꾸지 않았습니다.</p>'
            summary+='<p>시간 출처 분포: '+e(' · '.join(f'{k} {v}행' for k,v in types.items()))+'. Notional은 부여 시간, Assessed는 평가 시간, Rally2는 원본 재출발 관련 표기입니다. 출처를 일반 측정 랩처럼 섞어 원인을 추정하지 마세요.</p>'
            if number>1:
                prev={r['entryId']:r for r in overall[number-1]};eid=lead['entryId']
                if eid in prev:summary+=f'<p>현재 종합 선두 크루는 직전 SS 뒤 {prev[eid]["position"]}위에서 이번 SS 뒤 {lead["position"]}위입니다. SS 뒤 분류를 비교한 관측이며, 어떤 코너에서 추월했는지 또는 타이어가 원인이었는지를 뜻하지 않습니다.</p>'
            detail='<h3>이 SS의 기록</h3>'+timed_table(records,True,dist)+'<h3>이 SS 뒤 종합 분류</h3>'+timed_table(agg)
            metric=f'<p>첫 유효 행의 주행 시간/거리는 {first["elapsedDurationMs"]/1000/dist:.3f}초/km입니다. 다른 크루의 격차/거리는 별도 열에 표시합니다. 이 거리 {dist:.2f}km는 공식 일정 API 기준이며 다른 길이·노면·날씨를 완전히 보정한 지표가 아닙니다.</p>'
            sources_for_counts=records
        elif kind in ['day','final']:
            records=load('day'+str(number)) if kind=='day' else finals;agg=overall[current] if kind=='day' else finals
            sources += ['day'+str(number),f'SS{current:02}-overall'] if kind=='day' else ['final-results','penalties','retirements']+[f'SS{n:02}-stage' for n in stages]
            lead=records[0];summary=f'<p>{"당일 원본 집계" if kind=="day" else "대회 전체"} 공식 분류 첫 행은 #{e(car(lead["entryId"]))} {e(crew(lead["entryId"]))}, 총 시간 {fmt(lead["totalTimeMs"])}입니다. 분류 범위는 {len(records)}개 크루입니다. 이 대회의 공식 엔트리는 {len(entries)}개이므로 분류표에 없는 참가자도 별도로 구분합니다.</p>'
            if kind=='day':
                ds=days[number-1];summary+=f'<p>일일 범위는 SS{min(ds["numbers"])}–SS{max(ds["numbers"])}이며 일정의 하루 상태는 {e(ds["status"])}입니다. 하루 분류와 SS{current} 뒤의 대회 전체 누적 분류를 별도 표로 표시합니다.</p>'
                detail='<h3>오늘만의 원본 집계</h3>'+timed_table(records,daily=True)+'<h3>오늘 종료 SS 뒤 대회 누적</h3>'+timed_table(agg)
            else:
                summary+='<p>공식 WRC 결과 페이지는 이 대회를 Completed, 종합 결과를 Final Results로 표시합니다. 대회 우승과 시즌 타이틀은 다른 성과이며, 이 보고서는 시즌 점수·Power Stage·일요일 보너스를 새로 계산하지 않습니다.</p>'
                detail=timed_table(records)
                missing=[r for r in entries if r['entryId'] not in finalby]
                more='<h3>최종 분류에 없는 엔트리</h3>'+table(['번호','크루','그룹','표시 범위'],[[e(r['identifier']),e(crew(r['entryId'])),e(r['group']['name']),'최종 결과표 미포함(사유 별도 확인)'] for r in missing],[rowattrs(r) for r in missing])
                pen=load('penalties');ret=load('retirements');controls={c['controlId']:c for leg in it['itineraryLegs'] for sec in leg['itinerarySections'] for c in sec['controls']}
                operations='<h3>대회 전체 페널티 원장</h3>'+table(['번호','크루','관리 지점','가산','원문 사유'],[[e(car(r['entryId'])),e(crew(r['entryId'])),e(controls.get(r['controlId'],{}).get('code',str(r['controlId']))),fmt(r['penaltyDurationMs']),e(r['reason'])] for r in pen],[rowattrs(r) for r in pen])+'<h3>리타이어·재출발 기록</h3>'+table(['번호','크루','현지 시각','상태','원문 사유'],[[e(car(r['entryId'])),e(crew(r['entryId'])),e(r['retirementDateTimeLocal']),e(r['status']),e(r['reason'])] for r in ret],[rowattrs(r) for r in ret])+'<p>한 크루에 여러 중단·재출발 기록이 있을 수 있습니다. 전체 원장의 기록 수를 리타이어 차량 수와 같다고 보지 않습니다.</p>'
            metric='<p>공식 누적 값은 구간 합계 + 페널티 = 총 시간으로 검산했습니다. Power Stage 원본은 0.001초, 누적 합계는 0.1초 단위이므로 단순 ms 합산과 수십 ms 차이가 있습니다. 최종 44개 분류 모두 원본 SS ms 합계를 100ms 미만 절사한 값과 stageTimeMs가 일치했습니다. 이는 이 데이터의 관측 검산이며, 다른 대회에 일괄 적용하는 규정 해석이 아닙니다.</p>'
            if kind=='day':metric='<p>이 하루 집계 피드는 모든 행의 totalTimeMs가 stageTimeMs와 같고, 페널티가 있는 행에서는 구간 합계+페널티와 일치하지 않습니다. 원본 값·원본 순서를 보존하고 독립 계산값과 차이를 별도 열로 표시했습니다. 이를 페널티까지 반영된 하루 최종 순위로 확정하지 않습니다. SS 뒤 종합 피드와 대회 최종 피드는 별도로 검산했습니다.</p>'
            sources_for_counts=records
        else:
            runs=load('shakedown');groups=defaultdict(list)
            for r in runs:groups[r['entryId']].append(r)
            records=sorted([dict(entryId=eid,best=min(x['runDurationMs'] for x in rr),runs=rr) for eid,rr in groups.items()],key=lambda x:x['best'])
            sources+=['shakedown'];stage_status='공식 런 기록 / 독립 관측 집계'
            summary=f'<p>셰이크다운 Number 1의 공식 런 기록 {len(runs)}개, 크루 {len(records)}개를 집계했습니다. 원본에는 정식 순위 열이 없으므로 각 크루의 최저 runDurationMs로 정렬한 <strong>계산 순서</strong>를 표시합니다. 이를 공식 셰이크다운 최종 순위나 대회 포인트로 부르지 않습니다.</p><p>사전 점검 주행의 한 번 또는 여러 번 기록입니다. SS 누적 총 시간에 더하지 않으며, 거리·노면의 세부 값이 별도 확인되지 않아 초/km를 만들지 않았습니다.</p>'
            detail=table(['계산 순서','번호','크루','그룹','원본 최저 시간','관측 런 수','런별 시간'],[[i+1,e(car(r['entryId'])),e(crew(r['entryId'])),e(group(r['entryId'])),fmt(r['best'],3),len(r['runs']),e(' / '.join(fmt(x['runDurationMs'],3) for x in sorted(r['runs'],key=lambda x:x['runNumber'])))] for i,r in enumerate(records)],[rowattrs(r) for r in records]);metric='<p>이벤트 정보의 roundShakedownTimes 설정과 원본 ms 기록을 구별하기 위해 원본 0.001초를 그대로 보존했습니다. 화면용 반올림과 공식 순위를 따로 확인하기 전에는 이를 공식 순위로 확정하지 않습니다.</p>';sources_for_counts=records
        if current:
            for ent in entries:
                eid=ent['entryId'];graph[str(eid)]=[]
                for n in range(1,current+1):
                    r=next((x for x in overall[n] if x['entryId']==eid),None);graph[str(eid)].append([n,r['diffFirstMs'] if r else None,r['position'] if r else None])
            choices=''.join(f'<option value="{r["entryId"]}">#{e(r["identifier"])} {e(crew(r["entryId"]))}</option>' for r in entries)
            graphhtml=f'<label>누적 격차를 볼 크루 <select id="crew">{choices}</select></label><div id="chart"></div><p class="muted">각 SS 뒤 현재 조회되는 공식 누적 선두 격차입니다. 아래쪽이 선두에 가깝습니다. 중간 분류에 없는 값은 점을 생략하며 0초로 대체하지 않습니다. 과거 당시 저장한 실시간 스냅샷이 아니라 지금 조회한 정정 반영 가능 자료입니다.</p>'
        else:graphhtml=''
        source_keys=list(dict.fromkeys(sources));used=[SOURCE[k] for k in source_keys];fingerprint=hashlib.sha256(''.join(sorted(s['sha256'] for s in used)).encode()).hexdigest()
        sourcehtml='<p>공식 WRC 결과 페이지가 브라우저에서 직접 호출하는 공개 타이밍 피드를 읽었습니다. eventId 647 / rallyId 715 / itineraryId 1495이며, 인증 정보 없이 페이지와 같은 엔트리 범위로 요청했습니다. 원자료·조회 시각·SHA-256을 보존했습니다. 검증 기준일은 2026-11-20입니다.</p><ul>'+''.join(f'<li><a href="{e(s["url"],quote=True)}">{e(s["name"])}</a><br><code>{s["sha256"]}</code></li>' for s in used)+f'</ul><p><a href="{e(OFFICIAL,quote=True)}">공식 결과·SS 상태</a> · <a href="{ARTICLE}">WRC 공식 대회 종료 기사</a> · <a href="https://rallyitaliasardegna.com/">공식 주최자·디지털 게시판</a></p><p>공식 페이지의 종료 상태와 완료된 대회의 SS·일일 분류를 사용합니다. Final Results 화면과 원문 시간 출처를 구분하며, 각 주최자 서명 최종 PDF·모든 위원회 판정과 전수 대조한 문서는 아닙니다. 미출발·중단·부여 시간·최종 분류 미포함을 임의로 정상 완주로 바꾸지 않았습니다.</p>'
        commonops='<p>드라이버는 차량을 운전하고 코드라이버는 앞 도로의 페이스노트와 일정·통과 시각 관리를 돕습니다. 리에종은 일반 도로 이동이며 SS처럼 빠르기를 겨루는 구간이 아닙니다. 루프의 서비스·타이어 선택·출발 순서는 기록을 읽는 조건이지만, 개별 크루의 실제 정비·타이어 선택·날씨·출발 순서를 이번 결과 데이터만으로 확정하지 않습니다.</p><p>표의 페널티는 공식 누적 결과 값입니다. 원장의 미래 기록을 앞선 SS 시점에 미리 적용하지 않도록 대회 전체 페널티·리타이어 원장은 종합 리포트에만 둡니다. 스플릿은 이번 수집 범위에 없으므로 구간 중간 진행을 만들어내지 않습니다.</p>'
        glossary='<dl><dt>SS / 종합</dt><dd>한 구간의 시간 / 해당 시점까지의 누적 합계. SS 1위가 종합 선두라는 뜻은 아닙니다.</dd><dt>Notional / Assessed</dt><dd>원자료가 표시하는 부여·평가 시간. 정상 측정 시간과 구별합니다.</dd><dt>타임컨트롤</dt><dd>지정 시각을 관리하는 통과 지점. 이동 구간의 시간 관리도 경기 운영의 일부입니다.</dd><dt>초/km</dt><dd>주행 시간/거리와 격차/거리를 구분합니다. 조건을 완전히 보정하는 지표가 아닙니다.</dd></dl><details><summary>먼저 도착한 크루가 가장 빠른가요?</summary><p>시간차 출발하므로 각자의 소요 시간과 공식 분류를 봐야 합니다.</p></details><details><summary>SS17은 Power Stage니까 점수를 바로 계산해도 되나요?</summary><p>시즌 규정, 실제 분류·자격·중단 시 점수 성립을 확인해야 합니다. 이 보고서는 점수를 새로 계산하지 않습니다.</p></details><label><input type="checkbox"> SS 상태와 시간 출처를 확인했다.</label><label><input type="checkbox"> 구간·일일·종합 기록을 구분했다.</label>'
        note=f'[WRC 관전 노트]\n2026 Sardegna / {title}\nSS 번호·이름 / 거리 / 노면:\n번호 / 드라이버 / 코드라이버 / 팀:\nSS 시간·순위 / 누적 시간·격차 / 페널티:\nCompleted·Interrupted·DNS / Default·Notional·Assessed:\n확인된 조건 / 해석 / 미확인 사항:\n공식 출처 / 결과 상태 / 조회 시각:'
        body=render_intro('2026 Rally Italia Sardegna',title,kind,records,entries,agg if current else [],stage if kind=='stage' else None)+section(1,'3분 기초 · 대회에서 SS와 크루로','<p>2026 WRC Rally Italia Sardegna · 10월 1–4일 · 비포장 랠리. 공식 엔트리 61개를 기준으로 이 문서의 실제 결과 범위를 분리했습니다. 한 SS·하루·대회 전체는 서로 다른 기록입니다.</p>'+summary)+section(2,'공식 기록을 같은 범위로 읽기','<div class="filters"><label>차량 그룹 <select id="group"><option value="">전체</option>'+''.join(f'<option>{e(g)}</option>' for g in sorted({x['group']['name'] for x in entries}))+'</select></label><label>번호·크루 검색 <input id="search" type="search"></label></div><p id="filter-status" role="status">모든 제공 행을 표시합니다.</p>'+detail+more)+section(3,'누적 격차와 단위 해석',metric+graphhtml)+section(4,'운영·서비스·페널티·재출발',commonops+operations)+section(5,'용어·FAQ·관전 체크리스트',glossary)+section(6,'관전 노트',f'<label for="note">편집 후 복사하세요.</label><textarea id="note">{e(note)}</textarea><button id="copy">노트 복사</button><p id="copy-status" role="status"></p>')+section(7,'공식 출처·계산·확인 한계',sourcehtml)
        style='''select,input[type=search]{max-width:100%;background:var(--panel);color:var(--ink);padding:10px;font:inherit;border:1px solid var(--line);border-radius:6px}.filters{display:flex;flex-wrap:wrap;gap:18px}#crew{width:100%}svg{width:100%;color:var(--ink)}svg text{fill:var(--ink);font:16px system-ui}code{overflow-wrap:anywhere;font-size:11px}dt{color:var(--accent);font-weight:bold}dd{margin-bottom:12px}label{display:block}@media print{.filters,select{display:none}tr[hidden]{display:table-row!important}details>p{display:block!important}svg{max-height:240px}}
'''
        filename=ident+'.html';encoded=json.dumps(graph,ensure_ascii=False).replace('<','\\u003c')
        content=f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WRC Sardegna 2026 · {e(title)}</title><style>{CSS}{style}</style></head><body class="wrc" data-file="{filename}"><main><header><div class="eyebrow">SEONY MOTORSPORTS / WRC</div><h1>SARDEGNA<small>{e(title)}</small></h1><p class="lead">2026 · 대회 → SS → 크루 → 누적 기록</p><div class="meta">확인 2026-11-20 · {e(stage_status if kind=="stage" or kind=="shakedown" else "공식 일일 분류" if kind=="day" else "공식 페이지 Final Results")}</div><button id="save">HTML 저장</button> <button id="print">인쇄 / PDF</button></header><nav aria-label="목차"><a href="#s0">00 기록 쉽게 읽기</a>'+''.join(f'<a href="#s{i}">{t}</a>' for i,t in enumerate(['기초','결과','격차·단위','운영','용어·FAQ','노트','출처'],1))+'</nav>'+body+f'</main><footer>독립 분석 · 공식 WRC 공개 타이밍 자료 기반</footer><script id="chart-data" type="application/json">{encoded}</script><script>{JS}</script></body></html>'
        (OUT/filename).write_text(content,encoding='utf-8')
        reports.append(dict(id=ident,title=title,kind=kind,file=filename,record_count=len(sources_for_counts),stage_status=stage_status,source_fingerprint=fingerprint,report_sha256=hashlib.sha256((OUT/filename).read_bytes()).hexdigest(),sources=[{k:v for k,v in s.items() if k not in ('file','path')} for s in used]))
    assert len(reports)==23
    links=''.join(f'<article><h3>{e(r["title"])}</h3><p>{r["record_count"]}개 기록 · {e(r["stage_status"] if r["kind"] in ["stage","shakedown"] else "일일 분류" if r["kind"]=="day" else "종합 분류")}</p><a href="{r["file"]}">보고서 열기</a></article>' for r in reports)
    (OUT/'index.html').write_text('<!DOCTYPE html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WRC Sardegna 2026 세션 보고서</title><style>'+CSS+'</style><body class="wrc"><main><header><div class="eyebrow">SEONY MOTORSPORTS / WRC</div><h1>SARDEGNA<small>구간·일일·종합 23개 보고서</small></h1><p>2026-10-01–04 · 확인 2026-11-20</p><p>SS 17개, 일일 요약 4개, 대회 종합 1개, 셰이크다운 관측 요약 1개입니다. SS2·SS17의 Interrupted 상태와 부여 시간을 구별했습니다. 셰이크다운은 원본 런의 독립 집계이며 공식 순위로 확정하지 않았습니다.</p><a href="WRC_Sardegna_2026_reports.zip">전체 HTML·출처 메타데이터 ZIP</a></header><section class="cards">'+links+'</section></main></body></html>',encoding='utf-8')
    (OUT/'sources.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(OUT/'WRC_Sardegna_2026_reports.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in OUT.glob('*.html'):z.write(p,p.name)
        z.write(OUT/'sources.json','sources.json')
    print(json.dumps(dict(reports=len(reports),path=str(OUT/'index.html')),ensure_ascii=False))

if __name__=='__main__':build()
