#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
采蘑菇论坛（caimogu.cc）自动签到脚本
功能：每天自动在指定圈子板块回复若干帖子，获取活跃度

用法：
  python caimogu_signin.py            执行自动签到
  python caimogu_signin.py --login    配置登录（首次使用）
  python caimogu_signin.py --test     测试评论生成效果
  python caimogu_signin.py --help     显示帮助
"""

import json
import os
import re
import random
import time
import sys
import logging
from datetime import datetime, date
from pathlib import Path

# ============================================================
#  1. 路径与常量
# ============================================================

if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).parent.absolute()
else:
    SCRIPT_DIR = Path(__file__).parent.absolute()

PATHS = {
    "config":  SCRIPT_DIR / "config.json",
    "auth":    SCRIPT_DIR / "auth_state.json",
    "replied": SCRIPT_DIR / "replied_posts.json",
    "log":     SCRIPT_DIR / "signin_log.txt",
}

# 免安装版优先使用程序目录旁边的 Playwright 浏览器
_browsers_dir = SCRIPT_DIR / "playwright-browsers"
if _browsers_dir.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browsers_dir))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG = {
    "circle_url": "https://www.caimogu.cc/circle/492.html",
    "reply_count": 3,
    "min_delay": 8,
    "max_delay": 20,
    "headless": True,
    "page_timeout_ms": 90000,
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com/v1",
    "deepseek_model": "deepseek-chat",
}

# 页面选择器集中定义（顺序敏感，勿随意调整）
SELECTORS = {
    "post_item":  ".list-container .list .item",
    "post_title": ".title",
    "content": (
        ".post-content", ".content", ".detail-content",
        ".post-body", ".text", ".post-detail-content",
    ),
    "editor": (
        ".ql-editor",
        "#editor .ql-editor",
        ".editor .ql-editor",
        ".comment-editor .ql-editor",
        "[contenteditable='true']",
    ),
    "reply_btn": (
        ".btn-reply-root", ".btn-reply", ".reply-btn",
        'a:has-text("回复")', 'button:has-text("回复")',
    ),
    "submit": (
        ".btn-reply-root",
        'button:has-text("回复")',
        'button:has-text("发表")',
        'button:has-text("提交")',
        ".submit-btn",
        ".btn-publish",
        ".btn-send",
        'input[type="submit"]',
    ),
    "error": ".error, .alert, .toast-error, .msg-error",
    "login_link": 'a[href*="login"]',
}

SKIP_PIN_KEYWORDS = ["圈规", "答题系统反馈", "新圈规", "不允许乱转"]

# ============================================================
#  2. 评论模板与关键词常量
# ============================================================

COMMENT_TEMPLATES = [
    "{keyword}这个确实挺有意思的",
    "看到{keyword}了感觉还不错哦",
    "{keyword}这话题值得聊一聊哈",
    "楼主说的{keyword}我也关注了",
    "关于{keyword}学习了感谢哈",
    "{keyword}看起来挺有意思的呢",
    "这个{keyword}确实有道理啊",
    "{keyword}深有同感顶一个楼主",
    "感谢分享{keyword}相关内容哈",
    "{keyword}这个挺实用的马克了",
    "说到{keyword}我就来精神了哈",
    "{keyword}这波操作可以的样子",
    "看完{keyword}觉得挺靠谱的呢",
    "{keyword}确实是这样没毛病啊",
    "mark一下{keyword}回头细看看",
    "{keyword}这个信息很有用感谢",
    "关于{keyword}我也来说两句",
    "{keyword}这个观点我比较赞同",
    "每次看到{keyword}都想点进来",
    "{keyword}这内容质量挺高支持",
]

UNIVERSAL_COMMENTS = [
    "这帖子内容不错挺有参考价值",
    "感谢楼主分享学到了不少东西",
    "这个话题确实值得讨论一下哈",
    "看完觉得挺有收获的感谢分享",
    "楼主说得有道理支持一下你了",
    "这内容质量挺高的马克收藏了",
    "正好需要这个信息感谢楼主哈",
    "挺有意思的帖子顶一下楼主哈",
    "学到了新知识感谢楼主分享哈",
    "这帖子说到了点子上支持一下",
    "内容挺实用的感谢分享收藏了",
    "看完了感觉挺不错支持楼主哈",
    "好帖子必须顶一下感谢分享哈",
    "这分享挺有用的谢谢楼主了哈",
    "帖子写得挺详细的支持一个哈",
]

_MEANINGLESS_PREFIXES = [
    '大家来展示一下', '有没有人遇到', '求推荐几款', '请问一下大家',
    '大家来', '有没有人', '求推荐', '请问', '求教', '求助',
    '各位大佬', '大佬们', '各位', '有没有', '谁知道', '今天',
]

_MEANINGLESS_SUFFIXES = [
    '分享一下好运', '分享一下', '的效果吧', '效果吧', '的问题求助',
    '求助', '分享', '效果', '吧', '呢', '啊', '吗', '哦', '哈', '了',
]

_BAD_PARTS = ['一下', '目前', '有没有', '谁知道', '大家来', '展示', '这个游戏', '好玩的单']

_BANNED_COMMENT_PARTS = [
    "感谢分享", "支持一下", "学到了", "坐等后续", "确实如此",
    "期待更新", "前排围观", "有道理", "这波可以",
    "说得好", "支持楼主", "码住", "马克", "不错", "挺有意思",
    "值得讨论", "内容质量", "参考价值", "信息量", "蹲一个靠谱"
]

_SKIP_TITLE_PATTERNS = [
    r'^\s*签到\s*$', r'每日签到', r'打卡', r'水帖', r'路过',
    r'顶一下', r'冒个泡', r'有人吗', r'随便聊聊', r'无内容',
]

_DETAIL_STOP_WORDS = [
    "这个", "那个", "什么", "一下", "一个", "不是", "就是", "可以", "感觉",
    "真的", "然后", "还是", "已经", "自己", "大家", "楼主", "帖子", "内容",
    "回复", "签到", "每日", "今天", "有人", "有没有", "为什么", "怎么",
    "分享", "看看", "求助", "推荐", "问题"
]

_DETAIL_PATTERNS = [
    r'多次.{0,3}换导演', r'换导演', r'剧本调整',
    r'特效.{0,8}看不清怪', r'特效.{0,8}看不清',
    r'节奏慢', r'开放世界', r'草元素', r'新地图',
    r'雨天场景', r'反光', r'窗口.{0,4}消失', r'错误提示',
    r'最后一发', r'蓝光',
    r'登录.{0,3}闪退', r'刷图.{0,3}效果', r'抽卡.{0,3}出货',
    r'版本.{0,3}更新', r'画面.{0,3}(绝|糊|卡|舒服|清楚)',
    r'真人.{0,3}电影', r'单机.{0,3}游戏', r'取消', r'延期',
    r'报错', r'卡住', r'掉帧', r'联机', r'存档', r'补丁'
]

_REPLY_TEMPLATES = {
    "help": [
        "{d}这里看着像关键卡点，先别急着重装",
        "{d}这类问题最怕没提示，排查会很绕",
        "{d}如果能稳定复现，处理起来会清楚些",
        "先看{d}这一步，感觉更像问题源头",
    ],
    "regret": [
        "{d}折腾到最后没成，听着就挺亏的",
        "{d}拖到现在才没了，这个落差有点大",
        "卡在{d}这里收场，确实挺可惜的",
        "{d}这个细节比取消本身还扎眼",
    ],
    "update": [
        "{d}这项改动得看实机表现，公告不够判断",
        "{d}如果只是表面变化，玩起来会很尴尬",
        "先看{d}这块有没有真变化，别急着下结论",
        "{d}这里别只看公告措辞，实际体验更关键",
    ],
    "recommend": [
        "{d}这个偏好挺明确，按这个方向找会准些",
        "按{d}这个方向筛，应该能少踩不少坑",
        "{d}要是再耐玩一点，选择范围会舒服很多",
        "只看{d}这个要求，其实能排掉一大批了",
    ],
    "luck": [
        "{d}这个结果看着挺拉仇恨，差一点就反转",
        "看到{d}这种运气，很难不有点酸",
        "{d}这一下比玄学还刺激，前面铺垫太长了",
        "这种{d}截图最容易劝人手痒，太会卡点",
    ],
    "media": [
        "{d}这个点拍不好会很别扭，改编压力不小",
        "{d}放到真人版里挺考验取舍，不能只靠阵容",
        "单看{d}就知道风险不小，方向比噱头重要",
        "{d}这块比阵容更关键，处理不好很容易散",
    ],
    "normal": [
        "{d}这个细节比主楼更有意思，能接着聊",
        "{d}这里看着像真正想聊的点，不算空泛",
        "{d}这句比大段描述更直观，画面感更强",
        "我更在意{d}这块怎么处理，影响会更明显",
    ],
}

# ============================================================
#  3. JSON 工具函数
# ============================================================

def load_json(path, default):
    """读取 JSON 文件，出错时返回 default"""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return default


def save_json(path, data):
    """写入 JSON 文件"""
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================
#  4. 日志
# ============================================================

def setup_logging():
    """配置日志（同时输出到文件和控制台）"""
    logger = logging.getLogger("caimogu")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(str(PATHS["log"]), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger

# ============================================================
#  5. 配置与执行记录
# ============================================================

def load_config():
    """加载配置，不存在则自动创建默认配置"""
    config = DEFAULT_CONFIG.copy()
    if not PATHS["config"].exists():
        save_json(PATHS["config"], config)
        return config
    config.update(load_json(PATHS["config"], {}))
    return config


def get_today_reply_count():
    """获取今天已成功回复的数量"""
    data = load_json(PATHS["replied"], {})
    today = date.today().isoformat()
    if data.get("last_run_date") == today:
        return int(data.get("last_run_posts", 0) or 0)
    return 0


def mark_today_progress(post_count):
    """记录进度，避免中断后重复回复"""
    data = load_json(PATHS["replied"], {})
    data["last_run_date"] = date.today().isoformat()
    data["last_run_posts"] = post_count
    data["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["status"] = "running" if post_count < DEFAULT_CONFIG["reply_count"] else "done"
    save_json(PATHS["replied"], data)


def mark_done_today(post_count):
    """标记今天签到完成"""
    data = load_json(PATHS["replied"], {})
    data["last_run_date"] = date.today().isoformat()
    data["last_run_posts"] = post_count
    data["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["status"] = "done"
    save_json(PATHS["replied"], data)

# ============================================================
#  6. 评论生成（纯逻辑，不涉及页面操作）
# ============================================================

def _comment_len(text):
    """计算评论有效字数"""
    return len(re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text))


def _normalize_comment(text):
    """清理评论，避免过度模板化和超长"""
    text = re.sub(r'\s+', '', text)
    text = text.strip('，。！？!?、；; ')
    return text


def _valid_comments(candidates):
    """过滤出 10 到 20 字之间的评论"""
    result = []
    for item in candidates:
        item = _normalize_comment(item)
        if 10 <= _comment_len(item) <= 20:
            result.append(item)
    return result


def detect_title_type(title):
    """粗略判断帖子类型，用于生成更贴合标题的回复"""
    if re.search(r'取消|砍|延期|跳票|停服|下架|暴死|失败|崩|凉', title):
        return "regret"
    if re.search(r'求助|请问|有没有|怎么|如何|为啥|为什么|闪退|报错|问题|卡住', title):
        return "help"
    if re.search(r'更新|版本|补丁|改动|上线|发布|公布|官宣|新增', title):
        return "update"
    if re.search(r'推荐|安利|好玩|入坑|值得买吗|买不买', title):
        return "recommend"
    if re.search(r'抽卡|出货|晒|欧|非|运气|掉落', title):
        return "luck"
    if re.search(r'电影|剧|漫威|动画|漫画|主创|演员', title):
        return "media"
    return "normal"


def extract_keyword(title):
    """从帖子标题中提取关键词"""
    title = re.sub(r'^【.*?】\s*', '', title)
    title = re.sub(r'^\[.*?\]\s*', '', title)

    match = re.search(r'《(.+?)》', title)
    if match and len(match.group(1)) >= 2:
        return match.group(1)[:6]

    match = re.search(r'[\u201c\u201d"\u300c\u300d\u300e\u300f](.+?)[\u201c\u201d"\u300c\u300d\u300e\u300f]', title)
    if match and len(match.group(1)) >= 2:
        return match.group(1)[:6]

    keyword_patterns = [
        r'单机游戏', r'登录闪退', r'闪退问题', r'游戏画面', r'刷图效果',
        r'版本更新', r'更新内容', r'抽卡出货', r'真人电影', r'档期原因',
        r'主创澄清', r'合约已签', r'突然砍剧', r'推荐.*游戏',
    ]
    for pattern in keyword_patterns:
        match = re.search(pattern, title)
        if match:
            found = match.group(0).replace('推荐几款', '').replace('推荐', '')
            if 2 <= len(found) <= 6:
                return found

    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', title)

    for prefix in _MEANINGLESS_PREFIXES:
        if clean.startswith(prefix) and len(clean) > len(prefix) + 2:
            clean = clean[len(prefix):]
            break

    for suffix in _MEANINGLESS_SUFFIXES:
        if clean.endswith(suffix) and len(clean) > len(suffix) + 2:
            clean = clean[:-len(suffix)]
            break

    if len(clean) >= 4:
        keyword = clean[:4]
        for bad in _BAD_PARTS:
            if bad in keyword:
                return ""
        return keyword
    elif len(clean) >= 2:
        return clean
    else:
        return ""


def _strip_html_and_noise(text):
    """清理正文噪音，保留适合判断和回复的文本"""
    text = text or ""
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\[[^\]]{1,20}\]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _meaningful_text_len(text):
    """统计中文、字母和数字的有效长度"""
    return len(re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text or ""))


def _is_generic_or_empty(title, content):
    """判断帖子是否太空泛"""
    title = title or ""
    content = _strip_html_and_noise(content)
    compact_title = re.sub(r'\s+', '', title)
    compact_content = re.sub(r'\s+', '', content)

    if any(re.search(pattern, compact_title) for pattern in _SKIP_TITLE_PATTERNS):
        if _meaningful_text_len(compact_content) < 30:
            return True

    if _meaningful_text_len(compact_title + compact_content) < 10:
        return True

    generic_phrases = ["如题", "RT", "rt", "看看", "分享一下", "随便说说", "占个楼"]
    if compact_content in generic_phrases:
        return True

    if not content and not any(re.search(p, compact_title) for p in _DETAIL_PATTERNS):
        keyword = extract_keyword(title)
        if not keyword or len(keyword) < 2:
            return True

    return False


def judge_replyability(title, content):
    """判断是否有明确可回应点，返回 REPLY 或 SKIP"""
    title = title or ""
    content = _strip_html_and_noise(content)
    combined = title + " " + content

    if _is_generic_or_empty(title, content):
        return "SKIP"

    if any(bad in combined for bad in ["灌水", "纯水", "无意义", "占楼"]):
        return "SKIP"

    signal_patterns = [
        r'取消|延期|下架|停服|砍了|跳票',
        r'求助|请问|闪退|报错|卡住|失败|问题|怎么|为什么',
        r'更新|版本|补丁|改动|新增|上线|发布',
        r'推荐|安利|入坑|好玩|单机|联机',
        r'抽卡|出货|掉落|运气|晒',
        r'电影|动画|漫画|真人|演员|主创',
        r'画面|刷图|存档|掉帧|优化|手感|剧情|玩法',
    ]
    if any(re.search(pattern, combined) for pattern in signal_patterns):
        return "REPLY"

    if _meaningful_text_len(content) >= 30:
        return "REPLY"

    return "SKIP"


def _extract_detail(title, content):
    """提取一个确实出现在标题或正文里的细节"""
    title = title or ""
    content = _strip_html_and_noise(content)

    def clean_detail(raw):
        detail = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', raw or "")
        if "特效" in detail and "看不清" in detail:
            return "特效看不清怪" if "怪" in detail else "特效看不清"
        if "窗口" in detail and "消失" in detail:
            return "窗口直接消失"
        if "多次" in detail and "换导演" in detail:
            return "多次换导演"
        return detail[:10]

    compact_content = re.sub(r'\s+', '', content)
    for pattern in _DETAIL_PATTERNS:
        m = re.search(pattern, compact_content)
        if m:
            return clean_detail(m.group(0))

    sentences = re.split(r'[。！？!?；;\n\r]+', content)
    chunks = []
    for sentence in sentences:
        sentence = re.sub(r'\s+', '', sentence)
        if 4 <= _meaningful_text_len(sentence) <= 40:
            chunks.extend(re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{2,8}', sentence))

    scored = []
    for chunk in chunks:
        if any(stop in chunk for stop in _DETAIL_STOP_WORDS):
            continue
        if any(bad in chunk for bad in _BANNED_COMMENT_PARTS):
            continue
        score = len(chunk)
        if content and chunk in content:
            score += 3
        if chunk in title:
            score += 1
        scored.append((score, chunk))

    if scored:
        scored.sort(reverse=True)
        return scored[0][1][:8]

    compact_title = re.sub(r'\s+', '', title)
    for pattern in _DETAIL_PATTERNS:
        m = re.search(pattern, compact_title)
        if m:
            return clean_detail(m.group(0))

    chunks = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{2,8}', title)
    for chunk in chunks:
        if not any(stop in chunk for stop in _DETAIL_STOP_WORDS):
            return chunk[:8]

    keyword = extract_keyword(title)
    return keyword[:8] if keyword else ""


def _normalize_generated_comment(text):
    """清理模型或模板生成的回复"""
    text = (text or "").strip()
    text = text.strip('"\u2018\u2019\u201c\u201d\'')
    text = re.sub(r'^(REPLY|回复|评论)[:：\s-]*', '', text, flags=re.I)
    text = re.sub(r'\s+', '', text)
    text = text.strip('，。！？!?、；; ')
    return text


def _is_reply_valid(comment, title="", content=""):
    """检查回复是否符合规则"""
    comment = _normalize_generated_comment(comment)
    if not comment or comment.upper() == "SKIP":
        return False
    if any(part in comment for part in _BANNED_COMMENT_PARTS):
        return False
    length = _comment_len(comment)
    if not (15 <= length <= 35):
        return False
    compact_title = re.sub(r'\s+', '', title or "")
    if compact_title and comment == compact_title:
        return False
    if "我也" in comment and not re.search(r'求助|请问|有没有|问题|推荐', title or ""):
        return False
    return True


def generate_comment_template(title, content=""):
    """模板模式：先判断 REPLY/SKIP，再生成短回复"""
    decision = judge_replyability(title, content)
    if decision == "SKIP":
        return "SKIP"

    detail = _extract_detail(title, content)
    if not detail:
        return "SKIP"

    title_type = detect_title_type((title or "") + " " + (content or "")[:120])
    templates = _REPLY_TEMPLATES.get(title_type, _REPLY_TEMPLATES["normal"])
    candidates = [tpl.replace("{d}", detail) for tpl in random.sample(templates, len(templates))]
    valid = [_normalize_generated_comment(x) for x in candidates if _is_reply_valid(x, title, content)]
    if valid:
        return random.choice(valid)
    return "SKIP"


def _call_deepseek_api(url, headers, data, logger):
    """发起一次 API 请求，返回 (raw_content, returned_model)"""
    import requests
    resp = requests.post(url, headers=headers, json=data, timeout=20)
    resp.raise_for_status()
    result = resp.json()
    returned_model = result.get("model", "未知")
    logger.info("AI 返回模型: %s", returned_model)
    raw_content = result["choices"][0]["message"]["content"]
    return raw_content, returned_model


def generate_comment_ai(title, content, api_key, base_url, model):
    """AI 模式：让 AI 直接生成评论或 SKIP，含空返回重试和429重试"""
    import requests as _requests
    logger = logging.getLogger("caimogu")
    try:
        base_url = (base_url or "https://api.deepseek.com/v1").rstrip("/")
        model = model or "deepseek-chat"
        url = base_url + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json"
        }

        title_clean = (title or "").strip()
        if len(title_clean) > 200:
            title_clean = title_clean[:200]
            logger.info("标题过长(>%d字)，已截断", len(title or ""))

        content_summary = _strip_html_and_noise(content)[:700] if content else ""
        prompt = (
            "你是一个论坛用户，正在浏览帖子。请根据标题和正文，写一条真实的回复。\n\n"
            "规则：\n"
            "- 抓住帖子里一个具体细节来回复，不要泛泛而谈\n"
            "- 语气口语化，像真人在闲聊，可以吐槽、提问、补充\n"
            "- 15到40个字，别太短也别太长\n"
            "- 绝对不要用这些套话：感谢分享、支持一下、学到了、坐等后续、确实如此、期待更新、前排围观、有道理、这波可以、说得好、支持楼主、码住、马克\n"
            "- 不要假装亲身经历过\n"
            "- 不要总结帖子内容\n"
            "- 不要重复标题原话\n\n"
            "如果帖子内容太少、没法自然接话，只回复两个字母：SKIP\n"
            "能回复就直接输出回复内容，不要加任何前缀、编号、解释\n"
        )
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "标题：" + title_clean + "\n正文：" + content_summary}
            ],
            "max_tokens": 200,
            "temperature": 0.9
        }

        logger.info("AI 请求: base_url=%s, model=%s", base_url, model)
        try:
            raw_content, _ = _call_deepseek_api(url, headers, data, logger)
        except _requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning("触发429限流，等待3秒后重试一次")
                time.sleep(3)
                raw_content, _ = _call_deepseek_api(url, headers, data, logger)
            else:
                raise

        logger.info("AI 原始返回: %s", raw_content)
        comment = _normalize_generated_comment(raw_content)
        logger.info("AI 清洗后: %s (字数=%d)", comment, _comment_len(comment))

        if comment.upper() == "SKIP":
            return "SKIP"

        if _comment_len(comment) < 5:
            logger.warning("AI 返回空或太短，缩短输入后重试一次")
            retry_data = {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "标题：" + title_clean[:80] + "\n正文：" + content_summary[:300]}
                ],
                "max_tokens": 200,
                "temperature": 0.9
            }
            time.sleep(1)
            try:
                raw_content2, _ = _call_deepseek_api(url, headers, retry_data, logger)
            except _requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    logger.warning("重试也触发429，回退模板")
                    return generate_comment_template(title, content)
                raise
            logger.info("AI 重试返回: %s", raw_content2)
            comment = _normalize_generated_comment(raw_content2)
            logger.info("AI 重试清洗后: %s (字数=%d)", comment, _comment_len(comment))

            if comment.upper() == "SKIP":
                return "SKIP"
            if _comment_len(comment) < 5:
                logger.warning("AI 重试仍为空，回退模板")
                return generate_comment_template(title, content)

        _HARD_BANNED = ["感谢分享", "支持一下", "学到了", "坐等后续", "期待更新", "前排围观"]
        if any(part in comment for part in _HARD_BANNED):
            logger.warning("AI 回复含套话，回退模板: %s", comment)
            return generate_comment_template(title, content)

        return comment
    except Exception as e:
        logging.getLogger("caimogu").warning("AI生成评论失败，回退到模板模式: %s", e)
        return generate_comment_template(title, content)


def generate_comment(title, content, config):
    """根据配置选择 AI 模式或模板模式生成评论；可能返回 SKIP"""
    api_key = config.get("deepseek_api_key", "")
    if api_key:
        base_url = config.get("deepseek_base_url", "https://api.deepseek.com/v1")
        model = config.get("deepseek_model", "deepseek-chat")
        return generate_comment_ai(title, content, api_key, base_url, model)
    return generate_comment_template(title, content)

# ============================================================
#  7. Playwright 工具函数
# ============================================================

def first_element(page, selectors, *, wait=False, timeout=5000):
    """按顺序查找第一个存在的元素，返回 (element, selector) 或 (None, None)"""
    for selector in selectors:
        try:
            if wait:
                element = page.wait_for_selector(selector, timeout=timeout)
            else:
                element = page.query_selector(selector)
            if element:
                return element, selector
        except Exception:
            continue
    return None, None


def get_text(page, selectors, limit=500):
    """从多个选择器中提取第一个匹配元素的文本"""
    element, _ = first_element(page, selectors)
    if not element:
        return ""
    try:
        return element.inner_text()[:limit].strip()
    except Exception:
        return ""


def create_context(playwright, *, headless=True, storage_state=None):
    """创建浏览器上下文，返回 (browser, context)"""
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=USER_AGENT,
        storage_state=storage_state,
    )
    return browser, context

# ============================================================
#  8. 页面操作
# ============================================================

def get_post_list(page, config, count, logger):
    """从板块页面获取帖子列表，自动跳过置顶帖"""
    circle_url = config["circle_url"]
    logger.info("正在获取帖子列表: %s", circle_url)
    try:
        page.goto(circle_url, timeout=config.get("page_timeout_ms", 90000),
                  wait_until="domcontentloaded")
    except Exception as e:
        logger.warning("板块页面加载超时，尝试继续解析已加载内容: %s", e)
    page.wait_for_timeout(3000)

    try:
        page.wait_for_selector(SELECTORS["post_item"], timeout=10000)
    except Exception:
        logger.error("帖子列表未加载，可能页面结构有变化")
        return []

    items = page.query_selector_all(SELECTORS["post_item"])
    posts = []
    skipped_pinned = 0
    max_candidates = max(count * 8, count + 10)

    for item in items[:max_candidates]:
        try:
            title_el = item.query_selector(SELECTORS["post_title"])
            if not title_el:
                continue
            href = title_el.get_attribute("href")
            title = title_el.inner_text().strip()
            if not (href and title):
                continue

            item_class = item.get_attribute("class") or ""
            item_html = item.inner_html()[:500] if hasattr(item, "inner_html") else ""
            is_pinned = (
                "sticky" in item_class.lower()
                or "pin" in item_class.lower()
                or "top" in item_class.lower()
                or "置顶" in item_html
                or "精华" in item_html
            )
            title_matches_skip = any(kw in title for kw in SKIP_PIN_KEYWORDS)

            if is_pinned or title_matches_skip:
                skipped_pinned += 1
                logger.info("跳过置顶帖: %s", title)
                continue

            if not href.startswith("http"):
                href = "https://www.caimogu.cc" + href
            posts.append({"url": href, "title": title})
            if len(posts) >= max_candidates:
                break
        except Exception:
            continue

    logger.info("跳过 %d 个置顶帖，获取到 %d 个普通帖子", skipped_pinned, len(posts))
    return posts


def extract_post_info(page):
    """从当前帖子页面提取标题和内容"""
    page_title = page.title()
    title = re.sub(r'\s*-\s*.*$', '', page_title).strip()
    content = get_text(page, SELECTORS["content"], limit=500)
    return title, content


def find_editor(page, logger):
    """查找回复编辑器，必要时先点击回复按钮"""
    editor, sel = first_element(page, SELECTORS["editor"], wait=True, timeout=5000)
    if editor:
        logger.info("找到回复编辑器: %s", sel)
        return editor

    # 尝试点击回复按钮后再查找
    btn, _ = first_element(page, SELECTORS["reply_btn"])
    if btn:
        try:
            btn.click()
            page.wait_for_timeout(2000)
        except Exception:
            pass

    editor, sel = first_element(page, SELECTORS["editor"], wait=True, timeout=5000)
    if editor:
        logger.info("找到回复编辑器(点击回复后): %s", sel)
    return editor


def input_comment(page, editor, comment, logger):
    """输入评论到编辑器，依次尝试 fill → evaluate → keyboard.type"""
    editor.click()
    page.wait_for_timeout(300)

    # 方式一：fill
    try:
        editor.fill(comment)
        page.wait_for_timeout(500)
        logger.info("评论已输入编辑器(fill)")
        return True
    except Exception:
        pass

    # 方式二：直接设置 Quill 编辑器内容
    try:
        page.evaluate(
            '(text) => { var ed = document.querySelector(".ql-editor"); '
            'if(ed) { ed.innerHTML = "<p>" + text + "</p>"; '
            'ed.dispatchEvent(new Event("input", {bubbles: true})); } }',
            comment
        )
        page.wait_for_timeout(500)
        logger.info("评论已输入编辑器(evaluate)")
        return True
    except Exception:
        pass

    # 方式三：键盘逐字输入
    try:
        editor.click()
        page.wait_for_timeout(200)
        page.keyboard.type(comment, delay=50)
        page.wait_for_timeout(500)
        logger.info("评论已输入编辑器(keyboard)")
        return True
    except Exception as e:
        logger.error("输入评论失败: %s", e)
        return False


def submit_reply(page, logger):
    """查找并点击提交按钮，返回是否成功"""
    btn, sel = first_element(page, SELECTORS["submit"])
    if btn:
        try:
            btn.click()
            logger.info("点击提交按钮: %s", sel)
            return True
        except Exception as e:
            logger.error("点击提交按钮失败: %s", e)
            return False

    # 备选：Ctrl+Enter
    try:
        page.keyboard.press("Control+Enter")
        logger.info("通过 Ctrl+Enter 提交")
        return True
    except Exception:
        logger.error("未找到提交按钮")
        return False


def reply_to_post(page, post_url, config, logger):
    """打开帖子并回复（页面交互层，评论生成委托给 generate_comment）"""
    logger.info("正在打开帖子: %s", post_url)

    try:
        try:
            page.goto(post_url, timeout=config.get("page_timeout_ms", 90000),
                      wait_until="domcontentloaded")
        except Exception as e:
            logger.warning("帖子页面加载超时，尝试继续: %s", e)
        page.wait_for_timeout(3000)

        # 提取帖子信息
        title, content = extract_post_info(page)

        # 生成评论（纯逻辑，不涉及页面操作）
        comment = generate_comment(title, content, config)
        logger.info("帖子标题: %s", title)
        if comment == "SKIP":
            logger.info("判断结果: SKIP，跳过此帖")
            return False
        logger.info("生成评论: %s", comment)

        # 滚动到底部
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        # 查找编辑器
        editor = find_editor(page, logger)
        if not editor:
            logger.error("未找到回复输入框，跳过此帖子")
            return False

        # 输入评论
        if not input_comment(page, editor, comment, logger):
            return False

        # 提交回复
        if not submit_reply(page, logger):
            return False

        # 等待提交完成
        page.wait_for_timeout(3000)

        # 检查错误提示
        try:
            error_el = page.query_selector(SELECTORS["error"])
            if error_el:
                error_text = error_el.inner_text()
                if error_text and len(error_text) > 2:
                    logger.warning("页面提示: %s", error_text)
        except Exception:
            pass

        logger.info("回复提交完成")
        return True

    except Exception as e:
        logger.error("回复帖子时出错: %s", e)
        return False

# ============================================================
#  9. 登录流程
# ============================================================

def setup_login():
    """首次登录配置：打开浏览器让用户手动登录，保存登录状态"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[错误] 未安装 Playwright，请先运行 install.bat")
        input("按回车键退出...")
        return

    print("=" * 50)
    print("  采蘑菇论坛 - 登录配置")
    print("=" * 50)
    print()
    print("即将打开浏览器，请在浏览器中手动登录采蘑菇论坛。")
    print("登录成功后，回到这里按回车键保存登录状态。")
    print()
    input("按回车键打开浏览器...")

    with sync_playwright() as p:
        browser, context = create_context(p, headless=False)
        try:
            page = context.new_page()
            page.goto("https://www.caimogu.cc/login.html")
            print()
            print("浏览器已打开采蘑菇论坛登录页面。")
            print("请在浏览器中完成登录操作。")
            print("(支持手机号登录、微信登录、Apple登录)")
            print()
            input(">>> 登录完成后按回车键保存 <<<")

            context.storage_state(path=str(PATHS["auth"]))
            print()
            print("[成功] 登录状态已保存到: %s" % PATHS["auth"])
            print()
            print("配置完成！接下来你可以：")
            print("  1. 运行 启动签到.bat 手动测试签到")
            print("  2. 运行 设置开机自启.bat 设置开机自启动")
            print()
        finally:
            context.close()
            browser.close()
    input("按回车键退出...")


