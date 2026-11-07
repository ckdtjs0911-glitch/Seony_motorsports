"""Collect and render a complete OpenF1 weekend. Run with --help for options."""

import argparse
import html
import json
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from race_events import render_race_events

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from openf1.util import openf1_client  # noqa: E402

SESSION_NAMES = ("Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race")
LABELS = dict(zip(SESSION_NAMES, ("프랙티스 1", "프랙티스 2", "프랙티스 3", "퀄리파잉", "레이스")))
ENDPOINTS = ("drivers", "session_result", "laps", "stints", "pit", "race_control")
RETRY_STATUS = (429, 500, 502, 503, 504)
ROOT = Path(__file__).resolve().parents[1]
ENCODING = "utf-8"


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch(endpoint, params):
    for attempt in range(4):
        try:
            value = openf1_client.get("v1/" + endpoint, params=params)
            if not isinstance(value, list):
                raise ValueError(f"{endpoint}: expected an array")
            time.sleep(0.4)
            return value
        except requests.HTTPError as exc:
            response = exc.response
            if response is None or response.status_code not in RETRY_STATUS:
                raise
            if attempt == 3:
                raise
            delay = response.headers.get("Retry-After", "")
            time.sleep(min(60, int(delay)) if delay.isdigit() else 2 ** (attempt + 1))
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def load_json(path):
    return json.loads(path.read_text(encoding=ENCODING))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding=ENCODING
    )
    temporary.replace(path)


def seconds(value):
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        return "—"
    return f"{int(value // 60)}:{value % 60:06.3f}"


def esc(value):
    return html.escape(str(value))


