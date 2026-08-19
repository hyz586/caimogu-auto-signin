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
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

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
    "keywords": SCRIPT_DIR / "keywords.json",
    "lock":    SCRIPT_DIR / "signin.lock",
}

# 免安装版优先使用程序目录旁边的 Playwright 浏览器
_browsers_dir = SCRIPT_DIR / "playwright-browsers"
if _browsers_dir.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browsers_dir))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36",
]

VIEWPORT_SIZES = [
    {"width": 1280, "height": 720},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 800},
    {"width": 1536, "height": 864},
]

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
#  2. 关键词提取与过滤常量
# ============================================================

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

# 强禁词：全局过滤，出现即判废
_HARD_BANNED_PARTS = [
    "感谢分享", "支持一下", "学到了", "坐等后续", "确实如此",
    "期待更新", "前排围观", "有道理", "这波可以",
    "说得好", "支持楼主", "码住", "马克", "蹲一个靠谱",
    "666", "顶一下", "水帖", "占楼", "路过", "沙发",
    "学习了", "感谢楼", "谢谢分享", "辛苦了",
]

# 弱检测词：仅在评论开头出现时才过滤，避免误杀正文正常提及
_WEAK_BANNED_PREFIXES = [
    "值得讨论", "内容质量", "参考价值", "信息量", "不错",
    "挺有意思", "有道理",
]

# 兼容旧引用
_BANNED_COMMENT_PARTS = _HARD_BANNED_PARTS

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