def check_login_status(page, logger):
    """检查登录状态是否有效"""
    try:
        page.goto("https://www.caimogu.cc/", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        login_links = page.query_selector_all(SELECTORS["login_link"])
        for link in login_links:
            try:
                text = link.inner_text()
                if "登录" in text or "登陆" in text:
                    return False
            except Exception:
                continue
        return True
    except Exception as e:
        logger.warning("检查登录状态时出错: %s", e)
        return True

# ============================================================
#  10. 签到流程
# ============================================================

def run_signin():
    """执行自动签到主流程"""
    logger = setup_logging()
    config = load_config()

    logger.info("=" * 50)
    logger.info("采蘑菇论坛自动签到开始")
    logger.info("时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 50)

    if not PATHS["auth"].exists():
        logger.error("未找到登录状态文件！请先配置登录。")
        logger.error("请运行: python caimogu_signin.py --login")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("未安装 Playwright，请先运行 install.bat")
        return

    reply_count = config.get("reply_count", 3)
    headless = config.get("headless", True)
    already_count = get_today_reply_count()
    if already_count >= reply_count:
        logger.info("今天已经成功回复 %d 条，已达到目标，自动跳过。", already_count)
        return
    remaining_count = reply_count - already_count
    logger.info("今天已记录成功回复 %d 条，本次还需要回复 %d 条。", already_count, remaining_count)

    with sync_playwright() as p:
        browser, context = create_context(
            p, headless=headless, storage_state=str(PATHS["auth"])
        )
        try:
            page = context.new_page()

            if not check_login_status(page, logger):
                logger.error("登录状态已失效！请重新配置登录。")
                logger.error("请运行: python caimogu_signin.py --login")
                return

            logger.info("登录状态有效")

            posts = get_post_list(page, config, remaining_count, logger)
            if not posts:
                logger.error("未获取到帖子列表，签到失败")
                return

            success_count = already_count
            for i, post in enumerate(posts):
                if success_count >= reply_count:
                    break

                logger.info("--- 本次第 %d/%d 个帖子，总进度 %d/%d ---",
                            i + 1, remaining_count, success_count, reply_count)
                logger.info("标题: %s", post["title"])

                if reply_to_post(page, post["url"], config, logger):
                    success_count += 1
                    logger.info("回复成功 (%d/%d)", success_count, reply_count)
                    mark_today_progress(success_count)
                    if success_count < reply_count:
                        delay = random.randint(config["min_delay"], config["max_delay"])
                        logger.info("等待 %d 秒...", delay)
                        time.sleep(delay)
                else:
                    logger.warning("回复失败，尝试下一个帖子")
                    time.sleep(3)

            logger.info("=" * 50)
            logger.info("签到完成！今天累计成功回复 %d/%d 个帖子", success_count, reply_count)
            logger.info("=" * 50)
            if success_count >= reply_count:
                mark_done_today(success_count)

        except Exception as e:
            logger.error("签到过程出错: %s", e)
        finally:
            context.close()
            browser.close()

    logger.info("脚本结束")

# ============================================================
#  11. 命令行入口
# ============================================================

def show_help():
    """显示帮助信息"""
    print("采蘑菇论坛自动签到脚本")
    print()
    print("用法:")
    print("  python caimogu_signin.py            执行自动签到")
    print("  python caimogu_signin.py --login    配置登录（首次使用）")
    print("  python caimogu_signin.py --test     测试评论生成效果")
    print("  python caimogu_signin.py --help     显示帮助")


def show_test_comments():
    """测试模式：预览评论生成效果"""
    config = load_config()
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("评论生成测试（不会实际回复帖子）")
    logger.info("=" * 50)

    test_posts = [
        ("历经七年制作波折 《刀锋战士》真人电影正式宣告取消", "项目经历多次换导演和剧本调整，最后还是被取消了。"),
        ("大家来展示一下目前刷图的效果吧", "我这边刷图速度还行，就是特效一多会有点看不清怪。"),
        ("求推荐几款好玩的单机游戏", "想找节奏慢一点的，不太想玩特别肝的开放世界。"),
        ("《原神》3.0版本更新内容汇总分享", "这次主要加了新地图和草元素相关机制，任务线也比较长。"),
        ("这个游戏画面真的绝了分享给大家看看", "雨天场景的反光做得很明显，截图看着比白天舒服。"),
        ("有没有人遇到登录闪退的问题求助", "点登录后窗口直接消失，没有弹错误提示。"),
        ("今天抽卡出货了分享一下好运", "十连最后一发才出的，前面全是蓝光。"),
        ("每日签到", "如题"),
    ]

    for i, (title, content) in enumerate(test_posts):
        keyword = extract_keyword(title)
        decision = judge_replyability(title, content)
        comment = generate_comment(title, content, config)
        char_count = _comment_len(comment)
        logger.info("-" * 40)
        logger.info("标题: %s", title)
        logger.info("正文: %s", content)
        logger.info("判断: %s", decision)
        logger.info("关键词: %s", keyword)
        if comment == "SKIP":
            logger.info("结果: SKIP")
        else:
            logger.info("评论: %s (%d字)", comment, char_count)
        if config.get("deepseek_api_key") and i < len(test_posts) - 1:
            time.sleep(2)
    logger.info("-" * 40)
    logger.info("测试完成")


def main():
    actions = {
        "--login": setup_login,
        "--setup": setup_login,
        "--test":  show_test_comments,
        "--help":  show_help,
        "-h":      show_help,
    }
    action = next(
        (actions[arg] for arg in sys.argv[1:] if arg in actions),
        run_signin,
    )
    action()


if __name__ == "__main__":
    main()
