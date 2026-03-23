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
GMAIL_USER      = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASS  = os.environ.get("GMAIL_APP_PASS", "")          # Gmail 앱 비밀번호
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER    = os.environ.get("GITHUB_OWNER", "goodwon89")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "ceo-morning-briefing")
GITHUB_BRANCH   = "main"

# 수신자 목록 — GitHub Secrets의 EMAIL_RECIPIENTS (쉼표 구분) 로 관리
EMAIL_RECIPIENTS = [
    e.strip() for e in os.environ.get("EMAIL_RECIPIENTS", "").split(",") if e.strip()
]

# 뉴스 아카이브 파일 (GitHub repo 내)
ARCHIVE_FILE = "news_archive.json"

# 뉴스 수집 설정
NEWS_WINDOW_DAYS = 7       # 최근 N일 기사 수집
ARCHIVE_DAYS     = 3       # 과거 N일 아카이브 중복 방지

# 섹션별 목표 기사 수 (카테고리별 최소 4건)
TARGET = {
    "hr":              4,   # HR/인사
    "ai":              4,   # AI/기술트렌드
    "startup_invest":  4,   # 스타트업 투자
    "startup_launch":  4,   # 스타트업 출시/성과
    "startup_issue":   4,   # 스타트업 지원/이슈
}
TOTAL_TARGET = sum(TARGET.values())   # 20건

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


def load_archive() -> list:
    """GitHub에서 아카이브 JSON 로드 (list of {date, news} 포맷)
    구 포맷(dict)은 자동 마이그레이션"""
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{ARCHIVE_FILE}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"token {GITHUB_TOKEN}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, dict):  # 구 포맷 → 신 포맷 마이그레이션
                migrated = [
                    {"date": k, "news": [{"title": t, "url": "", "source": "", "section": ""}
                                         for t in v]}
                    for k, v in sorted(data.items(), reverse=True)
                ]
                return migrated
            return data
    except Exception:
        return []