_DEFAULT_DETAIL_PATTERNS = [
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


def _load_keywords():
    """从 keywords.json 加载关键词库，不存在时使用默认值"""
    defaults = {
        "known_game_names": _DEFAULT_KNOWN_GAME_NAMES,
        "detail_patterns": _DEFAULT_DETAIL_PATTERNS,
    }
    if PATHS["keywords"].exists():
        data = load_json(PATHS["keywords"], {})
        if isinstance(data.get("known_game_names"), list):
            defaults["known_game_names"] = data["known_game_names"]
        if isinstance(data.get("detail_patterns"), list):
            defaults["detail_patterns"] = data["detail_patterns"]
    return defaults

_REPLY_TEMPLATES = {
    "help": [
        "{d}这步最怕没提示，我之前也卡在这，最后靠回档才过去",
        "{d}看着像兼容性问题，等个补丁估计就好了，先别折腾",
        "说到{d}，我遇到过一模一样的，清缓存没用，重装才解决",
        "{d}要是能稳定复现就好办了，就怕随机触发排查到崩溃",
        "{d}这种问题最恶心，没报错没日志，只能盲猜",
        "我猜{d}是源头，楼主试试把这步跳过看会不会好",
        "{d}这情况我熟，先别急着重装，试试点修复看看",
        "{d}能每次都触发吗？如果随机出现的话大概率是内存泄漏",
    ],
    "regret": [
        "{d}可惜了，等了这么久就这结局，感觉之前的期待全白费了",
        "看到{d}被砍说实话挺难受的，毕竟关注了那么长时间",
        "{d}这种结局最搞心态，投入的精力直接打水漂",
        "又是{d}这一刀，怎么感觉最近好项目都活不下来",
        "{d}到这步戛然而止，就问之前预热的意义在哪",
        "说实话{d}这消息一点缓冲都没有，太突然了",
        "{d}这种收场方式真的让人不想再关注新项目了",
        "卡在{d}收尾，怎么说呢，期待越大失望越大吧",
    ],
    "update": [
        "{d}方向没问题，就是别最后又缩水，不然期待全落空",
        "{d}这块如果能影响玩法就好了，别只换皮不换骨",
        "说实话{d}这改动我挺期待的，就怕实装之后又是另一回事",
        "{d}看着有诚意，但执行力度才是关键，别光说不练",
        "{d}这个改动要是真能落地就舒服了，就怕砍一半",
        "我比较担心{d}会不会影响平衡，到时候又是一波调整",
        "{d}方向是对的，就怕优化跟不上，先观望吧",
        "光看{d}描述还行，等实机出来再判断，现在说啥都早",
    ],
    "recommend": [
        "{d}这个偏好挺明确，我玩过几个对口的，回头整理给你",
        "按{d}这个方向找准没错，能少踩不少坑",
        "{d}要是再耐玩一点就好了，不然选择面确实窄",
        "说到{d}，我第一个想到的就是那几个老牌作品，稳",
        "{d}这个需求其实挺好满足的，就是看你想不想接受老画面",
        "{d}按这个标准筛的话选择面会窄不少，但质量有保障",
        "{d}这个方向我还真玩过几个，主要看你能不能接受肝度",
        "单看{d}这个要求，能排掉一大批了，剩下的都还行",
    ],
    "luck": [
        "{d}这运气没谁了，我抽了八十发才出，人比人气死人",
        "看到{d}这种结果默默关掉了游戏，差距太大了",
        "{d}这波属实离谱，我十连全是保底，太酸了",
        "这种{d}截图最容易劝人手痒，下次我也想试试",
        "{d}比玄学还刺激，差一点就反转了，运气这东西真没道理",
        "看到{d}我突然不想玩这游戏了，非酋不配拥有快乐",
        "{d}这波操作妥妥的欧皇附体，建议去买彩票",
        "单看{d}就知道这运气逆天，我连续保底三个月了都",
    ],
    "media": [
        "{d}这块改编好了是神作，改砸了就是灾难，风险太大",
        "说到{d}，我觉得选角比剧情更决定成败，别只靠阵容",
        "{d}这种设定搬到银幕上观众接不接受是个大问题",
        "{d}改编的难点就在这，原著粉肯定会盯着不放",
        "我比较担心{d}会不会为了大众化把核心改没了",
        "{d}这个点处理不好整部就散了，不能只靠噱头",
        "说实话{d}看着就压力大，改编这种东西吃力不讨好",
        "{d}方向比噱头重要，别到时候光有阵容没有内容",
    ],
    "rumor": [
        "{d}如果消息属实后续影响应该不小，但先等官方回应吧",
        "{d}这种爆料看看就好，别太早下结论，之前翻车的还少吗",
        "说实话{d}现在信息还有限，等正式消息比较稳",
        "{d}如果是真的那确实炸裂，就怕最后又辟谣",
        "{d}这种传闻我持观望态度，毕竟消息来源太模糊了",
        "看到{d}先别激动，等实锤再说，假爆料太多了",
        "{d}要是真延了那影响可太大了，但我赌大概率是误传",
        "单看{d}这爆料可信度一般，等个官方公告比较靠谱",
    ],
    "sales": [
        "{d}这成绩放在同类里已经不错了，说明玩家反馈还可以",
        "{d}销量能起来说明确实有竞争力，后续能不能保持才是关键",
        "说实话{d}这数据比预期好，看来口碑发酵起作用了",
        "{d}这成绩不算意外，毕竟前期宣发到位了",
        "{d}后续热度能不能稳住才重要，别又是一波流",
        "看到{d}我觉得这个类型还是有市场的，别家可以跟进了",
        "{d}这数据说明玩家用脚投票了，质量说话比营销管用",
        "单看{d}确实亮眼，但长线运营才是考验，别高兴太早",
    ],
    "normal": [
        "{d}这块我比较在意，处理好了体验会好不少",
        "说实话{d}这方向挺有意思的，之前没往这方面想过",
        "{d}如果能落地的话影响会很明显，先观望吧",
        "我比较担心{d}会不会有隐藏问题，等实测再说",
        "{d}这个角度挺新颖的，细想的话确实值得关注",
        "看到{d}我觉得可以期待一下，就怕最后虎头蛇尾",
        "{d}细想的话影响挺深远的，不只是表面上那么简单",
        "说到{d}我也有同感，这确实是个容易被忽略的点",
    ],
}

# 同义词库：仅替换描述词，不替换功能词（应该/还是/建议等会导致语义变怪）
_SYNONYMS = {
    "看着": ["感觉", "瞧着"],
    "确实": ["真的", "属实"],
    "挺": ["蛮", "相当"],
    "有点": ["略微", "稍许"],
    "不过": ["但是", "然而"],
    "其实": ["说到底", "老实说"],
    "觉得": ["感觉", "认为"],
    "不错": ["还行", "可以"],
    "关键": ["重要", "核心"],
    "挺可惜": ["蛮遗憾", "挺遗憾"],
    "说实话": ["老实讲", "说真的"],
    "属实离谱": ["太夸张", "太离谱"],
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
    """原子写入 JSON 文件，避免程序中断导致 JSON 损坏"""
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


class SingleInstanceLock:
    """Windows 单实例锁，防止多个签到进程同时运行"""

    def __init__(self, lock_path):
        self.lock_path = str(lock_path)
        self._fh = None

    def acquire(self):
        if msvcrt is None:
            return True
        try:
            self._fh = open(self.lock_path, "w")
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            if self._fh:
                self._fh.close()
                self._fh = None
            return False

    def release(self):
        if msvcrt is None or self._fh is None:
            return
        try:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None
            try:
                os.unlink(self.lock_path)
            except Exception:
                pass


# ============================================================
#  4. 日志
# ============================================================

def setup_logging():
    """配置日志（同时输出到文件和控制台），按天轮转保留7天"""
    from logging.handlers import TimedRotatingFileHandler
    logger = logging.getLogger("caimogu")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = TimedRotatingFileHandler(
        str(PATHS["log"]), when='midnight', backupCount=7, encoding='utf-8'
    )
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

def validate_config(config):
    """校验配置参数合法性，返回修正后的 config"""
    try:
        rc = int(config.get("reply_count", 3))
        config["reply_count"] = max(1, min(rc, 20))
    except (TypeError, ValueError):
        config["reply_count"] = 3

    try:
        mind = int(config.get("min_delay", 8))
        maxd = int(config.get("max_delay", 20))
        if mind < 1: mind = 1
        if maxd < mind: maxd = mind
        config["min_delay"] = mind
        config["max_delay"] = maxd
    except (TypeError, ValueError):
        config["min_delay"] = 8
        config["max_delay"] = 20

    try:
        pt = int(config.get("page_timeout_ms", 90000))
        config["page_timeout_ms"] = max(10000, pt)
    except (TypeError, ValueError):
        config["page_timeout_ms"] = 90000

    url = config.get("circle_url", "")
    if not url or not url.startswith("http"):
        config["circle_url"] = DEFAULT_CONFIG["circle_url"]

    return config


def load_config():
    """加载配置，不存在则自动创建默认配置"""
    config = DEFAULT_CONFIG.copy()
    if not PATHS["config"].exists():
        save_json(PATHS["config"], config)
        return config
    config.update(load_json(PATHS["config"], {}))
    return validate_config(config)


def get_today_reply_count():
    """获取今天已成功回复的数量（基于已确认 SUCCESS 的帖子 ID）"""
    return len(get_today_replied_ids())


def get_today_replied_ids():
    """获取今天已回复的帖子ID列表，防止中断后重复回复"""
    data = load_json(PATHS["replied"], {})
    today = date.today().isoformat()
    if data.get("last_run_date") == today:
        return data.get("today_post_ids", [])
    return []


def get_replied_history():
    """获取最近30天内已回复过的帖子ID集合，防止跨天重复回复"""
    data = load_json(PATHS["replied"], {})
    history = data.get("replied_history", {})
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    return {pid for pid, dt in history.items() if dt >= cutoff}


def normalize_post_id(url):
    """从帖子 URL 中提取稳定数字 ID，提取失败时返回去斜杠 URL"""
    m = re.search(r'/(\d+)\.html', url)
    if m:
        return m.group(1)
    return url.rstrip('/').split('/')[-1]


def get_unknown_posts():
    """获取3天内状态未知的帖子（超过3天的标记为 EXPIRED 并清理）

    UNKNOWN 生命周期：
    - 0-3天：可验证（由调用方在遍历帖子时自动检查）
    - 超过3天：EXPIRED，自动清理避免长期悬挂
    """
    data = load_json(PATHS["replied"], {})
    unknown = data.get("unknown_posts", {})
    cutoff = (date.today() - timedelta(days=3)).isoformat()

    active = {}
    expired = []
    for pid, info in unknown.items():
        post_date = info.get("date", "")
        if post_date >= cutoff:
            active[pid] = info
        else:
            expired.append(pid)

    if expired:
        for pid in expired:
            unknown.pop(pid, None)
        data["unknown_posts"] = unknown
        save_json(PATHS["replied"], data)

    return active


def mark_today_progress(post_count, reply_count, post_id=None, result=None, comment=None):
    """记录进度，避免中断后重复回复；同时保存帖子ID和历史记录

    result: True=成功(记入history并清理UNKNOWN), None=未知状态(记入unknown_posts)
    comment: 评论内容（仅UNKNOWN状态时记录）
    """
    data = load_json(PATHS["replied"], {})
    today = date.today().isoformat()
    data["last_run_date"] = today
    data["last_run_posts"] = post_count
    data["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["status"] = "running" if post_count < reply_count else "done"

    if post_id:
        # 处理成功状态
        if result is True:
            ids = data.get("today_post_ids", [])
            if post_id not in ids:
                ids.append(post_id)
            data["today_post_ids"] = ids

            # 更新历史记录
            history = data.get("replied_history", {})
            history[post_id] = today
            # 清理超过30天的旧记录
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            history = {pid: dt for pid, dt in history.items() if dt >= cutoff}
            data["replied_history"] = history

            # 成功后清理该帖的 UNKNOWN 记录
            unknown = data.get("unknown_posts", {})
            unknown.pop(post_id, None)
            data["unknown_posts"] = unknown

        # 处理未知状态：记录待人工复核
        elif result is None and comment:
            unknown = data.get("unknown_posts", {})
            unknown[post_id] = {
                "date": today,
                "comment": comment,
                "status": "pending_review"
            }
            data["unknown_posts"] = unknown

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


def detect_title_type(title):
    """粗略判断帖子类型，用于生成更贴合标题的回复"""
    if re.search(r'取消|砍|延期|跳票|停服|下架|暴死|失败|崩|凉', title):
        return "regret"
    if re.search(r'求助|请问|有没有|怎么|如何|为啥|为什么|闪退|报错|问题|卡住', title):
        return "help"
    if re.search(r'爆料|传闻|泄露|消息人士|据说|内部消息|疑似|可能延期|或将于', title):
        return "rumor"
    if re.search(r'销量|销售额|突破|万套|百万|销量榜|成绩|首周|月销|出货量', title):
        return "sales"
    if re.search(r'更新|版本|补丁|改动|上线|发布|公布|官宣|新增', title):
        return "update"
    if re.search(r'推荐|安利|好玩|入坑|值得买吗|买不买', title):
        return "recommend"
    if re.search(r'抽卡|出货|晒|欧|非|运气|掉落', title):
        return "luck"
    if re.search(r'电影|剧|漫威|动画|漫画|主创|演员', title):
        return "media"
    return "normal"


# 常见游戏/作品名词库：优先匹配，避免硬截前4字产生无意义关键词
_DEFAULT_KNOWN_GAME_NAMES = [
    "黑神话悟空", "黑神话", "原神", "崩坏星穹铁道", "星穹铁道", "崩坏",
    "艾尔登法环", "老头环", "刺客信条", "GTA", "侠盗猎车手",
    "塞尔达", "王国之泪", "旷野之息", "最终幻想", "勇者斗恶龙",
    "怪物猎人", "怪猎", "荒野大镖客", "使命召唤", "战神",
    "对马岛之魂", "赛博朋克", "巫师", "霍格沃茨", "帕鲁",
    "幻兽帕鲁", "绝区零", "鸣潮", "明日方舟", "王者荣耀",
    "和平精英", "永劫无间", "双人成行", "糖豆人", "光遇",
    "崩坏三", "崩坏3", "蔚蓝档案", "妮姬",
    "胜利女神", "无主之地", "生化危机", "寂静岭", "龙之信条",
    "死亡搁浅", "往日不再", "地平线", "极限竞速",
    "刀锋战士", "超人", "蝙蝠侠", "蜘蛛侠", "复仇者联盟",
    "明日之子", "沙丘", "三体",
]

_keywords_data = _load_keywords()
_KNOWN_GAME_NAMES = _keywords_data["known_game_names"]
_DETAIL_PATTERNS = _keywords_data["detail_patterns"]


def extract_keyword(title):
    """从帖子标题中提取关键词，优先匹配游戏名/专有名词"""
    title = re.sub(r'^【.*?】\s*', '', title)
    title = re.sub(r'^\[.*?\]\s*', '', title)

    # 优先级1：书名号《》内的内容（通常是游戏名或作品名）
    match = re.search(r'《(.+?)》', title)
    if match and len(match.group(1)) >= 2:
        return match.group(1)[:6]

    # 优先级1.5：引号内的内容
    match = re.search(r'[\u201c\u201d"\u300c\u300d\u300e\u300f](.+?)[\u201c\u201d"\u300c\u300d\u300e\u300f]', title)
    if match and len(match.group(1)) >= 2:
        return match.group(1)[:6]

    # 优先级2：已知游戏/作品名词库
    for name in _KNOWN_GAME_NAMES:
        if name in title:
            return name

    # 优先级3：已知的复合关键词模式
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

    # 优先级4：清理后提取，但不再硬截前4字，而是取较长的中文连续片段
    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', title)

    for prefix in _MEANINGLESS_PREFIXES:
        if clean.startswith(prefix) and len(clean) > len(prefix) + 2:
            clean = clean[len(prefix):]
            break

    for suffix in _MEANINGLESS_SUFFIXES:
        if clean.endswith(suffix) and len(clean) > len(suffix) + 2:
            clean = clean[:-len(suffix)]
            break

    # 从清理后的文本中提取2-6字的中文片段，取最长的
    segments = re.findall(r'[\u4e00-\u9fa5]{2,6}', clean)
    if segments:
        # 从最长候选开始，真正过滤掉包含无意义片段的关键词
        for best in sorted(segments, key=len, reverse=True):
            if any(bad in best for bad in _BAD_PARTS):
                continue
            if 2 <= len(best) <= 6:
                return best

    # 兜底：如果以上都没匹配到，取前2-4字
    if len(clean) >= 2:
        return clean[:min(4, len(clean))]
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
        r'爆料|传闻|泄露|消息人士|据说|内部消息|疑似',
        r'销量|突破|万套|百万|销量榜|成绩|首周|出货量',
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
        if any(bad in chunk for bad in _HARD_BANNED_PARTS):
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
    # 强禁词：全局过滤
    if any(part in comment for part in _HARD_BANNED_PARTS):
        return False
    # 弱检测词：仅在开头出现时过滤，避免误杀正文正常提及
    if any(comment.startswith(prefix) for prefix in _WEAK_BANNED_PREFIXES):
        return False
    length = _comment_len(comment)
    if not (15 <= length <= 40):
        return False
    compact_title = re.sub(r'\s+', '', title or "")
    if compact_title and comment == compact_title:
        return False
    if "我也" in comment and not re.search(r'求助|请问|有没有|问题|推荐', title or ""):
        return False
    return True


def _apply_synonyms(text):
    """随机替换同义词，增加回复多样性"""
    for word, subs in _SYNONYMS.items():
        if word in text and random.random() < 0.4:
            text = text.replace(word, random.choice(subs), 1)
    return text


def generate_comment_template(title, content=""):
    """模板模式：先判断 REPLY/SKIP，再生成短回复"""
    decision = judge_replyability(title, content)
    if decision == "SKIP":
        return "SKIP"

    detail = _extract_detail(title, content)
    if not detail:
        return "SKIP"

    keyword = extract_keyword(title) or ""
    title_type = detect_title_type((title or "") + " " + (content or "")[:120])
    templates = _REPLY_TEMPLATES.get(title_type, _REPLY_TEMPLATES["normal"])

    # 打乱模板顺序，填充插槽并应用同义词随机化
    candidates = []
    for tpl in random.sample(templates, len(templates)):
        filled = tpl.replace("{d}", detail).replace("{kw}", keyword)
        filled = _apply_synonyms(filled)
        candidates.append(filled)

    valid = [c for c in candidates if _is_reply_valid(c, title, content)]
    if valid:
        return random.choice(valid)
    return "SKIP"


def _call_deepseek_api(url, headers, data, logger, max_retries=3):
    """发起 API 请求，对可重试错误（429/5xx/网络超时）使用指数退避"""
    import requests
    retryable_codes = {429, 500, 502, 503, 504}
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=20)
            resp.raise_for_status()
            result = resp.json()
            returned_model = result.get("model", "未知")
            logger.info("AI 返回模型: %s", returned_model)
            raw_content = result["choices"][0]["message"]["content"]
            return raw_content, returned_model
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in retryable_codes and attempt < max_retries:
                wait = 2 ** (attempt + 1)
                logger.warning("API 返回 %d，%d 秒后重试 (%d/%d)", status, wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                logger.warning("网络错误，%d 秒后重试 (%d/%d): %s", wait, attempt + 1, max_retries, e)
                time.sleep(wait)
                continue
            raise


def generate_comment_ai(title, content, api_key, base_url, model):
    """AI 模式：让 AI 直接生成评论或 SKIP，含空返回重试和指数退避"""
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
            "你是一个游戏论坛用户，正在浏览帖子。请根据标题和正文，写一条真实的回复。\n\n"
            "规则：\n"
            "- 从玩家立场出发回复，表达个人态度（担忧、期待、吐槽、对比、怀疑），不要像在评价新闻\n"
            "- 抓住帖子里一个具体细节来回复，可以推测影响、表达预期\n"
            "- 语气口语化，像真人在闲聊，可以吐槽、提问、补充\n"
            "- 15到40个字，别太短也别太长\n"
            "- 绝对不要用这些套话：感谢分享、支持一下、学到了、坐等后续、确实如此、期待更新、前排围观、有道理、这波可以、说得好、支持楼主、码住、马克\n"
            "- 不要假装亲身经历过\n"
            "- 不要总结帖子内容或复述标题\n"
            "- 不要用\"这个细节\"\"这个改动\"\"这个消息\"开头\n\n"
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
        raw_content, _ = _call_deepseek_api(url, headers, data, logger)

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
            raw_content2, _ = _call_deepseek_api(url, headers, retry_data, logger)
            logger.info("AI 重试返回: %s", raw_content2)
            comment = _normalize_generated_comment(raw_content2)
            logger.info("AI 重试清洗后: %s (字数=%d)", comment, _comment_len(comment))

            if comment.upper() == "SKIP":
                return "SKIP"
            if _comment_len(comment) < 5:
                logger.warning("AI 重试仍为空，回退模板")
                return generate_comment_template(title, content)

        if any(part in comment for part in _HARD_BANNED_PARTS):
            logger.warning("AI 回复含套话，回退模板: %s", comment)
            return generate_comment_template(title, content)

        # AI 输出必须经过与模板模式相同的本地规则校验。
        if not _is_reply_valid(comment, title, content):
            logger.warning(
                "AI 回复未通过本地规则校验，回退模板: %s", comment
            )
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
#  6.5 V3.2 评论质量评分、重复检测与状态机
# ============================================================

# 帖子状态机
POST_STATUS = (
    "DISCOVERED",   # 发现候选帖
    "SKIPPED",      # 判断为不可回复，跳过
    "GENERATED",    # 评论已生成
    "SUBMITTED",    # 已点击提交
    "SUCCESS",      # 确认成功
    "FAILED",       # 确认失败
    "UNKNOWN",      # 状态未知
    "VERIFIED",     # UNKNOWN 经验证确认为成功
    "EXPIRED",      # UNKNOWN 超过3天过期
    "AUTH_EXPIRED", # 登录失效
)

# 质量评分权重
_SCORE_WEIGHTS = {
    "keyword": 20,    # 提及标题核心对象
    "detail": 25,     # 引用正文具体细节
    "type_match": 20, # 与帖子类型匹配
    "no_cliche": 15,  # 没有套话
    "length": 10,     # 长度合适
    "low_repeat": 10, # 与历史评论重复度低
}


def score_comment_quality(comment, title, content):
    """评估评论质量，返回 0-100 分及各维度得分明细"""
    scores = {}
    comment_clean = _normalize_generated_comment(comment)
    if not comment_clean or comment_clean.upper() == "SKIP":
        return 0, {}

    # 1. 提及标题核心对象（+20）
    keyword = extract_keyword(title or "") or ""
    if keyword and keyword in comment_clean:
        scores["keyword"] = _SCORE_WEIGHTS["keyword"]
    elif keyword and len(keyword) >= 2:
        # 部分匹配（关键词的前2字出现在评论中）
        if keyword[:2] in comment_clean:
            scores["keyword"] = _SCORE_WEIGHTS["keyword"] // 2

    # 2. 引用正文具体细节（+25）
    detail = _extract_detail(title, content) or ""
    if detail and detail in comment_clean:
        scores["detail"] = _SCORE_WEIGHTS["detail"]
    elif detail and len(detail) >= 2 and detail[:2] in comment_clean:
        scores["detail"] = _SCORE_WEIGHTS["detail"] // 2

    # 3. 与帖子类型匹配（+20）
    title_type = detect_title_type((title or "") + " " + (content or "")[:120])
    type_keywords = {
        "regret": ["可惜", "难受", "期待", "失望", "白费"],
        "help": ["问题", "遇到", "排查", "解决", "兼容"],
        "rumor": ["观望", "爆料", "消息", "等官方", "辟谣"],
        "sales": ["成绩", "销量", "竞争力", "口碑", "反馈"],
        "update": ["改动", "更新", "优化", "方向", "落地"],
        "recommend": ["推荐", "对口", "踩坑", "老牌", "方向"],
        "luck": ["运气", "抽", "保底", "欧", "非"],
        "media": ["改编", "选角", "风险", "阵容", "核心"],
    }
    type_words = type_keywords.get(title_type, [])
    if any(w in comment_clean for w in type_words):
        scores["type_match"] = _SCORE_WEIGHTS["type_match"]

    # 4. 没有套话（+15）
    if not any(part in comment_clean for part in _HARD_BANNED_PARTS):
        scores["no_cliche"] = _SCORE_WEIGHTS["no_cliche"]

    # 5. 长度合适（+10）：15-40字为合适
    clen = _comment_len(comment_clean)
    if 15 <= clen <= 40:
        scores["length"] = _SCORE_WEIGHTS["length"]
    elif 10 <= clen <= 50:
        scores["length"] = _SCORE_WEIGHTS["length"] // 2

    # 6. 与历史评论重复度低（+10）：由调用方传入 recent_comments 后计算
    # 此项在 is_comment_too_similar 检查后由调用方补充
    # 默认给满分，如果检测到相似则扣分
    scores["low_repeat"] = _SCORE_WEIGHTS["low_repeat"]

    total = sum(scores.values())
    return total, scores


def _comment_ngrams(text, n=2):
    """提取评论的字符 n-gram 集合"""
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i+n] for i in range(len(text) - n + 1)}


def comment_similarity(text1, text2, n=2):
    """计算两条评论的 Jaccard 相似度（0-1）"""
    if not text1 or not text2:
        return 0.0
    grams1 = _comment_ngrams(text1, n)
    grams2 = _comment_ngrams(text2, n)
    if not grams1 or not grams2:
        return 0.0
    intersection = grams1 & grams2
    union = grams1 | grams2
    return len(intersection) / len(union) if union else 0.0


def get_recent_comments(days=7):
    """获取最近 N 天内成功发表的评论列表"""
    data = load_json(PATHS["replied"], {})
    records = data.get("post_records", [])
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [r.get("comment", "") for r in records
            if r.get("date", "") >= cutoff
            and r.get("status") == "SUCCESS"
            and r.get("comment")]


def is_comment_too_similar(comment, recent_comments, threshold=0.6):
    """检查评论是否与历史评论过于相似，返回 (is_similar, max_similarity, similar_comment)"""
    if not comment or not recent_comments:
        return False, 0.0, ""
    max_sim = 0.0
    most_similar = ""
    for prev in recent_comments:
        sim = comment_similarity(comment, prev)
        if sim > max_sim:
            max_sim = sim
            most_similar = prev
    return max_sim >= threshold, max_sim, most_similar


def record_post_execution(post_id, title, status, comment=None, comment_source=None,
                           attempts=1, duration_ms=0, verification=None, error=None,
                           quality_score=None):
    """记录单个帖子的完整执行结果到 replied_posts.json"""
    data = load_json(PATHS["replied"], {})
    records = data.get("post_records", [])
    entry = {
        "post_id": post_id,
        "date": date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M:%S"),
        "title": (title or "")[:80],
        "status": status,
        "comment": comment or "",
        "comment_source": comment_source or "",
        "attempts": attempts,
        "duration_ms": duration_ms,
        "verification": verification or "",
        "error": error,
    }
    if quality_score is not None:
        entry["quality_score"] = quality_score
    records.append(entry)
    # 只保留最近200条记录
    if len(records) > 200:
        records = records[-200:]
    data["post_records"] = records
    save_json(PATHS["replied"], data)


def generate_daily_report(logger, stats):
    """生成并输出每日签到报告"""
    report_lines = [
        "=" * 50,
        "采蘑菇签到报告",
        "=" * 50,
        f"目标：{stats.get('target', 0)}",
        f"成功：{stats.get('success', 0)}   "
        f"失败：{stats.get('failed', 0)}   "
        f"UNKNOWN：{stats.get('unknown', 0)}   "
        f"SKIP：{stats.get('skipped', 0)}",
        f"AI评论：{stats.get('ai_comments', 0)}   "
        f"模板评论：{stats.get('template_comments', 0)}",
    ]
    quality_scores = stats.get("quality_scores", [])
    if quality_scores:
        avg_q = sum(quality_scores) / len(quality_scores)
        report_lines.append(f"平均评论质量：{avg_q:.1f}")
    else:
        report_lines.append("平均评论质量：N/A")
    duration_s = stats.get("duration_s", 0)
    if duration_s > 0:
        mins, secs = divmod(int(duration_s), 60)
        report_lines.append(f"耗时：{mins}分{secs}秒")
    report_lines.append("=" * 50)

    report_text = "\n".join(report_lines)
    for line in report_lines:
        logger.info(line)

    # 写入 daily_report.json
    report_data = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **stats,
        "avg_quality": round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0,
    }
    report_path = SCRIPT_DIR / "daily_report.json"
    save_json(report_path, report_data)

    return report_text


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
        viewport=random.choice(VIEWPORT_SIZES),
        user_agent=random.choice(USER_AGENTS),
        storage_state=storage_state,
    )
    return browser, context

