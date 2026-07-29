"""Single source of truth for report scope, focus, and presentation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from newsroom.control.digests import DEFAULT_TOPIC_BRIEF, InterestPolicy


@dataclass(frozen=True)
class ReportProfile:
    """Editorial contract for one user-facing report mode."""

    mode: str
    title_fa: str
    title_en: str
    source_types: frozenset[str] | None
    comprehensive: bool
    max_stories: int
    minimum_telegram_stories: int


_DEFAULT = ReportProfile(
    mode="scheduled",
    title_en="News digest",
    title_fa="\u062e\u0628\u0631\u0646\u0627\u0645\u0647",
    source_types=None,
    comprehensive=False,
    max_stories=15,
    minimum_telegram_stories=2,
)

_PROFILES = {
    "scheduled": _DEFAULT,
    "manual": _DEFAULT,
    "manual_new": _DEFAULT,
    "manual_comprehensive": ReportProfile(
        mode="manual_comprehensive",
        title_en="Comprehensive digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639",
        source_types=None,
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=2,
    ),
    "platform_telegram": ReportProfile(
        mode="platform_telegram",
        title_en="Telegram digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 \u062a\u0644\u06af\u0631\u0627\u0645",
        source_types=frozenset({"telegram"}),
        comprehensive=True,
        max_stories=30,
        minimum_telegram_stories=30,
    ),
    "platform_x": ReportProfile(
        mode="platform_x",
        title_en="X digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 X",
        source_types=frozenset({"x_timeline"}),
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_web": ReportProfile(
        mode="platform_web",
        title_en="Website digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 \u0648\u0628\u200c\u0633\u0627\u06cc\u062a\u200c\u0647\u0627",
        source_types=frozenset({"web_page", "rss"}),
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_github": ReportProfile(
        mode="platform_github",
        title_en="GitHub digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 GitHub",
        source_types=frozenset({"github_releases"}),
        comprehensive=True,
        max_stories=24,
        minimum_telegram_stories=0,
    ),
    "platform_reddit": ReportProfile(
        mode="platform_reddit",
        title_en="Reddit digest",
        title_fa="\u06af\u0632\u0627\u0631\u0634 \u062c\u0627\u0645\u0639 Reddit",
        source_types=frozenset({"reddit_subreddit"}),
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
    r"|\u0628\u0631\u0646\u0627\u0645\u0647[‌\s-]?\u0646\u0648\u06cc\u0633\u06cc|\u062a\u0648\u0633\u0639\u0647[‌\s-]?\u062f\u0647\u0646\u062f\u0647|\u06a9\u062f\u0646\u0648\u06cc\u0633\u06cc|\u0645\u062a\u0646[‌\s-]?\u0628\u0627\u0632|"
    r"\u06a9\u062a\u0627\u0628\u062e\u0627\u0646\u0647|\u0686\u0627\u0631\u0686\u0648\u0628|\u067e\u0631\u0648\u0698\u0647|\u0645\u062e\u0632\u0646|\u0627\u0628\u0632\u0627\u0631|\u0645\u062f\u0644 \u0647\u0648\u0634 \u0645\u0635\u0646\u0648\u0639\u06cc|\u0631\u0627\u0628\u0637 \u0628\u0631\u0646\u0627\u0645\u0647[‌\s-]?\u0646\u0648\u06cc\u0633\u06cc|"
    r"\u0627\u06cc[‌\s-]?\u067e\u06cc[‌\s-]?\u0622\u06cc|\u0627\u0646\u062a\u0634\u0627\u0631 \u0646\u0633\u062e\u0647|\u0631\u0641\u0639 \u0628\u0627\u06af|\u0622\u0633\u06cc\u0628[‌\s-]?\u067e\u0630\u06cc\u0631\u06cc"
)

_NON_ARTICLE_RE = re.compile(
    r"(?ix)"
    r"^\s*(?:https?://|www\.)"
    r"|<\s*(?:table|div|span|a|img)\b"
    r"|submitted\s+by"
    r"|share\s+(?:on|to)"
    r"|\u0627\u0634\u062a\u0631\u0627\u06a9[‌\s-]?\u06af\u0630\u0627\u0631\u06cc|\u0628\u0647\s+\u0627\u0634\u062a\u0631\u0627\u06a9\s+\u06af\u0630\u0627\u0634\u062a\u0646"
    r"|\u062f\u0631 \u067e\u0646\u062c\u0631[\u06c0\u0647] \u062a\u0627\u0632\u0647 \u0628\u0627\u0632 \u0645\u06cc[‌\s-]?\u0634\u0648\u062f"
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

DEFAULT_INTEREST_POLICY = InterestPolicy(DEFAULT_TOPIC_BRIEF)
_TOPIC_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "also",
        "and",
        "from",
        "into",
        "news",
        "selected",
        "that",
        "the",
        "their",
        "this",
        "tools",
        "with",
        "\u0628\u0631\u0627\u06cc",
        "\u0627\u06cc\u0646",
        "\u062e\u0628\u0631",
        "\u062f\u0631\u0628\u0627\u0631\u0647",
        "\u0647\u0627\u06cc",
    }
)


def resolve_report_profile(report_mode: str) -> ReportProfile:
    """Resolve aliases while keeping unknown legacy modes safe."""
    profile = _PROFILES.get(report_mode, _DEFAULT)
    if profile.mode == report_mode:
        return profile
    return ReportProfile(
        mode=report_mode,
        title_en=profile.title_en,
        title_fa=profile.title_fa,
        source_types=profile.source_types,
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
    if source_type in {"web_page", "rss", "youtube_rss"} and any(
        signal in normalized_category for signal in _PROGRAMMING_CATEGORY_SIGNALS
    ):
        # Category metadata is a useful high-recall hint, but cannot turn a
        # reaction, channel announcement, or empty navigation row into news.
        meaningful_words = {
            word.casefold() for word in re.findall(r"[\w\u0600-\u06FF]+", combined) if len(word) > 2
        }
        return len(meaningful_words) >= 10
    return False


def is_interest_material(
    *,
    interest: InterestPolicy,
    category: str,
    title: str,
    description: str,
    source_type: str,
) -> bool:
    """Apply a high-recall deterministic interest filter before LLM work."""
    combined = f"{category}\n{title}\n{description}".casefold()
    if any(term.casefold() in combined for term in interest.exclude_terms):
        return False
    if any(term.casefold() in combined for term in interest.include_terms):
        return True
    if interest.topic_brief == DEFAULT_TOPIC_BRIEF:
        return is_programming_material(
            category=category,
            title=title,
            description=description,
            source_type=source_type,
        )
    topic_terms = {
        token.casefold()
        for token in re.findall(r"[\w\u0600-\u06FF-]+", interest.topic_brief)
        if len(token) >= 4 and token.casefold() not in _TOPIC_STOP_WORDS
    }
    return bool(
        topic_terms and topic_terms.intersection(set(re.findall(r"[\w\u0600-\u06FF-]+", combined)))
    )


def is_usable_editorial_material(*, title: str, description: str) -> bool:
    """Reject navigation, profile, syndication markup, and channel ads."""
    clean_title = unescape(title).strip()
    if len(clean_title) < 8 or _NON_ARTICLE_RE.search(clean_title):
        return False
    words = re.findall(r"[\w\u0600-\u06FF]+", clean_title)
    return not (len(words) < 3 and not description.strip())


def editorial_focus_instruction(
    report_mode: str,
    interest: InterestPolicy = DEFAULT_INTEREST_POLICY,
) -> str:
    """Return a compact prompt rule tailored to the selected profile."""
    profile = resolve_report_profile(report_mode)
    source_rule = (
        "Use only evidence from the requested platform."
        if profile.source_types
        else "Use only the selected digest sources."
    )
    include_rule = (
        f" Give particular attention to: {', '.join(interest.include_terms)}."
        if interest.include_terms
        else ""
    )
    exclude_rule = (
        f" Exclude: {', '.join(interest.exclude_terms)}." if interest.exclude_terms else ""
    )
    return (
        f"The operator-defined subject is: {interest.topic_brief} "
        "Include only evidence relevant to that subject. Never combine unrelated evidence "
        f"items into one story. {source_rule}{include_rule}{exclude_rule}"
    )
