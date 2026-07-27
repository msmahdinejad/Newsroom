"""Single source of truth for report scope, focus, and presentation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape


@dataclass(frozen=True)
class ReportProfile:
    """Editorial contract for one user-facing report mode."""

    mode: str
    title_fa: str
    source_types: frozenset[str] | None
    programming_only: bool
    comprehensive: bool
    max_stories: int
    minimum_telegram_stories: int


_DEFAULT = ReportProfile(
    mode="scheduled",
    title_fa="اخبار برنامه‌نویسی و ابزارهای توسعه",
    source_types=None,
    programming_only=True,
    comprehensive=False,
    max_stories=15,
    minimum_telegram_stories=9,
)

_PROFILES = {
    "scheduled": _DEFAULT,
    "manual": _DEFAULT,
    "manual_new": _DEFAULT,
    "manual_comprehensive": ReportProfile(
        mode="manual_comprehensive",
        title_fa="گزارش جامع برنامه‌نویسی",
        source_types=None,
        programming_only=True,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=12,
    ),
    "platform_telegram": ReportProfile(
        mode="platform_telegram",
        title_fa="گزارش جامع برنامه‌نویسی از تلگرام",
        source_types=frozenset({"telegram"}),
        programming_only=True,
        comprehensive=True,
        max_stories=30,
        minimum_telegram_stories=30,
    ),
    "platform_x": ReportProfile(
        mode="platform_x",
        title_fa="گزارش جامع برنامه‌نویسی از X",
        source_types=frozenset({"x_timeline"}),
        programming_only=True,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_web": ReportProfile(
        mode="platform_web",
        title_fa="گزارش جامع برنامه‌نویسی از وب‌سایت‌ها",
        source_types=frozenset({"web_page", "rss"}),
        programming_only=True,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_github": ReportProfile(
        mode="platform_github",
        title_fa="گزارش جامع پروژه‌ها و انتشارهای GitHub",
        source_types=frozenset({"github_releases"}),
        programming_only=True,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_reddit": ReportProfile(
        mode="platform_reddit",
        title_fa="گزارش جامع برنامه‌نویسی از Reddit",
        source_types=frozenset({"reddit_subreddit"}),
        programming_only=True,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
}

_PROGRAMMING_CATEGORY_SIGNALS = (
    "program",
    "developer",
    "development",
    "engineering",
    "open source",
    "api",
    "web",
    "devops",
    "cloud",
    "database",
    "data ",
    "python",
    "javascript",
    "typescript",
    "rust",
    "linux",
    "automation",
    "computer science",
    "system design",
    "mlops",
    "machine learning",
    "ai engineering",
    "ai infrastructure",
    "ai tools",
    "ai agents",
    "open source ai",
    "generative ai",
    "prompt engineering",
    "self hosting",
    "no-code",
    "vibe coding",
    "embedded",
)

_PROGRAMMING_TEXT_RE = re.compile(
    r"(?ix)"
    r"\b(apis?|sdk|cli|ide|library|framework|package|plugin|extension|repository|repo|"
    r"open[\s-]?source|release|changelog|developer|programming|software|coding|codebase|"
    r"python|javascript|typescript|node(?:\.js)?|react|vue|angular|rust|golang|\.net|"
    r"kotlin|swift|php|ruby|java|c\+\+|docker|kubernetes|linux|github|gitlab|"
    r"html|css|sql|git|web\s+app|mobile\s+app|"
    r"postgres(?:ql)?|mysql|database|devops|mlops|backend|frontend|fullstack|"
    r"debug|compiler|runtime|dependency|vulnerability|self[\s-]?host|terminal|"
    r"powershell|forensics|"
    r"free\s+api|ai\s+(?:model|tool|agent)|llm|rag|inference)\b"
    r"|برنامه[‌\s-]?نویسی|توسعه[‌\s-]?دهنده|کدنویسی|متن[‌\s-]?باز|"
    r"کتابخانه|چارچوب|پروژه|مخزن|ابزار|مدل هوش مصنوعی|رابط برنامه[‌\s-]?نویسی|"
    r"ای[‌\s-]?پی[‌\s-]?آی|انتشار نسخه|رفع باگ|آسیب[‌\s-]?پذیری"
)

_NON_ARTICLE_RE = re.compile(
    r"(?ix)"
    r"^\s*(?:https?://|www\.)"
    r"|<\s*(?:table|div|span|a|img)\b"
    r"|submitted\s+by"
    r"|share\s+(?:on|to)"
    r"|اشتراک[‌\s-]?گذاری|به\s+اشتراک\s+گذاشتن"
    r"|در پنجر[ۀه] تازه باز می[‌\s-]?شود"
    r"|this\s+channels?\s+is\s+for"
    r"|join\s+(?:our|this|the)\s+channel"
    r"|^done\b.*\breact\s+for\s+more"
    r"|giveaway\s+done|react\s+for\s+more\s+such\s+giveaways"
    r"|got\s+its\s+official,\s*stable\s+android"
    r"|snapdragon.+(?:ram|storage|main\s+cam)"
    r"|looking\s+for\s+paid"
    r"|paid\s+(?:bot|project|app)"
    r"|contact\s+@"
    r"|support\s+our\s+domain\s+purchase"
    r"|supporting\s+our\s+bot\s+server|(?:any\s+)?donation"
    r"|price\s*:"
    r"|ready\s+to.*(?:business|online\s+presence)"
    r"|hey\s+there.+welcome|welcome\s+@"
    r"|welcome.+let\s+us\s+know\s+your\s+coding"
    r"(?:\s+or\s+learning)?\s+plans"
    r"|free\s+access\s+to\s+our\s+premium.+channel"
    r"|position\s*:\s*.+developer.+qualification"
    r"|gemini\s+pro.+cdk"
    r"|\#?user_joined|event\s+stamp"
    r"|back\s+and\s+working\s+perfectly"
)


def resolve_report_profile(report_mode: str) -> ReportProfile:
    """Resolve aliases while keeping unknown legacy modes safe."""
    profile = _PROFILES.get(report_mode, _DEFAULT)
    if profile.mode == report_mode:
        return profile
    return ReportProfile(
        mode=report_mode,
        title_fa=profile.title_fa,
        source_types=profile.source_types,
        programming_only=profile.programming_only,
        comprehensive=profile.comprehensive,
        max_stories=profile.max_stories,
        minimum_telegram_stories=profile.minimum_telegram_stories,
    )


def is_programming_material(
    *,
    category: str,
    title: str,
    description: str,
    source_type: str,
) -> bool:
    """High-recall filter for useful programming material, not general tech."""
    if source_type == "github_releases":
        return True
    normalized_category = category.casefold().strip()
    combined = f"{title}\n{description}"
    if _PROGRAMMING_TEXT_RE.search(combined):
        return True
    if (
        source_type in {"web_page", "rss", "youtube_rss"}
        and any(
            signal in normalized_category
            for signal in _PROGRAMMING_CATEGORY_SIGNALS
        )
    ):
        # Category metadata is a useful high-recall hint, but cannot turn a
        # reaction, channel announcement, or empty navigation row into news.
        meaningful_words = {
            word.casefold()
            for word in re.findall(r"[\w\u0600-\u06FF]+", combined)
            if len(word) > 2
        }
        return len(meaningful_words) >= 10
    return False


def is_usable_editorial_material(*, title: str, description: str) -> bool:
    """Reject navigation, profile, syndication markup, and channel ads."""
    clean_title = unescape(title).strip()
    if len(clean_title) < 8 or _NON_ARTICLE_RE.search(clean_title):
        return False
    words = re.findall(r"[\w\u0600-\u06FF]+", clean_title)
    return not (len(words) < 3 and not description.strip())


def editorial_focus_instruction(report_mode: str) -> str:
    """Return a compact prompt rule tailored to the selected profile."""
    profile = resolve_report_profile(report_mode)
    source_rule = (
        "Use only evidence from the requested platform."
        if profile.source_types
        else "Prefer Telegram evidence when quality is comparable."
    )
    return (
        "This is a programming newsroom report. Include programming news plus useful "
        "developer tools, open-source projects, libraries, frameworks, models, websites, "
        "tutorials, and free APIs. Exclude unrelated consumer technology, sport, health, "
        "entertainment, and general business. Never combine unrelated evidence items into "
        f"one story. {source_rule}"
    )
