#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CEO Morning Briefing — 상상인그룹 그룹사 대표이사 대상
HR · AI/기술 · 국내 스타트업 뉴스 자동 수집 및 이메일 발송 + GitHub Pages 게시
"""

import os
import re
import json
import time
import urllib.parse
import smtplib
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import utils as email_utils
import urllib.request

# ─────────────────────────────────────────────
#  ① 사용자 설정 (GitHub Actions Secrets로 주입)
# ─────────────────────────────────────────────
GMAIL_USER      = os.environ.get("GMAIL_USER", "jangkeunwon@gmail.com")
GMAIL_APP_PASS  = os.environ.get("GMAIL_APP_PASS", "")          # Gmail 앱 비밀번호
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER    = os.environ.get("GITHUB_OWNER", "goodwon89")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "ceo-morning-briefing")
GITHUB_BRANCH   = "main"

# 수신자 목록 (그룹사 대표이사)
EMAIL_RECIPIENTS = [
    "jangkeunwon@gmail.com",          # 담당자 (테스트용)
    # "ceo1@sangsangin.com",          # 계열사1 대표이사
    # "ceo2@sangsangin.com",          # 계열사2 대표이사
    # 추가 수신자 이메일을 여기에 입력하세요
]

# 뉴스 아카이브 파일 (GitHub repo 내)
ARCHIVE_FILE = "news_archive.json"

# 뉴스 수집 설정
NEWS_WINDOW_DAYS = 7       # 최근 N일 기사 수집
ARCHIVE_DAYS     = 3       # 과거 N일 아카이브 중복 방지

# 섹션별 목표 기사 수
TARGET = {
    "hr":              4,   # HR/인사
    "ai":              3,   # AI/기술트렌드
    "startup_invest":  2,   # 스타트업 투자
    "startup_launch":  2,   # 스타트업 출시/성과
    "startup_issue":   2,   # 스타트업 지원/이슈
}
TOTAL_TARGET = sum(TARGET.values())   # 13건

# ─────────────────────────────────────────────
#  ② 뉴스 수집 쿼리
# ─────────────────────────────────────────────
HR_QUERIES = [
    "채용공고 연봉 임금 공시 표기",
    "기업 인사 채용 트렌드",
    "성과관리 평가제도 인사혁신",
    "직원 몰입도 이직률 인재 유지",
    "조직문화 유연근무 워크라이프",
    "HR 디지털 전환 HRIS",
    "기간제 비정규직 정규직 전환",
    "퇴직연금 퇴직급여 제도 개편",
    "육아휴직 모성보호 저출생 정책",
    "다양성 포용 DEI 직장",
    "최저임금 임금 체계 개편",
    "기업 복리후생 근무환경",
    "인재경영 리더십 교육훈련",
    "노동법 고용 규제 변화",
    "구인구직 채용 시장 동향",
    "기업 조직 구조조정 합병",
    "직장 내 괴롭힘 ESG 인권",
    "인사담당자 HR 컨퍼런스",
    "글로벌 인력 해외 채용 주재원",
    "AI 인사 채용 자동화 HR테크",
]

AI_QUERIES = [
    "생성 AI 기업 도입 활용 사례",
    "LLM 거대언어모델 최신 기술",
    "AI 스타트업 투자 기술 트렌드",
    "AI 규제 정책 인공지능법",
    "클라우드 SaaS 디지털 전환 기업",
    "AI 에이전트 자동화 업무 혁신",
    "반도체 AI 인프라 GPU 데이터센터",
    "로봇 자동화 스마트팩토리",
]

STARTUP_INVEST_QUERIES = [
    "스타트업 투자 유치 시리즈",
    "벤처 투자 VC 펀드 한국",
    "스타트업 엑셀러레이터 보육",
    "유니콘 기업 기업가치 투자",
    "코스닥 IPO 스타트업 상장",
]

STARTUP_LAUNCH_QUERIES = [
    "스타트업 신규 서비스 출시 런칭",
    "국내 스타트업 성과 수상 글로벌",
    "스타트업 해외 진출 수출",
    "앱 서비스 플랫폼 베타 공개",
    "스타트업 제품 특허 기술개발",
]

STARTUP_ISSUE_QUERIES = [
    "스타트업 정부 지원 사업 공모",
    "창업 지원 보조금 바우처",
    "스타트업 규제 샌드박스 특례",
    "창업 생태계 청년 창업 정책",
    "스타트업 폐업 경영난 이슈",
]

# 중복 판단 시 공통 단어 제외 목록
COMMON_WORDS = {
    "기업", "회사", "서비스", "시장", "사업", "제품", "기술", "운영",
    "발표", "추진", "강조", "예정", "계획", "진행", "확대", "도입",
    "한국", "국내", "글로벌", "업계", "시스템", "플랫폼",
    "스타트업", "대표", "투자", "채용",
}

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
#  ③ 유틸리티 함수
# ─────────────────────────────────────────────
def _parse_pub_time(entry) -> float:
    """기사 발행 시각을 타임스탬프(float)로 반환. 파싱 실패 시 0.0"""
    # 1차: feedparser published_parsed
    pp = getattr(entry, "published_parsed", None)
    if pp:
        try:
            return time.mktime(pp)
        except Exception:
            pass
    # 2차: email.utils RFC 2822 파싱 (+0900 포함)
    raw = getattr(entry, "published", "") or ""
    if raw:
        try:
            dt = email_utils.parsedate_to_datetime(raw)
            return dt.timestamp()
        except Exception:
            pass
    return 0.0


def normalize_title(title: str) -> str:
    """제목 정규화 (표기 통일만, 의미 변경 X)"""
    title = re.sub(r"\[.*?\]|\(.*?\)", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def extract_keywords(title: str) -> set:
    """제목에서 의미 있는 키워드 추출"""
    title = normalize_title(title)
    tokens = re.findall(r"[가-힣]{2,}", title)
    return {t for t in tokens if t not in COMMON_WORDS and len(t) >= 2}


def is_duplicate_topic(title_a: str, candidates: list[str]) -> bool:
    """title_a 가 candidates 중 하나와 주제가 유사하면 True"""
    kw_a = extract_keywords(title_a)
    if not kw_a:
        return False
    for c in candidates:
        kw_c = extract_keywords(c)
        overlap = kw_a & kw_c
        # 4글자 이상 단어 2개 이상 겹치면 중복
        long_overlap = {w for w in overlap if len(w) >= 4}
        if len(long_overlap) >= 2:
            return True
        # 2글자 단어 5개 이상 겹치면 중복
        if len(overlap) >= 5:
            return True
    return False


def shorten_url(url: str) -> str:
    """TinyURL로 단축 (실패 시 원본 반환)"""
    try:
        api = "https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            short = resp.read().decode().strip()
        return short if short.startswith("http") else url
    except Exception:
        return url


def load_archive() -> dict:
    """GitHub에서 아카이브 JSON 로드"""
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{ARCHIVE_FILE}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def save_archive(archive: dict, new_articles: list):
    """아카이브에 새 기사 추가 후 GitHub에 저장"""
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    if today_str not in archive:
        archive[today_str] = []
    archive[today_str].extend([a["title"] for a in new_articles])

    # 30일 이상 된 기록 삭제
    cutoff = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
    archive = {k: v for k, v in archive.items() if k >= cutoff}

    content = json.dumps(archive, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    # 현재 파일 SHA 조회
    sha = ""
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{ARCHIVE_FILE}"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"Authorization": f"token {GITHUB_TOKEN}", "User-Agent": "CEO-Morning-Briefing"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read().decode()).get("sha", "")
    except Exception:
        pass

    payload = json.dumps({
        "message": f"[archive] {today_str}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
        **({"sha": sha} if sha else {}),
    }).encode()
    try:
        req = urllib.request.Request(
            api_url,
            data=payload,
            method="PUT",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Content-Type": "application/json",
                "User-Agent": "CEO-Morning-Briefing",
            },
        )
        urllib.request.urlopen(req, timeout=15)
        print("[archive] 저장 완료")
    except Exception as e:
        print(f"[archive] 저장 실패: {e}")

    return archive


def load_recent_archive_titles(archive: dict) -> set:
    """최근 N일 아카이브에서 이미 발송된 기사 제목 집합 반환"""
    cutoff = (datetime.now(KST) - timedelta(days=ARCHIVE_DAYS)).strftime("%Y-%m-%d")
    titles = set()
    for date_str, title_list in archive.items():
        if date_str >= cutoff:
            titles.update(title_list)
    print(f"[archive] 최근 {ARCHIVE_DAYS}일 기사 {len(titles)}건 중복 방지 로드")
    return titles


# ─────────────────────────────────────────────
#  ④ RSS 뉴스 수집
# ─────────────────────────────────────────────
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False
    print("[경고] feedparser 미설치. pip install feedparser")


def _fetch_from_queries(queries: list[str], window_days: int = NEWS_WINDOW_DAYS) -> list[dict]:
    """Google News RSS에서 기사 수집 → 날짜 필터 적용"""
    if not HAS_FEEDPARSER:
        return []

    cutoff_ts = (datetime.now(KST) - timedelta(days=window_days)).timestamp()
    results = []
    seen_urls = set()

    for q in queries:
        encoded = urllib.parse.quote(q)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            feed = feedparser.parse(rss_url)
        except Exception:
            continue

        for entry in feed.entries:
            url = getattr(entry, "link", "")
            if not url or url in seen_urls:
                continue
            title = normalize_title(getattr(entry, "title", ""))
            if not title:
                continue
            pub_time = _parse_pub_time(entry)
            if pub_time > 0 and pub_time < cutoff_ts:
                continue   # 오래된 기사 제외
            source = getattr(entry, "source", None)
            source_name = getattr(source, "title", "알 수 없음") if source else "알 수 없음"
            results.append({
                "title": title,
                "url": url,
                "source": source_name,
                "pub_time": pub_time,
                "query": q,
            })
            seen_urls.add(url)

    return results


def _pick_articles(
    candidates: list[dict],
    target: int,
    chosen_titles: set,
    max_per_source: int = 2,
    check_topic: bool = True,
) -> list[dict]:
    """candidates에서 조건에 맞는 기사 target건 선택"""
    candidates_sorted = sorted(candidates, key=lambda x: x["pub_time"], reverse=True)
    result = []
    source_count: dict[str, int] = {}

    for art in candidates_sorted:
        if len(result) >= target:
            break
        title = art["title"]
        if title in chosen_titles:
            continue
        if source_count.get(art["source"], 0) >= max_per_source:
            continue
        if check_topic and is_duplicate_topic(title, list(chosen_titles)):
            continue
        result.append(art)
        chosen_titles.add(title)
        source_count[art["source"]] = source_count.get(art["source"], 0) + 1

    return result


def fetch_section_news(
    queries: list[str],
    target: int,
    section_name: str,
    chosen_titles: set,
    archive_titles: set,
) -> list[dict]:
    """
    섹션별 뉴스 수집 (5단계 폴백)
    chosen_titles : 이 실행 세션 전체에서 이미 채택된 제목 집합 (수정됨)
    archive_titles: 과거 발송 기록 (중복 방지용)
    """
    all_candidates = _fetch_from_queries(queries)
    # 아카이브 exact-title 중복 제거
    all_candidates = [a for a in all_candidates if a["title"] not in archive_titles]

    result = []

    # Stage 1 — 언론사당 2건 제한, 주제 중복 체크
    picked = _pick_articles(all_candidates, target, chosen_titles, max_per_source=2, check_topic=True)
    result.extend(picked)
    print(f"[{section_name}] Stage1: {len(result)}/{target}")

    # Stage 2 — 언론사 제한 해제
    if len(result) < target:
        picked = _pick_articles(all_candidates, target - len(result), chosen_titles, max_per_source=99, check_topic=True)
        result.extend(picked)
        print(f"[{section_name}] Stage2: {len(result)}/{target}")

    # Stage 3 — 주제 중복 체크 해제
    if len(result) < target:
        picked = _pick_articles(all_candidates, target - len(result), chosen_titles, max_per_source=99, check_topic=False)
        result.extend(picked)
        print(f"[{section_name}] Stage3: {len(result)}/{target}")

    # Stage 4 — 광범위 보충 쿼리
    if len(result) < target:
        backup_queries = [
            f"{q.split()[0]} 뉴스" for q in queries[:3]
        ] + ["스타트업 뉴스", "AI 뉴스", "HR 인사 뉴스"]
        backup_candidates = _fetch_from_queries(backup_queries)
        backup_candidates = [a for a in backup_candidates if a["title"] not in archive_titles]
        picked = _pick_articles(backup_candidates, target - len(result), chosen_titles, max_per_source=99, check_topic=False)
        result.extend(picked)
        print(f"[{section_name}] Stage4: {len(result)}/{target}")

    # Stage 5 — URL 중복만 방지 (아카이브 무시)
    if len(result) < target:
        all_with_archive = _fetch_from_queries(queries)
        picked = _pick_articles(all_with_archive, target - len(result), chosen_titles, max_per_source=99, check_topic=False)
        result.extend(picked)
        print(f"[{section_name}] Stage5(final): {len(result)}/{target}")

    # URL 단축
    for art in result:
        art["short_url"] = shorten_url(art["url"])

    return result


# ─────────────────────────────────────────────
#  ⑤ 전체 뉴스 수집 (섹션별)
# ─────────────────────────────────────────────
def collect_all_news() -> dict:
    """
    반환값:
    {
      "hr": [...],
      "ai": [...],
      "startup_invest": [...],
      "startup_launch": [...],
      "startup_issue": [...],
    }
    """
    archive = load_archive()
    archive_titles = load_recent_archive_titles(archive)
    chosen_titles: set = set()

    sections = {}

    # AI — 고정 3건 (가장 먼저 채택)
    sections["ai"] = fetch_section_news(
        AI_QUERIES, TARGET["ai"], "AI/기술", chosen_titles, archive_titles
    )

    # HR
    sections["hr"] = fetch_section_news(
        HR_QUERIES, TARGET["hr"], "HR/인사", chosen_titles, archive_titles
    )

    # 스타트업 투자
    sections["startup_invest"] = fetch_section_news(
        STARTUP_INVEST_QUERIES, TARGET["startup_invest"], "스타트업투자", chosen_titles, archive_titles
    )

    # 스타트업 출시/성과
    sections["startup_launch"] = fetch_section_news(
        STARTUP_LAUNCH_QUERIES, TARGET["startup_launch"], "스타트업출시", chosen_titles, archive_titles
    )

    # 스타트업 지원/이슈
    sections["startup_issue"] = fetch_section_news(
        STARTUP_ISSUE_QUERIES, TARGET["startup_issue"], "스타트업지원", chosen_titles, archive_titles
    )

    total = sum(len(v) for v in sections.values())
    print(f"\n[수집 완료] 총 {total}건 / 목표 {TOTAL_TARGET}건")

    # 아카이브 저장
    all_articles = [a for s in sections.values() for a in s]
    save_archive(archive, all_articles)

    return sections


# ─────────────────────────────────────────────
#  ⑥ HTML 이메일 템플릿
# ─────────────────────────────────────────────
SECTION_META = {
    "hr":             {"icon": "👥", "title": "HR / 인사"},
    "ai":             {"icon": "🤖", "title": "AI / 기술 트렌드"},
    "startup_invest": {"icon": "💰", "title": "스타트업 · 투자"},
    "startup_launch": {"icon": "🚀", "title": "스타트업 · 출시 / 성과"},
    "startup_issue":  {"icon": "📋", "title": "스타트업 · 지원 / 이슈"},
}
SECTION_ORDER = ["hr", "ai", "startup_invest", "startup_launch", "startup_issue"]


def _article_rows(articles: list[dict]) -> str:
    rows = []
    for art in articles:
        source = art.get("source", "")
        pub_ts = art.get("pub_time", 0)
        if pub_ts:
            pub_date = datetime.fromtimestamp(pub_ts, tz=KST).strftime("%m.%d")
        else:
            pub_date = ""
        date_src = f"{source} | {pub_date}" if pub_date else source

        rows.append(f"""
        <tr>
          <td style="padding:11px 0 11px 0; border-bottom:1px solid #f0f0f0; vertical-align:top;">
            <a href="{art['short_url']}" target="_blank"
               style="font-size:14px; color:#1a1a1a; text-decoration:none; line-height:1.55;
                      font-weight:500; display:block;">
              {art['title']}
            </a>
            <span style="font-size:11px; color:#999; margin-top:3px; display:block;">{date_src}</span>
          </td>
        </tr>""")
    return "\n".join(rows)


def _section_block(section_key: str, articles: list[dict]) -> str:
    if not articles:
        return ""
    meta = SECTION_META[section_key]
    rows_html = _article_rows(articles)
    return f"""
    <!-- {meta['title']} 섹션 -->
    <tr>
      <td style="padding: 28px 0 6px 0;">
        <span style="display:inline-block; background:#f5f5f5; border-radius:20px;
                     padding:5px 14px; font-size:13px; font-weight:700; color:#333;">
          {meta['icon']} {meta['title']}
        </span>
      </td>
    </tr>
    <tr>
      <td>
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {rows_html}
        </table>
      </td>
    </tr>"""


def build_email_html(sections: dict) -> str:
    today_str = datetime.now(KST).strftime("%Y.%m.%d (%a)")
    day_map = {"Mon":"Mon","Tue":"Tue","Wed":"Wed","Thu":"Thu","Fri":"Fri","Sat":"Sat","Sun":"Sun"}
    for en, ko in [("Mon","월"),("Tue","화"),("Wed","수"),("Thu","목"),("Fri","금"),("Sat","토"),("Sun","일")]:
        today_str = today_str.replace(en, ko)

    all_sections_html = "".join(
        _section_block(k, sections.get(k, [])) for k in SECTION_ORDER
    )

    subscribe_subject   = urllib.parse.quote("CEO Morning Briefing 구독 신청")
    subscribe_body      = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 신청합니다.\n\n이메일 주소: ")
    unsubscribe_subject = urllib.parse.quote("CEO Morning Briefing 구독 취소")
    unsubscribe_body    = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 취소 요청합니다.\n\n이메일 주소: ")
    mailto_subscribe   = f"mailto:{GMAIL_USER}?subject={subscribe_subject}&body={subscribe_body}"
    mailto_unsubscribe = f"mailto:{GMAIL_USER}?subject={unsubscribe_subject}&body={unsubscribe_body}"
    pages_url = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CEO Morning Briefing</title>
</head>
<body style="margin:0; padding:0; background:#f4f4f4; font-family:'Apple SD Gothic Neo',Malgun Gothic,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f4f4f4">
  <tr>
    <td align="center" style="padding: 24px 16px;">

      <!-- 카드 -->
      <table width="600" cellpadding="0" cellspacing="0" border="0"
             style="max-width:600px; background:#ffffff; border-radius:12px;
                    box-shadow:0 2px 12px rgba(0,0,0,0.08);">

        <!-- 헤더 -->
        <tr>
          <td style="background:#1a1a2e; border-radius:12px 12px 0 0; padding:30px 36px 24px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <div style="font-size:20px; font-weight:800; color:#ffffff; letter-spacing:-0.3px;">
                    CEO Morning Briefing
                  </div>
                  <div style="font-size:12px; color:#aaa; margin-top:4px;">
                    {today_str} &nbsp;|&nbsp; 상상인그룹 인재경영실
                  </div>
                </td>
                <td align="right" style="vertical-align:middle;">
                  <a href="{mailto_subscribe}"
                     style="display:inline-block; padding:7px 16px; border:1.5px solid #4fc3a1;
                            border-radius:20px; color:#4fc3a1; font-size:12px;
                            text-decoration:none; font-weight:600;">
                    ✉️ 구독 신청
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- 본문 -->
        <tr>
          <td style="padding: 8px 36px 12px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              {all_sections_html}
            </table>
          </td>
        </tr>

        <!-- 구분선 -->
        <tr>
          <td style="padding:0 36px;">
            <hr style="border:none; border-top:1px solid #eeeeee; margin:0;">
          </td>
        </tr>

        <!-- 푸터 -->
        <tr>
          <td style="padding:20px 36px 28px; text-align:center;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding-bottom:12px;">
                  <a href="{mailto_subscribe}"
                     style="display:inline-block; padding:9px 20px;
                            background:#4fc3a1; border-radius:20px;
                            color:#ffffff; font-size:13px; font-weight:700;
                            text-decoration:none; margin-right:8px;">
                    ✉️ 구독 신청
                  </a>
                  <a href="{mailto_unsubscribe}"
                     style="display:inline-block; padding:9px 20px;
                            border:1.5px solid #ccc; border-radius:20px;
                            color:#666; font-size:13px; font-weight:600;
                            text-decoration:none;">
                    구독 취소
                  </a>
                </td>
              </tr>
              <tr>
                <td align="center">
                  <a href="https://ssihr.oopy.io" target="_blank"
                     style="font-size:12px; color:#4fc3a1; text-decoration:none;">
                    👋 인재경영실 소개
                  </a>
                  &nbsp;&nbsp;
                  <a href="{pages_url}" target="_blank"
                     style="font-size:12px; color:#999; text-decoration:none;">
                    🌐 웹사이트
                  </a>
                </td>
              </tr>
              <tr>
                <td align="center" style="padding-top:10px;">
                  <span style="font-size:11px; color:#bbb;">
                    매일 오전 9시 자동 발송 · 상상인그룹 인재경영실
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


# ─────────────────────────────────────────────
#  ⑦ 이메일 발송
# ─────────────────────────────────────────────
def send_email(sections: dict):
    today_str = datetime.now(KST).strftime("%Y.%m.%d")
    subject = f"[CEO Morning Briefing] {today_str} — HR·AI·스타트업 주요 뉴스"
    html_body = build_email_html(sections)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"상상인그룹 인재경영실 <{GMAIL_USER}>"
    msg["To"]      = ", ".join(EMAIL_RECIPIENTS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASS)
            smtp.sendmail(GMAIL_USER, EMAIL_RECIPIENTS, msg.as_string())
        print(f"[이메일] 발송 완료 → {len(EMAIL_RECIPIENTS)}명")
    except Exception as e:
        print(f"[이메일] 발송 실패: {e}")
        raise


# ─────────────────────────────────────────────
#  ⑧ GitHub Pages 업데이트
# ─────────────────────────────────────────────
def _push_file_to_github(filepath: str, content_bytes: bytes, commit_msg: str):
    """GitHub API로 파일 push"""
    encoded = base64.b64encode(content_bytes).decode()
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filepath}"
    sha = ""
    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "User-Agent": "CEO-Morning-Briefing",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            sha = json.loads(resp.read().decode()).get("sha", "")
    except Exception:
        pass

    payload = json.dumps({
        "message": commit_msg,
        "content": encoded,
        "branch": GITHUB_BRANCH,
        **({"sha": sha} if sha else {}),
    }).encode()

    req = urllib.request.Request(
        api_url,
        data=payload,
        method="PUT",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "CEO-Morning-Briefing",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"[GitHub] {filepath} 업로드 완료 ({resp.status})")


def build_github_page_html(sections: dict) -> str:
    """GitHub Pages 전용 HTML (index.html 내 최신 브리핑 삽입)"""
    today_str = datetime.now(KST).strftime("%Y.%m.%d")
    for en, ko in [("Mon","월"),("Tue","화"),("Wed","수"),("Thu","목"),("Fri","금"),("Sat","토"),("Sun","일")]:
        today_str = today_str.replace(en, ko)

    pages_url = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/"
    subscribe_subject   = urllib.parse.quote("CEO Morning Briefing 구독 신청")
    subscribe_body      = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 신청합니다.\n\n이메일 주소: ")
    unsubscribe_subject = urllib.parse.quote("CEO Morning Briefing 구독 취소")
    unsubscribe_body    = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 취소 요청합니다.\n\n이메일 주소: ")
    mailto_subscribe   = f"mailto:{GMAIL_USER}?subject={subscribe_subject}&body={subscribe_body}"
    mailto_unsubscribe = f"mailto:{GMAIL_USER}?subject={unsubscribe_subject}&body={unsubscribe_body}"

    sections_html_parts = []
    for key in SECTION_ORDER:
        arts = sections.get(key, [])
        if not arts:
            continue
        meta = SECTION_META[key]
        items_html = ""
        for art in arts:
            source = art.get("source", "")
            pub_ts = art.get("pub_time", 0)
            pub_date = datetime.fromtimestamp(pub_ts, tz=KST).strftime("%m.%d") if pub_ts else ""
            date_src = f"{source} | {pub_date}" if pub_date else source
            items_html += f"""
              <div class="article-item">
                <a href="{art['short_url']}" target="_blank" rel="noopener">{art['title']}</a>
                <span class="article-meta">{date_src}</span>
              </div>"""
        sections_html_parts.append(f"""
          <div class="section-block">
            <div class="section-tag">{meta['icon']} {meta['title']}</div>
            {items_html}
          </div>""")

    sections_html = "\n".join(sections_html_parts)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="상상인그룹 CEO Morning Briefing — HR·AI·스타트업 뉴스">
<title>CEO Morning Briefing | 상상인그룹</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #f2f2f7; font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
          color: #1a1a1a; }}
  .wrap {{ max-width: 680px; margin: 0 auto; padding: 20px 16px 60px; }}

  /* 헤더 */
  .header {{ background: #1a1a2e; border-radius: 14px; padding: 28px 32px 24px;
             margin-bottom: 20px; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .header h1 {{ font-size: 22px; font-weight: 800; color: #fff; letter-spacing: -0.3px; }}
  .header .sub {{ font-size: 12px; color: #aaa; margin-top: 5px; }}
  .btn-subscribe {{
    display: inline-block; padding: 7px 16px;
    border: 1.5px solid #4fc3a1; border-radius: 20px;
    color: #4fc3a1; font-size: 12px; font-weight: 600;
    text-decoration: none; white-space: nowrap;
  }}

  /* 카드 */
  .card {{ background: #fff; border-radius: 12px; padding: 24px 28px;
           box-shadow: 0 1px 6px rgba(0,0,0,0.07); margin-bottom: 14px; }}

  /* 섹션 */
  .section-block {{ margin-bottom: 24px; }}
  .section-block:last-child {{ margin-bottom: 0; }}
  .section-tag {{
    display: inline-block; background: #f5f5f5; border-radius: 20px;
    padding: 5px 14px; font-size: 13px; font-weight: 700; color: #333;
    margin-bottom: 10px;
  }}

  /* 기사 */
  .article-item {{ padding: 10px 0; border-bottom: 1px solid #f0f0f0; }}
  .article-item:last-child {{ border-bottom: none; }}
  .article-item a {{
    display: block; font-size: 14px; color: #1a1a1a; text-decoration: none;
    font-weight: 500; line-height: 1.55;
  }}
  .article-item a:hover {{ color: #4fc3a1; }}
  .article-meta {{ display: block; font-size: 11px; color: #999; margin-top: 3px; }}

  /* 푸터 */
  .footer {{ text-align: center; padding: 24px 0 8px; }}
  .footer-btns {{ margin-bottom: 12px; }}
  .btn-fill {{
    display: inline-block; padding: 9px 22px; background: #4fc3a1;
    border-radius: 20px; color: #fff; font-size: 13px; font-weight: 700;
    text-decoration: none; margin-right: 8px;
  }}
  .btn-outline {{
    display: inline-block; padding: 9px 22px; border: 1.5px solid #ccc;
    border-radius: 20px; color: #666; font-size: 13px; font-weight: 600;
    text-decoration: none;
  }}
  .footer-links {{ font-size: 12px; margin-bottom: 10px; }}
  .footer-links a {{ color: #4fc3a1; text-decoration: none; margin: 0 8px; }}
  .footer-note {{ font-size: 11px; color: #bbb; }}

  @media (max-width: 480px) {{
    .header {{ padding: 20px 18px; }}
    .card {{ padding: 18px 16px; }}
    .header h1 {{ font-size: 18px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <!-- 헤더 -->
  <div class="header">
    <div class="header-top">
      <div>
        <h1>CEO Morning Briefing</h1>
        <div class="sub">{today_str} &nbsp;|&nbsp; 상상인그룹 인재경영실</div>
      </div>
      <a href="{mailto_subscribe}" class="btn-subscribe">✉️ 구독 신청</a>
    </div>
  </div>

  <!-- 뉴스 카드 -->
  <div class="card">
    {sections_html}
  </div>

  <!-- 푸터 -->
  <div class="footer">
    <div class="footer-btns">
      <a href="{mailto_subscribe}" class="btn-fill">✉️ 구독 신청</a>
      <a href="{mailto_unsubscribe}" class="btn-outline">구독 취소</a>
    </div>
    <div class="footer-links">
      <a href="https://ssihr.oopy.io" target="_blank">👋 인재경영실 소개</a>
      <a href="#top">↑ 맨 위로</a>
    </div>
    <div class="footer-note">매일 오전 9시 자동 발송 · 상상인그룹 인재경영실</div>
  </div>

</div>
</body>
</html>"""


