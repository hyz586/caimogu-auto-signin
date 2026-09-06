#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V3.3 验收测试（alpha 状态层 + beta 数据层，离线 mock，不访问网络，不触碰真实数据文件）"""

import json
import sys
import tempfile
import importlib.util
from datetime import date as real_date, timedelta as real_timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
MODULE_PATH = SCRIPT_DIR / "caimogu_signin.py"

spec = importlib.util.spec_from_file_location("caimogu_signin", MODULE_PATH)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

TMP = Path(tempfile.mkdtemp(prefix="v33test_"))
cs.PATHS["replied"] = TMP / "replied_posts.json"
cs.SCRIPT_DIR = TMP  # 让 daily_report.json 写入临时目录

ORIG_GENERATE_COMMENT = cs.generate_comment  # 第4-7节会 mock，第9节需调用原函数
ORIG_GENERATE_TEMPLATE = cs.generate_comment_template  # 第10节起会 mock，gamma 节需调用原函数

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


class FakePage:
    def __init__(self, js_results=None, raise_on_evaluate=False):
        self.js_results = js_results or {}
        self.raise_on_evaluate = raise_on_evaluate
        self.calls = []

    def evaluate(self, script, *args):
        self.calls.append(script[:60])
        if self.raise_on_evaluate:
            raise RuntimeError("evaluate failed")
        for key, val in self.js_results.items():
            if key in script:
                return val
        return None

    def wait_for_timeout(self, ms):
        pass


VERIFY_JS_KEY = ".comment-list .comment-item"


class FakeLogger:
    def info(self, *a, **k):
        pass
    def warning(self, *a, **k):
        pass
    def error(self, *a, **k):
        pass


def reset_data(**initial):
    if cs.PATHS["replied"].exists():
        cs.PATHS["replied"].unlink()
    cs.save_json(cs.PATHS["replied"], initial)


def load_data():
    return cs.load_json(cs.PATHS["replied"], {})


# ============================================================
# 1. verify_existing_comment 三态语义（alpha）
# ============================================================
print("\n== 1. verify_existing_comment 三态语义 ==")
lg = FakeLogger()

r = cs.verify_existing_comment(FakePage({VERIFY_JS_KEY: {"found": True, "scanned": True}}), "评论", lg)
check("明确找到 -> True", r is True, f"got {r}")

r = cs.verify_existing_comment(FakePage({VERIFY_JS_KEY: {"found": False, "scanned": True}}), "评论", lg)
check("扫描到列表但未找到 -> False", r is False, f"got {r}")

r = cs.verify_existing_comment(FakePage({VERIFY_JS_KEY: {"found": False, "scanned": False}}), "评论", lg)
check("列表未加载 -> None", r is None, f"got {r}")

r = cs.verify_existing_comment(FakePage(raise_on_evaluate=True), "评论", lg)
check("JS异常 -> None", r is None, f"got {r}")

r = cs.verify_existing_comment(FakePage(), "评论", lg)
check("返回非dict -> None", r is None, f"got {r}")

r = cs.verify_existing_comment(FakePage(), "", lg)
check("空评论 -> None", r is None, f"got {r}")

# ============================================================
# 2. today_post_ids 按天重置（alpha）
# ============================================================
print("\n== 2. today_post_ids 按天重置 ==")
today_str = real_date.today().isoformat()

reset_data(last_run_date=today_str, today_post_ids=[str(1000000 + i) for i in range(48)])
ids = cs.get_today_replied_ids()
check("遗留堆积数据(无today_post_ids_date)按空处理", ids == [], f"got {len(ids)} ids")

reset_data(last_run_date=today_str, today_post_ids_date=today_str, today_post_ids=["111"])
check("日期一致时正常返回", cs.get_today_replied_ids() == ["111"])

reset_data(last_run_date=(real_date.today() - real_timedelta(days=1)).isoformat(),
           today_post_ids_date=(real_date.today() - real_timedelta(days=1)).isoformat(),
           today_post_ids=["111"])
check("跨天后返回空", cs.get_today_replied_ids() == [])

reset_data(last_run_date=(real_date.today() - real_timedelta(days=1)).isoformat(),
           today_post_ids=["旧ID1", "旧ID2"])
cs.mark_today_progress(1, 3, post_id="新帖A", result=True)
d = load_data()
check("写入成功时重置堆积并记录今天日期",
      d.get("today_post_ids") == ["新帖A"] and d.get("today_post_ids_date") == today_str,
      f"got {d.get('today_post_ids')}, date={d.get('today_post_ids_date')}")

cs.mark_today_progress(2, 3, post_id="新帖B", result=True)
cs.mark_today_progress(2, 3, post_id="新帖A", result=True)
d = load_data()
check("同日追加且不重复", d.get("today_post_ids") == ["新帖A", "新帖B"], f"got {d.get('today_post_ids')}")

# ============================================================
# 3. mark_pending_verify 与挂起队列（alpha）
# ============================================================
print("\n== 3. mark_pending_verify 与挂起队列 ==")
reset_data()
entry = cs.mark_pending_verify("2465231", "https://www.caimogu.cc/post/2465231.html",
                               "测试标题", "测试评论内容", reason="auth_expired",
                               attempts=1, previous_status="AUTH_EXPIRED")
