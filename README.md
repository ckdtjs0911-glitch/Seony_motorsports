# Seony Motorsports · F1 / WEC 자동 리포트

기존 Seony_F1의 OpenF1 리포트 생성기를 옮기고 WEC 공식 Al Kamel CSV 수집기를 추가했습니다.
F1 코드는 원본 로컬 커밋 `98c4443ed6ebcd6ff9784e0d8f150abc973ee108`에서 가져왔습니다.
OpenF1 원본 라이선스는 LICENSE에 유지합니다. API 서버나 MongoDB는 리포트 생성에 필요하지 않습니다.

## 실행

Python 3.12 이상:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tools -p 'test_*.py'
.venv/bin/python tools/wec_report.py --year 2026 --event MONZA
.venv/bin/python tools/weekend_report.py --output-root .report-staging
.venv/bin/python tools/review_pipeline.py --staging .report-staging --destination reports --optional
.venv/bin/python tools/build_archive.py
.venv/bin/python tools/build_portal.py
```

`reports/index.html`이 통합 입구, `reports/f1.html`이 F1 아카이브,
`reports/wec/index.html`이 WEC 대회 목록입니다. 같은 연도·대회의 연습·예선·레이스를
한 대회 페이지의 세션 탭으로 모으며, 가장 최근에 수집한 세션을 기본으로 표시합니다.
대회 HTML에 세션 내용을 직접 포함하므로 프레임 차단 환경에서도 표와 탭을 볼 수 있습니다.
탭 전환 시 필터와 페이지 상태를 유지하며, 세션별 리포트와 원본 파일도 유지합니다. WEC는 `--event`를 생략하면 선택 연도의
공식 목록 전체를 수집합니다. 기본 연도는 현재 UTC 연도입니다. 별도 API 키는 필요 없습니다.

WEC는 FIA WEC 세션의 Analysis CSV와 있으면 Classification CSV를 사용합니다.
프로롤로그와 지원 경기는 제외합니다. 원본 CSV, 랩 JSON, 출처 URL 및 SHA-256을 보존합니다.
피트 진입·출차·플래그를 사용한 페이스 표본 필터, 차량·드라이버별 중앙값,
피트·교대 경계의 관측 주행 구간, 차량별 랩타임 차트, 공식 순위표를 제공합니다.
플래그는 결승선 통과 시점 값입니다. 타이어 스틴트·연료·트래픽을 추정하지 않습니다.
차량 순위표는 전체 클래스 통합을 기본으로 10대씩, 선수별 페이스 표는 10명씩, 관측 주행 구간 표는 10개씩 페이지를 나눕니다.
각 표는 `이전 · 1–10 · 11–20 · … · 다음` 구간 버튼을 사용하고 선택 구간을 민트색으로 표시합니다.
실제 자료에 있는 클래스와 팀으로 필터링할 수 있습니다.
클래스를 바꾸면 해당 클래스의 팀 목록으로 갱신하며 순위표·페이스·주행 구간·차트에 함께 적용합니다.
필터를 바꾸면 순위표는 첫 페이지로 돌아가며 순위 숫자는 공식 전체 순위를 유지합니다.
시간별 Race CSV는 숫자로 가장 늦은 Hour를 선택하며, 별도 최종 파일이 있으면 우선합니다.
정정된 공식 CSV는 다음 실행에서 다시 읽습니다. 원본에 없는 세션은 생성하지 않습니다.

## GitHub 자동 실행 및 게시

- `Motorsport reports`: 6시간마다 한국 시간 03:17 / 09:17 / 15:17 / 21:17 (지연 가능).
- 수동 실행의 `series`는 all/f1/wec, `year`는 WEC 연도입니다.
- WEC는 임시 폴더에서 전체 수집 성공 후 보고서를 복사합니다. 수집 실패 시 마지막 성공본을 유지합니다.
- F1/WEC 한쪽 수집이 실패해도 다른 쪽 성공본은 커밋하며 워크플로는 실패로 표시합니다.
- 결과 artifact는 30일 유지합니다. 보고서 커밋이 생기면 Pages 워크플로가 최신 main을 게시합니다.
- 저장소 Settings → Pages → Source를 **GitHub Actions**로 설정해야 합니다.
- Actions가 활성화되고 기본 GITHUB_TOKEN의 contents:write 권한이 허용되어야 합니다.
- Pages 워크플로는 main의 보고서 변경, 자동 수집 완료, 수동 실행으로 시작합니다.

공개 WEC 기록은 인증 없이 수집합니다. F1 접근 제한 시 기존 F1 보고서를 유지합니다.
필요한 OpenF1 인증은 저장소 Actions secrets의 `OPENF1_CLIENT_ID`, `OPENF1_CLIENT_SECRET`으로 설정합니다.
기존 F1 선택적 AI 첨삭은 `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`가 모두 있을 때 사용합니다.
키 없이 기본 보고서 생성이 가능합니다. 상세 F1 동작은 [기존 자동화 문서](reports/AUTOMATION.md)를 참고하세요.
그 문서의 이전 '외부 게시 없음' 설명 대신 이 저장소에서는 별도 Pages 워크플로가 게시를 담당합니다.

## 검증 범위

단위 테스트와 공식 WEC 몬차 CSV를 사용한 실제 생성, 기존 F1 스냅샷 오프라인 생성으로 검증합니다.
실시간 수집 성공과 GitHub Actions/Pages 실행 성공은 별도로 확인해야 합니다.
데이터는 공식 제공사의 공개 범위와 이용 조건에 따릅니다. 누락값은 성능 수치로 대체하지 않습니다.
