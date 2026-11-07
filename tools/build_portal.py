"""Build the shared landing page after generating the F1 archive."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'reports'


def build():
    archive = ROOT / 'index.html'
    if archive.exists() and 'F1 누적 보고서' in archive.read_text(encoding='utf-8'):
        archive.replace(ROOT / 'f1.html')
    archive.write_text('''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Seony Motorsports</title>
<style>body{background:#101827;color:#edf2ff;font:18px system-ui;max-width:900px;margin:80px auto;padding:24px}a{display:block;background:#20304d;color:#82d6ff;padding:28px;margin:20px 0;border-radius:12px}</style>
<h1>Seony Motorsports</h1><p>공식 공개 기록을 바탕으로 생성하는 모터스포츠 리포트</p>
<a href="f1.html">F1 · 연도 / 그랑프리 / 세션</a><a href="wec/index.html">WEC · 클래스 / 차량 / 드라이버 랩 분석</a>
<p>자료 갱신은 공식 기록 공개 및 자동 수집 성공 시 반영됩니다.</p></html>''', encoding='utf-8')


if __name__ == '__main__':
    build()