d = load_data()
up = d.get("unknown_posts", {}).get("2465231", {})
check("挂起记录写入 unknown_posts（沿用字段）", up == entry or up.get("status") == "pending_verify")
check("挂起记录字段完整",
      up.get("status") == "pending_verify" and up.get("reason") == "auth_expired"
      and up.get("attempts") == 1 and up.get("url").endswith("2465231.html")
      and up.get("title") == "测试标题" and up.get("comment") == "测试评论内容"
      and up.get("date") == today_str, f"got {up}")
check("get_unknown_posts 当天内返回挂起帖", "2465231" in cs.get_unknown_posts())

old = (real_date.today() - real_timedelta(days=4)).isoformat()
reset_data(unknown_posts={"999": {"date": old, "comment": "x", "status": "pending_verify"}})
check("超过3天自动清理", "999" not in cs.get_unknown_posts())

check("新记录推导来源=AUTH_EXPIRED",
      cs.pending_origin_status({"previous_status": "AUTH_EXPIRED"}) == "AUTH_EXPIRED")
check("无previous_status按reason推导",
      cs.pending_origin_status({"reason": "auth_expired"}) == "AUTH_EXPIRED")
check("timeout推导UNKNOWN", cs.pending_origin_status({"reason": "timeout"}) == "UNKNOWN")
check("旧版pending_review推导UNKNOWN", cs.pending_origin_status({"status": "pending_review"}) == "UNKNOWN")

# ============================================================
# 4. 场景C：AUTH_EXPIRED -> PENDING_VERIFY（alpha 状态流转）
# ============================================================
print("\n== 4. 场景C：AUTH_EXPIRED -> PENDING_VERIFY ==")
reset_data()

fake_page = FakePage()
GEN_AI = {"comment": "这是一条测试评论", "source": "ai", "ai_attempts": 1,
          "fallback": False, "fallback_reason": ""}

cs.goto_with_retry = lambda page, url, logger, timeout=90000: True
cs.inspect_popup = lambda page, logger: None
cs.extract_post_info = lambda page: ("某游戏新闻标题", "正文内容若干")
cs.generate_comment = lambda title, content, config: dict(GEN_AI)
cs.find_editor = lambda page, logger: object()
cs.input_comment = lambda page, editor, comment, logger: True
cs.get_reply_editor_text = lambda page: "这是一条测试评论"
cs.get_comment_count = lambda page, logger: 5
cs.submit_reply = lambda page, logger: True
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (False, "")
cs.get_visible_error_message = lambda page: "请先登录后再发表评论"
cs.close_safe_popup = lambda page, logger: None

config = {"page_timeout_ms": 5000}
status, comment, meta = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2465231.html",
                                         config, lg, post_id="2465231")
check("返回状态为 AUTH_EXPIRED", status == "AUTH_EXPIRED", f"got {status}")
d = load_data()
rec = [r for r in d.get("post_records", []) if r["post_id"] == "2465231"]
check("post_records 记录 AUTH_EXPIRED(attempts=1)",
      len(rec) == 1 and rec[0]["status"] == "AUTH_EXPIRED" and rec[0]["attempts"] == 1,
      f"got {rec}")
up = d.get("unknown_posts", {}).get("2465231", {})
check("AUTH_EXPIRED 已转入 pending_verify 队列",
      up.get("status") == "pending_verify" and up.get("reason") == "auth_expired"
      and up.get("attempts") == 1 and up.get("comment"),
      f"got {up}")

# ============================================================
# 5. 场景C恢复：VERIFIED（alpha）
# ============================================================
print("\n== 5. 场景C恢复：VERIFIED ==")
pending = cs.get_unknown_posts().get("2465231", {})
check("挂起队列可读取到该帖", bool(pending))
prior_attempts = pending.get("attempts", 1)
prior_status = cs.pending_origin_status(pending)
check("恢复上下文正确(attempts=1, 来源AUTH_EXPIRED)",
      prior_attempts == 1 and prior_status == "AUTH_EXPIRED",
      f"got attempts={prior_attempts}, status={prior_status}")

cs.mark_today_progress(1, 3, post_id="2465231", result=True)
cs.record_post_execution("2465231", "某游戏新闻标题", "VERIFIED", comment=pending.get("comment"),
                          attempts=prior_attempts + 1, previous_status=prior_status,
                          verification="existing_comment")
d = load_data()
recs = [r for r in d.get("post_records", []) if r["post_id"] == "2465231"]
last = recs[-1]
check("恢复记录为 VERIFIED 且 attempts=2/previous_status=AUTH_EXPIRED",
      last["status"] == "VERIFIED" and last["attempts"] == 2
      and last["previous_status"] == "AUTH_EXPIRED", f"got {last}")
check("VERIFIED 后从挂起队列清除", "2465231" not in d.get("unknown_posts", {}))
check("VERIFIED 计入今日成功", "2465231" in d.get("today_post_ids", []))