# ============================================================
#  8. 页面操作
# ============================================================

def goto_with_retry(page, url, logger, timeout=90000, retries=2):
    """带重试的页面导航，网络抖动时不浪费时间"""
    for attempt in range(retries + 1):
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return True
        except Exception as e:
            if attempt < retries:
                wait = 5 * (attempt + 1)
                logger.warning("页面加载失败(%s)，%d秒后重试(%d/%d): %s", url, wait, attempt + 1, retries, e)
                time.sleep(wait)
            else:
                logger.warning("页面加载重试%d次仍失败: %s", retries, url)
                return False
    return False


def get_post_list(page, config, count, logger):
    """从板块页面获取帖子列表，自动跳过置顶帖"""
    circle_url = config["circle_url"]
    logger.info("正在获取帖子列表: %s", circle_url)
    timeout = config.get("page_timeout_ms", 90000)
    goto_with_retry(page, circle_url, logger, timeout=timeout)
    page.wait_for_timeout(3000)

    try:
        page.wait_for_selector(SELECTORS["post_item"], timeout=10000)
    except Exception:
        logger.error("帖子列表未加载，可能页面结构有变化")
        return []

    items = page.query_selector_all(SELECTORS["post_item"])
    posts = []
    skipped_pinned = 0
    # 给“内容不可回复/已回复/失败”的情况留出更大的候选池。
    # 当前版本不假设网站的分页 URL 结构，避免因猜测分页规则导致失效。
    max_candidates = max(count * 15, count + 30)

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
            try:
                item_html = item.inner_html()[:500]
            except Exception:
                item_html = ""
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
    """输入评论到编辑器，依次尝试 Quill API → keyboard → fill → execCommand"""

    def get_editor_text():
        try:
            return page.evaluate('() => { var ed = document.querySelector(".ql-editor"); return ed ? ed.innerText.trim() : ""; }')
        except Exception:
            return ""

    def focus_quill():
        """用 Quill API 聚焦编辑器（比 DOM .focus() 更可靠）"""
        close_safe_popup(page, logger)
        try:
            page.evaluate(
                '() => { var ed = document.querySelector(".ql-editor"); '
                'if(!ed) return; '
                'var container = ed.closest(".ql-container"); '
                'if(container && window.Quill) { '
                '  var quill = Quill.find(container); '
                '  if(quill) { quill.focus(); return; } '
                '} '
                'ed.focus(); }'
            )
            page.wait_for_timeout(200)
        except Exception:
            pass

    # 方式一：Quill API setText（最可靠，直接更新 Quill 内部状态）
    focus_quill()
    try:
        result = page.evaluate(
            '(text) => {'
            '  var ed = document.querySelector(".ql-editor"); '
            '  if(!ed) return false; '
            '  var container = ed.closest(".ql-container"); '
            '  if(container && window.Quill) { '
            '    var quill = Quill.find(container); '
            '    if(quill) { '
            '      quill.setContents([{insert: text}]); '
            '      quill.setSelection(text.length, 0); '
            '      ed.dispatchEvent(new Event("input", {bubbles: true})); '
            '      ed.dispatchEvent(new Event("change", {bubbles: true})); '
            '      return true; '
            '    } '
            '  } '
            '  return false; '
            '}',
            comment
        )
        if result:
            page.wait_for_timeout(300)
            actual = get_editor_text()
            if actual and len(actual) >= 5:
                logger.info("评论已输入编辑器(Quill API)")
                return True
    except Exception:
        pass

    # 方式二：键盘逐字输入（触发完整DOM事件链）
    focus_quill()
    try:
        page.evaluate(
            '() => { var ed = document.querySelector(".ql-editor"); '
            'if(ed) { ed.focus(); var range = document.createRange(); '
            'range.selectNodeContents(ed); var sel = window.getSelection(); '
            'sel.removeAllRanges(); sel.addRange(range); } }'
        )
        page.wait_for_timeout(100)
        page.keyboard.press("Backspace")
        page.wait_for_timeout(200)
        page.keyboard.type(comment, delay=50)
        page.wait_for_timeout(500)
        actual = get_editor_text()
        if actual and len(actual) >= 5:
            logger.info("评论已输入编辑器(keyboard)")
            return True
    except Exception:
        pass

    # 方式三：fill
    close_safe_popup(page, logger)
    try:
        editor.fill(comment, timeout=5000)
        page.wait_for_timeout(500)
        actual = get_editor_text()
        if actual and len(actual) >= 5:
            logger.info("评论已输入编辑器(fill)")
            return True
    except Exception:
        pass

    # 方式四：execCommand 选中并插入文本
    focus_quill()
    try:
        page.evaluate(
            '() => { var ed = document.querySelector(".ql-editor"); '
            'if(ed) { ed.focus(); var range = document.createRange(); '
            'range.selectNodeContents(ed); var sel = window.getSelection(); '
            'sel.removeAllRanges(); sel.addRange(range); } }'
        )
        page.wait_for_timeout(100)
        page.evaluate('(text) => { document.execCommand("insertText", false, text); }', comment)
        page.wait_for_timeout(500)
        actual = get_editor_text()
        if actual and len(actual) >= 5:
            logger.info("评论已输入编辑器(execCommand)")
            return True
    except Exception:
        pass

    logger.error("所有输入方式均失败")
    return False


