"""用户问天气 / 所在城市：查设置里保存的城市并注入 LLM（禁止编造）。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_STRIP_CLOCK = re.compile(r"^\[clock\][^\n]*\n+", re.IGNORECASE)
_STRIP_WEATHER = re.compile(r"^\[weather\][^\n]*\n+", re.IGNORECASE)

_WEATHER_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:查|看|告诉|说说|帮忙|查看).{0,12}天气", re.IGNORECASE),
    re.compile(r"天气.{0,12}(?:怎么样|如何|咋样|怎样|情况|预报)", re.IGNORECASE),
    re.compile(r"(?:今天|明天|明日|当地|现在|今晚).{0,10}天气", re.IGNORECASE),
    re.compile(r"(?:明天|明日).{0,12}(?:气温|温度|下雨|下雪|出门|出去玩|郊游|踏青)", re.IGNORECASE),
    re.compile(r"(?:天气|天気).{0,12}(?:适合|能|可以).{0,8}(?:郊游|出去玩|出门|踏青)", re.IGNORECASE),
    re.compile(r"(?:气温|温度|多少度|几度|冷不冷|热不热)", re.IGNORECASE),
    re.compile(r"(?:会|要)(?:下雨|下雪)", re.IGNORECASE),
    re.compile(r"(?:没有|没|怎么没有).{0,10}(?:查|看).{0,10}天气", re.IGNORECASE),
    re.compile(r"天気|天候|天気予報|明日の天気", re.IGNORECASE),
)

_OUTING_HINT_RE = re.compile(
    r"适合.{0,8}(?:出门|出去玩|出去|外出|郊游|踏青)"
    r"|(?:出门|出去玩|出去|郊游|踏青).{0,8}(?:吗|么|不)",
    re.IGNORECASE,
)

_DATE_INVITE_RE = re.compile(
    r"约会|デート|和你约会|与你约会|和我去|跟你去|跟我去|一起去|一同去|一緒に(?:行|出)|お出かけ|出去约会",
    re.IGNORECASE,
)

_BAD_WEATHER_REPLY_RE = re.compile(
    r"MSN|查过|已查|查询|查到了|播报|大约\s*\d|的明天[，,]\s*大约|龙港的明天|已经在",
    re.IGNORECASE,
)

_CITY_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:城市|在哪|哪儿|哪里).{0,12}(?:哪|什么|哪里|哪儿)", re.IGNORECASE),
    re.compile(r"(?:知道|告诉).{0,10}(?:城市|在哪|哪儿)", re.IGNORECASE),
    re.compile(r"我们在哪", re.IGNORECASE),
    re.compile(r"(?:什么|哪个)城市", re.IGNORECASE),
    re.compile(r"所在城市", re.IGNORECASE),
)


@dataclass(frozen=True)
class WeatherSnapshot:
    city: str
    line: str
    source: str = ""

    @property
    def ok(self) -> bool:
        return bool((self.line or "").strip())


def _normalize_body(text: str) -> str:
    body = (text or "").strip()
    body = _STRIP_CLOCK.sub("", body).strip()
    body = _STRIP_WEATHER.sub("", body).strip()
    return body


def saved_weather_city() -> str:
    try:
        from pnn.pet.presence.config import load_presence_config

        cfg = load_presence_config()
        return (cfg.presence_weather_city or "").strip()
    except Exception:
        return ""


def weather_query_horizon(text: str) -> str:
    """today | tomorrow"""
    body = _normalize_body(text)
    if re.search(r"明天|明日|明早|明晚|翌日", body):
        return "tomorrow"
    return "today"


def user_mentions_date_invite(text: str) -> bool:
    body = _normalize_body(text)
    return bool(_DATE_INVITE_RE.search(body))


def user_asks_outing_suitability(text: str) -> bool:
    body = _normalize_body(text)
    return bool(_OUTING_HINT_RE.search(body)) or user_mentions_date_invite(body)


def _active_character_label() -> str:
    try:
        from pnn.llm.config_store import load_llm_config
        from pnn.characters.pack import load_pack

        cid = (load_llm_config().active_character or "").strip()
        pack = load_pack(cid) if cid else None
        if pack and (pack.name or pack.id):
            return (pack.name or pack.id).strip()
    except Exception:
        pass
    return "当前角色"


def _weather_reply_language_reminder() -> str:
    from pnn.characters.reply_lang import active_reply_language, is_chinese, is_japanese

    code = active_reply_language()
    if is_japanese(code):
        return (
            "必须用日语（日本語）回复整条消息，即使用户用中文提问；"
            "禁止用中文播天气或接约会话。"
        )
    if is_chinese(code):
        return "必须用简体中文回复整条消息。"
    return ""


def _line_implies_precipitation(line: str) -> bool:
    body = (line or "").strip()
    if not body:
        return False
    return bool(
        re.search(
            r"暴雨|大雨|中雨|小雨|阵雨|雷阵雨|雨雪|(?:^|[，,]\s*)[^，,]*雨|雪|预警",
            body,
        )
    )


def _weather_scene_hints(user_message: str, *, weather_line: str = "") -> str:
    """通用场景说明（不写死任何角色 ID）。"""
    hints: list[str] = []
    if weather_query_horizon(user_message) == "tomorrow":
        hints.append("用户问的是「明天」预报，不要只报此刻实况。")
    if _line_implies_precipitation(weather_line):
        hints.append(
            "【内部天气】显示当前有降雨或已发布降水/暴雨类预警；"
            "禁止说「阳光不强、天气正好、适合散步/出门」等与雨矛盾的内容；"
            "应自然提醒带伞、路滑注意安全，或建议待在室内。"
        )
    if user_mentions_date_invite(user_message):
        who = _active_character_label()
        hints.append(
            f"用户想与「{who}」约会或一同外出；你就是对话中的该角色本人"
            f"（用户直呼角色名也是在和你说话）。"
            "须用【角色设定】口吻接话（害羞、傲娇、关心等），"
            "把气温、晴雨、是否适合出门自然融进同一段；"
            "不要只报数字，不要推脱，不要像天气预报员念稿。"
        )
    elif user_asks_outing_suitability(user_message):
        hints.append("用户关心是否适合出门；结合降雨与气温给建议，语气像熟人聊天。")
    if not hints:
        return ""
    return "【天气场景】" + " ".join(hints)


def _weather_reply_rules() -> str:
    lang = _weather_reply_language_reminder()
    rules = (
        "【程序天气·回答规则】"
        "下列天气数据仅供你转述，禁止向用户提及来源、渠道或查询过程。"
        "禁止出现的词与说法：MSN、查、查询、查过、已查、程序、API、后台、数据、工具、"
        "「我已经查过了」「稍等我去查」「没有查询工具」。"
        "禁止播报腔（如单独一句「XX明天24〜29度」）或先汇报查到了什么再报数字。"
        "用【角色设定】像熟人聊天：一两段内自然说出气温、晴雨、是否适合出门；"
        "可用【表情:…】；不要列清单、不要分点、不要中英混杂。"
        "气温与晴雨必须与【内部天气】完全一致，禁止编造；"
        "若【内部天气】含具体温度区间，回复中须自然带出该数字，禁止只说「凉快/暖和」等模糊词。"
    )
    if lang:
        rules += lang
    return rules


def _weather_user_reply_hint() -> str:
    """附在用户消息末尾，提高模型对口吻约束的服从度。"""
    return (
        "[weather-reply] 口语化角色对白；禁止MSN/查过/播报/列数字；"
        "遵守【最重要规则-回复语言】；约会邀约须接话并融入天气判断。"
    )


def user_asks_weather(text: str) -> bool:
    body = _normalize_body(text)
    if not body or len(body) > 200:
        return False
    if not any(p.search(body) for p in _WEATHER_QUERY_PATTERNS):
        return False
    # 纯感慨「今天天气不错」不算查询
    if re.fullmatch(r".{0,20}天气(?:不错|真好|很好|真棒)[！!。~～]*", body):
        return False
    return True


def is_bad_weather_reply(text: str) -> bool:
    """播报腔 / 提及 MSN·查询过程 / 仅列数字。"""
    body = (text or "").strip()
    if not body:
        return False
    if _BAD_WEATHER_REPLY_RE.search(body):
        return True
    if re.search(r"^\s*[\u4e00-\u9fff]{1,6}的明天", body):
        return True
    return False


def sanitize_chat_history_for_weather(
    history: list[dict[str, str]] | None,
    user_message: str,
) -> list[dict[str, str]]:
    """天气问句时剔除历史中错误的播报式助理回复，避免模型照抄。"""
    hist = list(history or [])
    if not user_asks_weather(user_message):
        return hist
    cleaned: list[dict[str, str]] = []
    for item in hist:
        role = (item.get("role") or "").strip()
        content = (item.get("content") or "").strip()
        if role == "assistant" and is_bad_weather_reply(content):
            continue
        cleaned.append(item)
    return cleaned


def build_weather_polish_instruction(*, draft: str) -> str:
    return (
        "【天气润色·必须执行】上一版助理回复不合格（提到MSN/查过/播报腔或语言错误）。"
        "请根据【角色设定】与【内部天气】重写为一段自然口语；接用户的约会/出门话题；"
        "禁止MSN、查、查询、程序、API；禁止单独列气温；遵守【最重要规则-回复语言】。"
        f"不合格草稿：{draft.strip()[:400]}"
    )


def user_asks_saved_city(text: str) -> bool:
    body = _normalize_body(text)
    if not body or len(body) > 120:
        return False
    return any(p.search(body) for p in _CITY_QUERY_PATTERNS)


def needs_weather_injection(text: str) -> bool:
    return user_asks_weather(text) or user_asks_saved_city(text)


def prime_weather_for_message(user_message: str) -> WeatherSnapshot:
    """天气问句：API 侧用 Playwright 直抓 MSN（不走 MCP），供终端日志与 LLM 注入。"""
    if not user_asks_weather(user_message):
        return WeatherSnapshot(city="", line="")
    hz = weather_query_horizon(user_message)
    return fetch_live_weather_for_saved_city(force_refresh=False, horizon=hz)


def weather_status_payload(snap: WeatherSnapshot, user_message: str) -> dict[str, str | bool]:
    hz = weather_query_horizon(user_message)
    return {
        "city": snap.city,
        "line": snap.line,
        "horizon": hz,
        "ok": snap.ok,
        "via": snap.source or "playwright/msn",
    }


def weather_status_json(snap: WeatherSnapshot, user_message: str) -> str:
    import json

    return json.dumps(weather_status_payload(snap, user_message), ensure_ascii=False)


def fetch_live_weather_for_saved_city(
    *,
    force_refresh: bool = False,
    horizon: str = "today",
) -> WeatherSnapshot:
    city = saved_weather_city()
    if not city:
        return WeatherSnapshot(city="", line="")
    try:
        from pnn.core.msn_weather import fetch_msn_weather_snapshot

        snap = fetch_msn_weather_snapshot(
            city=city, enabled=True, force_refresh=force_refresh, horizon=horizon
        )
    except Exception as exc:
        logger.warning("MSN 天气查询失败: %s", exc)
        return WeatherSnapshot(city=city, line="")
    line = (snap.line or "").strip()
    if line:
        logger.info("[weather] MSN 查询 %s: %s", city, line)
        try:
            from pnn.pet.console_log import log_weather_query

            log_weather_query(city, line, ok=True)
        except Exception:
            pass
    return WeatherSnapshot(city=city, line=line, source="msn/playwright")


def build_weather_system_context(user_message: str) -> str | None:
    """天气/城市问句：注入程序查询结果，供 LLM 用角色口吻转述。"""
    if not needs_weather_injection(user_message):
        return None

    blocks: list[str] = []

    if user_asks_saved_city(user_message):
        city = saved_weather_city()
        if city:
            blocks.append(
                f"【程序定位】用户在桌宠设置中保存的所在城市：{city}。"
                "回答「我们在哪座城市」类问题必须使用该城市名，禁止编造其他城市。"
            )
        else:
            blocks.append(
                "【程序定位】桌宠设置中未填写「所在城市」（日程与提醒页）。"
                "请如实说明尚未配置，不要猜测城市。"
            )

    wx_line = ""
    if user_asks_weather(user_message):
        hz = weather_query_horizon(user_message)
        snap = fetch_live_weather_for_saved_city(force_refresh=False, horizon=hz)
        wx_line = snap.line if snap.ok else ""
        scene = _weather_scene_hints(user_message, weather_line=wx_line)
        if scene:
            blocks.append(scene)
        blocks.append(_weather_reply_rules())
        if not snap.city:
            blocks.append(
                "【程序天气】未配置所在城市，无法查询实时天气。"
                "请提醒用户在设置→日程与提醒填写城市；禁止编造气温或晴雨。"
            )
        elif snap.ok:
            blocks.append(f"【内部天气·勿提来源】{snap.city}：{snap.line}")
        else:
            blocks.append(
                f"【内部天气·勿提来源】{snap.city}：暂无可用数据。"
                "请用角色口吻如实说暂时不清楚具体气温，禁止编造数字。"
            )
    else:
        scene = _weather_scene_hints(user_message)
        if scene:
            blocks.append(scene)

    if not blocks:
        return None
    return "\n".join(blocks)


def format_weather_user_prefix(user_message: str) -> str:
    """机器可读天气行（附在用户消息前，与 [clock] 并列）。"""
    if not needs_weather_injection(user_message):
        return ""
    city = saved_weather_city()
    if user_asks_weather(user_message):
        hz = weather_query_horizon(user_message)
        snap = fetch_live_weather_for_saved_city(force_refresh=False, horizon=hz)
        if snap.ok:
            return f"[weather] city={snap.city}; horizon={hz}; live={snap.line}"
        if city:
            return f"[weather] city={city}; live=unavailable"
        return "[weather] city=unset; live=unavailable"
    if user_asks_saved_city(user_message) and city:
        return f"[weather] city={city}; saved_in_settings=true"
    return ""


def augment_user_message_prefix(text: str) -> str:
    """[clock]（每条消息）+ 可选 [weather] + 用户正文。"""
    from pnn.core.clock import format_clock_user_prefix

    body = (text or "").strip()
    if not body:
        return body
    blocks: list[str] = [format_clock_user_prefix()]
    wx = format_weather_user_prefix(body)
    if wx:
        blocks.append(wx)
    blocks.append(body)
    if user_asks_weather(body):
        blocks.append(_weather_user_reply_hint())
    return "\n\n".join(blocks)
