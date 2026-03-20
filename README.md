# CEO Morning Briefing

상상인그룹 그룹사 대표이사 대상 HR·AI·스타트업 뉴스 자동 브리핑

## 구조
- `ceo_morning_briefing.py` — 메인 실행 스크립트
- `.github/workflows/daily_briefing.yml` — GitHub Actions 자동화
- `index.html` — GitHub Pages 웹사이트 (매일 자동 업데이트)
- `archive/` — 날짜별 HTML 아카이브
- `news_archive.json` — 중복 방지용 발송 기록 (자동 생성)

## GitHub Secrets 설정 필요
| Secret 이름 | 내용 |
|------------|------|
| `GMAIL_USER` | Gmail 주소 (예: jangkeunwon@gmail.com) |
| `GMAIL_APP_PASS` | Gmail 앱 비밀번호 (16자리) |

## GitHub Pages 설정
Settings → Pages → Source: **Deploy from branch** → Branch: `main` / `(root)`

## 수신자 추가
`ceo_morning_briefing.py` 내 `EMAIL_RECIPIENTS` 리스트에 추가