def inspect_popup(page, logger):
    """读取 SweetAlert2 等弹窗内容，不关闭任何弹窗。
    业务流程开始时调用，避免误关包含关键错误信息的弹窗。
    """
    try:
        info = page.evaluate(
            '() => { var c = document.querySelector(".swal2-container"); '
            'if(!c) return null; '
            'var t = c.querySelector(".swal2-title"); '
            'var h = c.querySelector(".swal2-html-container"); '
            'return { title: t ? t.innerText.trim() : "", content: h ? h.innerText.trim() : "" }; }'
        )
        if info and (info.get("title") or info.get("content")):
            logger.info("页面弹窗: [%s] %s", info.get("title", ""), info.get("content", ""))
            return info
    except Exception:
        pass
    return None


def close_safe_popup(page, logger):
    """关闭 SweetAlert2 等遮罩弹窗，防止遮挡编辑器与提交按钮。
    输入/提交前调用，先记录弹窗内容再关闭可关闭的弹窗。
    """
    # 先读取弹窗内容（用于诊断提交失败原因）
    inspect_popup(page, logger)

    # 优先用 Escape 与按钮关闭
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    for sel in (".swal2-close", ".swal2-confirm", ".swal2-cancel"):
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click(timeout=2000)
                page.wait_for_timeout(300)
        except Exception:
            continue
    # 不再直接删除未知弹窗 DOM。
    # SweetAlert 可能承载登录失效、风控、验证码或提交失败等关键信息，
    # 强行 remove 可能导致后续逻辑误判。


