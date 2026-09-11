#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# TokensMonitor —— API Key 余额/用量统一监控面板
# Copyright (C) 2026 TokensMonitor Contributors
# 本程序是自由软件：你可以在 GNU 通用公共许可证（GPL-3.0）条款下重新分发或修改它。
# 详见 LICENSE 文件（https://www.gnu.org/licenses/gpl-3.0.html）。

"""
TokensMonitor —— 统一查询各平台 API Key 余额/用量
零依赖，仅使用 Python 标准库。用法： python server.py
"""
import json
import math
import os
import re
import shutil
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATIC_DIR = BASE_DIR / "static"
UA = "TokensMonitor/1.0"

DEFAULT_CONFIG = {
    "host": "0.0.0.0",        # 0.0.0.0 = 局域网内手机可访问；改成 127.0.0.1 则仅本机可访问
    "port": 8787,
    "refresh_seconds": 60,    # 页面自动刷新间隔（秒，默认1分钟）
    "timeout": 15,            # 每个请求的超时（秒）
    "proxy": "",              # 出站代理；代理失败自动回退直连
    "access_key": "",         # 网页访问口令，留空则不启用；建议局域网多人环境设置
    "title": "TokensMonitor",  # 页面标题（前台 + 浏览器标签，设置页可改）
    "settings_password": "",  # 设置页口令；首次进入设置页时会要求设置（留空则无保护）
    "accounts": [],
}

CONFIG_LOCK = threading.Lock()
CONFIG = {}


def load_config():
    global CONFIG
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[初始化] 已生成示例配置: {CONFIG_FILE}")
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] config.json 解析失败({e})，使用默认配置")
        cfg = {}
    merged = {k: cfg.get(k, v) for k, v in DEFAULT_CONFIG.items() if k != "accounts"}
    merged["accounts"] = cfg.get("accounts", []) or []
    with CONFIG_LOCK:
        CONFIG = merged
    return merged


def validate_config(cfg):
    if not isinstance(cfg, dict):
        return "配置必须是 JSON 对象"
    accounts = cfg.get("accounts", [])
    if not isinstance(accounts, list):
        return "accounts 必须是数组"
    seen=set()
    for i, a in enumerate(accounts):
        where = f"accounts[{i}]" + (f" ({a.get('name')})" if isinstance(a, dict) and a.get("name") else "")
        if not isinstance(a, dict):
            return f"{where} 必须是对象"
        if a.get("name") in seen:
            return f"{where} 名称重复：每个账号的 name 必须唯一（卡片排序依赖它）"
        seen.add(a.get("name"))
        if not a.get("name"):
            return f"{where} 缺少 name"
        if not a.get("base_url") and a.get("type", "oneapi") not in ("deepseek", "siliconflow", "minimax", "codex", "zhipu"):
            return f"{where} 缺少 base_url"
        if not a.get("key") and a.get("enabled", True) and a.get("type", "oneapi") not in ("custom", "codex", "dxkp", "atomcode"):
            return f"{where} 缺少 key"
            return f"{where} 缺少 key"
        if a.get("type") == "custom" and not a.get("query"):
            return f"{where} 为 custom 类型，需要 query 字段"
    return None


class ApiError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = (body or "")[:300]
        super().__init__(f"HTTP {status}: {self.body[:200]}")


def http_request(url, headers=None, method="GET", body=None, timeout=15, verify_ssl=True):
    """返回 (status, raw_text)；非 2xx 抛 ApiError（带响应体便于排查）"""
    data = None
    if body is not None:
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else str(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA, **(headers or {})})
    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    def _open(proxy):
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        if ctx:
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")

    px = (CONFIG or {}).get("proxy") if isinstance(CONFIG, dict) else None
    # 先直连（国内站点最优）；连接层失败且配置了代理时，自动改走代理重试
    try:
        return _open(None)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise ApiError(e.code, detail)
    except (urllib.error.URLError, OSError, ssl.SSLError):
        if not px:
            raise
        try:
            return _open(px)
        except urllib.error.HTTPError as e2:
            raise ApiError(e2.code, e2.read().decode("utf-8", "replace")[:300])
        except Exception:
            raise