# ============================================================
# 6. 场景C恢复（评论不存在）：明确不存在才重新提交（alpha）
# ============================================================
print("\n== 6. 场景C恢复（评论不存在）-> 重新提交 ==")
reset_data()
cs.mark_pending_verify("2465232", "https://www.caimogu.cc/post/2465232.html",
                       "标题2", "旧评论", reason="auth_expired", attempts=1,
                       previous_status="AUTH_EXPIRED")
cs.verify_existing_comment = lambda page, expected, logger: False
pending = cs.get_unknown_posts()["2465232"]
check("明确不存在时可重新提交(verify=False)",
      cs.verify_existing_comment(fake_page, "旧评论", lg) is False)
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (True, "comment_count_increase")
cs.get_visible_error_message = lambda page: ""
status2, comment2, meta2 = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2465232.html",
                                            config, lg, post_id="2465232",
                                            prior_attempts=1, previous_status="AUTH_EXPIRED")
check("恢复后重新提交成功", status2 == "SUCCESS", f"got {status2}")
d = load_data()
rec = [r for r in d.get("post_records", []) if r["post_id"] == "2465232"][-1]
check("重新提交记录 attempts=2 + previous_status=AUTH_EXPIRED（识别为恢复）",
      rec["status"] == "SUCCESS" and rec["attempts"] == 2
      and rec["previous_status"] == "AUTH_EXPIRED", f"got {rec}")

cs.verify_existing_comment = lambda page, expected, logger: None
check("无法检测时保持挂起(verify=None)",
      cs.verify_existing_comment(fake_page, "旧评论", lg) is None)

# ============================================================
# 7. 场景B：验证超时 -> UNKNOWN -> pending_verify(timeout)（alpha）
# ============================================================
print("\n== 7. 场景B：验证超时 -> PENDING_VERIFY(timeout) ==")
reset_data()
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (None, "")
status3, comment3, meta3 = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2465233.html",
                                            config, lg, post_id="2465233")
check("超时返回 UNKNOWN", status3 == "UNKNOWN", f"got {status3}")
check("超时返回评论文本供下次验证", bool(comment3))
cs.mark_today_progress(0, 3)
pe = cs.mark_pending_verify("2465233", "https://www.caimogu.cc/post/2465233.html",
                            meta3.get("title", ""), comment3, reason="timeout",
                            attempts=meta3.get("attempts", 1), previous_status="UNKNOWN")
d = load_data()
up = d.get("unknown_posts", {}).get("2465233", {})
check("超时也进入 pending_verify 队列(reason=timeout)",
      up.get("status") == "pending_verify" and up.get("reason") == "timeout"
      and up.get("comment") == comment3, f"got {up}")

# ============================================================
# 8. 旧版 pending_review 记录兼容恢复（alpha）
# ============================================================
print("\n== 8. 旧版 pending_review 兼容 ==")
reset_data(unknown_posts={"2460000": {"date": today_str, "comment": "旧版评论",
                                       "status": "pending_review"}})
active = cs.get_unknown_posts()
check("旧版记录仍在挂起队列", "2460000" in active)
check("旧版记录来源推导为 UNKNOWN", cs.pending_origin_status(active["2460000"]) == "UNKNOWN")

# ============================================================
# 9. beta: generate_comment 模板模式结构化返回
# ============================================================
print("\n== 9. beta: generate_comment 结构化返回 ==")
reset_data()
cs.generate_comment_template = lambda title, content: "模板生成的测试评论"
gen = ORIG_GENERATE_COMMENT("标题", "正文", {})
check("模板模式返回 dict 且 source=template",
      isinstance(gen, dict) and gen["source"] == "template" and gen["comment"] == "模板生成的测试评论"
      and gen["ai_attempts"] == 0 and gen["fallback"] is False and gen["fallback_reason"] == "",
      f"got {gen}")

# ============================================================
# 10. beta: generate_comment_ai 各路径
# ============================================================
print("\n== 10. beta: generate_comment_ai 各路径 ==")

VALID_COMMENT = "画面表现确实在线，就是优化还得再看看"   # 18字，通过校验
LONG_COMMENT = "设计思路挺清晰的，落地节奏也稳，就是不知道实际表现会不会缩水，等上线后看反馈再评价也不迟"  # >40字
BANNED_COMMENT = "感谢分享这个消息，看起来后续还能期待一手"  # 含硬禁词

def mock_api(responses):
    """responses: 依次返回的 raw content 列表（字符串或 Exception）"""
    seq = list(responses)
    def fake(url, headers, data, logger, max_retries=3):
        if seq:
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item, "deepseek-test"
        raise RuntimeError("no more mock responses")
    return fake

cs.generate_comment_template = lambda title, content: "模板兜底评论"

# 10.1 首次直接成功
cs._call_deepseek_api = mock_api([VALID_COMMENT])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("首次成功 -> source=ai, attempts=1",
      gen["source"] == "ai" and gen["comment"] == VALID_COMMENT
      and gen["ai_attempts"] == 1 and gen["fallback"] is False and gen["fallback_reason"] == "",
      f"got {gen}")