def get_reply_editor_text(page):
    """读取当前回复编辑器文本"""
    try:
        return page.evaluate(
            "() => { const ed = document.querySelector('.ql-editor'); "
            "return ed ? ed.innerText.trim() : ''; }"
        )
    except Exception:
        return ""


def get_visible_success_message(page):
    """读取页面上常见的成功提示；未知提示不做猜测"""
    selectors = (
        ".swal2-container .swal2-title",
        ".swal2-container .swal2-html-container",
        ".toast-success",
        ".alert-success",
        ".msg-success",
    )
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                if el.is_visible():
                    txt = el.inner_text().strip()
                    if txt:
                        return txt
        except Exception:
            continue
    return ""


def get_visible_error_message(page):
    """读取页面上常见的错误提示"""
    selectors = (
        ".swal2-container .swal2-title",
        ".swal2-container .swal2-html-container",
        SELECTORS["error"],
    )
    for sel in selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                if el.is_visible():
                    txt = el.inner_text().strip()
                    if txt:
                        return txt
        except Exception:
            continue
    return ""


def get_comment_count(page, logger):
    """获取当前帖子页面的评论/回复数量，用于检测提交后新评论是否出现

    返回 None 表示无法检测到评论 DOM（与 0 条评论区分开）
    """
    try:
        count = page.evaluate(
            '''() => {
                var selectors = [
                    ".comment-list .comment-item",
                    ".reply-list .reply-item",
                    "#comments .comment",
                    ".post-comments .comment",
                    ".comment-list .item",
                    ".reply-item",
                    "[class*='comment'] [class*='item']",
                    "[class*='reply'] [class*='item']"
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var items = document.querySelectorAll(selectors[i]);
                    if (items.length > 0) return items.length;
                }
                return null;
            }'''
        )
        return count
    except Exception:
        return None