def _parse_json(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def _timeout():
    return int(CONFIG.get("timeout", 15))


def _get_json(url, headers, acc):
    status, raw = http_request(url, headers=headers, timeout=_timeout(),
                               verify_ssl=acc.get("verify_ssl", True))
    if status != 200:
        raise ApiError(status, raw)
    data = _parse_json(raw)
    if data is None:
        raise ValueError("响应不是 JSON: " + raw[:200])
    return data


def _bearer(key):
    return {"Authorization": "Bearer " + (key or "")}


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def dig(obj, path):
    """按 a.b.0.c 的点路径从 dict/list 中取值"""
    cur = obj
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except Exception:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


# ---------------- 各平台探测逻辑 ----------------

def probe_oneapi(acc):
    """one-api / new-api / veloera 等兼容 OpenAI 计费接口的中转站，key 为 sk- 开头的令牌"""
    base = acc["base_url"].rstrip("/")
    h = _bearer(acc.get("key"))
    out = {"currency": "USD", "extra": []}
    errs = []
    try:
        d = _get_json(base + "/v1/dashboard/billing/subscription", h, acc)
        if isinstance(d, dict):
            err = d.get("error")
            if err:
                raise ValueError(err.get("message") if isinstance(err, dict) else str(err))
            if d.get("hard_limit_usd") is not None:
                out["balance"] = float(d["hard_limit_usd"])
    except Exception as e:
        errs.append("余额: " + str(e))
    try:
        d = _get_json(base + "/v1/dashboard/billing/usage", h, acc)
        if isinstance(d, dict) and d.get("total_usage") is not None:
            out["used"] = round(float(d["total_usage"]) / 100.0, 4)
    except Exception as e:
        errs.append("用量: " + str(e))
    if "balance" not in out and "used" not in out:
        raise ValueError("；".join(errs) or "接口返回为空")
    if errs:
        out["extra"].append({"label": "部分接口失败", "value": "；".join(errs)[:120]})
    return out


def probe_newapi(acc):
    """new-api 站点用户接口：key 为 站点『系统访问令牌』，另需 user_id（个人设置页可见）"""
    base = acc["base_url"].rstrip("/")
    h = {"Authorization": "Bearer " + acc.get("key", ""),
         "New-Api-User": str(acc.get("user_id", ""))}
    d = _get_json(base + "/api/user/self", h, acc)
    if isinstance(d, dict) and d.get("success") is False:
        raise ValueError(d.get("message") or "接口返回 success=false")
    u = (d.get("data") if isinstance(d, dict) else None) or {}
    if not u:
        raise ValueError("返回数据中没有 data 字段: " + json.dumps(d, ensure_ascii=False)[:200])
    quota_per_usd = float(acc.get("quota_per_usd", 500000))
    out = {"currency": "USD",
           "balance": round((u.get("quota") or 0) / quota_per_usd, 4),
           "used": round((u.get("used_quota") or 0) / quota_per_usd, 4),
           "extra": []}
    if u.get("request_count") is not None:
        out["extra"].append({"label": "调用次数", "value": u["request_count"]})
    if u.get("group"):
        out["extra"].append({"label": "分组", "value": u["group"]})
    return out


def probe_deepseek(acc):
    """DeepSeek 官方
    - 余额: GET /user/balance（sk- API key）
    - 可选 web_token: platform.deepseek.com 网页会话 token（F12 → 请求头 Authorization 里的
      Bearer 后面那串），配置后可显示 今日消费/请求数/Token 消耗"""
    base = (acc.get("base_url") or "https://api.deepseek.com").rstrip("/")
    d = _get_json(base + "/user/balance", _bearer(acc.get("key")), acc)
    infos = (d.get("balance_infos") or []) if isinstance(d, dict) else []
    total, parts = 0.0, []
    for i in infos:
        v = _to_float(i.get("total_balance"))
        if v is not None:
            total += v
        parts.append(f"{i.get('currency')}: {i.get('total_balance')}")
    out = {"currency": "CNY", "balance": round(total, 4), "stats": []}

    wt = acc.get("web_token")
    if not wt:
        return out

    H = {"Authorization": "Bearer " + wt,
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0",
         "Accept": "application/json",
         "Referer": "https://platform.deepseek.com/usage",
         "Origin": "https://platform.deepseek.com"}
    day0 = int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))
    q = f"?start={day0}&end={day0 + 86400}&tz={-time.timezone}"  # 接口要求按天对齐
    kw = dict(headers=H, timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))

    def _j(url):
        st, raw = http_request(url, **kw)
        return (_parse_json(raw) or {}).get("data") or {}

    # 累计消费 + 累计/本月 Token：get_user_summary → biz_data
    total_cost_val = None
    try:
        summary = _j("https://platform.deepseek.com/api/v0/users/get_user_summary").get("biz_data") or {}
        for g in summary.get("total_costs") or []:
            amt = _to_float(g.get("amount"))
            if amt is not None and g.get("currency") in (None, "CNY"):
                total_cost_val = round(amt, 2)
        total_usage = summary.get("total_usage")
        monthly_usage = summary.get("monthly_usage")
    except Exception:
        total_usage = monthly_usage = None

    try:
        biz_a = _j("https://platform.deepseek.com/api/v0/usage/by_api_key/amount" + q).get("biz_data") or {}
        biz_c = _j("https://platform.deepseek.com/api/v0/usage/by_api_key/cost" + q).get("biz_data") or {}
        tokens = reqs = 0
        for s_ in biz_a.get("series") or []:
            for b_ in s_.get("buckets") or []:
                u = b_.get("usage") or {}
                tokens += (u.get("PROMPT_CACHE_HIT_TOKEN") or 0) + (u.get("PROMPT_CACHE_MISS_TOKEN") or 0) + (u.get("RESPONSE_TOKEN") or 0)
                reqs += u.get("REQUEST") or 0
        cost = 0.0
        for g_ in biz_c.get("data") or []:
            for s_ in g_.get("series") or []:
                for b_ in s_.get("buckets") or []:
                    cost += b_.get("cost") or 0

        def add(label, val, prefix=None):
            if val is None:
                return
            st_ = {"label": label, "value": val}
            if prefix:
                st_["prefix"] = prefix
            out["stats"].append(st_)

        add("今日请求", reqs)
        add("今日消费", round(cost, 4), prefix="¥")
        add("今日 Token", tokens)
        add("累计消费", total_cost_val, prefix="¥")
    except Exception as e:
        out["extra"] = (out.get("extra") or []) + [{"label": "今日用量获取失败", "value": str(e)[:100]}]
    return out


def probe_siliconflow(acc):
    """硅基流动
    - sk- key 可查余额明细（/v1/user/info 已被官方下线，改走控制台接口）
    - 配 cookie（cloud.siliconflow.cn 网页会话）后自动试多个控制台路径取余额"""
    out = {"currency": "CNY", "extra": [], "stats": [], "ok": False}
    cookie = acc.get("cookie")
    errors = []

    if cookie:
        base = "https://cloud.siliconflow.cn"
        H = {"Cookie": cookie, "Accept": "application/json",
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0",
             "Referer": "https://cloud.siliconflow.cn/me/account/ak",
             "Content-Type": "application/json"}
        sid = acc.get("subject_id")
        if sid:
            H["X-Subject-Id"] = sid
        # 已确认的余额接口 + 历史候选
        cand = ["/walletd-server/api/v1/subject/profile/peek",
                "/api/v1/user/info", "/api/v1/users/me", "/api/v1/account/info"]
        for path in cand:
            try:
                st, raw = http_request(base + path, headers=H, timeout=_timeout(),
                                       verify_ssl=acc.get("verify_ssl", True))
            except ApiError as e:
                errors.append(f"{path}: {e.status}")
                continue
            if st != 200:
                errors.append(f"{path}: {st}")
                continue
            d = _parse_json(raw)
            data = (d.get("data") if isinstance(d, dict) else None) or d or {}
            fin = data.get("financialInfo") if isinstance(data, dict) else None
            if isinstance(fin, dict):
                # 金额单位 1e-12 元（控制台按截断显示两位小数）
                def yuan(v):
                    f = _to_float(v)
                    return math.floor(f / 1e12 * 100) / 100 if f is not None else None
                out["balance"] = yuan(fin.get("balance"))
                used = yuan(fin.get("used")); rech = yuan(fin.get("recharged"))

                def addst(label, val, prefix="¥"):
                    if val is None:
                        return
                    out["stats"].append({"label": label, "value": val, "prefix": prefix})

                # 今日用量 / 今日消费：账单聚合与按模型用量（毫秒时间戳按天对齐）
                try:
                    day0 = int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))
                    rng = f"startTime={day0 * 1000}&endTime={(day0 + 86400) * 1000 - 1}"
                    _, rawu = http_request(base + "/panel-server/api/v1/bill/items/allocation_aggregate?"
                                           + "aggregateByApiKey=false&aggregateByModelName=false"
                                           + "&aggregateByUnit=true&current=1&pageSize=10&type=3&" + rng,
                                           headers=H, timeout=_timeout(),
                                           verify_ssl=acc.get("verify_ssl", True))
                    la = ((_parse_json(rawu) or {}).get("data") or {}).get("list") or []
                    kuse = sum(_to_float(it.get("grossUsage")) or 0 for it in la)
                    if kuse:
                        addst("今日用量", f"{kuse:.2f}K", prefix="")
                    _, rawb = http_request(base + "/panel-server/api/v1/bill/aggregate_amount?" + rng,
                                           headers=H, timeout=_timeout(),
                                           verify_ssl=acc.get("verify_ssl", True))
                    bd = (_parse_json(rawb) or {}).get("data") or {}
                    addst("今日消费", _to_float(bd.get("netAmount")))
                except Exception:
                    pass
                # 已用金额 / 累计充值（来自钱包 peek，不依赖上面的请求）
                addst("已用金额", used)
                addst("累计充值", rech)
                out["ok"] = True
                return out
            bal = None
            for k in ("balance", "totalBalance", "total_balance", "credit"):
                v = data.get(k) if isinstance(data, dict) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bal = v
                    break
            if bal is not None:
                out["balance"] = bal
                out["ok"] = True
                return out
            errors.append(f"{path}: 无余额字段 " + json.dumps(data, ensure_ascii=False)[:120])

    # 回退：老接口（部分账号可能仍可用）
    try:
        base = (acc.get("base_url") or "https://api.siliconflow.cn").rstrip("/")
        d = _get_json(base + "/v1/user/info", _bearer(acc.get("key")), acc)
        data = d.get("data") if isinstance(d, dict) else None
        if isinstance(data, dict):
            for label, k in (("总余额", "totalAmount"), ("充值余额", "chargeAmount"), ("赠送余额", "totalNps")):
                if data.get(k) is not None:
                    out["extra"].append({"label": label, "value": data[k]})
            out["balance"] = _to_float(data.get("balance"))
            out["ok"] = True
            return out
    except Exception as e:
        errors.append("legacy: " + str(e)[:120])

    if out.get("balance") is None:
        raise ValueError("；".join(errors) or "未能获取余额")