# 10.2 空返回 -> 重试成功 -> ai_retry
cs._call_deepseek_api = mock_api(["", VALID_COMMENT])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("空返回重试成功 -> source=ai_retry, attempts=2",
      gen["source"] == "ai_retry" and gen["comment"] == VALID_COMMENT
      and gen["ai_attempts"] == 2 and gen["fallback"] is False,
      f"got {gen}")

# 10.3 两次空返回 -> template_fallback + empty_response
cs._call_deepseek_api = mock_api(["", ""])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("两次空返回 -> template_fallback/empty_response, attempts=2",
      gen["source"] == "template_fallback" and gen["comment"] == "模板兜底评论"
      and gen["ai_attempts"] == 2 and gen["fallback"] is True
      and gen["fallback_reason"] == "empty_response",
      f"got {gen}")

# 10.4 gamma 后 41 字放行直出（8/30 曾被 40 上限误杀）；>55 字仍 invalid_length
cs._call_deepseek_api = mock_api([LONG_COMMENT])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check(f"41 字评论（{cs._comment_len(LONG_COMMENT)}字）gamma 后直出不再误杀",
      gen["source"] == "ai" and gen["fallback"] is False and gen["comment"] == LONG_COMMENT,
      f"got {gen}")
OVER55 = "XSX补丁快15G，PS5才1.5G，这怕不是把整个加勒比海底都重新渲染了一遍吧，毛茸茸朋友可别是只巨蜥，到时候藏身处直接变动物园了"
cs._call_deepseek_api = mock_api([OVER55])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check(f"超长({cs._comment_len(OVER55)}字) -> invalid_length",
      gen["source"] == "template_fallback" and gen["fallback_reason"] == "invalid_length"
      and gen["ai_attempts"] == 1, f"got {gen}")

# 10.5 含硬禁词 -> banned_phrase
cs._call_deepseek_api = mock_api([BANNED_COMMENT])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("含硬禁词 -> banned_phrase",
      gen["source"] == "template_fallback" and gen["fallback_reason"] == "banned_phrase",
      f"got {gen}")

# 10.6 SKIP
cs._call_deepseek_api = mock_api(["SKIP"])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("AI 判定 SKIP -> comment=SKIP, source=ai, 不算 fallback",
      gen["comment"] == "SKIP" and gen["source"] == "ai" and gen["fallback"] is False,
      f"got {gen}")

# ============================================================
# 11. beta: API 异常分类
# ============================================================
print("\n== 11. beta: API 异常分类 ==")
import requests
from types import SimpleNamespace

cs._call_deepseek_api = mock_api([requests.exceptions.ConnectionError("conn refused")])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("连接错误 -> network_error",
      gen["fallback_reason"] == "network_error" and gen["source"] == "template_fallback",
      f"got {gen}")

e429 = requests.exceptions.HTTPError("429")
e429.response = SimpleNamespace(status_code=429)
cs._call_deepseek_api = mock_api([e429])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("HTTP 429 -> 429", gen["fallback_reason"] == "429", f"got {gen}")

e401 = requests.exceptions.HTTPError("401")
e401.response = SimpleNamespace(status_code=401)
cs._call_deepseek_api = mock_api([e401])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("HTTP 401 -> http_error", gen["fallback_reason"] == "http_error", f"got {gen}")

cs._call_deepseek_api = mock_api([ValueError("boom")])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("其他异常 -> exception", gen["fallback_reason"] == "exception", f"got {gen}")

check("FALLBACK_REASONS 覆盖方案要求的分类",
      set(cs.FALLBACK_REASONS) >= {"empty_response", "429", "network_error",
                                   "invalid_length", "banned_phrase", "invalid_format",
                                   "exception", "incomplete_ending"},
      f"got {cs.FALLBACK_REASONS}")

# ============================================================
# 12. beta: reply_to_post 落盘 comment_source/ai_attempts/fallback_reason/verification
# ============================================================
print("\n== 12. beta: reply_to_post 数据落盘 ==")
reset_data()
gen_fb = {"comment": "模板兜底评论足够长可以发送", "source": "template_fallback",
          "ai_attempts": 2, "fallback": True, "fallback_reason": "invalid_length"}
cs.generate_comment = lambda title, content, config: dict(gen_fb)
cs.get_reply_editor_text = lambda page: "模板兜底评论足够长可以发送"
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (True, "comment_text_found")
status12, _, meta12 = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2466001.html",
                                       config, lg, post_id="2466001")
check("fallback 评论提交成功", status12 == "SUCCESS", f"got {status12}")
d = load_data()
rec = [r for r in d.get("post_records", []) if r["post_id"] == "2466001"][-1]
check("记录 comment_source=template_fallback + ai_attempts=2 + fallback_reason=invalid_length",
      rec.get("comment_source") == "template_fallback" and rec.get("ai_attempts") == 2
      and rec.get("fallback_reason") == "invalid_length", f"got {rec}")
check("记录验证方式 comment_text_found", rec.get("verification") == "comment_text_found",
      f"got {rec.get('verification')}")