def wait_reply_result(page, logger, previous_editor_text, initial_comments=None, post_id=None):
    """
    提交后判断结果：
      True  = 明确成功
      False = 明确失败
      None  = 状态未知，不重复提交

    initial_comments: 提交前的评论数（由 reply_to_post 在提交前获取并传入）
    """
    success_words = ("成功", "发表成功", "回复成功", "发布成功", "评论成功")
    error_words = ("失败", "错误", "禁止", "频繁", "限制", "验证码", "未登录", "登录")

    if initial_comments is not None:
        logger.info("提交前评论数: %d", initial_comments)

    for _ in range(10):
        page.wait_for_timeout(1000)

        # 1. 检查新评论是否出现（最可靠的成功信号）
        current_comments = get_comment_count(page, logger)
        if initial_comments is not None and current_comments is not None:
            if current_comments > initial_comments:
                logger.info("评论数从 %d 增加到 %d，确认提交成功", initial_comments, current_comments)
                return True

        # 2. 检查明确成功提示
        msg = get_visible_success_message(page)
        if msg:
            logger.info("检测到提交提示: %s", msg)
            if any(word in msg for word in success_words):
                return True
            if any(word in msg for word in error_words):
                return False

        # 3. 检查明确错误提示
        err = get_visible_error_message(page)
        if err:
            logger.warning("检测到提交错误提示: %s", err)
            if any(word in err for word in error_words):
                return False

        # 4. 编辑器清空只能作为"可能成功"的辅助信号，
        # 不能单独判定成功；继续等待页面状态变化。
        current = get_reply_editor_text(page)
        if not current and previous_editor_text:
            logger.info("回复编辑器已清空，继续等待最终提交状态")

    logger.warning("提交结果无法明确确认，标记为未知状态")
    return None


def submit_reply(page, logger):
    """查找并点击提交按钮；只负责发起一次提交"""
    close_safe_popup(page, logger)

    # 防止双击重复提交：检查JS标志位
    try:
        already_submitted = page.evaluate('() => window.__caimogu_submit_flag === true')
        if already_submitted:
            logger.warning("检测到重复提交标志，跳过本次提交")
            return False
    except Exception:
        pass

    # 检查提交按钮是否被禁用，遍历所有提交选择器
    try:
        disabled = page.evaluate(
            '''() => {
                var selectors = [".btn-reply-root", 'button:has-text("回复")',
                    'button:has-text("发表")', 'button:has-text("提交")',
                    ".submit-btn", ".btn-publish", ".btn-send", 'input[type="submit"]'];
                for (var i = 0; i < selectors.length; i++) {
                    var btn = document.querySelector(selectors[i]);
                    if (btn) {
                        return btn.disabled || btn.classList.contains("disabled") || btn.getAttribute("aria-disabled") === "true";
                    }
                }
                return false;
            }'''
        )
        if disabled:
            logger.info("提交按钮处于禁用状态，尝试触发编辑器更新")
            try:
                page.evaluate(
                    '() => { var ed = document.querySelector(".ql-editor"); '
                    'if(ed) { ed.focus(); ed.dispatchEvent(new Event("input", {bubbles: true})); '
                    'ed.dispatchEvent(new KeyboardEvent("keyup", {bubbles: true, key: "a"})); } }'
                )
                page.wait_for_timeout(500)
            except Exception:
                pass
    except Exception:
        pass

    # 优先在编辑器附近查找提交按钮，避免点到帖子列表中的回复按钮
    btn, sel = None, None
    try:
        handle = page.evaluate_handle(
            '''() => {
                var ed = document.querySelector(".ql-editor");
                if (!ed) return null;
                var container = ed.closest("form") || ed.closest(".comment-form")
                    || ed.closest(".reply-box") || ed.parentElement.parentElement;
                if (!container) return null;
                var candidates = [".btn-reply-root", ".btn-publish", ".btn-send",
                    ".submit-btn", 'button[type="submit"]'];
                for (var i = 0; i < candidates.length; i++) {
                    var b = container.querySelector(candidates[i]);
                    if (b) return b;
                }
                return null;
            }'''
        )
        btn = handle.as_element()
        if btn:
            sel = "editor-container"
    except Exception:
        pass

    # 兜底：全局查找
    if not btn:
        btn, sel = first_element(page, SELECTORS["submit"])

    if btn:
        try:
            # 设置提交标志位，15秒后自动重置（防止异常导致永久阻塞）
            page.evaluate('() => { window.__caimogu_submit_flag = true; setTimeout(() => { window.__caimogu_submit_flag = false; }, 15000); }')
            btn.click()
            logger.info("点击提交按钮: %s", sel)
            page.wait_for_timeout(2000)
            return True
        except Exception as e:
            # 提交失败，重置标志位
            try:
                page.evaluate('() => { window.__caimogu_submit_flag = false; }')
            except Exception:
                pass
            logger.error("点击提交按钮失败: %s", e)
            # 弹窗残留遮挡时，用 JS 直接派发点击
            try:
                page.evaluate('() => { window.__caimogu_submit_flag = true; setTimeout(() => { window.__caimogu_submit_flag = false; }, 15000); }')
                page.evaluate("(el) => el.click()", btn)
                logger.info("JS 兜底点击提交按钮: %s", sel)
                page.wait_for_timeout(2000)
                return True
            except Exception as e2:
                try:
                    page.evaluate('() => { window.__caimogu_submit_flag = false; }')
                except Exception:
                    pass
                logger.error("JS 兜底点击仍失败: %s", e2)
                return False

    # 备选：Ctrl+Enter
    try:
        page.evaluate('() => { window.__caimogu_submit_flag = true; setTimeout(() => { window.__caimogu_submit_flag = false; }, 15000); }')
        page.keyboard.press("Control+Enter")
        logger.info("通过 Ctrl+Enter 提交")
        page.wait_for_timeout(2000)
        return True
    except Exception:
        logger.error("未找到提交按钮")
        return False