def probe_minimax(acc):
    """MiniMax Token Plan：/v1/token_plan/remains，Token Plan 专用 sk-cp Key
    官方未公开返回结构，自动识别数值字段并展示候选路径；可用 balance_field 手动指定"""
    base = (acc.get("base_url") or "https://www.minimaxi.com").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if acc.get("cookie"):
        headers["Cookie"] = acc["cookie"]
        if acc.get("key"):
            headers["Authorization"] = "Bearer " + acc["key"]
    else:
        headers["Authorization"] = "Bearer " + acc.get("key", "")
    d = _get_json(base + acc.get("remains_path", "/v1/token_plan/remains"), headers, acc)
    if isinstance(d, dict):
        br = d.get("base_resp")
        if isinstance(br, dict) and br.get("status_code") not in (0, None):
            msg = str(br.get("status_msg") or br)
            if "cookie" in msg.lower():
                raise ValueError('Key 未被接受、接口要求登录态：在账号配置加 "cookie": "..."（浏览器登录平台后 F12→网络→任一请求→复制 Cookie 值）')
            raise ValueError(f"接口返回错误 {br.get('status_code')}: {msg}")
    # 已知结构：model_remains 列表，每个条目是一个模型组的 5 小时/周窗口，以百分比字段为准
    mr = d.get("model_remains") if isinstance(d, dict) else None
    if isinstance(mr, list) and mr and isinstance(mr[0], dict):
        out = {"currency": "%", "extra": [], "quotas": []}
        NAME_MAP = {"general": "通用", "video": "视频"}

        def fmt_reset(ms):
            if not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms <= 0:
                return None
            m = int(ms / 60000)
            if m >= 2880:
                return f"{m // 1440} 天 {m % 1440 // 60} 小时后重置"
            if m >= 60:
                return f"{m // 60} 小时 {m % 60} 分钟后重置"
            return f"{m} 分钟后重置"

        for e in mr:
            if not isinstance(e, dict):
                continue
            g = NAME_MAP.get(e.get("model_name"), e.get("model_name") or "套餐")
            iv_r = e.get("current_interval_remaining_percent")
            if isinstance(iv_r, (int, float)) and not isinstance(iv_r, bool):
                used = max(0, round(100 - iv_r, 1))
                out["quotas"].append({"label": f"{g} · 5h 额度", "pct": used,
                                      "text": f"已用 {used}%", "note": fmt_reset(e.get("remains_time"))})
            wk_r = e.get("current_weekly_remaining_percent")
            if isinstance(wk_r, (int, float)) and not isinstance(wk_r, bool):
                # remaining_percent 按"含加成的总额度"计；官方按点数显示（如 已用75/总额度150%）
                boost = e.get("weekly_boost_permille")
                if isinstance(boost, (int, float)) and not isinstance(boost, bool) and boost > 0:
                    total = boost / 10
                    used = max(0.0, round((100 - wk_r) * boost / 1000, 1))
                    pct = round(used / total * 100, 1)
                    text = f"已用 {used:g}% · 总额度 {total:g}%"
                else:
                    used = max(0, round(100 - wk_r, 1))
                    pct = used
                    text = f"已用 {used:g}%"
                out["quotas"].append({"label": f"{g} · 周额度", "pct": pct,
                                      "text": text, "note": fmt_reset(e.get("weekly_remains_time"))})
        if out["quotas"]:
            return out
        # 结构存在但字段没对上，落到下面的通用识别

    if acc.get("balance_field"):
        return {"currency": acc.get("currency", "CREDIT"),
                "balance": dig(d, acc["balance_field"]),
                "extra": [{"label": "原始响应", "value": json.dumps(d, ensure_ascii=False)[:200]}]}

    cands = []

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}.{i}" if prefix else str(i))
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            cands.append((prefix, obj))

    walk(d, "")

    def score(name):
        n = name.lower()
        s = 0
        if "remain" in n or "left" in n:
            s += 10
        elif any(w in n for w in ("used", "expire", "id", "count")):
            s -= 6
        if "time" in n or "start" in n or "end" in n:
            s -= 20
        if any(w in n for w in ("credit", "token", "quota", "balance")):
            s += 5
        return s

    cands.sort(key=lambda kv: -score(kv[0]))
    out = {"currency": "CREDIT", "extra": []}
    for p, v in cands[:8]:
        out["extra"].append({"label": p, "value": v})
    if not cands:
        raise ValueError("接口通了但没解析到数值字段，原始响应: " + json.dumps(d, ensure_ascii=False)[:200])
    out["balance"] = cands[0][1]
    return out