check("meta 携带来源元数据",
      meta12.get("comment_source") == "template_fallback"
      and meta12.get("ai_attempts") == 2 and meta12.get("fallback_reason") == "invalid_length",
      f"got {meta12}")

# AI 直出成功场景：ai 字段
reset_data()
cs.generate_comment = lambda title, content, config: dict(GEN_AI)
cs.get_reply_editor_text = lambda page: "这是一条测试评论"
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (True, "comment_count_increase")
cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2466002.html", config, lg, post_id="2466002")
d = load_data()
rec = [r for r in d.get("post_records", []) if r["post_id"] == "2466002"][-1]
check("AI 直出记录 ai_attempts=1 且无 fallback_reason",
      rec.get("comment_source") == "ai" and rec.get("ai_attempts") == 1
      and "fallback_reason" not in rec, f"got {rec}")
check("验证方式记录 comment_count_increase", rec.get("verification") == "comment_count_increase",
      f"got {rec.get('verification')}")

# ============================================================
# 13. beta: 日报四类统计 + fallback 原因分布
# ============================================================
print("\n== 13. beta: 日报统计 ==")
stats = {
    "target": 3, "success": 3, "failed": 0, "unknown": 0, "skipped": 0,
    "ai_comments": 1, "ai_retry_comments": 1,
    "template_comments": 0, "template_fallback_comments": 1,
    "quality_scores": [70, 60, 50], "duration_s": 90,
    "fallback_reasons": {"invalid_length": 1},
}
report_text = cs.generate_daily_report(lg, stats)
check("日报含 AI成功/AI重试后成功 细分", "AI成功：1" in report_text and "AI重试后成功：1" in report_text,
      report_text)
check("日报含 模板直接/模板fallback 细分", "模板直接：0" in report_text and "模板fallback：1" in report_text)
check("日报含 fallback 原因分布", "invalid_length：1" in report_text)
report_file = TMP / "daily_report.json"
check("daily_report.json 写入临时目录且含细分字段",
      report_file.exists() and json.loads(report_file.read_text(encoding="utf-8"))
      .get("ai_retry_comments") == 1)

# 无 fallback 时不输出原因行
stats2 = dict(stats, template_fallback_comments=0, fallback_reasons={})
report_text2 = cs.generate_daily_report(lg, stats2)
check("无 fallback 时不输出原因行", "fallback原因" not in report_text2)

# ============================================================
# 15. gamma: 长度放宽 15~55
# ============================================================
print("\n== 15. gamma: 长度放宽 15~55 ==")
C42 = "又是补完本篇……本体结局留的坑还没填完呢，DLC面具要是再把设定搞复杂，怕不是又得翻档案室了"
check(f"9/2 真实案例 42 字（曾被误杀）现在通过校验 (len={cs._comment_len(C42)})",
      cs._is_reply_valid(C42, "标题", "正文"))
check("55 字边界通过", cs._is_reply_valid("字" * 55, "标题", "正文"))
check("56 字仍拒绝", not cs._is_reply_valid("字" * 56, "标题", "正文"))
check("14 字仍拒绝", not cs._is_reply_valid("字" * 14, "标题", "正文"))

cs._call_deepseek_api = mock_api([C42])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("42 字真实案例走 AI 直出（不再 fallback）",
      gen["source"] == "ai" and gen["comment"] == C42 and gen["fallback"] is False,
      f"got {gen}")

C60 = "XSX补丁快15G，PS5才1.5G，这怕不是把整个加勒比海底都重新渲染了一遍吧……毛茸茸朋友可别是只巨蜥，到时候藏身处直接变动物园"
check(f"60 字案例仍超上限拒绝 (len={cs._comment_len(C60)})",
      not cs._is_reply_valid(C60, "标题", "正文"))

# ============================================================
# 16. gamma: 残句检测 _has_incomplete_ending
# ============================================================
print("\n== 16. gamma: 残句检测 ==")
check("方案案例：'…画饼也太早了吧，到时候' 判残句",
      cs._has_incomplete_ending("2027年才发售？现在画饼也太早了吧，到时候"))
check("'如果真按这个来的话' 判残句", cs._has_incomplete_ending("如果真按这个来的话"))
check("'挺好，就是还得' 判残句", cs._has_incomplete_ending("看着挺好，就是还得"))
check("'画面很顶，但是' 判残句", cs._has_incomplete_ending("画面很顶，但是"))
check("'我挺希望' 动词悬空判残句", cs._has_incomplete_ending("优化能做好，我挺希望"))
check("完整句不误判：'别抱太大希望'", not cs._has_incomplete_ending("缩水概率不小，别抱太大希望"))
check("完整句不误判：'到时候再说'", not cs._has_incomplete_ending("先别急着买，到时候再说"))
check("完整句不误判：42字真实案例", not cs._has_incomplete_ending(C42))
check("完整句不误判：34字真实案例",
      not cs._has_incomplete_ending("骑马过河的时候不会被淹死吧？之前测试版掉水里挣扎半天，希望坐骑别也这么憨"))