def reply_to_post(page, post_url, config, logger, post_id=None):
    """打开帖子并回复（页面交互层，评论生成委托给 generate_comment）
    返回 (status, comment, meta): status="SUCCESS"/"FAILED"/"UNKNOWN"/"AUTH_EXPIRED"
    meta 包含 quality_score, comment_source, duration_ms, title, verification, error
    """
    start_time = time.time()
    pid = post_id or normalize_post_id(post_url)
    logger.info("[POST %s] DISCOVERED", pid)

    meta = {"quality_score": 0, "comment_source": "", "duration_ms": 0,
            "title": "", "verification": "", "error": None}

    try:
        timeout = config.get("page_timeout_ms", 90000)
        goto_with_retry(page, post_url, logger, timeout=timeout)
        page.wait_for_timeout(3000)
        inspect_popup(page, logger)

        # 提取帖子信息
        title, content = extract_post_info(page)
        meta["title"] = (title or "")[:80]
        logger.info("帖子标题: %s", title)

        # 生成评论（纯逻辑，不涉及页面操作）
        comment_source = "ai" if config.get("deepseek_api_key") else "template"
        comment = generate_comment(title, content, config)
        if comment == "SKIP":
            logger.info("[POST %s] SKIPPED - 判断为不可回复", pid)
            meta["duration_ms"] = int((time.time() - start_time) * 1000)
            record_post_execution(pid, title, "SKIPPED", error="judged_skip")
            return ("FAILED", None, meta)
        logger.info("[POST %s] GENERATED: %s", pid, comment)
        meta["comment_source"] = comment_source

        # 评论质量评分
        quality_score, quality_detail = score_comment_quality(comment, title, content)

        # 评论重复检测
        recent = get_recent_comments(days=7)
        if recent:
            is_sim, max_sim, sim_comment = is_comment_too_similar(comment, recent)
            if is_sim:
                logger.warning("[POST %s] 评论与历史相似度 %.0f%%，扣减重复分: %s",
                               pid, max_sim * 100, sim_comment[:30])
                quality_detail.pop("low_repeat", None)
                quality_score = sum(quality_detail.values())

        logger.info("[POST %s] 质量评分: %d/100 (%s)", pid, quality_score, quality_detail)
        meta["quality_score"] = quality_score

        # 滚动到底部
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        # 查找编辑器
        editor = find_editor(page, logger)
        if not editor:
            logger.error("未找到回复输入框，跳过此帖子")
            meta["duration_ms"] = int((time.time() - start_time) * 1000)
            meta["error"] = "editor_not_found"
            record_post_execution(pid, title, "FAILED", error="editor_not_found",
                                   duration_ms=meta["duration_ms"])
            return ("FAILED", None, meta)

        # 输入评论
        if not input_comment(page, editor, comment, logger):
            meta["duration_ms"] = int((time.time() - start_time) * 1000)
            meta["error"] = "input_failed"
            record_post_execution(pid, title, "FAILED", comment=comment,
                                   comment_source=comment_source,
                                   duration_ms=meta["duration_ms"], error="input_failed")
            return ("FAILED", None, meta)

        # 提交回复前保存编辑器内容。
        previous_editor_text = get_reply_editor_text(page)
        if not previous_editor_text:
            logger.error("提交前读取不到编辑器内容，停止提交")
            meta["duration_ms"] = int((time.time() - start_time) * 1000)
            meta["error"] = "editor_empty"
            record_post_execution(pid, title, "FAILED", comment=comment,
                                   comment_source=comment_source,
                                   duration_ms=meta["duration_ms"], error="editor_empty")
            return ("FAILED", None, meta)

        # 提交前记录评论数，提交后检测是否增加（核心修复）
        initial_comments = get_comment_count(page, logger)

        logger.info("[POST %s] SUBMITTED", pid)
        # 只发起一次提交。状态未知时绝不自动再次点击，避免重复回复。
        if not submit_reply(page, logger):
            meta["duration_ms"] = int((time.time() - start_time) * 1000)
            meta["error"] = "submit_failed"
            record_post_execution(pid, title, "FAILED", comment=comment,
                                   comment_source=comment_source,
                                   duration_ms=meta["duration_ms"], error="submit_failed")
            return ("FAILED", None, meta)

        result = wait_reply_result(page, logger, previous_editor_text,
                                   initial_comments=initial_comments, post_id=post_id)

        meta["duration_ms"] = int((time.time() - start_time) * 1000)

        # 登录失效需要单独处理。
        if result is False:
            err = get_visible_error_message(page)
            if "登录" in err or "登陆" in err:
                logger.error("登录状态已失效！请重新运行 --login 配置登录")
                logger.info("[POST %s] AUTH_EXPIRED", pid)
                meta["error"] = "auth_expired"
                record_post_execution(pid, title, "AUTH_EXPIRED", comment=comment,
                                       comment_source=comment_source,
                                       duration_ms=meta["duration_ms"], error="auth_expired")
                return ("AUTH_EXPIRED", None, meta)

        if result is True:
            logger.info("[POST %s] SUCCESS", pid)
            # 成功提示出现后再关闭可关闭的提示，不删除未知弹窗。
            close_safe_popup(page, logger)
            meta["verification"] = "comment_count"
            record_post_execution(pid, title, "SUCCESS", comment=comment,
                                   comment_source=comment_source,
                                   quality_score=quality_score,
                                   duration_ms=meta["duration_ms"],
                                   verification="comment_count")
            return ("SUCCESS", comment, meta)

        if result is None:
            # 状态未知：不要把它记为成功，也不要再次提交。
            logger.warning("[POST %s] UNKNOWN - 状态未知，不重复提交", pid)
            record_post_execution(pid, title, "UNKNOWN", comment=comment,
                                   comment_source=comment_source,
                                   quality_score=quality_score,
                                   duration_ms=meta["duration_ms"])
            return ("UNKNOWN", comment, meta)

        logger.info("[POST %s] FAILED", pid)
        meta["error"] = "result_false"
        record_post_execution(pid, title, "FAILED", comment=comment,
                               comment_source=comment_source,
                               duration_ms=meta["duration_ms"], error="result_false")
        return ("FAILED", None, meta)

    except Exception as e:
        logger.error("回复帖子时出错: %s", e)
        meta["duration_ms"] = int((time.time() - start_time) * 1000)
        meta["error"] = str(e)
        record_post_execution(pid, meta.get("title", ""), "FAILED",
                               error=str(e), duration_ms=meta["duration_ms"])
        return ("FAILED", None, meta)


def verify_existing_comment(page, expected_comment, logger):
    """检查页面上是否已存在之前 UNKNOWN 状态的评论文本

    保守处理：只能证明相同文本出现在页面上，不能确定是当前账号发表的。
    返回 True=明确找到 / False=明确没找到 / None=无法检测
    """
    if not expected_comment:
        return None
    try:
        found = page.evaluate(
            '''(expected) => {
                var selectors = [
                    ".comment-list .comment-item",
                    ".reply-list .reply-item",
                    "#comments .comment",
                    ".post-comments .comment",
                    "[class*='comment'] [class*='item']",
                    "[class*='reply'] [class*='item']"
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var items = document.querySelectorAll(selectors[i]);
                    for (var j = 0; j < items.length; j++) {
                        if (items[j].textContent.includes(expected)) return true;
                    }
                }
                return false;
            }''',
            expected_comment
        )
        return bool(found)
    except Exception:
        return None


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
    # 先检查 auth_state.json 中 cmg_token 是否已过期
    try:
        with open(str(PATHS["auth"]), 'r', encoding='utf-8') as f:
            state = json.load(f)
        for cookie in state.get('cookies', []):
            if cookie.get('name') == 'cmg_token':
                expires = cookie.get('expires', -1)
                if expires > 0:
                    exp_time = datetime.fromtimestamp(expires)
                    if exp_time < datetime.now():
                        logger.error("登录令牌(cmg_token)已于 %s 过期", exp_time.strftime('%Y-%m-%d %H:%M'))
                        return False
                    days_left = (exp_time - datetime.now()).days
                    if days_left <= 2:
                        logger.warning("登录令牌将在 %d 天后过期，请尽快重新登录", days_left)
                    logger.info("登录令牌有效期至: %s", exp_time.strftime('%Y-%m-%d %H:%M'))
                break
    except Exception as e:
        logger.warning("检查令牌过期时间时出错: %s", e)

    try:
        goto_with_retry(page, "https://www.caimogu.cc/", logger, timeout=60000)
        page.wait_for_timeout(2000)

        login_links = page.query_selector_all(SELECTORS["login_link"])
        for link in login_links:
            try:
                text = link.inner_text()
                if "登录" in text or "登陆" in text:
                    return False
            except Exception:
                continue

        # 登录有效，访问个人中心触发服务器刷新 token
        try:
            goto_with_retry(page, "https://www.caimogu.cc/user/setting.html", logger, timeout=30000)
            page.wait_for_timeout(1000)
            logger.info("已访问个人中心，可能刷新登录令牌")
        except Exception:
            pass

        return True
    except Exception as e:
        logger.warning("检查登录状态时出错: %s", e)
        return False

# ============================================================
#  10. 签到流程
# ============================================================

def show_notification(title, message):
    """显示 Windows 弹窗通知（后台签到失败时提醒用户）"""
    try:
        import ctypes
        # MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST = 0x30 | 0x10000 | 0x40000
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x30 | 0x10000 | 0x40000)
    except Exception:
        pass


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
        show_notification("采蘑菇签到失败", "未安装 Playwright，请先运行 install.bat")
        return

    reply_count = config.get("reply_count", 3)
    headless = config.get("headless", True)
    already_count = get_today_reply_count()
    if already_count >= reply_count:
        logger.info("今天已经成功回复 %d 条，已达到目标，自动跳过。", already_count)
        return
    remaining_count = reply_count - already_count
    logger.info("今天已记录成功回复 %d 条，本次还需要回复 %d 条。", already_count, remaining_count)

    lock = SingleInstanceLock(PATHS["lock"])
    if not lock.acquire():
        logger.warning("另一个签到进程正在运行，本次跳过")
        return

    try:
        _run_signin_locked(logger, config, reply_count, headless, already_count, remaining_count, sync_playwright)
    finally:
        lock.release()