def display_time(value):
    """Format an ISO timestamp as 'YYYY-MM-DD HH:MM UTC'; keep other text as is."""
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = stamp(str(value))
        except ValueError:
            return str(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def anchor(name):
    return name.replace(" ", "-")


def deleted_laps(messages):
    deleted = set()
    for message in messages:
        match = re.search(
            r"CAR (\d+).*TIME .*DELETED.*LAP (\d+)", message.get("message") or ""
        )
        if match:
            deleted.add(tuple(map(int, match.groups())))
    return deleted


def result_status(result):
    if result.get("dsq"):
        return "DSQ"
    if result.get("dns"):
        return "DNS"
    if result.get("dnf"):
        return "DNF"
    return "기록 있음" if result else "결과 대기"


def qualifying_phase(q):
    if q[2] is not None:
        return "Q3 기록"
    if q[1] is not None:
        return "Q2 기록 / Q3 없음"
    if q[0] is not None:
        return "Q1 기록 / Q2 없음"
    return "단계 자료 없음"


def format_gap(gap):
    if isinstance(gap, list):
        return " / ".join(str(x) if x is not None else "—" for x in gap)
    if isinstance(gap, (float, int)) and not isinstance(gap, bool):
        return f"+{gap:.3f}s"
    return "—" if gap is None else gap


def tyre_for_lap(stints, lap_number):
    """Only explicit, unambiguous stint ranges establish a lap's tyre."""
    compounds = {
        str(stint.get("compound") or "UNKNOWN").upper()
        for stint in stints
        if isinstance(stint.get("lap_start"), int)
        and isinstance(stint.get("lap_end"), int)
        and stint["lap_start"] <= lap_number <= stint["lap_end"]
    }
    return compounds.pop() if len(compounds) == 1 else "UNKNOWN"


def render_verdicts(name, rows):
    available = [row["fastest"] for row in rows if row["fastest"] is not None]
    best = min(available) if available else None
    lines = []
    for row in rows:
        if row["status"] in ("DNF", "DNS", "DSQ"):
            text = f"{row['status']}로 기록됐으며, 완료 랩은 {row['completed'] if row['completed'] is not None else '미확인'}랩입니다."
        elif row["fastest"] is None:
            text = "유효한 관측 랩타임이 없어 페이스 평가는 보류합니다."
        elif name == "Race":
            rank = (
                f"API 결과 P{row['position']}"
                if row["position"] is not None
                else "API 순위 미제공"
            )
            text = f"{rank} · 관측 최속 {seconds(row['fastest'])}, 피트 레인 진입 {row['pits']}회가 기록됐습니다."
        else:
            delta = row["fastest"] - best
            assessment = "관측 최속 기준 선두" if delta == 0 else f"세션 관측 최속보다 {delta:.3f}초 느림"
            text = f"{assessment} · 최속 {seconds(row['fastest'])}, {row['records']}개 랩 기록으로 비교한 결과입니다."
        rank = row["position"] if row["position"] is not None else "—"
        search = esc((row["name"] + " " + row["team"]).lower())
        lines.append(
            f'<tr data-search="{search}"><td>{rank}</td><td><b>#{row["number"]} {esc(row["name"])}</b><small>{esc(row["team"])}</small></td><td class="verdict-text">{esc(text)}</td></tr>'
        )
    return (
        '<h3>선수별 한줄 평</h3><p class="meta">관측 기록에 근거한 자동 요약입니다. 연료량·타이어·트래픽을 보정한 실력 평가는 아닙니다. 10명씩 넘겨 볼 수 있습니다.</p>'
        '<div class="scroll result-table driver-verdict-table"><table><thead><tr><th>API 순위</th><th>드라이버 / 팀</th><th>기록 기반 한줄 평</th></tr></thead><tbody>'
        + "".join(lines)
        + "</tbody></table></div>"
    )


def summarize(snapshot):
    data = snapshot["data"]
    drivers = {x["driver_number"]: x for x in data.get("drivers", [])}
    results = {x["driver_number"]: x for x in data.get("session_result", [])}
    all_laps = data.get("laps", [])
    numbers = set(drivers) | set(results) | {x["driver_number"] for x in all_laps}
    deleted = deleted_laps(data.get("race_control", []))
    starts = [stamp(x["date_start"]) for x in all_laps if x.get("date_start")]
    start = min(starts) if starts else None
    ends = [
        stamp(x["date_start"]) + timedelta(seconds=x.get("lap_duration") or 0)
        for x in all_laps
        if x.get("date_start")
    ]
    end = max(ends) if ends else None
    rows = []
    for number in numbers:
        driver = drivers.get(number, {})
        result = results.get(number, {})
        laps = sorted(
            [x for x in all_laps if x["driver_number"] == number],
            key=lambda x: x["lap_number"],
        )
        pits = [
            x
            for x in data.get("pit", [])
            if x["driver_number"] == number
            and start
            and end
            and x.get("date")
            and start <= stamp(x["date"]) <= end
        ]
        pit_laps = {x["lap_number"] for x in pits}
        valid = [
            x
            for x in laps
            if isinstance(x.get("lap_duration"), (float, int))
            and x["lap_duration"] > 0
            and (number, x["lap_number"]) not in deleted
        ]
        clean = [
            x
            for x in valid
            if x["lap_number"] > 1
            and not x.get("is_pit_out_lap")
            and x["lap_number"] not in pit_laps
        ]
        by_compound = []
        stints = sorted(
            [x for x in data.get("stints", []) if x["driver_number"] == number],
            key=lambda x: x["stint_number"],
        )
        for stint in stints:
            first = stint.get("lap_start")
            last = stint.get("lap_end") or -1
            samples = [
                x["lap_duration"]
                for x in clean
                if first is not None and first <= x["lap_number"] <= last
            ]
            by_compound.append(
                dict(
                    stint,
                    sample_count=len(samples),
                    median=statistics.median(samples) if samples else None,
                )
            )
        fastest = min(valid, key=lambda x: x["lap_duration"]) if valid else None
        durations = result.get("duration")
        rows.append(
            {
                "number": number,
                "name": driver.get("full_name", f"Driver {number}"),
                "team": driver.get("team_name", "팀 정보 없음"),
                "position": result.get("position"),
                "status": result_status(result),
                "completed": result.get("number_of_laps"),
                "points": result.get("points"),
                "gap": result.get("gap_to_leader"),
                "duration": durations,
                "q": (durations + [None] * 3)[:3]
                if isinstance(durations, list)
                else [None] * 3,
                "fastest": fastest["lap_duration"] if fastest else None,
                "median": statistics.median(x["lap_duration"] for x in clean)
                if clean
                else None,
                "samples": len(clean),
                "pits": len(pits),
                "records": len(laps),
                "stints": by_compound,
                "laps": [
                    {
                        "lap": x["lap_number"],
                        "time": x.get("lap_duration"),
                        "s1": x.get("duration_sector_1"),
                        "s2": x.get("duration_sector_2"),
                        "s3": x.get("duration_sector_3"),
                        "tyre": tyre_for_lap(stints, x["lap_number"]),
                        "deleted": (number, x["lap_number"]) in deleted,
                    }
                    for x in laps
                ],
            }
        )
    rows.sort(
        key=lambda x: (
            x["position"] is None,
            x["position"] or 999,
            x["fastest"] or float("inf"),
            x["number"],
        )
    )
    return rows


def or_dash(value):
    return "—" if value is None else value


def render_table(name, rows):
    bests = [r["fastest"] for r in rows if r["fastest"] is not None]
    best = min(bests) if bests else None
    head = (
        "<th>Q1</th><th>Q2</th><th>Q3</th><th>기록 단계</th>"
        if name == "Qualifying"
        else "<th>관측 최속</th><th>최속 대비</th>"
    )
    records = []
    for row in rows:
        if name == "Qualifying":
            q = row["q"]
            extra = "".join(f"<td>{seconds(v)}</td>" for v in q)
            extra += f"<td>{qualifying_phase(q)}</td>"
        else:
            delta = (
                f'+{row["fastest"] - best:.3f}s'
                if row["fastest"] is not None and best is not None
                else "—"
            )
            extra = f'<td>{seconds(row["fastest"])}</td><td>{delta}</td>'
        search = esc((row["name"] + " " + row["team"]).lower())
        records.append(
            f'<tr data-search="{search}">'
            f'<td>{or_dash(row["position"])}</td>'
            f'<td><b>#{row["number"]} {esc(row["name"])}</b>'
            f'<small>{esc(row["team"])}</small></td>'
            f'<td>{esc(row["status"])}</td>{extra}'
            f'<td>{seconds(row["median"])}<small>표본 {row["samples"]}랩</small></td>'
            f'<td>{or_dash(row["completed"])} / {row["records"]}</td>'
            f'<td>{esc(format_gap(row["gap"]))}</td>'
            f'<td>{or_dash(row["points"])}</td>'
            f'<td>{row["pits"]}</td></tr>'
        )
    return (
        '<div class="scroll result-table"><table><thead><tr><th>API 순위</th><th>드라이버 / 팀</th>'
        f"<th>상태</th>{head}<th>랩 중앙값</th><th>완료 / 기록 랩</th>"
        "<th>API 선두 격차</th><th>점수</th><th>피트 진입</th></tr></thead>"
        f'<tbody>{"".join(records)}</tbody></table></div>'
    )


def render_stints(rows):
    cards = []
    for row in rows:
        items = "".join(
            f'<li>{esc(s.get("compound") or "UNKNOWN")} '
            f'L{or_dash(s.get("lap_start"))}–{s.get("lap_end") or "?"} · '
            f'중앙값 {seconds(s["median"])} · 표본 {s["sample_count"]}랩</li>'
            for s in row["stints"]
        )
        cards.append(
            f'<article><h3>#{row["number"]} {esc(row["name"])}</h3>'
            f'<ul>{items or "<li>스틴트 데이터 없음</li>"}</ul></article>'
        )
    return (
        "<details><summary>전체 선수 타이어 스틴트 · 롱런 참고 지표</summary>"
        f'<div class="cards">{"".join(cards)}</div></details>'
    )


STYLE = """html{color-scheme:dark}body{background:#0b1321;color:#edf4fc;font:15px/1.7 system-ui,sans-serif;margin:0}main{max-width:1500px;margin:auto;padding:36px 22px}h1{font-size:clamp(28px,5vw,40px);line-height:1.25}h2{margin-top:48px;border-top:2px solid #335170;padding-top:22px}p,small{color:#b7c9df}small{display:block}a{color:#6deac9}.eyebrow{letter-spacing:2px;color:#6deac9;font-size:13px}.meta{font-size:13px}.notice{padding:16px;background:#342b20;border-left:3px solid #f1c472}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:11px;border-bottom:1px solid #314158;text-align:left}tbody tr:hover{background:#13203a}th,article{background:#152339}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}article{padding:16px;border-radius:10px}article ul{padding-left:18px;margin:0}input,select,button{background:#152339;color:white;border:1px solid #46617d;padding:10px;margin:6px 6px 6px 0;font:inherit;border-radius:6px}input{min-width:260px}button{cursor:pointer}svg{width:100%;min-width:650px;background:#152339}svg text{fill:#b7c9df;font-size:13px}details{margin:20px 0}summary{cursor:pointer;color:#6deac9}@media print{html{color-scheme:light}body{background:white;color:black}small,p{color:#333}button,input,select{display:none}th,article,svg{background:#eee}svg text{fill:#333}.scroll{overflow:visible}table{font-size:8px;white-space:normal}article{break-inside:avoid}a{color:#15584a}}"""

METHODOLOGY = (
    "순위·완료 랩·점수·격차는 session_result 원본 값입니다. API가 순위를 제공하지 않으면 임의로 순위를 매기지 않습니다.",
    "퀄리파잉 Q1/Q2/Q3 기록은 API의 duration 배열만 사용합니다. 특정 단계 기록이 비어 있다는 이유만으로 탈락을 단정하지 않으며, 미진출·미출전·기록 삭제를 구분하려면 공식 판정과 대조해야 합니다.",
    "관측 최속은 양수 랩타임 중 race_control에서 삭제가 확인된 랩을 제외한 최솟값입니다. 공식 유효 랩 판정과 다를 수 있습니다.",
    "랩 중앙값과 스틴트 중앙값은 1랩, 피트 아웃 랩, 피트 진입 랩, 삭제 확인 랩, 시간이 누락된 랩을 제외하고 계산합니다. 연료량·트래픽·SC·VSC·트랙 변화는 보정하지 않으므로 순수 페이스나 롱런 우열을 단정할 수 없습니다. 스틴트별 표본 수를 함께 표시합니다.",
    "피트 진입 수는 관측된 랩의 시간 범위 안에서만 집계하며, 타이어 교체 횟수나 실제 정차 시간을 뜻하지 않습니다.",
    "공식 완료 랩(session_result)과 관측 랩 기록 수(laps)는 따로 집계합니다. 누락된 값은 0초나 0랩으로 바꾸지 않습니다.",
    "스프린트 주말처럼 프랙티스 2·3이 열리지 않으면 '일정 없음'으로 표시합니다. 이 보고서는 지정된 5개 세션만 다루며 스프린트는 포함하지 않습니다.",
    "원본 데이터와 수집 시각은 세션별 JSON 스냅샷에 보존합니다. 라이브 세션 중 공개 API 접근이 막히면 기존 스냅샷을 유지하고 다음 예약 실행에서 다시 조회합니다.",
)

CHART_CSS = ROOT / "tools" / "report_charts.css"
CHART_JS = ROOT / "tools" / "report_charts.js"

CHART_SECTION = """<section id="lap-sector-analysis" class="chart-workspace" style="scroll-margin-top:24px"><div class="chart-kicker">SESSION TELEMETRY</div><h2>랩타임 &amp; 섹터 분석</h2><div id="session-tabs" class="session-tabs" role="tablist" aria-label="세션 선택"></div><div id="chart-panel" role="tabpanel"><div class="chart-toolbar"><label for="chart-search">선수 / 팀 검색</label><input id="chart-search" type="search" placeholder="예: 노리스, 멕라렌, McLaren" aria-label="차트 선수 또는 팀 검색"><select id="chart-driver" aria-label="드라이버 선택"></select><span id="chart-search-status" class="meta" role="status" aria-live="polite"></span></div><p id="chart-summary" class="chart-caption"></p><article class="chart-card"><h3>랩타임 <small>점에 마우스를 올리거나 터치하면 0.001초 단위 기록이 표시됩니다</small></h3><div class="scroll"><svg id="chart-time" viewBox="0 0 1100 320" role="img" aria-label="랩타임 차트"></svg></div></article><h3 class="sector-heading">섹터별 선수 시간</h3><p class="sector-hint">같은 세션·드라이버의 섹터 1·2·3 기록입니다. 기록이 없는 랩 앞뒤는 선으로 잇지 않습니다. 타이어는 스틴트의 명시된 랩 범위로 연결하며, 범위가 겹치거나 없으면 미확인입니다.</p><article class="chart-card"><h3>섹터 1</h3><div class="scroll"><svg id="chart-s1" viewBox="0 0 1100 320" role="img" aria-label="섹터 1 차트"></svg></div></article><article class="chart-card"><h3>섹터 2</h3><div class="scroll"><svg id="chart-s2" viewBox="0 0 1100 320" role="img" aria-label="섹터 2 차트"></svg></div></article><article class="chart-card"><h3>섹터 3</h3><div class="scroll"><svg id="chart-s3" viewBox="0 0 1100 320" role="img" aria-label="섹터 3 차트"></svg></div></article></div><p class="chart-caption">점 색상은 사용 타이어를 나타내며, 빨간 테두리는 삭제가 확인된 랩입니다 · 키보드 Tab으로 점을 선택할 수 있습니다 · 느린 랩도 생략하지 않고 표시합니다</p></section><div id="chart-tooltip" class="chart-tooltip" role="status" aria-live="polite" hidden></div>"""


def render(snapshots, output, now=None):
    now = now or datetime.now(timezone.utc)
    sections, chart_data, summary = [], [], []
    for item in snapshots:
        session = item["session"]
        name = session["session_name"]
        label = LABELS.get(name, name)
        data = item.get("data", {})
        rows = summarize(item) if data else []
        count = f"{len(rows)}명" if rows else "데이터 없음"
        summary.append(
            f'<li><a href="#{anchor(name)}">{label}</a> · {count} · {esc(item["status"])}</li>'
        )
        fetched = item.get("fetched_at")
        body = (
            f'<h2 id="{anchor(name)}">{label}</h2>'
            f'<p class="meta">{esc(item["status"])} · session_key {esc(session.get("session_key", "—"))}'
            f' · 수집 시각 {esc(display_time(fetched) if fetched else "—")}</p>'
        )
        if item.get("error"):
            body += (
                f'<p class="notice">이번 갱신에 실패했습니다({esc(item["error"])}). '
                "이전에 성공한 스냅샷이 있으면 그 데이터를 표시합니다.</p>"
            )
        if not rows:
            sections.append(
                body + "<p>아직 수집된 데이터가 없습니다. 세션이 열리지 않았거나 데이터 제공을 기다리는 중입니다.</p>"
            )
            continue
        body += (
            render_table(name, rows) + render_verdicts(name, rows) + render_stints(rows)
        )
        body += render_race_events(item, rows)
        chart_data.extend(dict(row, session=label) for row in rows)
        sections.append(body)
    location = next(
        (
            x["session"].get("location")
            for x in snapshots
            if x["session"].get("location")
        ),
        "Grand Prix",
    )
    meeting = next(
        (
            s["session"].get("meeting_key")
            for s in snapshots
            if s["session"].get("meeting_key")
        ),
        "",
    )
    safe_json = json.dumps(chart_data, ensure_ascii=False).replace("</", "<\\/")
    methodology = "".join(f"<li>{text}</li>" for text in METHODOLOGY)
    chart_css = CHART_CSS.read_text(encoding=ENCODING)
    chart_js = CHART_JS.read_text(encoding=ENCODING).replace("REPORT_ROWS", safe_json)
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(location)} · F1 주말 전체 선수 보고서</title>
<style>{STYLE}</style></head><body>
<main><header><p class="eyebrow">SEONY F1 / WEEKEND REPORT</p><h1>{esc(location)} · 주말 전체 선수 보고서</h1><p>프랙티스 1·2·3 + 퀄리파잉 + 레이스<br>생성 시각 {display_time(now)} · 데이터 출처 OpenF1 API</p><button type="button" onclick="document.querySelectorAll('details').forEach(d=>d.open=true);window.print()">인쇄 / PDF 저장</button></header>
<p class="notice">OpenF1 API 데이터로 만든 보고서이며, FIA 공식 결과와 별도로 대조하지 않았습니다. 데이터 대기·누락·갱신 실패는 구분해 표시합니다. 각 세션의 선수 목록은 drivers·session_result·laps 응답에 나온 선수를 모두 합친 것입니다. 일정에 따라 아직 열리지 않은 세션이 있을 수 있습니다.</p>
<ul>{"".join(summary)}<li><a href="#Race">레이스 주요 상황 · 리타이어</a></li><li><a href="#lap-sector-analysis">랩타임 &amp; 섹터 분석</a> · 세션별 랩·섹터·타이어 차트</li></ul><input id="search" type="search" placeholder="선수 / 팀 검색 (예: 노리스, 멕라렌)" aria-label="선수 또는 팀 검색">{"".join(sections)}
{CHART_SECTION}
<h2>지표 해석과 한계</h2><ul>{methodology}</ul><h2>출처</h2><p><a href="https://api.openf1.org/v1/sessions?meeting_key={esc(meeting)}">OpenF1 주말 세션 목록</a> · 각 session_key에 대한 drivers, session_result, laps, stints, pit, race_control 엔드포인트<br>이 HTML 파일 하나로 인터넷 연결 없이 표·검색·차트를 사용할 수 있습니다.</p></main>
<style>{chart_css}</style><script>{chart_js}</script></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding=ENCODING)