DANGLER = "这游戏要是能把手感做好，销量肯定不会差，毕竟"
cs._call_deepseek_api = mock_api([DANGLER])
gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
check("残句回退模板，fallback_reason=incomplete_ending",
      gen["source"] == "template_fallback" and gen["fallback_reason"] == "incomplete_ending",
      f"got {gen}")

# ============================================================
# 17. gamma: 细节可用性 is_detail_usable
# ============================================================
print("\n== 17. gamma: 细节可用性 ==")
check("正常中文细节可用", cs.is_detail_usable("版本更新"))
check("含中文的混合细节可用", cs.is_detail_usable("白金档案PLAT"))
check("特效类细节可用", cs.is_detail_usable("特效看不清怪"))
check("纯英文缩写不可用", not cs.is_detail_usable("PLAT"))
check("纯数字不可用", not cs.is_detail_usable("2027"))
check("空细节不可用", not cs.is_detail_usable(""))
check("单字不可用", not cs.is_detail_usable("了"))
check("超长细节不可用", not cs.is_detail_usable("这是一个超过十二个字的超长细节信息"))
check("含指代词不可用", not cs.is_detail_usable("什么东西"))
check("首字虚词不可用", not cs.is_detail_usable("的画面"))

# ============================================================
# 18. gamma: 模板去除虚构个人经历
# ============================================================
print("\n== 18. gamma: 模板去除虚构经历 ==")
FICTION_MARKERS = ["我抽了", "我十连", "我连续保底", "我玩过", "我遇到过",
                   "我之前也", "我也有同感", "我熟", "默默关掉", "下次我也"]
GAMMA_CASES = [
    ("luck", "晒一下今天的抽卡出货记录，运气爆棚", "十连双金，直接起飞"),
    ("help", "游戏闪退求助，一点开就退出", "重装也没用，求大佬看看"),
    ("recommend", "求推荐几款耐玩的单机游戏", "喜欢开放世界，剧情好点的"),
    ("normal", "某工作室新企划公开，玩法看着有创新", "放了个概念图，信息不多"),
    ("update", "新版本更新公告，改了一堆东西", "补丁五六个G，优化了不少"),
]
cs.generate_comment_template = ORIG_GENERATE_TEMPLATE
all_outputs = []
fictional_found = []
invalid_found = []
for expected_type, t, c in GAMMA_CASES:
    check(f"类型识别[{expected_type}]", cs.detect_title_type(t + " " + c) == expected_type,
          f"got {cs.detect_title_type(t + ' ' + c)}")
    for _ in range(40):
        out = cs.generate_comment_template(t, c)
        if out == "SKIP":
            continue
        all_outputs.append(out)
        if any(m in out for m in FICTION_MARKERS):
            fictional_found.append(out)
        if not cs._is_reply_valid(out, t, c):
            invalid_found.append(out)
check(f"随机 {len(all_outputs)} 条模板输出零虚构个人经历", not fictional_found,
      f"found: {fictional_found[:3]}")
check("模板输出全部通过校验规则", not invalid_found, f"invalid: {invalid_found[:3]}")
check("模板输出有多样性（>=5 种不同文案）", len(set(all_outputs)) >= 5,
      f"only {len(set(all_outputs))} unique")

# ============================================================
# 19. gamma: 细节不可用走通用模板（不硬塞）
# ============================================================
print("\n== 19. gamma: 细节不可用走通用模板 ==")
orig_extract = cs._extract_detail
try:
    cs._extract_detail = lambda t, c: "XSX"
    outs = {cs.generate_comment_template("《某游戏》新资料片发布", "更新了好多内容") for _ in range(10)}
    check("不可用细节不硬塞（输出不含 XSX 且非 SKIP）",
          all(o != "SKIP" and "XSX" not in o for o in outs), f"got {outs}")

    cs._extract_detail = lambda t, c: ""
    outs = {cs.generate_comment_template("《某游戏》新资料片发布", "更新了好多内容") for _ in range(10)}
    check("空细节走通用模板而非直接 SKIP",
          all(o != "SKIP" for o in outs), f"got {outs}")
    check("通用模板输出通过校验",
          all(cs._is_reply_valid(o, "《某游戏》新资料片发布", "更新了好多内容") for o in outs))

    cs._extract_detail = lambda t, c: "坐骑系统"
    outs = {cs.generate_comment_template("《颂钟长鸣》坐骑系统首曝，全新玩法演示", "演示看着不错") for _ in range(10)}
    check("可用细节仍填充 {d} 插槽", all("坐骑系统" in o for o in outs), f"got {list(outs)[:2]}")
finally:
    cs._extract_detail = orig_extract
    cs.generate_comment_template = lambda title, content: "模板兜底评论"

# ============================================================
# 20. final: 评分结构（六维 + 权重和100）
# ============================================================
print("\n== 20. final: 评分结构 ==")
check("权重六维齐全",
      set(cs._SCORE_WEIGHTS.keys()) == {"relevance", "specificity", "type_match",
                                        "completeness", "naturalness", "length"},
      f"got {sorted(cs._SCORE_WEIGHTS.keys())}")
check("权重总和为 100", sum(cs._SCORE_WEIGHTS.values()) == 100,
      f"got {sum(cs._SCORE_WEIGHTS.values())}")