def _run_signin_locked(logger, config, reply_count, headless, already_count, remaining_count, sync_playwright):
    """实际签到逻辑（在获取单实例锁后执行）"""
    run_start_time = time.time()
    stats = {
        "target": reply_count, "success": 0, "failed": 0,
        "unknown": 0, "skipped": 0, "ai_comments": 0,
        "template_comments": 0, "quality_scores": [], "duration_s": 0,
    }
    with sync_playwright() as p:
        browser, context = create_context(
            p, headless=headless, storage_state=str(PATHS["auth"])
        )
        try:
            page = context.new_page()

            if not check_login_status(page, logger):
                logger.error("登录状态已失效！请重新配置登录。")
                logger.error("请运行: python caimogu_signin.py --login")
                show_notification("采蘑菇签到失败", "登录状态已失效！\n\n请运行以下命令重新登录：\npython caimogu_signin.py --login")
                return

            logger.info("登录状态有效")

            posts = get_post_list(page, config, remaining_count, logger)
            if not posts:
                logger.error("未获取到帖子列表，签到失败")
                show_notification("采蘑菇签到失败", "未获取到帖子列表，可能是网络问题或页面结构变化。")
                return

            success_count = already_count
            replied_ids = set(get_today_replied_ids())
            replied_history = get_replied_history()
            unknown_posts = get_unknown_posts()
            auth_expired = False
            for i, post in enumerate(posts):
                if success_count >= reply_count:
                    break

                # 帖子 ID 统一规范化
                post_id = normalize_post_id(post["url"])

                # 跳过今天已回复过的帖子（防止中断后重复回复）
                if post_id in replied_ids:
                    logger.info("跳过今天已回复的帖子: %s", post["title"])
                    continue

                # 跳过30天内已回复过的帖子（防止跨天重复回复）
                if post_id in replied_history:
                    logger.info("跳过近期已回复的帖子: %s", post["title"])
                    continue

                logger.info("--- 扫描候选帖 %d，目标进度 %d/%d ---",
                            i + 1, success_count, reply_count)
                logger.info("标题: %s", post["title"])

                # UNKNOWN 恢复：上次提交状态未知，先检查评论是否已存在
                if post_id in unknown_posts:
                    expected = unknown_posts[post_id].get("comment", "")
                    logger.info("发现上次 UNKNOWN 记录，检查评论是否已存在")
                    timeout = config.get("page_timeout_ms", 90000)
                    goto_with_retry(page, post["url"], logger, timeout=timeout)
                    page.wait_for_timeout(3000)
                    verify_result = verify_existing_comment(page, expected, logger)
                    if verify_result is True:
                        logger.info("[POST %s] VERIFIED - 确认上次 UNKNOWN 评论已存在", post_id)
                        success_count += 1
                        stats["success"] += 1
                        mark_today_progress(success_count, reply_count, post_id, result=True)
                        record_post_execution(post_id, post["title"][:80], "VERIFIED",
                                               comment=expected, verification="existing_comment")
                        replied_ids.add(post_id)
                        replied_history.add(post_id)
                        unknown_posts.pop(post_id, None)
                        if success_count < reply_count:
                            mean = (config["min_delay"] + config["max_delay"]) / 2
                            std = (config["max_delay"] - config["min_delay"]) / 4
                            delay = max(config["min_delay"], min(config["max_delay"], int(random.gauss(mean, std))))
                            logger.info("等待 %d 秒...", delay)
                            time.sleep(delay)
                        continue
                    elif verify_result is False:
                        logger.info("上次 UNKNOWN 评论确认不存在，尝试重新回复: %s", post["title"])
                        unknown_posts.pop(post_id, None)
                    else:
                        logger.info("上次 UNKNOWN 评论无法检测，跳过避免重复提交: %s", post["title"])
                        stats["skipped"] += 1
                        continue

                result, reply_comment, meta = reply_to_post(page, post["url"], config, logger, post_id=post_id)

                if result == "AUTH_EXPIRED":
                    logger.error("登录已过期，请重新运行 --login 配置登录后再次签到")
                    auth_expired = True
                    break
                elif result == "SUCCESS":
                    success_count += 1
                    stats["success"] += 1
                    if meta.get("comment_source") == "ai":
                        stats["ai_comments"] += 1
                    else:
                        stats["template_comments"] += 1
                    if meta.get("quality_score"):
                        stats["quality_scores"].append(meta["quality_score"])
                    logger.info("回复成功 (%d/%d)", success_count, reply_count)
                    mark_today_progress(success_count, reply_count, post_id, result=True)
                    replied_ids.add(post_id)
                    replied_history.add(post_id)
                    unknown_posts.pop(post_id, None)
                    if success_count < reply_count:
                        # 正态分布延迟，比均匀随机更像真人行为
                        mean = (config["min_delay"] + config["max_delay"]) / 2
                        std = (config["max_delay"] - config["min_delay"]) / 4
                        delay = max(config["min_delay"], min(config["max_delay"], int(random.gauss(mean, std))))
                        logger.info("等待 %d 秒...", delay)
                        time.sleep(delay)
                elif result == "UNKNOWN":
                    # 状态未知：记录但不计入成功，不重复提交
                    stats["unknown"] += 1
                    if meta.get("quality_score"):
                        stats["quality_scores"].append(meta["quality_score"])
                    logger.warning("回复状态未知，已记录待人工复核")
                    mark_today_progress(success_count, reply_count, post_id, result=None, comment=reply_comment)
                    unknown_posts[post_id] = {
                        "date": date.today().isoformat(),
                        "comment": reply_comment or "",
                        "status": "pending_review",
                    }
                    if success_count < reply_count:
                        mean = (config["min_delay"] + config["max_delay"]) / 2
                        std = (config["max_delay"] - config["min_delay"]) / 4
                        delay = max(config["min_delay"], min(config["max_delay"], int(random.gauss(mean, std))))
                        logger.info("等待 %d 秒...", delay)
                        time.sleep(delay)
                else:
                    stats["failed"] += 1
                    if meta.get("error") == "editor_not_found":
                        stats["skipped"] += 1
                    logger.warning("回复失败，尝试下一个帖子")
                    # 检查页面是否崩溃，若崩溃则创建新页面
                    try:
                        page.evaluate("1")
                    except Exception:
                        logger.warning("页面已崩溃，创建新页面继续")
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = context.new_page()
                    time.sleep(3)

            logger.info("=" * 50)
            logger.info("签到完成！今天累计成功回复 %d/%d 个帖子", success_count, reply_count)
            logger.info("=" * 50)

            # V3.2 生成每日报告
            stats["duration_s"] = time.time() - run_start_time
            stats["success"] = success_count
            generate_daily_report(logger, stats)

            if success_count >= reply_count:
                mark_done_today(success_count)
            else:
                # 签到未完成，弹窗提醒用户
                if auth_expired:
                    show_notification(
                        "采蘑菇签到失败 - 登录已过期",
                        "登录令牌已过期，签到中止。\n\n请运行以下命令重新登录：\npython caimogu_signin.py --login"
                    )
                else:
                    show_notification(
                        "采蘑菇签到未完成",
                        f"今天仅成功回复 {success_count}/{reply_count} 个帖子。\n\n请查看签到日志了解详情：\n{PATHS['log']}"
                    )

        except Exception as e:
            logger.error("签到过程出错: %s", e)
            show_notification("采蘑菇签到出错", f"签到过程发生异常：{e}\n\n请查看签到日志了解详情：\n{PATHS['log']}")
        finally:
            # 保存浏览器状态（可能包含服务器刷新的 cookie，延长登录有效期）
            try:
                context.storage_state(path=str(PATHS["auth"]))
                logger.info("已更新登录状态文件")
            except Exception as e:
                logger.warning("保存登录状态失败: %s", e)
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
        ("爆料：《GTA6》可能延期至2026年发售", "据业内人士透露，Rockstar内部开发进度不及预期。"),
        ("《黑神话悟空》海外销量突破千万套", "发售首月海外销量已突破1000万套，成绩远超预期。"),
        ("每日签到", "如题"),
    ]

    for i, (title, content) in enumerate(test_posts):
        keyword = extract_keyword(title)
        decision = judge_replyability(title, content)
        logger.info("-" * 40)
        logger.info("标题: %s", title)
        logger.info("正文: %s", content)
        comment = generate_comment(title, content, config)
        char_count = _comment_len(comment)
        logger.info("判断: %s", decision)
        logger.info("关键词: %s", keyword)
        if comment == "SKIP":
            logger.info("结果: SKIP")
        else:
            source = "AI" if config.get("deepseek_api_key") else "模板"
            score, detail = score_comment_quality(comment, title, content)
            logger.info("评论: %s (%d字) [%s]", comment, char_count, source)
            logger.info("质量评分: %d/100 (%s)", score, detail)
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