def collect(meeting_key=None, output_root=None):
    now = datetime.now(timezone.utc)
    sessions = fetch(
        "sessions", {"meeting_key": meeting_key} if meeting_key else {"year": now.year}
    )
    if meeting_key is None:
        past = [
            s
            for s in sessions
            if stamp(s["date_start"]) <= now and s["session_name"] in SESSION_NAMES
        ]
        if not past:
            raise ValueError("No started weekend available for the current year")
        meeting_key = max(past, key=lambda s: stamp(s["date_start"]))["meeting_key"]
    sessions = [s for s in sessions if s["meeting_key"] == meeting_key]
    directory = (output_root or ROOT / "reports") / f"weekend-{meeting_key}"
    save_json(directory / "sessions.json", sessions)
    snapshots, errors = [], []
    for name in SESSION_NAMES:
        candidates = [s for s in sessions if s["session_name"] == name]
        if not candidates:
            snapshots.append(
                {
                    "session": {"session_name": name, "meeting_key": meeting_key},
                    "status": "일정 없음 / API 목록에 없음",
                    "data": {},
                }
            )
            continue
        session = max(candidates, key=lambda s: stamp(s["date_start"]))
        path = directory / "data" / f'{session["session_key"]}.json'
        previous = load_json(path) if path.exists() else None
        if session.get("is_cancelled"):
            snapshots.append({"session": session, "status": "취소", "data": {}})
            continue
        if now < stamp(session["date_end"]) + timedelta(minutes=30):
            snapshots.append(
                previous
                or {
                    "session": session,
                    "status": "수집 대기 (세션 종료 30분 후 시작)",
                    "data": {},
                }
            )
            continue
        try:
            data = {
                endpoint: fetch(endpoint, {"session_key": session["session_key"]})
                for endpoint in ENDPOINTS
            }
            if not data["drivers"] or not data["laps"] or not data["session_result"]:
                raise ValueError(
                    "Required driver, lap or result data not available yet"
                )
            snapshot = {
                "session": session,
                "status": "수집 완료 (OpenF1 기준)",
                "fetched_at": now.isoformat(),
                "data": data,
            }
            save_json(path, snapshot)
        except (requests.RequestException, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            errors.append(f"{name}: {error}")
            snapshot = dict(previous) if previous else {"session": session, "data": {}}
            snapshot.update(status="갱신 실패 / 재시도 대기", error=error)
        snapshots.append(snapshot)
    render(snapshots, directory / "weekend-report.html", now)
    print(directory / "weekend-report.html")
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


def load_offline(directory):
    snapshots = [load_json(p) for p in sorted((directory / "data").glob("*.json"))]
    snapshots = [s for s in snapshots if isinstance(s, dict) and "session" in s]
    if not snapshots:
        raise ValueError("No session snapshots found")
    by_name = {s["session"]["session_name"]: s for s in snapshots}
    return [
        by_name.get(
            n,
            {"session": {"session_name": n}, "status": "로컬 스냅샷 없음", "data": {}},
        )
        for n in SESSION_NAMES
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meeting",
        type=int,
        help="OpenF1 meeting_key; default: most recent started weekend",
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--offline",
        type=Path,
        help="Render an existing weekend directory without network access",
    )
    args = parser.parse_args()
    try:
        if args.offline:
            render(load_offline(args.offline), args.offline / "weekend-report.html")
            return 0
        return collect(args.meeting, args.output_root)
    except (requests.RequestException, ValueError) as exc:
        print(f"Collection failed; existing reports preserved: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