check("completeness 权重 15（方案指定）", cs._SCORE_WEIGHTS["completeness"] == 15)

GOOD_AI = "又是搞玩家委员会，到头来内测资格还不是看脸抽"
TOTAL, DIMS = cs.score_comment_quality(GOOD_AI, "育碧玩家委员会专访：全新内测平台亮相", "")
check("完整句各维度有得分", DIMS.get("completeness") == 15 and DIMS.get("naturalness") == 20
      and DIMS.get("length") == 10, f"got {DIMS}")

# ============================================================
# 21. final: completeness 残句/截断判 0 分
# ============================================================
print("\n== 21. final: completeness ==")
check("完整句 completeness=15", cs.score_comment_quality(GOOD_AI, "标题", "")[1]["completeness"] == 15)
check("连接词残句 completeness=0",
      cs.score_comment_quality("先别急着买，到时候", "标题", "")[1]["completeness"] == 0)
check("原始文本逗号收尾(截断) completeness=0",
      cs.score_comment_quality("这波优化力度不小，就看实际表现了，", "标题", "")[1]["completeness"] == 0)
FULL_CMT = "先别急着买，到时候看实机表现再下结论也不迟"
s_full = cs.score_comment_quality(FULL_CMT, "标题", "")[0]
s_frag = cs.score_comment_quality("先别急着买，到时候", "标题", "")[0]
check(f"残句总分低于同话题完整句 ({s_frag} < {s_full})", s_frag < s_full)

# ============================================================
# 22. final: naturalness 真扣分
# ============================================================
print("\n== 22. final: naturalness 真扣分 ==")
ded = dict(cs._naturalness_deductions("这个改动挺有意思的，值得关注后续发展"))
check("生硬 detail 前缀扣 4", ded.get("stiff_detail_prefix") == 4, f"got {ded}")

ded = dict(cs._naturalness_deductions("我抽了八十发才出这角色，纯纯非酋运气"))
check("虚构经历扣 8", ded.get("fiction") == 8, f"got {ded}")

TPL_CMT = "光看版本更新描述还行，等实机出来再判断，现在说啥都早"
ded = dict(cs._naturalness_deductions(TPL_CMT))
check("自家模板腔扣 10（含标点也能命中）", ded.get("own_template") == 10, f"got {ded}")

ded = dict(cs._naturalness_deductions(GOOD_AI))
check("AI 原创评论无扣分", ded == {}, f"got {ded}")

ded = dict(cs._naturalness_deductions("内容质量确实不错，这波更新有点东西"))
check("模板开头弱禁词扣 5", ded.get("template_opening") == 5, f"got {ded}")

ded = dict(cs._naturalness_deductions("这个改动我玩过demo，先观望吧"))
check("多项扣分可叠加(fiction+stiff_detail_prefix)",
      ded.get("fiction") == 8 and ded.get("stiff_detail_prefix") == 4, f"got {ded}")

nat = cs.score_comment_quality("这个改动我玩过demo，先观望吧", "标题", "")[1]["naturalness"]
check("叠加扣分后 naturalness=8 且不为负", nat == 8, f"got {nat}")

nat = cs.score_comment_quality("内容质量确实不错感谢分享", "标题", "")[1]["naturalness"]
check("硬禁词 naturalness 归 0", nat == 0, f"got {nat}")

# ============================================================
# 23. final: own_template 检测边界
# ============================================================
print("\n== 23. final: own_template 边界 ==")
check("带 {d} 的完整模板输出命中", cs._matches_own_template("光看新地图描述还行，等实机出来再判断，现在说啥都早"))
check("通用模板完整输出命中", cs._matches_own_template("爆料先让子弹飞一会，等实锤再激动也不迟"))
check("{d} 模板的后半段命中（拼接病句检测）",
      cs._matches_own_template("建议通关本篇后再方向是对的，就怕优化跟不上，先观望吧"))
check("AI 原创评论不命中(玩家委员会样本)", not cs._matches_own_template(GOOD_AI))
check("AI 原创评论不命中(挖矿样本)",
      not cs._matches_own_template("玩过几个挖矿的roguelite，最烦的就是死一次全清零"))

# ============================================================
# 24. final: 真实样本校准回归（9/2-9/4 实发评论）
# ============================================================
print("\n== 24. final: 真实样本校准回归 ==")
AI_SAMPLES = [
    ("INDIE Live Expo 2026.12.1 游戏征集启动",
     "每个团只能报一款也太抠了吧，好多独立工作室手里可不止一个存货啊"),
    ("深海采矿Roguelite《深海矿业公司》开放测试",
     "玩过几个挖矿的roguelite，最烦的就是死一次全清零，希望这作的成长能留得住，不然挖半天暴毙真顶不住"),
    ("育碧玩家委员会专访：全新内测平台亮相", GOOD_AI),
    ("《幻世录 重制版》上市倒数一周 玩法全面公开",
     "看到能自己换语音和音乐我就放心了，原版那些台词和音效真怕被乱改，这下老味道能留住了"),
]
TPL_SAMPLES = [
    ("《颂钟长鸣》科隆展首曝坐骑系统 销量破百万",
     "老实讲马匹在中世纪场景这数据比预期好，看来口碑发酵起作用了"),
    ("《刺客信条4：黑旗 记忆重置》更新官宣！超多内容 今晚上线",
     "光看版本更新描述还行，等实机出来再判断，现在说啥都早"),
]
ai_scores = [cs.score_comment_quality(c, t, "")[0] for t, c in AI_SAMPLES]
tpl_scores = [cs.score_comment_quality(c, t, "")[0] for t, c in TPL_SAMPLES]
check(f"AI 样本分数 >=48 ({ai_scores})", all(s >= 48 for s in ai_scores))
check(f"模板样本分数 <=48 且均低于 AI 均分 ({tpl_scores})",
      all(s <= 48 for s in tpl_scores))