def save_archive(archive: list, new_articles: list):
    """아카이브에 새 기사 추가 후 GitHub에 저장 (ssi-hr-news 호환 포맷)"""
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    new_entries = [
        {
            "title": a["title"],
            "url":   a.get("short_url", a.get("url", "")),
            "source": a.get("source", ""),
            "section": a.get("section", ""),
        }
        for a in new_articles
    ]

    # 오늘 날짜 항목 업데이트 or 신규 삽입
    found = False
    for entry in archive:
        if entry["date"] == today_str:
            entry["news"] = new_entries
            found = True
            break
    if not found:
        archive.insert(0, {"date": today_str, "news": new_entries})

    # 30일 이상 된 기록 삭제 후 최신순 정렬
    cutoff = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
    archive = [e for e in archive if e["date"] >= cutoff]
    archive.sort(key=lambda x: x["date"], reverse=True)

    content = json.dumps(archive, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

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
            api_url, data=payload, method="PUT",
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


def load_recent_archive_titles(archive: list) -> set:
    """최근 N일 아카이브에서 이미 발송된 기사 제목+URL 집합 반환 (이중 중복 방지)"""
    cutoff = (datetime.now(KST) - timedelta(days=ARCHIVE_DAYS)).strftime("%Y-%m-%d")
    keys = set()
    for entry in archive:
        if entry["date"] >= cutoff:
            for item in entry.get("news", []):
                if isinstance(item, dict):
                    title = item.get("title", "").strip()
                    url = item.get("url", "").strip()
                    if title:
                        keys.add(title)
                    if url:
                        keys.add(url)
                else:
                    keys.add(str(item))
    print(f"[archive] 최근 {ARCHIVE_DAYS}일 기사 {len(keys)}건 중복 방지 로드 (제목+URL)")
    return keys


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
    # 아카이브 중복 제거 (제목 OR URL 일치 시 제외)
    all_candidates = [
        a for a in all_candidates
        if a["title"] not in archive_titles and a.get("url", "") not in archive_titles
    ]

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
        backup_candidates = [
            a for a in backup_candidates
            if a["title"] not in archive_titles and a.get("url", "") not in archive_titles
        ]
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

    # 아카이브 저장 (각 기사에 section 키 추가)
    all_articles = []
    for section_key, articles in sections.items():
        for a in articles:
            a["section"] = section_key
            all_articles.append(a)
    save_archive(archive, all_articles)

    return sections


# ─────────────────────────────────────────────
#  ⑥ HTML 이메일 템플릿
# ─────────────────────────────────────────────
SECTION_META = {
    "hr":             {"icon": "👥", "title": "HR",          "desc": "인사기획 · 평가 · 조직문화 · 노동법 핵심 이슈"},
    "ai":             {"icon": "🤖", "title": "AI / 기술",    "desc": "AI · 디지털 전환이 기업과 HR에 미치는 영향"},
    "startup_invest": {"icon": "💰", "title": "투자",         "desc": "국내 스타트업 투자 · VC · IPO 동향"},
    "startup_launch": {"icon": "🚀", "title": "출시 / 성과",  "desc": "스타트업 신규 서비스 · 해외 진출 · 수상"},
    "startup_issue":  {"icon": "📋", "title": "지원 / 이슈",  "desc": "정부 지원 · 규제 · 창업 생태계 이슈"},
}
SECTION_ORDER = ["hr", "ai", "startup_invest", "startup_launch", "startup_issue"]


LOGO_URL = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/logo.png"


def build_email_html(sections: dict) -> str:
    """ssi-hr-news 스타일 이메일 HTML 생성"""
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    days = ["월","화","수","목","금","토","일"]
    weekday = days[datetime.now(KST).weekday()]

    subscribe_subject   = urllib.parse.quote("CEO Morning Briefing 구독 신청")
    subscribe_body      = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 신청합니다.\n\n수신 이메일: (여기에 이메일 주소를 입력해 주세요)\n\n감사합니다.")
    unsubscribe_subject = urllib.parse.quote("CEO Morning Briefing 구독 취소")
    unsubscribe_body    = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 취소 요청합니다.\n\n수신 이메일: (취소할 이메일 주소를 입력해 주세요)\n\n감사합니다.")
    mailto_subscribe   = f"mailto:{GMAIL_USER}?subject={subscribe_subject}&body={subscribe_body}"
    mailto_unsubscribe = f"mailto:{GMAIL_USER}?subject={unsubscribe_subject}&body={unsubscribe_body}"
    pages_url = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/"

    # 섹션별 뉴스 행 생성 (번호 뱃지 + 카테고리 구분선)
    news_rows = ""
    item_num = 1
    prev_section = None
    for key in SECTION_ORDER:
        articles = sections.get(key, [])
        if not articles:
            continue
        meta = SECTION_META[key]
        # 카테고리 구분 헤더
        news_rows += f"""
        <tr>
          <td style="padding:14px 20px 10px; background:#f4f6f9; border-bottom:2px solid #1a1a2e;">
            <div style="font-size:13px; font-weight:700; color:#1a1a2e; letter-spacing:0.3px;">
              {meta['icon']}&nbsp;{meta['title']}
            </div>
            <div style="font-size:11px; color:#6b7280; margin-top:3px;">{meta.get('desc','')}</div>
          </td>
        </tr>"""
        for art in articles:
            source = art.get("source", "")
            url    = art.get("short_url", art.get("url", "#"))
            title  = art["title"].replace("<","&lt;").replace(">","&gt;")
            news_rows += f"""
        <tr>
          <td style="padding:16px 20px; border-bottom:1px solid #f0f0f0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="32" valign="top" style="padding-top:2px;">
                  <div style="width:24px; height:24px; background:#1a1a2e; border-radius:50%;
                              color:#fff; font-size:12px; font-weight:700;
                              text-align:center; line-height:24px;">{item_num}</div>
                </td>
                <td style="padding-left:12px;">
                  <a href="{url}" target="_blank"
                     style="font-size:15px; font-weight:600; color:#1a1a2e;
                            text-decoration:none; line-height:1.5;">{title}</a>
                  <div style="margin-top:6px;">
                    <span style="font-size:12px; color:#9ca3af;">{source}</span>
                    &nbsp;&nbsp;
                    <a href="{url}" target="_blank"
                       style="font-size:12px; color:#fff; background:#1a1a2e;
                              text-decoration:none; padding:3px 10px; border-radius:4px;">
                      기사 보기 →
                    </a>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""
            item_num += 1

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0; padding:0; background:#f0f2f5;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5; padding:32px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%;">

      <!-- 헤더 -->
      <tr>
        <td style="background:#e7f0e9; border-radius:12px 12px 0 0;
                   padding:28px 24px 22px; text-align:center;">
          <img src="{LOGO_URL}" alt="상상인그룹" width="90" height="85"
               style="display:block; margin:0 auto 14px;" />
          <div style="font-size:20px; font-weight:800; color:#1a1a2e; line-height:1.3;">
            CEO Morning Briefing
          </div>
          <div style="font-size:14px; font-weight:600; color:#1a1a2e; margin-top:2px;">
            HR · AI · 스타트업 주요 뉴스
          </div>
          <div style="font-size:12px; color:#5a7a60; margin-top:8px;">
            {today} ({weekday})
          </div>
        </td>
      </tr>

      <!-- 뉴스 목록 -->
      <tr>
        <td style="background:#ffffff;">
          <table width="100%" cellpadding="0" cellspacing="0">
            {news_rows}
          </table>
        </td>
      </tr>

      <!-- 푸터 -->
      <tr>
        <td style="background:#f8f9fa; border-radius:0 0 12px 12px;
                   padding:24px 24px 20px; text-align:center;
                   border-top:1px solid #e5e7eb;">
          <a href="{pages_url}" target="_blank"
             style="display:inline-block; font-size:13px; font-weight:600; color:#1a1a2e;
                    text-decoration:none; border:1px solid #1a1a2e; border-radius:6px;
                    padding:8px 20px;">
            📁 전체 뉴스 아카이브 보기
          </a>
          <div style="margin-top:14px;">
            <a href="{mailto_subscribe}"
               style="display:inline-block; font-size:12px; font-weight:600; color:#fff;
                      background:#1a1a2e; text-decoration:none; border-radius:6px;
                      padding:7px 18px; margin:0 4px;">
              ✉️ 구독 신청
            </a>
            <a href="{mailto_unsubscribe}"
               style="display:inline-block; font-size:12px; font-weight:500; color:#6b7280;
                      background:#fff; text-decoration:none; border:1px solid #d1d5db;
                      border-radius:6px; padding:7px 18px; margin:0 4px;">
              구독 취소
            </a>
          </div>
          <div style="margin-top:12px;">
            <a href="https://ssihr.oopy.io" target="_blank"
               style="font-size:12px; color:#1a1a2e; text-decoration:none; margin:0 8px;">
              인재경영실 소개
            </a>
          </div>
          <div style="font-size:11px; color:#9ca3af; margin-top:12px;">
            매일 오전 9시 자동 발송 · 상상인그룹 인재경영실
          </div>
        </td>
      </tr>

    </table>
  </td></tr>
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


def build_github_page_html() -> str:
    """ssi-hr-news 스타일 GitHub Pages index.html 생성
    (news_archive.json을 JS fetch로 동적 로딩 — 검색/필터/카드 그리드)"""
    subscribe_subject   = urllib.parse.quote("CEO Morning Briefing 구독 신청")
    subscribe_body      = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 신청합니다.\n\n수신 이메일: (여기에 이메일 주소를 입력해 주세요)\n\n감사합니다.")
    unsubscribe_subject = urllib.parse.quote("CEO Morning Briefing 구독 취소")
    unsubscribe_body    = urllib.parse.quote("안녕하세요,\n\nCEO Morning Briefing 구독을 취소 요청합니다.\n\n수신 이메일: (취소할 이메일 주소를 입력해 주세요)\n\n감사합니다.")
    mailto_subscribe   = f"mailto:{GMAIL_USER}?subject={subscribe_subject}&body={subscribe_body}"
    mailto_unsubscribe = f"mailto:{GMAIL_USER}?subject={unsubscribe_subject}&body={unsubscribe_body}"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CEO Morning Briefing | 상상인그룹</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --teal: #1CC9BE; --teal-dk: #17b0a6; --dark: #1a1a2e; --gray-lt: #f0f2f5; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
      background: var(--gray-lt); color: var(--dark); min-height: 100vh;
    }}
    header {{
      background: #e7f0e9; color: var(--dark);
      padding: 28px 24px 24px; text-align: center;
    }}
    header img {{ width: 72px; height: auto; display: block; margin: 0 auto 14px; }}
    header h1 {{ font-size: 1.55rem; font-weight: 700; letter-spacing: -0.3px; color: var(--dark); }}
    header p {{ margin-top: 6px; font-size: 0.83rem; color: #5a7a60; }}
    .stats {{
      display: flex; justify-content: center; gap: 0;
      background: #fff; border-bottom: 1px solid #e5e7eb;
    }}
    .stat {{ text-align: center; padding: 16px 40px; border-right: 1px solid #e5e7eb; }}
    .stat:last-child {{ border-right: none; }}
    .stat-num {{ font-size: 1.5rem; font-weight: 800; color: var(--teal); }}
    .stat-label {{ font-size: 0.72rem; color: #6b7280; margin-top: 3px; letter-spacing: 0.3px; }}
    .toolbar {{
      max-width: 1100px; margin: 28px auto 0; padding: 0 20px;
      display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
    }}
    #searchBox {{
      flex: 1; min-width: 200px; padding: 10px 16px;
      border: 1px solid #d1d5db; border-radius: 8px; font-size: 0.9rem;
      outline: none; background: #fff; transition: border-color .2s, box-shadow .2s;
    }}
    #searchBox:focus {{ border-color: var(--teal); box-shadow: 0 0 0 3px rgba(28,201,190,.12); }}
    #monthFilter {{
      padding: 10px 14px; border: 1px solid #d1d5db; border-radius: 8px;
      font-size: 0.88rem; background: #fff; color: var(--dark);
      outline: none; cursor: pointer; transition: border-color .2s;
    }}
    #monthFilter:focus {{ border-color: var(--teal); }}
    .result-count {{ font-size: 0.82rem; color: #6b7280; white-space: nowrap; }}
    main {{ max-width: 1100px; margin: 20px auto 80px; padding: 0 20px; }}
    .date-group {{ margin-bottom: 36px; }}
    .date-label {{
      font-size: 0.8rem; font-weight: 700; color: var(--dark);
      letter-spacing: 0.4px; margin-bottom: 14px; padding: 6px 12px;
      background: #fff; border-left: 3px solid var(--teal);
      border-radius: 0 6px 6px 0; display: inline-block;
    }}
    .card-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }}
    @media (max-width: 640px) {{
      .card-grid {{ grid-template-columns: 1fr; }}
      .stat {{ padding: 14px 20px; }}
      .toolbar {{ flex-direction: column; }}
      #searchBox {{ min-width: unset; }}
    }}
    .card {{
      background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
      padding: 18px 20px; display: flex; flex-direction: column; gap: 10px;
      transition: box-shadow .18s, transform .18s, border-color .18s;
    }}
    .card:hover {{
      border-color: var(--teal);
      box-shadow: 0 6px 20px rgba(28,201,190,.15);
      transform: translateY(-2px);
    }}
    .card-top {{ display: flex; align-items: flex-start; gap: 12px; }}
    .card-num {{
      flex-shrink: 0; width: 26px; height: 26px; background: var(--teal);
      color: var(--dark); border-radius: 50%; font-size: 0.72rem; font-weight: 800;
      display: flex; align-items: center; justify-content: center; margin-top: 1px;
    }}
    .card-title {{
      font-size: 0.93rem; font-weight: 600; line-height: 1.5;
      color: var(--dark); text-decoration: none; word-break: keep-all; flex: 1;
    }}
    .card-title:hover {{ color: var(--teal-dk); text-decoration: underline; }}
    .card-bottom {{
      display: flex; align-items: center; justify-content: space-between;
      padding-top: 6px; border-top: 1px solid #f3f4f6;
    }}
    .card-source {{ font-size: 0.75rem; color: #9ca3af; font-weight: 500; }}
    .card-section {{
      font-size: 0.68rem; font-weight: 700; color: #fff;
      background: var(--dark); border-radius: 4px; padding: 2px 7px;
    }}
    .card-link {{
      font-size: 0.76rem; font-weight: 700; color: var(--dark);
      background: var(--teal); text-decoration: none;
      border-radius: 5px; padding: 4px 11px; transition: background .15s; white-space: nowrap;
    }}
    .card-link:hover {{ background: var(--teal-dk); }}
    .empty, .loading {{
      text-align: center; padding: 80px 0; color: #9ca3af;
      font-size: 0.9rem; grid-column: 1 / -1;
    }}
    .empty-wrap {{ display: grid; }}
    #backToTop {{
      position: fixed; bottom: 32px; right: 28px;
      width: 44px; height: 44px; background: var(--teal); color: var(--dark);
      border: none; border-radius: 50%; font-size: 1.1rem; font-weight: 700;
      cursor: pointer; box-shadow: 0 4px 14px rgba(28,201,190,.4);
      display: flex; align-items: center; justify-content: center;
      opacity: 0; pointer-events: none; transition: opacity .25s, transform .25s; z-index: 100;
    }}
    #backToTop.visible {{ opacity: 1; pointer-events: auto; }}
    #backToTop:hover {{ transform: scale(1.1); background: var(--teal-dk); }}
    .subscribe-wrap {{ display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }}
    .btn-subscribe {{
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 0.82rem; font-weight: 700; text-decoration: none;
      border-radius: 6px; padding: 7px 18px;
      transition: background .15s, color .15s, border-color .15s;
      cursor: pointer; white-space: nowrap;
    }}
    .btn-subscribe.primary {{
      background: var(--teal); color: var(--dark); border: 1px solid var(--teal);
    }}
    .btn-subscribe.primary:hover {{ background: var(--teal-dk); border-color: var(--teal-dk); }}
    .btn-subscribe.ghost {{
      background: transparent; color: #6b7280; border: 1px solid #d1d5db;
    }}
    .btn-subscribe.ghost:hover {{ border-color: #9ca3af; color: #374151; }}
    footer {{
      background: #fff; border-top: 1px solid #e5e7eb;
      padding: 28px 24px; text-align: center;
    }}
    .footer-links {{
      display: flex; justify-content: center; align-items: center;
      gap: 16px; flex-wrap: wrap; margin-top: 16px;
    }}
    .footer-link {{ font-size: 0.8rem; color: #9ca3af; text-decoration: none; }}
    .footer-link:hover {{ color: var(--teal); text-decoration: underline; }}
    .footer-divider {{ color: #d1d5db; font-size: 0.75rem; }}
    .footer-copy {{ font-size: 0.75rem; color: #9ca3af; margin-top: 14px; }}
  </style>
</head>
<body>

<header>
  <img src="logo.png" alt="상상인그룹" />
  <h1>CEO Morning Briefing</h1>
  <p>HR · AI · 스타트업 주요 뉴스 · 매일 오전 9시 수신</p>
  <div class="subscribe-wrap" style="margin-top:18px;">
    <a class="btn-subscribe primary" href="{mailto_subscribe}">✉️ 구독 신청</a>
  </div>
</header>

<div class="stats">
  <div class="stat">
    <div class="stat-num" id="statDays">-</div>
    <div class="stat-label">수집 일수</div>
  </div>
  <div class="stat">
    <div class="stat-num" id="statTotal">-</div>
    <div class="stat-label">누적 기사</div>
  </div>
  <div class="stat">
    <div class="stat-num" id="statLatest">-</div>
    <div class="stat-label">최근 수신</div>
  </div>
</div>

<div class="toolbar">
  <input id="searchBox" type="text" placeholder="🔍 기사 제목 검색..." oninput="renderNews()" />
  <select id="monthFilter" onchange="renderNews()">
    <option value="">전체 기간</option>
  </select>
  <span class="result-count" id="resultCount"></span>
</div>

<main>
  <div id="content">
    <div class="loading">뉴스 데이터를 불러오는 중...</div>
  </div>
</main>

<button id="backToTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" title="맨 위로">↑</button>

<footer>
  <div class="subscribe-wrap">
    <a class="btn-subscribe primary" href="{mailto_subscribe}">✉️ 구독 신청</a>
    <a class="btn-subscribe ghost"   href="{mailto_unsubscribe}">구독 취소</a>
  </div>
  <div class="footer-links">
    <a class="footer-link" href="https://ssihr.oopy.io" target="_blank" rel="noopener">
      👋 인재경영실 소개
    </a>
    <span class="footer-divider">|</span>
    <a class="footer-link" href="#"
       onclick="window.scrollTo({{top:0,behavior:'smooth'}});return false;">↑ 맨 위로</a>
  </div>
  <p class="footer-copy">매일 오전 9시 자동 발송 · 상상인그룹 인재경영실</p>
</footer>

<script>
  // 섹션 레이블 매핑
  const SECTION_LABELS = {{
    hr: "👥 HR",
    ai: "🤖 AI / 기술",
    startup_invest: "💰 투자",
    startup_launch: "🚀 출시 / 성과",
    startup_issue:  "📋 지원 / 이슈",
  }};

  let allData = [];

  async function loadData() {{
    try {{
      const res = await fetch('news_archive.json?_=' + Date.now());
      allData = await res.json();
      allData.sort((a, b) => b.date.localeCompare(a.date));
      updateStats();
      buildMonthFilter();
      renderNews();
    }} catch (e) {{
      document.getElementById('content').innerHTML =
        '<div class="empty">데이터를 불러오지 못했습니다.<br>잠시 후 새로고침 해주세요.</div>';
    }}
  }}

  function updateStats() {{
    const days   = allData.length;
    const total  = allData.reduce((s, d) => s + d.news.length, 0);
    const latest = days > 0 ? allData[0].date.replace(/-/g, '.') : '-';
    document.getElementById('statDays').textContent   = days;
    document.getElementById('statTotal').textContent  = total;
    document.getElementById('statLatest').textContent = latest;
  }}

  function buildMonthFilter() {{
    const months = [...new Set(allData.map(d => d.date.slice(0, 7)))];
    const sel = document.getElementById('monthFilter');
    months.forEach(m => {{
      const [y, mo] = m.split('-');
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = `${{y}}년 ${{parseInt(mo)}}월`;
      sel.appendChild(opt);
    }});
  }}

  function renderNews() {{
    const query  = document.getElementById('searchBox').value.trim().toLowerCase();
    const month  = document.getElementById('monthFilter').value;
    const container = document.getElementById('content');

    const filtered = allData.map(group => {{
      if (month && !group.date.startsWith(month)) return null;
      const news = group.news.filter(n => !query || n.title.toLowerCase().includes(query));
      return news.length > 0 ? {{ ...group, news }} : null;
    }}).filter(Boolean);

    const totalItems = filtered.reduce((s, g) => s + g.news.length, 0);
    document.getElementById('resultCount').textContent =
      filtered.length > 0 ? `${{filtered.length}}일 · ${{totalItems}}건` : '';

    if (filtered.length === 0) {{
      container.innerHTML = '<div class="empty-wrap"><div class="empty">검색 결과가 없습니다.</div></div>';
      return;
    }}

    container.innerHTML = filtered.map(group => `
      <div class="date-group">
        <div class="date-label">📅 ${{formatDate(group.date)}}</div>
        <div class="card-grid">
          ${{group.news.map((n, i) => `
            <div class="card">
              <div class="card-top">
                <div class="card-num">${{i + 1}}</div>
                <a class="card-title" href="${{n.url}}" target="_blank" rel="noopener">
                  ${{escHtml(n.title)}}
                </a>
              </div>
              <div class="card-bottom">
                <span class="card-section">${{SECTION_LABELS[n.section] || ''}}</span>
                <span class="card-source">${{escHtml(n.source || '')}}</span>
                <a class="card-link" href="${{n.url}}" target="_blank" rel="noopener">기사 보기 →</a>
              </div>
            </div>
          `).join('')}}
        </div>
      </div>
    `).join('');
  }}

  function formatDate(dateStr) {{
    const d = new Date(dateStr);
    const days = ['일','월','화','수','목','금','토'];
    return `${{d.getFullYear()}}년 ${{d.getMonth()+1}}월 ${{d.getDate()}}일 (${{days[d.getDay()]}})`;
  }}

  function escHtml(str) {{
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
              .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }}

  const btn = document.getElementById('backToTop');
  window.addEventListener('scroll', () => {{
    btn.classList.toggle('visible', window.scrollY > 300);
  }});

  loadData();
</script>
</body>
</html>"""


def push_to_github(sections: dict):
    """GitHub Pages 업데이트: index.html + logo.png 복사"""
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    # 1) index.html (동적 아카이브 페이지 — sections 불필요)
    index_html = build_github_page_html()
    _push_file_to_github(
        "index.html",
        index_html.encode("utf-8"),
        f"[pages] {today_str} index.html 업데이트",
    )

    # 2) logo.png — ssi-hr-news 레포에서 복사 (없으면 건너뜀)
    logo_url = "https://raw.githubusercontent.com/goodwon89/ssi-hr-news/main/logo.png"
    try:
        req = urllib.request.Request(logo_url, headers={"User-Agent": "CEO-Morning-Briefing"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            logo_bytes = resp.read()
        _push_file_to_github("logo.png", logo_bytes, "[logo] 상상인그룹 로고 업데이트")
    except Exception as e:
        print(f"[logo] 복사 실패(건너뜀): {e}")


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