def _fmt_secs(s):
    """秒数 → 人话倒计时"""
    if not isinstance(s, (int, float)) or isinstance(s, bool) or s <= 0:
        return None
    m = int(s // 60)
    if m >= 2880:
        return f"{m // 1440} 天 {m % 1440 // 60} 小时后重置"
    if m >= 60:
        return f"{m // 60} 小时 {m % 60} 分钟后重置"
    return f"{m} 分钟后重置"


def probe_codex(acc):
    """OpenAI Codex（ChatGPT 订阅）：读取本机 ~/.codex/auth.json 的 OAuth 凭证
    过期时自动用 refresh_token 续期；也可在配置里显式给 access_token"""
    tok = acc.get("access_token")
    path = os.path.expanduser(acc.get("auth_file", "~/.codex/auth.json"))
    refresh_tok = acc.get("refresh_token")
    if not tok and os.path.exists(path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        t = d.get("tokens") or {}
        tok = t.get("access_token")
        refresh_tok = refresh_tok or t.get("refresh_token")
    if not tok:
        raise ValueError("未找到 Codex 凭证：请先在本机登录 Codex（生成 ~/.codex/auth.json），或配置 access_token")

    headers = {"Authorization": "Bearer " + tok,
               "User-Agent": "codex_cli_rs",
               "Content-Type": "application/json"}
    url = acc.get("base_url", "https://chatgpt.com").rstrip("/") + "/backend-api/wham/usage"
    try:
        st, raw = http_request(url, headers=headers, timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))
    except ApiError as e:
        if e.status != 401 or not refresh_tok:
            raise
        # access_token 过期 → 用 refresh_token 续期后重试（codex 官方公开 client_id）
        st2, raw2 = http_request("https://auth.openai.com/oauth/token",
                                 headers={"Content-Type": "application/json"}, method="POST",
                                 body={"grant_type": "refresh_token", "refresh_token": refresh_tok,
                                       "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                                       "scope": "openid profile email offline_access"},
                                 timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))
        tok = (_parse_json(raw2) or {}).get("access_token")
        if not tok:
            raise ValueError("凭证已过期且续期失败，请重新运行一次 codex 登录") from e
        headers["Authorization"] = "Bearer " + tok
        st, raw = http_request(url, headers=headers, timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))
    if st != 200:
        raise ApiError(st, raw)
    d = _parse_json(raw)
    if not isinstance(d, dict):
        raise ValueError("响应异常: " + raw[:200])

    rl = d.get("rate_limit") or {}
    out = {"currency": "%", "extra": [], "quotas": []}

    def win(label, w):
        if not isinstance(w, dict) or w.get("used_percent") is None:
            return
        used = w["used_percent"]
        out["quotas"].append({"label": label, "pct": used,
                              "text": f"已用 {used:g}%", "note": _fmt_secs(w.get("reset_after_seconds"))})

    win("5h 额度", rl.get("primary_window"))
    win("周额度", rl.get("secondary_window"))
    if not out["quotas"]:
        raise ValueError("响应中没有用量窗口: " + json.dumps(d, ensure_ascii=False)[:200])
    if d.get("plan_type"):
        out["extra"].append({"label": "套餐", "value": d["plan_type"]})
    rc = (d.get("rate_limit_reset_credits") or {}).get("available_count")
    if rc:
        out["extra"].append({"label": "可用重置次数", "value": rc})
    cr = d.get("credits") or {}
    if cr.get("has_credits") and cr.get("balance") not in (None, "", "0"):
        out["extra"].append({"label": "Credits 余额", "value": cr["balance"]})
    return out


def probe_dxkp(acc):
    """AI STORE (ai.dxkp.com) 积分余额监控
    单调用 /api/user/stats/summary（按天对齐，自动算今天）。
    认证：key 字段优先（用户维护的新 Authorization），401 时回退 cookie 里的 accessToken。"""
    base = acc["base_url"].rstrip("/")
    today = time.strftime("%Y-%m-%d")

    # 备选令牌：cookie 里的 authorized-token.accessToken（URL 编码 JSON）
    cookie_token = ""
    import urllib.parse as _up
    m = re.search(r'authorized-token=({[^;]+})', acc.get("cookie", ""))
    if m:
        try:
            cookie_token = (json.loads(_up.unquote(m.group(1))) or {}).get("accessToken") or ""
        except Exception:
            pass

    def _get(bearer):
        h = {"Authorization": "Bearer " + bearer,
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0",
             "Referer": "https://ai.dxkp.com/user/dashboard"}
        if acc.get("cookie"):
            h["Cookie"] = acc["cookie"]
        return http_request(f"{base}/api/user/stats/summary?start_date={today}&end_date={today}",
                            headers=h, timeout=_timeout(),
                            verify_ssl=acc.get("verify_ssl", True))

    token = acc.get("key", "")
    # 依次尝试：key → cookie accessToken
    err = ""
    for bearer in [b for b in (token, cookie_token) if b]:
        try:
            st, raw = _get(bearer)
            if st == 200:
                break
            err = f"HTTP {st}: {raw[:120]}"
        except ApiError as e:
            err = str(e)[:200]
            if e.status != 401:
                raise
    else:
        if not err:
            err = "未配置任何认证令牌"
        raise ApiError(401 if "401" in err else 502, err)

    d = _parse_json(raw)
    if not isinstance(d, dict):
        raise ValueError("响应异常: " + raw[:200])

    out = {"currency": "积分", "stats": [], "ok": True}

    bal = d.get("current_points")
    if isinstance(bal, (int, float)) and not isinstance(bal, bool):
        out["balance"] = int(round(float(bal)))
        out["balance_label"] = "积分余额"

    def add(label, val):
        if val is None:
            return
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out["stats"].append({"label": label, "value": val})
        else:
            out["stats"].append({"label": label, "value": str(val)})

    add("当日请求", d.get("total_requests"))
    add("当日积分", d.get("total_points"))
    add("消耗 token", d.get("total_tokens"))
    sr = d.get("success_rate")
    if isinstance(sr, (int, float)) and not isinstance(sr, bool):
        out["stats"].append({"label": "调用成功率", "value": f"{sr:g}%"})

    out["stats"] = [s for s in out["stats"] if s.get("value") is not None]
    if not out["stats"] and out.get("balance") is None:
        raise ValueError("响应未识别: " + json.dumps(d, ensure_ascii=False)[:200])
    return out