def push_to_github(sections: dict):
    """뉴스 HTML을 GitHub Pages에 업로드"""
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    # 1) index.html (최신 브리핑)
    index_html = build_github_page_html(sections)
    _push_file_to_github(
        "index.html",
        index_html.encode("utf-8"),
        f"[briefing] {today_str} 최신 브리핑 업데이트",
    )

    # 2) 날짜별 아카이브 HTML
    archive_path = f"archive/{today_str}.html"
    _push_file_to_github(
        archive_path,
        index_html.encode("utf-8"),
        f"[archive] {today_str}",
    )


# ─────────────────────────────────────────────
#  ⑨ 메인 실행
# ─────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  CEO Morning Briefing 시작")
    print(f"  {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S KST')}")
    print("=" * 50)

    if not HAS_FEEDPARSER:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "feedparser", "-q"])
        import feedparser as _fp  # noqa: F401

    # 뉴스 수집
    sections = collect_all_news()

    # 이메일 발송
    send_email(sections)

    # GitHub Pages 업데이트
    if GITHUB_TOKEN:
        push_to_github(sections)
    else:
        print("[GitHub] GITHUB_TOKEN 미설정 — 업로드 생략")

    print("\n[완료] CEO Morning Briefing 실행 종료")


if __name__ == "__main__":
    main()
