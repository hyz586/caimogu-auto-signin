#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V3.6.0 验收测试（离线 mock，不访问网络，不触碰真实数据文件）

覆盖：
1. 令牌本地预检 check_token_expiry_local
2. 临期弹窗提醒每天一次 maybe_remind_token_expiry
3. 429 遵守 Retry-After
4. 401/403 分类为 auth_error
5. finish_reason=length 截断重试并放大 max_tokens
6. AI 降级禁用万能模板（allow_generic=False -> SKIP）
7. 401 后本次运行禁用 AI；连续 3 次 429 后禁用 AI
"""

import json
import logging
import os
import sys
import tempfile
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).parent.absolute()
MODULE_PATH = SCRIPT_DIR / "caimogu_signin.py"

spec = importlib.util.spec_from_file_location("caimogu_signin", MODULE_PATH)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

TMP = Path(tempfile.mkdtemp(prefix="v36test_"))
for k in ("replied", "api_key_enc", "auth_enc", "auth", "config", "log", "lock"):
    cs.PATHS[k] = TMP / cs.PATHS[k].name
cs.SCRIPT_DIR = TMP

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


import requests

logger = logging.getLogger("caimogu")


def make_state(days_from_now):
    exp = (datetime.now() + timedelta(days=days_from_now)).timestamp()
    return {"cookies": [{"name": "cmg_token", "value": "x", "expires": exp}]}


# ============================================================
# 1. 令牌本地预检
# ============================================================
print("\n== 1. 令牌本地预检 ==")
st, exp = cs.check_token_expiry_local(make_state(-1))
check("过期令牌 -> expired", st == "expired" and exp is not None)
st, exp = cs.check_token_expiry_local(make_state(5))
check("有效令牌 -> ok 且带过期时间", st == "ok" and exp is not None)
st, exp = cs.check_token_expiry_local({"cookies": []})
check("无 cmg_token -> no_token", st == "no_token")
st, exp = cs.check_token_expiry_local(None)
check("空状态 -> no_token", st == "no_token")

# ============================================================
# 2. 临期提醒每天一次
# ============================================================
print("\n== 2. 临期提醒每天一次 ==")
notices = []
orig_notify = cs.show_notification
cs.show_notification = lambda t, m: notices.append((t, m))
try:
    exp2 = datetime.now() + timedelta(days=2)
    cs.maybe_remind_token_expiry(exp2, logger)
    cs.maybe_remind_token_expiry(exp2, logger)
    check("同一天只弹一次", len(notices) == 1, f"got {len(notices)}")
    data = json.loads(cs.PATHS["replied"].read_text(encoding="utf-8"))
    check("提醒日期已落盘", data.get("token_reminder_date") == cs.date.today().isoformat())
    notices.clear()
    cs.maybe_remind_token_expiry(datetime.now() + timedelta(days=5), logger)
    check("超过 2 天不提醒", len(notices) == 0)
finally:
    cs.show_notification = orig_notify

# ============================================================
# 3. 429 遵守 Retry-After
# ============================================================
print("\n== 3. 429 遵守 Retry-After ==")


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.exceptions.HTTPError(str(self.status_code))
            e.response = self
            raise e

    def json(self):
        return self._payload


orig_post = requests.post
sleeps = []
orig_sleep = cs.time.sleep
cs.time.sleep = lambda s: sleeps.append(s)
try:
    seq = [FakeResp(429, headers={"Retry-After": "7"}),
           FakeResp(200, {"model": "m", "choices": [
               {"message": {"content": "ok"}, "finish_reason": "stop"}]})]
    requests.post = lambda url, headers=None, json=None, timeout=None: seq.pop(0)
    out = cs._call_ai_api("http://x", {}, {}, logger)
    check("429 后重试成功并返回三元组", out == ("ok", "m", "stop"), f"got {out}")
    check("遵守 Retry-After=7 而非默认 2 秒", sleeps == [7], f"got {sleeps}")
finally:
    requests.post = orig_post
    cs.time.sleep = orig_sleep

# ============================================================
# 4. 401/403 分类
# ============================================================
print("\n== 4. 401/403 分类 ==")
e401 = requests.exceptions.HTTPError("401")
e401.response = SimpleNamespace(status_code=401)
check("401 -> auth_error", cs._classify_api_exception(e401) == "auth_error")
e403 = requests.exceptions.HTTPError("403")
e403.response = SimpleNamespace(status_code=403)
check("403 -> auth_error", cs._classify_api_exception(e403) == "auth_error")

# ============================================================
# 5. finish_reason=length 截断重试
# ============================================================
print("\n== 5. finish_reason=length 截断重试 ==")
VALID = "画面表现确实在线，就是优化还得再看看"
calls = []


def mock_api3(responses):
    seq = list(responses)

    def fake(url, headers, data, logger, max_retries=3):
        calls.append(data.get("max_tokens"))
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return fake


orig_call = cs._call_ai_api
orig_tpl = cs.generate_comment_template
orig_sleep2 = cs.time.sleep
cs.time.sleep = lambda s: None
cs.generate_comment_template = lambda title, content, **_kw: "模板兜底评论"
try:
    cs._call_ai_api = mock_api3([("这个游戏", "m", "length"), (VALID, "m", "stop")])
    gen = cs.generate_comment_ai("标题", "正文", "key", None, None)
    check("截断后重试成功 -> ai_retry",
          gen["source"] == "ai_retry" and gen["comment"] == VALID, f"got {gen}")
    check("截断重试放大 max_tokens 200->400", calls == [200, 400], f"got {calls}")
finally:
    cs._call_ai_api = orig_call
    cs.generate_comment_template = orig_tpl
    cs.time.sleep = orig_sleep2

# ============================================================
# 6. AI 降级禁用万能模板
# ============================================================
print("\n== 6. AI 降级禁用万能模板 ==")
RICH_TITLE = "《某游戏》更新前瞻：新系统细节不少"
RICH_CONTENT = "正文内容足够多，写了好多关于新版本的东西，包括玩法和优化的细节。"
orig_extract = cs._extract_detail
cs._extract_detail = lambda t, c: ""  # 强制无可用细节
try:
    res = cs._template_fallback_result(RICH_TITLE, RICH_CONTENT, "429", 1)
    check("无细节时 AI 回退直接 SKIP，不发万能句",
          res["comment"] == "SKIP", f"got {res['comment']}")
    gen_generic = cs.generate_comment_template(RICH_TITLE, RICH_CONTENT, allow_generic=True)
    check("纯模板模式（allow_generic=True）仍可用通用模板兜底",
          gen_generic != "SKIP", f"got {gen_generic}")
finally:
    cs._extract_detail = orig_extract

# ============================================================
# 7. 运行级 AI 禁用
# ============================================================
print("\n== 7. 运行级 AI 禁用 ==")
orig_gen_ai = cs.generate_comment_ai
notices2 = []
cs.show_notification = lambda t, m: notices2.append((t, m))
os.environ["CAIMOGU_AI_API_KEY"] = "testkey"
try:
    cs.generate_comment_ai = lambda *a, **kw: {
        "comment": "SKIP", "source": "ai", "ai_attempts": 1,
        "fallback": True, "fallback_reason": "auth_error"}
    cfg = {}
    gen1 = cs.generate_comment("标题", "正文", cfg)
    check("auth_error 透传", gen1["fallback_reason"] == "auth_error")
    check("401 置位 _ai_disabled", cfg.get("_ai_disabled") is True)
    check("401 弹窗提醒一次", len(notices2) == 1, f"got {len(notices2)}")

    ai_called = []
    cs.generate_comment_ai = lambda *a, **kw: ai_called.append(1)
    gen2 = cs.generate_comment("标题", "正文", cfg)
    check("禁用后不再调用 AI",
          ai_called == [] and gen2["source"] == "template" and gen2["fallback"] is True,
          f"got {gen2}")

    cs.generate_comment_ai = lambda *a, **kw: {
        "comment": "SKIP", "source": "ai", "ai_attempts": 1,
        "fallback": True, "fallback_reason": "429"}
    cfg2 = {}
    for _ in range(3):
        cs.generate_comment("标题", "正文", cfg2)
    check("连续 3 次 429 后禁用 AI",
          cfg2.get("_ai_disabled") is True and cfg2.get("_ai_disabled_reason") == "429")
finally:
    cs.generate_comment_ai = orig_gen_ai
    cs.show_notification = orig_notify
    os.environ.pop("CAIMOGU_AI_API_KEY", None)

print("\n" + "=" * 50)
print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:")
    for f in FAIL:
        print("  -", f)
print("=" * 50)
sys.exit(1 if FAIL else 0)