def probe_atomcode(acc):
    """AtomCode (ai.atomgit.com/serverless-api) —— GitCode CodingPlan
    数据源: gitcode.com/widget/api/v1/token_usage/codingplan_token_usage
    认证: cookie 里的 GITCODE_ACCESS_TOKEN（或 key 字段直接放 token）"""
    cookie = acc.get("cookie", "")
    key = acc.get("key", "")
    at = key if key.startswith("eyJ") else ""
    if not at:
        m = re.search(r'GITCODE_ACCESS_TOKEN=([^;]+)', cookie)
        at = m.group(1) if m else ""
    if not cookie and not at:
        raise ValueError("需要 cookie 或 key（GITCODE_ACCESS_TOKEN）")

    H = {"Accept": "application/json",
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152.0.0.0",
         "Referer": "https://ai.atomgit.com/serverless-api"}
    if cookie:
        H["Cookie"] = cookie
    if at:
        H["Authorization"] = "Bearer " + at

    st, raw = http_request("https://gitcode.com/widget/api/v1/token_usage/codingplan_token_usage",
                           headers=H, timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))
    if st != 200:
        raise ApiError(st, raw)
    d = _parse_json(raw)
    if not isinstance(d, dict) or "current_usage" not in d:
        raise ValueError("响应异常: " + raw[:200])

    out = {"currency": "", "stats": [], "quotas": [], "ok": True}
    plan = d.get("codingplan_free") or {}
    if plan.get("plan_name"):
        out["extra"] = [{"label": "套餐", "value": f"{plan['plan_name']} · {plan.get('plan_type','')}"}]
    # 5h 窗口 → 进度条
    cu = d.get("current_usage") or {}
    used, limit = cu.get("window_tokens_used"), cu.get("window_token_limit")
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit:
        pct = round(used / limit * 100)
        out["quotas"].append({"label": "5小时用量", "pct": pct,
                              "text": f"{used:g}/{limit:g}（{pct}%）",
                              "note": f"{str(cu.get('reset_at_display',''))} 重置"})

    # 月度周期进度条：claimed_at → expires_at，已流逝天数占比
    try:
        from datetime import datetime
        ca = datetime.strptime(str(plan.get("claimed_at", ""))[:19], "%Y-%m-%dT%H:%M:%S")
        ex = datetime.strptime(str(plan.get("expires_at", ""))[:19], "%Y-%m-%dT%H:%M:%S")
        total = (ex - ca).total_seconds()
        if total > 0:
            elapsed = max(0.0, min(1.0, (datetime.now() - ca).total_seconds() / total))
            left_days = max(0, (ex - datetime.now()).days)
            out["quotas"].append({"label": "月度周期", "pct": round(elapsed * 100, 1),
                                  "text": f"剩 {left_days} 天 / 共 {plan.get('total_days', '?')} 天",
                                  "note": f"{str(plan.get('expires_at', ''))[:10]} 到期"})
    except Exception:
        pass

    # 今日 Token（rows 最后一天；数据有延迟时取最近一天）
    rows = d.get("rows") or []
    today = time.strftime("%Y-%m-%d")
    today_row = rows[-1] if rows else None
    today_tok = (today_row or {}).get("total_tokens") or 0

    def add(label, val):
        if val is None:
            return
        out["stats"].append({"label": label, "value": val})

    add("今日 Token", today_tok)
    add("7 天 Token", d.get("total_tokens"))
    return out


def probe_moonshot(acc):
    """Moonshot AI（Kimi）：GET /v1/users/me/balance"""
    base = (acc.get("base_url") or "https://api.moonshot.cn").rstrip("/")
    d = _get_json(base + "/v1/users/me/balance", _bearer(acc.get("key")), acc)
    data = d.get("data") or {}
    out = {"currency": "CNY", "balance": _to_float(data.get("available_balance")), "stats": []}
    if data.get("voucher_balance") not in (None, "0", 0):
        out["extra"] = [{"label": "代金券余额", "value": f"¥{data.get('voucher_balance')}"}]
    return out


def probe_openrouter(acc):
    """OpenRouter：GET /api/v1/credits（USD）"""
    d = _get_json("https://openrouter.ai/api/v1/credits", _bearer(acc.get("key")), acc)
    data = (d.get("data") if isinstance(d, dict) else None) or {}
    total = _to_float(data.get("total_credits"))
    used = _to_float(data.get("total_usage"))
    out = {"currency": "USD", "balance": (round(total - used, 4) if total is not None and used is not None else None),
           "stats": [], "extra": []}

    def add(label, val):
        if val is None:
            return
        out["stats"].append({"label": label, "value": val, "prefix": "$"})
    add("总额度", total)
    add("已用", used)
    return out


def probe_sisct(acc):
    """newapi.sisct.xyz / 类似站点
    /api/v1/auth/me 取余额，/api/v1/usage/dashboard/stats 取今日关键数字 + 平均响应"""
    base = acc["base_url"].rstrip("/")
    headers = {"Authorization": "Bearer " + acc.get("key", ""),
               "User-Agent": "TokensMonitor/1.0"}
    if acc.get("cookie"):
        headers["Cookie"] = acc["cookie"]

    st1, raw1 = http_request(base + "/api/v1/auth/me?timezone=Asia/Shanghai",
                             headers=headers, timeout=_timeout(),
                             verify_ssl=acc.get("verify_ssl", True))
    me = (_parse_json(raw1) or {}).get("data") if st1 == 200 else {}

    st2, raw2 = http_request(base + "/api/v1/usage/dashboard/stats",
                             headers=headers, timeout=_timeout(),
                             verify_ssl=acc.get("verify_ssl", True))
    if st2 != 200:
        raise ApiError(st2, raw2)
    stats = (_parse_json(raw2) or {}).get("data") or {}
    if not isinstance(stats, dict):
        raise ValueError("dashboard/stats 响应异常: " + raw2[:200])

    out = {"currency": "USD", "stats": [], "ok": True}
    bal = me.get("balance")
    if isinstance(bal, (int, float)) and not isinstance(bal, bool):
        out["balance"] = float(bal)

    def add(label, val, prefix=None):
        if val is None:
            return
        s = {"label": label, "value": val}
        if prefix:
            s["prefix"] = prefix
        out["stats"].append(s)

    add("今日请求", stats.get("today_requests"))
    add("今日消费", stats.get("today_actual_cost", stats.get("today_cost")), prefix="$")
    add("今日 Token", stats.get("today_tokens"))
    avg_ms = stats.get("average_duration_ms")
    if isinstance(avg_ms, (int, float)) and not isinstance(avg_ms, bool) and avg_ms > 0:
        out["stats"].append({"label": "平均响应", "value": f"{avg_ms / 1000:.2f}s"})


    out["stats"] = [s for s in out["stats"] if s.get("value") is not None]
    if not out["stats"] and out.get("balance") is None:
        raise ValueError("两个接口都返回空数据")
    return out


