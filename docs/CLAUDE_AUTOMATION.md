# F1·WEC Claude 자동 검토와 수정

`Motorsport reports`가 기본 보고서를 저장한 뒤 다음 순서로 실행합니다.

**보고서 생성·저장 → review → rescue 수정 패치 → 테스트·오프라인 재생성 → 자동 커밋·푸시**

플러그인의 `/cc:review`, `/cc:rescue` 명령을 직접 호출하는 방식은 아닙니다.
로그인된 Claude CLI에 같은 목적의 요청을 각각 전달합니다. `adversarial-review`는 실행하지 않습니다.

## Claude 구독 인증

Claude Pro 등 지원되는 구독으로 `claude setup-token`을 실행해 자동화용 토큰을 발급합니다.
이 저장소 Settings → Secrets and variables → Actions → Repository secrets에
`CLAUDE_CODE_OAUTH_TOKEN`으로 등록합니다. 다른 저장소의 같은 이름 시크릿은 자동 공유되지 않습니다.
토큰 값을 코드·커밋·채팅에 넣지 않습니다. 별도 Anthropic/OpenAI API 키는 사용하지 않습니다.
Claude 작업은 구독 사용량에 포함됩니다.

인증이 없으면 Claude 단계를 건너뛰고 기본 보고서는 계속 생성합니다.
인증 거부·사용량 한도·요청 실패와 수정안 검증 실패는 결과 파일에 기록합니다.

## 검토와 수정 범위

- review: F1·WEC 보고서의 계산·설명, 구조·UI, 한국어 문구를 검토합니다.
- rescue: review 결과를 원본 기록과 생성 코드로 다시 확인하고 최소 수정 패치를 만듭니다.
- Claude에는 읽기·검색 도구만 제공합니다. MCP 도구와 사용자 훅은 차단합니다.
  실제 패치 적용·테스트·재생성은 `tools/report_rescue.py`가 별도 복사본에서 수행합니다.
- 수정 가능한 생성 코드는 `weekend_report.py`, `build_archive.py`, `report_charts.js/css`,
  `race_events.py`, `wec_report.py`, `build_portal.py`입니다.
- 원본 CSV·JSON, 공식 순위, 출처·해시, 테스트·워크플로·인증 설정은 직접 수정하지 않습니다.
  수정 코드 실행 중에도 원본이나 다른 파일이 바뀌면 자동 반영을 거부합니다.
  재생성으로 갱신되는 `reports/catalog/archive-index.json`은 원본이 아닌 아카이브 목록 결과물로 함께 반영합니다.

전체 단위 테스트와 수정된 차트 JS 문법 검사를 통과해야 합니다.
`tools/rebuild_reports.py`로 저장된 F1 스냅샷과 WEC의 laps.json·classification.csv·source.json에서
세션별 HTML, WEC 대회별 탭·목록, F1 아카이브와 통합 입구를 다시 만듭니다.
검증 과정은 OpenF1·Al Kamel에 새 자료를 요청하지 않습니다.

검증된 패치만 별도 게시 작업이 main에 커밋·푸시합니다. 그 사이 main에 더 최신 커밋이
생겼으면 오래된 패치는 건너뜁니다. 강제 푸시는 하지 않습니다.
오류나 검증 실패 시 이미 저장한 기본 보고서를 유지합니다.
기존 Pages 워크플로는 수집·검토 워크플로 종료 후 최신 main을 게시합니다.

F1 또는 WEC 수집이 실패해도 정상 수집분이 커밋되어 있으면 그 커밋의 보고서를 검토합니다.
수집과 수정 게시만 같은 동시 실행 그룹을 사용하므로 긴 Claude 검토가 다음 수집을 막지 않습니다.

## 결과 확인

Actions 실행의 `claude-review-motorsport-reports` artifact에 30일간 보관합니다.

- `review.md`, `rescue.md`: 검토와 원인·수정안 설명
- `status.json`: 각 단계 완료·실패·건너뜀 및 수정안 검증 상태
- 수정 시 `proposed-rescue.patch`, `validation.log`, `validated-rescue.patch/json`

`claude-rescue-publish-motorsport-reports`의 `publish-status.json`은 실제 적용 여부와 커밋을 기록합니다.
강제 종료된 작업의 상태는 `running` 또는 `validating`으로 남을 수 있습니다.

로컬에서는 Claude CLI가 PATH에 있는 환경에서 실행합니다.

```sh
python tools/claude_report_review.py --local-login --output-dir /tmp/motorsport-review
```

기본 실행은 수정안만 작성합니다. `--apply`를 추가하면 복사본에서 자동 반영용 패치를
검증하지만 로컬 원본을 덮어쓰거나 푸시하지 않습니다. 실제 자동 게시는 Actions가 담당합니다.