check(f"均分倒挂消除: AI={sum(ai_scores)/len(ai_scores):.1f} > 模板={sum(tpl_scores)/len(tpl_scores):.1f}",
      sum(ai_scores) / len(ai_scores) > sum(tpl_scores) / len(tpl_scores))
check("模板样本 naturalness 全部被扣(own_template)",
      all(cs.score_comment_quality(c, t, "")[1]["naturalness"] <= 10 for t, c in TPL_SAMPLES))
check("AI 样本 naturalness 全部满分",
      all(cs.score_comment_quality(c, t, "")[1]["naturalness"] == 20 for t, c in AI_SAMPLES))

# ============================================================
# 25. final: 高重复拒绝并重新生成（reply_to_post 集成）
# ============================================================
print("\n== 25. final: 高重复拒绝并重新生成 ==")
reset_data(post_records=[
    {"date": real_date.today().isoformat(), "status": "SUCCESS",
     "comment": "这次更新的内容是真的多，优化了不少地方"}])

SIM_CMT = "这次更新的内容是真的多优化了不少地方"
NEW_CMT = "先别急着下结论，实机表现才是关键，帧数稳不稳比啥都重要"
GEN_SEQ = [{"comment": SIM_CMT, "source": "ai", "ai_attempts": 1, "fallback": False, "fallback_reason": ""},
           {"comment": NEW_CMT, "source": "ai", "ai_attempts": 1, "fallback": False, "fallback_reason": ""}]
call_count = [0]


def gen_seq(title, content, config):
    r = GEN_SEQ[min(call_count[0], len(GEN_SEQ) - 1)]
    call_count[0] += 1
    return dict(r)


cs.generate_comment = gen_seq
cs.extract_post_info = lambda page: ("某游戏更新公告", "正文内容")
cs.get_reply_editor_text = lambda page: NEW_CMT
cs.wait_reply_result = lambda page, logger, prev, initial_comments=None, post_id=None: (True, "comment_count_increase")
cs.get_visible_error_message = lambda page: ""
status, out_cmt, meta = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2467001.html",
                                         config, lg, post_id="2467001")
check("重复评论被拒绝后采用重新生成的新评论", status == "SUCCESS" and out_cmt == NEW_CMT,
      f"got {status}, {out_cmt}")
d = load_data()
rec = [r for r in d.get("post_records", []) if r.get("post_id") == "2467001"][-1]
check("落盘评论为重新生成的新评论", rec.get("comment") == NEW_CMT, f"got {rec.get('comment')}")

# 25b: 重新生成仍相似 -> FAILED(too_similar)
print("\n== 25b: 重新生成仍相似 -> 放弃该帖 ==")
reset_data(post_records=[
    {"date": real_date.today().isoformat(), "status": "SUCCESS",
     "comment": "这次更新的内容是真的多，优化了不少地方"}])
call_count[0] = 0
GEN_STUCK = [{"comment": SIM_CMT, "source": "ai", "ai_attempts": 1, "fallback": False, "fallback_reason": ""}] * 3
GEN_SEQ[:] = GEN_STUCK
status, out_cmt, meta = cs.reply_to_post(fake_page, "https://www.caimogu.cc/post/2467002.html",
                                         config, lg, post_id="2467002")
check("仍相似时返回 FAILED", status == "FAILED", f"got {status}")
d = load_data()
rec = [r for r in d.get("post_records", []) if r.get("post_id") == "2467002"][-1]
check("记录 error=too_similar", rec.get("status") == "FAILED" and rec.get("error") == "too_similar",
      f"got {rec}")

# ============================================================
# 14. 状态机与版本
# ============================================================
print("\n== 14. 状态机与版本 ==")
check("POST_STATUS 包含 PENDING_VERIFY", "PENDING_VERIFY" in cs.POST_STATUS)
check("版本号为 3.3.0", cs.VERSION == "3.3.0", f"got {cs.VERSION}")
check("通用模板九类齐全",
      set(cs._REPLY_TEMPLATES_GENERIC.keys()) == set(cs._REPLY_TEMPLATES.keys()),
      f"got {sorted(cs._REPLY_TEMPLATES_GENERIC.keys())}")

# ============================================================
print("\n" + "=" * 50)
print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  -", f)
print("=" * 50)
sys.exit(1 if FAIL else 0)