def probe_zhipu(acc):
    """智谱 BigModel / GLM Coding Plan：GET /api/monitor/usage/quota/limit
    key 为 BigModel 平台 API Key（形如 id.secret，直接放 Authorization，不带 Bearer）
    国际版 z.ai：base_url 填 https://api.z.ai"""
    base = (acc.get("base_url") or "https://open.bigmodel.cn").rstrip("/")
    h = {"Authorization": acc.get("key", ""), "Content-Type": "application/json"}
    d = _get_json(base + "/api/monitor/usage/quota/limit", h, acc)
    if isinstance(d, dict) and d.get("success") is False:
        raise ValueError(str(d.get("msg") or d)[:200])
    data = (d.get("data") if isinstance(d, dict) else None) or {}
    limits = [l for l in (data.get("limits") or []) if isinstance(l, dict)]
    out = {"currency": "%", "extra": [], "quotas": []}
    tok = [l for l in limits if isinstance(l.get("type"), str) and l.get("type") in ("TOKENS_LIMIT", "CREDIT_LIMIT")]
    if tok and all(isinstance(l.get("nextResetTime"), (int, float)) for l in tok):
        tok.sort(key=lambda l: l["nextResetTime"])  # 先重置的是 5h 窗口
    for i, l in enumerate(tok):
        pct = l.get("percentage")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        q = {"label": ("5h 额度" if i == 0 else "周额度" if i == 1 else f"额度{i + 1}"),
             "pct": pct, "text": f"已用 {pct:g}%"}
        nrt = l.get("nextResetTime")
        if isinstance(nrt, (int, float)) and not isinstance(nrt, bool) and nrt > 0:
            ts = nrt / 1000 if nrt > 1e12 else nrt
            q["note"] = time.strftime("%m-%d %H:%M 重置", time.localtime(ts))
        out["quotas"].append(q)
    for l in limits:
        if l.get("type") == "TIME_LIMIT" and l.get("usage") is not None:
            out["extra"].append({"label": "MCP 月度调用", "value": f"{l.get('currentValue')}/{l.get('usage')}"})
    if data.get("level"):
        out["extra"].append({"label": "套餐", "value": data["level"]})
    if not out["quotas"] and not out["extra"]:
        raise ValueError("未识别的响应: " + json.dumps(d, ensure_ascii=False)[:200])
    return out


def probe_custom(acc):
    """自定义接口：按 query 里的 path/method/headers/提取规则 获取余额或用量"""
    q = acc.get("query") or {}
    key = acc.get("key", "")
    url = (acc["base_url"].rstrip("/") + q.get("path", "")).replace("{key}", key)
    method = (q.get("method") or "GET").upper()
    headers = {k: str(v).replace("{key}", key)
               for k, v in (q.get("headers") or {"Authorization": "Bearer {key}"}).items()}
    body = q.get("body")
    if isinstance(body, str):
        body = body.replace("{key}", key)
    status, raw = http_request(url, headers=headers, method=method, body=body,
                               timeout=_timeout(), verify_ssl=acc.get("verify_ssl", True))
    if status != 200:
        raise ApiError(status, raw)
    data = _parse_json(raw)

    def pick(spec):
        if not isinstance(spec, dict):
            return None
        v = dig(data, spec["path"]) if (data is not None and spec.get("path")) else None
        if v is None and spec.get("regex"):
            m = re.search(spec["regex"], raw)
            if m:
                v = m.group(1) if m.groups() else m.group(0)
        if v is None:
            return None
        fv = _to_float(v)
        if fv is None:
            return v
        if spec.get("scale") is not None:
            fv *= float(spec["scale"])
        return round(fv, int(spec["round"])) if spec.get("round") is not None else fv

    out = {"currency": q.get("currency", "USD"), "extra": []}
    b, u = pick(q.get("balance")), pick(q.get("used"))
    if b is not None:
        out["balance"] = b
    if u is not None:
        out["used"] = u
    for ex in q.get("extra") or []:
        v = dig(data, ex.get("path")) if (data is not None and ex.get("path")) else None
        if v is not None:
            out["extra"].append({"label": ex.get("label", ex.get("path")), "value": v})
    if "balance" not in out and "used" not in out:
        raise ValueError("未能从响应中提取到余额/用量，原始响应: " + raw[:200])
    return out


PROBERS = {
    "oneapi": probe_oneapi,
    "newapi": probe_newapi,
    "deepseek": probe_deepseek,
    "siliconflow": probe_siliconflow,
    "minimax": probe_minimax,
    "codex": probe_codex,
    "zhipu": probe_zhipu,
    "sisct": probe_sisct,
    "dxkp": probe_dxkp,
    "atomcode": probe_atomcode,
    "moonshot": probe_moonshot,
    "openrouter": probe_openrouter,
    "custom": probe_custom,
}


def sisct_login(acc):
    """SISCT/VoAPI 系登录：POST /api/v1/auth/login {Email, Password}
    返回 {"key": 新 JWT, "cookie": 新 Set-Cookie}"""
    import http.cookiejar
    base = acc["base_url"].rstrip("/")
    creds = acc.get("creds") or {}
    email = creds.get("email") or creds.get("Email") or creds.get("username")
    pw = creds.get("password") or creds.get("Password")
    if not email or not pw:
        raise ValueError("auto_login 启用但缺少 creds.email / creds.password")
    body = {"Email": email, "Password": pw}
    # 用 CookieJar 自动捕获 Set-Cookie
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(base + "/api/v1/auth/login",
                                 data=json.dumps(body).encode(),
                                 headers=h_global_json(), method="POST")
    try:
        with opener.open(req, timeout=_timeout()) as r:
            st = r.status
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ValueError(f"登录失败 HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
    if st != 200:
        raise ValueError(f"登录失败 HTTP {st}: {raw[:200]}")
    d = _parse_json(raw) or {}
    data = d.get("data") if isinstance(d.get("data"), dict) else d
    token = (data.get("token") if isinstance(data, dict) else None) \
         or (data.get("access_token") if isinstance(data, dict) else None) \
         or d.get("token") or d.get("access_token")
    if not token and isinstance(d, str) and d.count(".") >= 2:
        token = d
    if not token:
        raise ValueError("登录响应未找到 token: " + raw[:200])
    # 收集 cookie
    cookie_str = "; ".join(f"{c.name}={c.value}" for c in jar)
    if not cookie_str:
        cookie_str = acc.get("cookie", "")
    return {"key": token, "cookie": cookie_str}


def dxkp_login(acc):
    """AI STORE 登录（待用户从 F12 拿到实际登录接口后启用）"""
    creds = acc.get("creds") or {}
    email = creds.get("email") or creds.get("Email")
    pw = creds.get("password") or creds.get("Password")
    if not email or not pw:
        raise ValueError("auto_login 启用但缺少 creds")
    raise NotImplementedError("AI STORE 登录接口待用户提供 F12 抓到的真实路径")


LOGIN_PROBERS = {
    "sisct": sisct_login,
    "dxkp": dxkp_login,
    # 其他平台（zhipu/deepseek/codex 等用长期 API key，不需要登录）
}


def h_global_json():
    return {"Content-Type": "application/json", "User-Agent": "TokensMonitor/1.0"}


def persist_creds(account_name, new_creds):
    """自动登录成功后，把新 token 持久化到 config.json"""
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for a in cfg.get("accounts", []):
            if a.get("name") == account_name:
                if "key" in new_creds:
                    a["key"] = new_creds["key"]
                if "cookie" in new_creds:
                    a["cookie"] = new_creds["cookie"]
                break
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_FILE)
    except Exception as e:
        print(f"[警告] 自动持久化失败: {e}")


