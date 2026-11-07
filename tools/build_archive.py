"""Build one offline HTML archive with year / Grand Prix / session selectors."""
import argparse
import base64
import gzip
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import weekend_report as report
from retention import first_year, prune

COUNTRIES = {
    "Australia": "호주",
    "Bahrain": "바레인",
    "Saudi Arabia": "사우디아라비아",
    "China": "중국",
    "Japan": "일본",
    "USA": "미국",
    "United States": "미국",
    "Italy": "이탈리아",
    "Monaco": "모나코",
    "Spain": "스페인",
    "Canada": "캐나다",
    "Austria": "오스트리아",
    "Great Britain": "영국",
    "United Kingdom": "영국",
    "Belgium": "벨기에",
    "Hungary": "헝가리",
    "Netherlands": "네덜란드",
    "Azerbaijan": "아제르바이잔",
    "Singapore": "싱가포르",
    "Mexico": "멕시코",
    "Brazil": "브라질",
    "Qatar": "카타르",
    "United Arab Emirates": "아부다비",
}


def build(root, since=None):
    prune(root)
    since = max(since or first_year(), first_year())
    catalog_path = root / "catalog" / "sessions.json"
    sessions = report.load_json(catalog_path) if catalog_path.exists() else []
    snapshots = {}
    for path in sorted(root.glob("weekend-*/data/*.json")):
        value = report.load_json(path)
        if isinstance(value, dict) and "session" in value:
            snapshots[value["session"]["session_key"]] = value
    known = {s["session_key"]: s for s in sessions}
    known.update({key: s["session"] for key, s in snapshots.items()})
    now = datetime.now(timezone.utc)
    entries = []
    with tempfile.TemporaryDirectory() as folder:
        for session in sorted(known.values(), key=lambda s: s["date_start"]):
            year = session.get("year") or report.stamp(session["date_start"]).year
            if not since <= year <= now.year:
                continue
            country = COUNTRIES.get(
                session.get("country_name"), session.get("country_name", "대회")
            )
            gp = (
                country
                + " 그랑프리 · "
                + session.get("circuit_short_name", session.get("location", ""))
            )
            label = report.LABELS.get(session["session_name"], session["session_name"])
            entry = {
                "year": year,
                "meeting": session["meeting_key"],
                "key": session["session_key"],
                "gp": gp,
                "session": label,
                "date": session["date_start"],
                "payload": None,
            }
            snapshot = snapshots.get(session["session_key"])
            if snapshot:
                path = Path(folder) / "report.html"
                report.render([snapshot], path)
                page = path.read_text(encoding="utf-8")
                a = page.index("<h1>")
                b = page.index("</h1>", a)
                title = report.esc(f"{year} {gp} · {label}")
                page = page[:a] + "<h1>" + title + page[b:]
                entry["payload"] = base64.b64encode(
                    gzip.compress(page.encode("utf-8"))
                ).decode()
                entry["status"] = "보고서 데이터 수집 완료"
            elif session.get("is_cancelled"):
                entry["status"] = "취소"
            elif report.stamp(session["date_end"]) > now:
                entry["status"] = "예정 / 진행 중"
            else:
                entry["status"] = "미수집 / 원본 수집 대기"
            entries.append(entry)
    if not entries:
        raise ValueError("No sessions found")
    data = json.dumps(entries, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>F1 누적 보고서</title><style>
body{margin:0;background:#0b1321;color:#edf4fc;font:16px/1.6 system-ui}header{padding:26px;max-width:1450px;margin:auto}h1{font-size:clamp(24px,4vw,38px)}.filters{display:flex;gap:16px;flex-wrap:wrap}label{display:flex;flex-direction:column;font-size:13px;color:#b7c9df;gap:6px}select,button{font:inherit;background:#152339;color:white;border:1px solid #45627e;border-radius:8px;padding:12px;max-width:90vw}a{color:#6deac9}iframe{display:block;border:0;width:100%;height:85vh;background:#0b1321}#status{color:#b7c9df}#empty{padding:30px}button:disabled{opacity:.4}</style></head><body><header><p>SEONY F1 / ACCUMULATED ARCHIVE</p><h1 id="title">년도 · 그랑프리 · 세션</h1><div class="filters"><label>년도<select id="year"></select></label><label>그랑프리<select id="gp"></select></label><label>세션<select id="session"></select></label></div><p id="status" role="status"></p><button id="download" disabled>선택한 보고서 HTML 다운로드</button><p>수집한 보고서는 계속 누적됩니다. 목록에 있다는 것이 원본 수집 완료를 뜻하지는 않습니다.<br>차량 텔레메트리 전체 원본은 별도 압축 아카이브로 보관하며 이 HTML에는 보고서용 수치·차트를 담습니다.</p></header><div id="empty"></div><iframe id="report" title="선택한 세션 보고서" sandbox="allow-scripts allow-modals" hidden></iframe>
<script>const entries=ARCHIVE_DATA;const year=document.getElementById('year'),gp=document.getElementById('gp'),session=document.getElementById('session'),frame=document.getElementById('report'),empty=document.getElementById('empty'),download=document.getElementById('download');let generation=0,blobURL=null;
function option(select,value,text){let o=document.createElement('option');o.value=value;o.textContent=text;select.append(o)}
function fillGP(){gp.replaceChildren();const matches=entries.filter(x=>x.year===+year.value);const seen=new Set;for(const e of matches){if(!seen.has(e.meeting)){option(gp,e.meeting,e.gp);seen.add(e.meeting)}}gp.value=matches.filter(x=>x.payload).at(-1)?.meeting||matches.at(-1)?.meeting;fillSessions()}
function fillSessions(){session.replaceChildren();for(const e of entries.filter(x=>x.year===+year.value&&x.meeting===+gp.value))option(session,e.key,`${e.session} · ${e.status}`);session.value=entries.filter(x=>x.meeting===+gp.value&&x.payload).at(-1)?.key||session.value;show()}
async function show(){const token=++generation,e=entries.find(x=>x.key===+session.value);download.disabled=true;if(blobURL){URL.revokeObjectURL(blobURL);blobURL=null}frame.hidden=true;frame.srcdoc='';empty.textContent='';if(!e)return;document.getElementById('title').textContent=`${e.year} ${e.gp} · ${e.session}`;document.getElementById('status').textContent=`${e.status} · 세션 ${e.key}`;if(!e.payload){empty.textContent=e.status==='미수집 / 원본 수집 대기'?'아직 다운로드되지 않은 세션입니다. 수집 완료 후 보고서가 추가됩니다.':e.status;return}try{if(!window.DecompressionStream)throw Error('브라우저에서 gzip 해제를 지원하지 않습니다. 최신 Chrome 또는 Edge를 사용하세요.');const bytes=Uint8Array.from(atob(e.payload),c=>c.charCodeAt(0));const text=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text();if(token!==generation)return;frame.srcdoc=text;frame.hidden=false;blobURL=URL.createObjectURL(new Blob([text],{type:'text/html;charset=utf-8'}));download.disabled=false;download.onclick=()=>{const a=document.createElement('a');a.href=blobURL;a.download=`${e.year}-${e.meeting}-${e.key}.html`;a.click()}}catch(error){if(token===generation)empty.textContent=error.message}}
for(const y of [...new Set(entries.map(x=>x.year))].sort((a,b)=>b-a))option(year,y,y);year.value=entries.filter(x=>x.payload).at(-1)?.year||year.value;year.onchange=fillGP;gp.onchange=fillSessions;session.onchange=show;fillGP();</script></body></html>""".replace(
        "ARCHIVE_DATA", data
    )
    (root / "index.html").write_text(page, encoding="utf-8")
    metadata = [{k: v for k, v in entry.items() if k != "payload"} for entry in entries]
    report.save_json(root / "catalog" / "archive-index.json", metadata)
    print(
        f'Archive: {len(entries)} listed sessions / {sum(bool(e["payload"]) for e in entries)} downloaded reports; {root / "index.html"}'
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=report.ROOT / "reports")
    parser.add_argument("--since", type=int, default=None)
    args = parser.parse_args()
    build(args.reports, args.since)
