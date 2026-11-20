"""Beginner explanations drawn from the current rally's supplied timing rows."""
from html import escape


def duration(ms):
    if ms is None:
        return '미제공'
    sign = '-' if ms < 0 else ''
    seconds = abs(ms) / 1000
    hours, minutes = int(seconds // 3600), int(seconds % 3600 // 60)
    return sign + (f'{hours}시간 ' if hours else '') + (f'{minutes}분 ' if minutes or hours else '') + f'{seconds % 60:.3f}초'


def render(event, title, kind, records, entries, aggregate=(), stage=None):
    """Keep SS, daily-feed, cumulative and independently sorted run scopes separate."""
    byid = {r['entryId']: r for r in entries}
    paragraphs = []

    def crew(row):
        ent = byid.get(row['entryId'], {})
        return escape('#' + str(ent.get('identifier', '—')) + ' ' +
                      ent.get('driver', {}).get('fullName', '미제공') + ' / ' +
                      ent.get('codriver', {}).get('fullName', '미제공'))

    if kind == 'stage':
        valid = [r for r in records if r.get('status') == 'Completed' and r.get('elapsedDurationMs') is not None]
        if valid:
            a = valid[0]
            paragraphs.append(f'<strong>{crew(a)}</strong>의 SS 시간 <strong>{duration(a["elapsedDurationMs"])}</strong>은 이번 한 구간을 통과하는 데 반영된 시간입니다. 서킷 레이스의 반복 랩타임과 달리, 여기서는 서로 시간차 출발한 크루의 한 SS 소요 시간을 비교합니다.')
            if len(valid) > 1:
                b = valid[1]
                gap = b.get('diffFirstMs')
                if gap is not None:
                    paragraphs.append(f'{crew(b)}의 SS 선두 격차 <strong>+{duration(gap)}</strong>는 이 구간의 원본 선두 기준 시간 차이입니다. 도로 위에서 두 차가 그 간격으로 붙어 달렸다는 뜻은 아닙니다.')
            distance = (stage or {}).get('distance')
            if distance and distance > 0:
                paragraphs.append(f'이번 SS 거리 {distance:.2f}km로 나누면 위 첫 유효 행의 주행 시간은 <strong>{a["elapsedDurationMs"]/1000/distance:.3f}초/km</strong>입니다. 1km당 걸린 평균 시간이며 낮을수록 짧습니다. 격차를 거리로 나눈 초/km와 구별하고, 노면·날씨·출발 순서를 보정한 성능으로 해석하지 않습니다.')
            if aggregate:
                lead = aggregate[0]
                paragraphs.append(f'반면 이번 SS 뒤 종합 선두 {crew(lead)}의 <strong>{duration(lead.get("totalTimeMs"))}</strong>은 해당 시점까지의 누적 기록입니다. 이번 SS 한 번의 시간과 비교하거나 서로 더하면 안 됩니다. 이번 첫 유효 SS 행과 종합 선두는 '+('같은 크루입니다.' if a['entryId'] == lead['entryId'] else '<strong>다른 크루입니다.</strong> 한 구간에서 앞서도 누적 선두가 아닐 수 있는 실제 사례입니다.'))
        if not valid:
            paragraphs.append('이 범위에 해설할 수 있는 공식 시간 기록이 없습니다. 미제공 시간을 0초로 대체하거나 임의의 예시 기록을 만들지 않았습니다.')
        status = (stage or {}).get('status', '미제공')
        paragraphs.append(f'이번 구간의 공식 일정 상태는 <strong>{escape(status)}</strong>입니다. '+('Interrupted는 중단 상태입니다. 일부 Completed 시간 행이 있어도 전체 구간을 정상 완료로 바꾸지 않습니다. ' if status == 'Interrupted' else '')+'각 행의 Default·Notional·Assessed·Rally2 시간 출처를 함께 확인하세요. 부여·평가 시간은 실제로 그 속도로 달렸다는 증거가 아니며, 기록이 없는 행은 0초가 아닙니다.')
    elif kind in ('day', 'final') and records:
        a = records[0]
        scope = '당일 원본 집계' if kind == 'day' else '대회 최종 누적 분류'
        paragraphs.append(f'<strong>{scope}</strong> 첫 행 {crew(a)}의 총 시간 <strong>{duration(a.get("totalTimeMs"))}</strong>은 '+('그날 집계 범위의 값입니다. 대회 첫 SS부터 누적한 시간은 아래 별도 종합 표에서 읽습니다.' if kind == 'day' else '대회의 누적 기록입니다. 며칠 동안 이동·휴식한 실제 달력상의 전체 경과 시간이 아닙니다.'))
        if len(records) > 1 and records[1].get('diffFirstMs') is not None:
            b = records[1]
            paragraphs.append(f'{crew(b)}의 원본 선두 격차 <strong>+{duration(b["diffFirstMs"])}</strong>는 같은 집계 범위의 선두 기준 차이입니다. 각 SS마다 이만큼 뒤졌다는 뜻은 아닙니다.')
        inconsistent = [r for r in records if all(r.get(k) is not None for k in ('stageTimeMs','penaltyTimeMs','totalTimeMs')) and r['stageTimeMs'] + r['penaltyTimeMs'] != r['totalTimeMs']]
        if inconsistent:
            a = inconsistent[0]
            paragraphs.append(f'<strong>이번 자료의 주의점:</strong> {crew(a)}는 구간 합계 {duration(a["stageTimeMs"])}와 페널티 {duration(a["penaltyTimeMs"])}를 더하면 {duration(a["stageTimeMs"]+a["penaltyTimeMs"])}이지만, 원본 총 시간은 {duration(a["totalTimeMs"])}입니다. 이런 행이 {len(inconsistent)}개 있습니다. 원본 순서를 유지하고 계산값을 별도로 보여 주며, 이를 페널티 반영 최종 순위로 단정하지 않습니다.')
        else:
            penalty = next((r for r in records if r.get('penaltyTimeMs', 0) > 0), None)
            if penalty:
                paragraphs.append(f'페널티 계산의 실제 예: {crew(penalty)}의 구간 합계 {duration(penalty["stageTimeMs"])} + 가산 {duration(penalty["penaltyTimeMs"])} = 총 시간 {duration(penalty["totalTimeMs"])}입니다. 이 숫자만으로 가산 사유를 추정하지 말고 확인된 판정 원문을 봅니다.')
    elif kind == 'shakedown' and records:
        a = records[0]
        paragraphs.append(f'{crew(a)}의 관측 최저 런 <strong>{duration(a.get("best"))}</strong>은 사전 점검 주행 중 가장 짧은 한 번의 기록입니다. 크루별 최저 런으로 계산 정렬한 것이며 공식 순위·SS 우승·대회 누적 시간에 더할 값이 아닙니다.')
    if not paragraphs:
        paragraphs.append('이 범위에 해설할 수 있는 공식 시간 기록이 없습니다. 임의의 예시 기록을 만들지 않았습니다.')
    return '<section id="s0"><div class="eyebrow">CHAPTER 00</div><h2>처음 보는 WRC · 이번 기록 쉽게 읽기</h2><p><strong>'+escape(event)+' · '+escape(title)+'</strong></p><p>WRC의 대회는 보통 그랑프리 대신 랠리라고 부릅니다. 드라이버와 코드라이버가 한 크루를 이루며, SS는 시간을 겨루는 구간입니다. <strong>SS 상태 → 크루·차량 그룹 → 이번 SS 시간 → 누적 시간·격차 → 페널티</strong> 순서로 보세요. 전체 순위와 같은 그룹 안의 성과도 구분합니다.</p>'+''.join('<p>'+p+'</p>' for p in paragraphs)+'</section>'