def try_auto_login(acc):
    """若账号配置了 auto_login + creds，调用对应平台的登录函数换新 token
    成功：返回新 (key, cookie)，并自动写回 config.json"""
    if not acc.get("auto_login") or not acc.get("creds"):
        return None
    fn = LOGIN_PROBERS.get(acc.get("type"))
    if not fn:
        return None
    try:
        new_creds = fn(acc)
        persist_creds(acc.get("name"), new_creds)
        return new_creds
    except Exception as e:
        print(f"[auto-login] {acc.get('name')} 失败: {e}")
        return None


LAST_GOOD = {}  # name -> 上一次成功的结果（网络抖动时兜底，避免卡片闪错）
LAST_GOOD_LOCK = threading.Lock()


def check_account(acc):
    t0 = time.time()
    res = {"name": acc.get("name") or acc.get("base_url", "?"),
           "type": acc.get("type", "oneapi"),
           "ok": False, "balance": None, "used": None,
           "currency": "USD", "extra": [], "error": None,
           "latency_ms": None, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    live_acc = acc
    auto_renewed = False
    for attempt in (1, 2):
        try:
            out = PROBERS.get(live_acc.get("type", "oneapi"), probe_oneapi)(live_acc)
            res.update(out)
            res["ok"] = True
            if auto_renewed:
                res["extra"] = (res.get("extra") or []) + [{"label": "auto-login", "value": "已自动续期"}]
            with LAST_GOOD_LOCK:
                LAST_GOOD[res["name"]] = {k: v for k, v in res.items() if k != "error"}
            break
        except ApiError as e:
            # 401 且配了自动登录 → 拿新 token 再试一次
            if e.status == 401 and attempt == 1 and live_acc.get("auto_login") and live_acc.get("creds"):
                new_creds = try_auto_login(live_acc)
                if new_creds:
                    live_acc = {**live_acc, **new_creds}
                    auto_renewed = True
                    continue
            res["error"] = str(e)[:500]
            break
        except Exception as e:
            res["error"] = str(e)[:500]
            break
    if not res["ok"]:
        # 查询失败但有过成功数据 → 返回上次数据（标记 stale），避免偶发网络抖动让卡片闪错
        with LAST_GOOD_LOCK:
            cached = LAST_GOOD.get(res["name"])
        if cached:
            res = {**cached, "checked_at": res["checked_at"],
                   "latency_ms": res["latency_ms"], "stale": True,
                   "stale_error": res["error"]}
    if not res["ok"] and acc.get("base_url"):
        res["reauth_url"] = acc["base_url"]
    res["latency_ms"] = int((time.time() - t0) * 1000)
    return res


RESULTS = {}          # name -> 最近一次结果（含 stale 标记）
RLOCK = threading.Lock()
LAST_REFRESH = 0.0
REFRESHING = False


def _refresh_worker(names):
    global REFRESHING
    try:
        with CONFIG_LOCK:
            accs = [a for a in CONFIG.get("accounts", [])
                    if a.get("enabled", True) and a.get("name") in names]
        if accs:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for res in ex.map(check_account, accs):
                    with RLOCK:
                        RESULTS[res["name"]] = res
    finally:
        with RLOCK:
            REFRESHING = False


def maybe_async_refresh(force=False):
    """距上次刷新超过 25 秒（或强制）时，启动后台刷新；立即返回不阻塞"""
    global LAST_REFRESH, REFRESHING
    with RLOCK:
        now = time.time()
        if REFRESHING:
            return True
        if not force and now - LAST_REFRESH < 25:
            return False
        REFRESHING = True
        LAST_REFRESH = now
    names = [a["name"] for a in CONFIG.get("accounts", []) if a.get("enabled", True)]
    threading.Thread(target=_refresh_worker, args=(names,), daemon=True).start()
    return True


def run_checks():
    """立即返回缓存结果（毫秒级）；缺失的新卡同步补齐；其余由后台线程异步刷新"""
    refreshing = maybe_async_refresh()
    with CONFIG_LOCK:
        enabled = [a for a in CONFIG.get("accounts", []) if a.get("enabled", True)]
    names = [a["name"] for a in enabled]
    with RLOCK:
        results = [RESULTS.get(n) for n in names]

    # 首次访问 / 新增卡片：同步补齐缺失的，保证卡片立即可见
    missing = [a for a, r in zip(enabled, results) if r is None]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for res in ex.map(check_account, missing):
                with RLOCK:
                    RESULTS[res["name"]] = res
        with RLOCK:
            results = [RESULTS.get(n) for n in names]

    with RLOCK:
        results = [RESULTS.get(n) for n in names]
    results = [r if r else {"name": n, "ok": False, "error": "探测中…", "extra": [], "stats": []}
               for n, r in zip(names, results)]
    checked = max([r.get("checked_at", "") for r in results], default="")
    return {"title": CONFIG.get("title") or "TokensMonitor",
            "accounts": results,
            "refreshing": refreshing,
            "checked_at": checked,
            "refresh_seconds": int(CONFIG.get("refresh_seconds", 60))}



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        with CONFIG_LOCK:
            expected = CONFIG.get("access_key") or ""
        if not expected:
            return True
        supplied = self.headers.get("X-Access-Key", "")
        if not supplied and "key=" in self.path:
            supplied = self.path.split("key=", 1)[1].split("&", 1)[0]
        return supplied == expected

    def _authed_settings(self):
        with CONFIG_LOCK:
            expected = CONFIG.get("settings_password") or ""
        if not expected:
            return True
        supplied = self.headers.get("X-Settings-Password", "")
        return supplied == expected

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                html = (STATIC_DIR / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, '{"error": "缺少 static/index.html"}')
        elif path == "/ssseetinnggg":
            try:
                html = (STATIC_DIR / "settings.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(500, '{"error": "缺少 static/settings.html"}')
        elif path == "/api/status":
            # 主页只读开放，不要求 access_key（不暴露写操作）
            res = run_checks()
            if "force=1" in (self.path.split("?", 1)[1] if "?" in self.path else ""):
                maybe_async_refresh(force=True)
            with CONFIG_LOCK:
                res["title"] = CONFIG.get("title") or "TokensMonitor"
                res["first_run"] = not (CONFIG.get("settings_password") or "")
            self._send(200, json.dumps(res, ensure_ascii=False))
        elif path == "/api/config":
            if not self._authed_settings():
                return self._send(401, '{"error":"unauthorized"}')
            with CONFIG_LOCK:
                cfg_out = {k: v for k, v in CONFIG.items() if k != "settings_password"}
                self._send(200, json.dumps(cfg_out, ensure_ascii=False))
        elif path == "/favicon.ico":
            self._send(200, b"", "image/x-icon")
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/order":
            # 卡片顺序（外观性操作，公开写；仅重排 accounts，不涉及密钥）
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                order = body.get("order")
                if not isinstance(order, list):
                    raise ValueError
            except Exception:
                return self._send(400, '{"error":"bad order"}')
            with CONFIG_LOCK:
                cur = {a.get("name"): a for a in CONFIG.get("accounts", [])}
                newlist = [cur[n] for n in order if n in cur]
                newlist += [a for n, a in cur.items() if n not in order]
                CONFIG["accounts"] = newlist
                cfg_disk = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
                cfg_disk["accounts"] = newlist
            try:
                tmp = CONFIG_FILE.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg_disk, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(CONFIG_FILE)
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:150]}))
            return self._send(200, '{"ok": true}')
        if path == "/api/test":
            # 单卡即时测试（需要设置口令）
            if not self._authed_settings():
                return self._send(401, '{"error":"unauthorized"}')
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return self._send(400, '{"error":"bad body"}')
            draft = body.get("draft")
            if isinstance(draft, dict) and draft.get("name"):
                # 测试未保存的草稿配置（可视化编辑器的 ▶ 测试按钮）
                merged = next((a for a in CONFIG.get("accounts", []) if a.get("name") == draft.get("name")), {})
                merged = {**merged, **draft}
                res = check_account(merged)
                return self._send(200, json.dumps({k: res.get(k) for k in ("ok","balance","used","currency","stats","extra","error","stale")}, ensure_ascii=False))
            name = body.get("name")
            with CONFIG_LOCK:
                acc = next((a for a in CONFIG.get("accounts", []) if a.get("name") == name), None)
            if not acc:
                return self._send(404, '{"error":"账号不存在"}')
            res = check_account(acc)
            return self._send(200, json.dumps({k: res.get(k) for k in ("ok","balance","used","currency","stats","extra","error","stale")}, ensure_ascii=False))
        if path == "/api/password":
            if not self._authed_settings():
                return self._send(401, '{"error":"unauthorized"}')
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                newpwd = str(body.get("new_password") or "").strip()
                oldpwd = str(body.get("old_password") or "").strip()
            except Exception:
                return self._send(400, '{"error":"bad body"}')
            with CONFIG_LOCK:
                cur = CONFIG.get("settings_password") or ""
            if not oldpwd or oldpwd != cur:
                return self._send(400, json.dumps({"error": "当前口令不正确"}, ensure_ascii=False))
            if len(newpwd) < 4:
                return self._send(400, json.dumps({"error": "新口令至少 4 个字符"}, ensure_ascii=False))
            if newpwd == cur:
                return self._send(400, json.dumps({"error": "新口令不能与当前口令相同"}, ensure_ascii=False))
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
                cfg["settings_password"] = newpwd
                tmp = CONFIG_FILE.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(CONFIG_FILE)
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:150]}))
            load_config()
            return self._send(200, '{"ok": true}')
        if path != "/api/config":
            return self._send(404, '{"error":"not found"}')
        if not self._authed_settings():
            return self._send(401, '{"error":"unauthorized"}')
        length = int(self.headers.get("Content-Length") or 0)
        try:
            cfg = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            return self._send(400, json.dumps({"error": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        err = validate_config(cfg)
        if err:
            return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
        # 首次保存：若 settings_password 尚未设置，要求 cfg 里带上至少 4 位的新口令
        with CONFIG_LOCK:
            cur_pwd = CONFIG.get("settings_password") or ""
        if not cur_pwd:
            newpwd = str(cfg.get("settings_password") or "").strip()
            if len(newpwd) < 4:
                return self._send(400, json.dumps({"error": "首次使用请先设置口令（至少 4 位）"}, ensure_ascii=False))
        try:
            # settings_password 只能在文件里改，浏览器保存不能改掉/丢失它
            if not cur_pwd and cfg.get("settings_password"):
                pass  # 首次设置，保留用户填的口令
            if CONFIG_FILE.exists():
                old_text = CONFIG_FILE.read_text(encoding="utf-8")
                try:
                    old_cfg = json.loads(old_text)
                    # 仅当"新配置没带口令"时才沿用旧口令（防浏览器端保存抹掉）；
                    # 新配置带非空口令时以其为准（支持首次设置）
                    if not str(cfg.get("settings_password") or "").strip():
                        old_pwd = str(old_cfg.get("settings_password") or "")
                        if old_pwd:
                            cfg["settings_password"] = old_pwd
                except Exception:
                    pass
                if old_text.strip() != json.dumps(cfg, ensure_ascii=False, indent=2).strip():
                    ts = time.strftime("%Y%m%d-%H%M%S")
                    shutil.copy2(CONFIG_FILE, BASE_DIR / f"config.json.{ts}.bak")
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            return self._send(500, json.dumps({"error": f"写入失败: {e}"}, ensure_ascii=False))
        load_config()
        self._send(200, '{"ok": true}')


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    load_config()
    host = CONFIG.get("host", "0.0.0.0")
    port = int(CONFIG.get("port", 8787))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("=" * 52)
    print("  TokensMonitor 已启动")
    print(f"  本机访问  http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f"  局域网    http://{lan_ip()}:{port}   (手机连同一 WiFi 可访问)")
    if not CONFIG.get("access_key"):
        print("  提示: 在 config.json 设置 access_key 可为网页加访问口令")
    print(f"  配置文件  {CONFIG_FILE}")
    print("  按 Ctrl+C 停止")
    print("=" * 52)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
