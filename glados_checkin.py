#!/usr/bin/env python3
"""GLaDOS 自动签到脚本。

原理：登录后点击"签到"时，浏览器实际是向 https://glados.rocks/api/user/checkin
发送一个 POST 请求。本脚本带上你登录后的 Cookie 复现这次请求，无需打开浏览器。

配置（环境变量优先，其次读取脚本同目录的 config.json）：
    GLADOS_COOKIE / config.json 的 "cookie"      登录后的完整 Cookie
    GLADOS_UA     / config.json 的 "user_agent"  登录浏览器的 User-Agent

注意：GLaDOS 会校验请求的 User-Agent 是否与登录浏览器一致，
不一致会返回"没有权限"，所以 user_agent 必须填你登录时那个浏览器的 UA。

用法：
    python3 glados_checkin.py

退出码：0 = 签到成功或今日已签到；2 = Cookie/UA 失效；1 = 其他错误
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

DOMAIN = os.environ.get("GLADOS_DOMAIN", "glados.rocks")
BASE_URL = f"https://{DOMAIN}"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
TIMEOUT = 30

EXIT_OK, EXIT_ERROR, EXIT_AUTH = 0, 1, 2


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def load_config() -> tuple[str, str]:
    env_cookie = os.environ.get("GLADOS_COOKIE", "").strip()
    env_ua = os.environ.get("GLADOS_UA", "").strip()
    file_cfg: dict = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            file_cfg = json.load(f)
    cookie = env_cookie or str(file_cfg.get("cookie", "")).strip()
    user_agent = env_ua or str(file_cfg.get("user_agent", "")).strip()

    missing = [name for name, value in (("cookie", cookie), ("user_agent", user_agent)) if not value]
    if missing:
        sys.exit(
            f"缺少配置项：{', '.join(missing)}\n"
            f"请在 {CONFIG_PATH} 填写（参考同目录 config.example.json），\n"
            "或设置环境变量 GLADOS_COOKIE 与 GLADOS_UA。获取方法见 README.md。"
        )
    return cookie, user_agent


def call_api(path: str, cookie: str, user_agent: str, payload: dict | None = None) -> dict:
    headers = {
        "cookie": cookie,
        "user-agent": user_agent,
        "referer": f"{BASE_URL}/console/checkin",
        "content-type": "application/json;charset=UTF-8",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络错误：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是 JSON（可能被防护页拦截）：{exc}") from exc


def extract_message(result: dict) -> str:
    # 真实签到响应形如：
    # {"code":0, "listV2":[{"type":"status","values":["哦耶!","自动签到成功"]}],
    #  "summary":"自动签到成功", "toast":true}
    for key in ("summary", "message"):
        if result.get(key):
            return str(result[key])
    for item in result.get("listV2") or result.get("list") or []:
        if not isinstance(item, dict):
            continue
        values = item.get("values")
        if not values:
            continue
        # values 可能是 ["标题", "内容"]，也可能是 [["标题", "内容"]]
        flat = values[0] if isinstance(values[0], list) else values
        return " ".join(str(x) for x in flat)
    return json.dumps(result, ensure_ascii=False)[:200]


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "未知账号"
    name, _, domain = email.partition("@")
    shown = name[:2] if len(name) > 2 else name[:1] or "*"
    return f"{shown}***@{domain}"


def main() -> int:
    cookie, user_agent = load_config()
    log(f"开始签到（{DOMAIN}）")

    try:
        result = call_api("/api/user/checkin", cookie, user_agent, {"token": DOMAIN})
    except RuntimeError as exc:
        log(f"签到请求失败：{exc}")
        return EXIT_ERROR

    code = result.get("code")
    message = extract_message(result)

    if code == -2:
        log(f"签到被拒绝（code={code}）：{message}")
        log("Cookie 已过期或 User-Agent 与登录浏览器不一致。请重新登录 glados.rocks，"
            "按 README.md 重新获取 cookie 和 user_agent 并更新 config.json。")
        return EXIT_AUTH
    if code not in (0, 1):
        log(f"签到失败（code={code}）：{message}")
        return EXIT_ERROR

    log(f"{'今日已签到过' if code == 1 else '签到成功'}：{message}")

    # 顺手查一下剩余天数，失败不影响签到结果
    try:
        status = call_api("/api/user/status", cookie, user_agent)
        data = status.get("data") or {}
        if data.get("leftDays") is not None:
            log(f"账号 {mask_email(data.get('email'))}：剩余 {data['leftDays']} 天")
    except (RuntimeError, AttributeError, KeyError) as exc:
        log(f"（查询剩余天数失败，不影响签到结果：{exc}）")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
