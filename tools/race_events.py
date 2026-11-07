"""Race-only event timeline and retirement list from explicit OpenF1 records."""

from datetime import datetime, timedelta, timezone
from html import escape


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except (ValueError, AttributeError):
        return None


def event_label(record):
    message = (record.get("message") or "").upper()
    flag = (record.get("flag") or "").upper().replace("_", " ")
    if flag == "RED" or "RED FLAG" in message:
        return "레드 플래그"
    if "VIRTUAL SAFETY CAR" in message or message.startswith("VSC "):
        return "VSC 종료 예고" if "ENDING" in message else "VSC"
    if "SAFETY CAR" in message:
        if "IN THIS LAP" in message:
            return "SC 철수 예고"
        if "DEPLOYED" in message:
            return "세이프티카 투입"
        return "세이프티카 안내"
    if flag == "DOUBLE YELLOW" or "DOUBLE YELLOW" in message:
        return "더블 옐로 플래그"
    if flag == "YELLOW" or message.startswith("YELLOW IN "):
        return "옐로 플래그"
    if "RESUMPTION ORDER" in message:
        return "재출발 순서 안내"
    if "WILL RESUME" in message or "WILL RESTART" in message:
        return "재출발 예정"
    if "RESTART" in message or "RESUMED" in message or message == "SESSION RESUMED":
        return "재개 안내"
    if "SUSPENDED" in message or "ABORTED" in message:
        return "세션 중단"
    if flag == "GREEN" and record.get("scope") == "Track":
        return "트랙 그린 플래그"
    if flag == "CHEQUERED":
        return "체커드 플래그"
    return None


def race_events(snapshot):
    if snapshot["session"]["session_name"] != "Race":
        return []
    data = snapshot.get("data", {})
    laps = data.get("laps", [])
    starts = [parse_time(lap.get("date_start")) for lap in laps]
    starts = [time for time in starts if time]
    if not starts:
        return []
    start = min(starts)
    end = max(
        parse_time(lap["date_start"]) + timedelta(seconds=lap.get("lap_duration") or 0)
        for lap in laps
        if parse_time(lap.get("date_start"))
    )
    events = []
    for record in data.get("race_control", []):
        date = parse_time(record.get("date"))
        label = event_label(record)
        if label and date and start <= date <= end:
            events.append(dict(record, label=label))
    return sorted(events, key=lambda record: parse_time(record["date"]))


def render_race_events(snapshot, rows):
    if snapshot["session"]["session_name"] != "Race":
        return ""

    def esc(value):
        return escape(str(value))

    events = race_events(snapshot)
    header = (
        '<section id="race-incidents"><h3>레이스 주요 상황 · 리타이어</h3>'
        '<p class="meta">race_control 원문 기준 · 시각은 UTC · SC 철수 예고·재출발 예정은 실제 재출발과 구분합니다. '
        "그린 플래그만으로 재출발을 단정하지 않습니다. 트랙 구간 번호는 랩타임 섹터 1·2·3과 다를 수 있습니다.</p>"
    )
    body = "<h4>레이스 상황 타임라인</h4>"
    if events:
        body += '<div class="scroll"><table><thead><tr><th>시각 UTC</th><th>랩</th><th>상황</th><th>범위</th><th>원문</th></tr></thead><tbody>'
        for event in events:
            when = (
                parse_time(event["date"])
                .astimezone(timezone.utc)
                .strftime("%m-%d %H:%M:%S")
            )
            scope = event.get("scope") or "—"
            if event.get("sector") is not None:
                scope += f" / 트랙 구간 {event['sector']}"
            lap = event.get("lap_number")
            body += f'<tr><td>{when}</td><td>{lap if lap is not None else "—"}</td><td>{esc(event["label"])}</td><td>{esc(scope)}</td><td class="event-message">{esc(event.get("message") or "—")}</td></tr>'
        body += "</tbody></table></div>"
    else:
        body += "<p>표시할 레이스 상황 메시지가 없습니다. 메시지 누락 가능성이 있어 사건이 없었다는 뜻은 아닙니다.</p>"
    body += "<h4>리타이어 및 미출전·실격</h4>"
    retired = [row for row in rows if row["status"] in ("DNF", "DNS", "DSQ")]
    if retired:
        body += '<p class="meta">DNF는 결과 API 기준입니다. 완료 랩 수·마지막 관측 랩은 리타이어 발생 랩이나 시각이 아닙니다. 원인은 추정하지 않습니다.</p><div class="scroll result-table"><table><thead><tr><th>선수</th><th>상태</th><th>공식 완료 랩</th><th>마지막 관측 랩</th><th>리타이어 시각·원인</th></tr></thead><tbody>'
        for row in retired:
            last = max((lap["lap"] for lap in row["laps"]), default=None)
            search = esc((row["name"] + " " + row["team"]).lower())
            body += f'<tr data-search="{search}"><td>#{row["number"]} {esc(row["name"])}<small>{esc(row["team"])}</small></td><td>{row["status"]}</td><td>{row["completed"] if row["completed"] is not None else "—"}</td><td>{last if last is not None else "—"}</td><td>미확인</td></tr>'
        body += "</tbody></table></div>"
    else:
        body += "<p>수집된 결과에서 DNF·DNS·DSQ로 표시된 선수는 없습니다. 결과 미수집 시에는 판정을 보류합니다.</p>"
    return header + body + "</section>"
