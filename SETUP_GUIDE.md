# 从零复刻：GLaDOS 自动签到（GitHub Actions 版）

本文教你在一台全新电脑上，从零搭一套"电脑不开机也能每天自动签 GLaDOS"的方案。全程约 15 分钟。

## 方案原理

你在网页上点"签到"时，浏览器实际是向 `https://glados.rocks/api/user/checkin` 发了一个 POST 请求。所谓自动签到，就是：

1. 用 Python 脚本带上你的登录 Cookie 复现这个请求（效果与手动点击完全一致）；
2. 把脚本放进 GitHub 仓库，用 **GitHub Actions**（GitHub 免费提供的云服务器）定时执行——它跑在 GitHub 机房里，与你的电脑无关，**电脑关机也照跑**；
3. 登录凭据（Cookie、User-Agent）放在仓库的 **Secrets** 里，加密存储、日志中自动打码，不出现在代码里。

费用：GitHub 免费账户每月 2000 分钟 Actions 额度，本方案每天 8 次、每次 10-20 秒，每月约 60 分钟（保守口径 240 分钟），完全免费。

## 第 1 步：创建两个文件

新建一个目录，放两个文件。

**文件一：`glados_checkin.py`**（签到脚本，纯 Python 标准库，无需安装任何依赖）

```python
#!/usr/bin/env python3
"""GLaDOS 自动签到脚本。

配置（环境变量优先，其次读取脚本同目录的 config.json）：
    GLADOS_COOKIE / config.json 的 "cookie"      登录后的完整 Cookie
    GLADOS_UA     / config.json 的 "user_agent"  登录浏览器的 User-Agent

注意：GLaDOS 会校验请求的 User-Agent 是否与登录浏览器一致，
不一致会返回"没有权限"，所以 user_agent 必须填你登录时那个浏览器的 UA。

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
            f"请在 {CONFIG_PATH} 填写，或设置环境变量 GLADOS_COOKIE 与 GLADOS_UA。"
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
    for key in ("summary", "message"):
        if result.get(key):
            return str(result[key])
    for item in result.get("listV2") or result.get("list") or []:
        if not isinstance(item, dict):
            continue
        values = item.get("values")
        if not values:
            continue
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
            "更新 Secrets 中的 GLADOS 和 GLADOS_UA。")
        return EXIT_AUTH
    if code not in (0, 1):
        log(f"签到失败（code={code}）：{message}")
        return EXIT_ERROR

    log(f"{'今日已签到过' if code == 1 else '签到成功'}：{message}")

    try:
        status = call_api("/api/user/status", cookie, user_agent)
        data = status.get("data") or {}
        if data.get("leftDays") is not None:
            log(f"账号 {mask_email(data.get('email'))}：剩余 {float(data['leftDays']):.0f} 天")
    except (RuntimeError, AttributeError, KeyError) as exc:
        log(f"（查询剩余天数失败，不影响签到结果：{exc}）")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

**文件二：`.github/workflows/checkin.yml`**（定时任务定义）

```yaml
name: GLaDOS Auto Checkin

on:
  schedule:
    # GitHub Actions 用 UTC，北京时间 = UTC+8。
    # 签到时段要求 23:00-04:00（凌晨签到积分多）。
    # 23:10 是当天最后的兜底：整个凌晨被 GitHub 漏掉时才会真正生效，
    # 其余情况脚本识别"今日已签到"后幂等跳过，多跑无害。
    - cron: "10 15 * * *" # 北京 23:10（前夜兜底）
    - cron: "10 16 * * *" # 北京 00:10
    - cron: "40 16 * * *" # 北京 00:40
    - cron: "10 17 * * *" # 北京 01:10
    - cron: "40 17 * * *" # 北京 01:40
    - cron: "10 18 * * *" # 北京 02:10
    - cron: "40 18 * * *" # 北京 02:40
    - cron: "10 19 * * *" # 北京 03:10
  workflow_dispatch: # 允许手动触发

jobs:
  checkin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Run checkin
        env:
          GLADOS_COOKIE: ${{ secrets.GLADOS }}
          GLADOS_UA: ${{ secrets.GLADOS_UA }}
        run: python glados_checkin.py
```

同时建一个 `.gitignore`（防止将来误提交本地凭据）：

```
config.json
secrets*.txt
cookie*.txt
*.log
```

## 第 2 步：创建私有仓库并推送

**必须私有**（Cookie 是登录凭据）。用命令行：

```bash
git init -b main
git add -A
git commit -m "GLaDOS auto check-in"
# 用 GitHub CLI 一条命令建私有仓库并推送（需先 gh auth login）：
gh repo create glados-checkin --private --source . --push
```

或者在 GitHub 网页上新建一个 Private 空仓库，再按页面提示 `git remote add` + `git push`。

## 第 3 步：获取 Cookie 和 User-Agent

1. 用浏览器登录 [glados.rocks](https://glados.rocks)
2. 按 `F12` 打开开发者工具，切到 **Network（网络）** 面板
3. **按 F5 刷新页面**（Network 只记录打开之后的请求）
4. 点击请求列表第一行（`glados.rocks`）
5. 右侧 **Request Headers** 里找 `cookie:` 一行，右键 → 复制值（整串形如 `koa:sess=...; koa:sess.sig=...`）
6. 同一区域找 `user-agent:` 一行，复制值

> ⚠️ GLaDOS 校验 UA 与登录浏览器一致，不一致返回"没有权限"。浏览器大版本更新后需重新取。
> Firefox 用户注意：Application 面板在 Firefox 里叫"存储（Storage）"，所以推荐用上面的 Network 方法，一次拿全两个值。

## 第 4 步：配置 Secrets

仓库页面 → **Settings → Secrets and variables → Actions** → New repository secret，添加两个：

| Name | Value |
|---|---|
| `GLADOS` | 第 3 步复制的完整 cookie |
| `GLADOS_UA` | 第 3 步复制的 user-agent |

## 第 5 步：验证

仓库 → **Actions** 标签 → 左侧选 "GLaDOS Auto Checkin" → **Run workflow** 手动触发一次。等十几秒刷新，点进运行记录看日志，出现下面任意一行即配置成功：

```
[...] 签到成功：Checkin! Got xx Points
[...] 今日已签到过：...
[...] 账号 xx***@xx.com：剩余 xx 天
```

之后就是全自动了，电脑关机也照跑。

## 踩坑清单（都是实际遇到过的）

1. **"没有权限"（code=-2）**：Cookie 过期（几个月一换）或浏览器升级导致 UA 变了。重新走第 3、4 步更新 Secrets 即可。
2. **GitHub 定时调度不可靠**：首跳丢失、延迟 20-60 分钟都是常态。对策就是上面 workflow 里的多点位 + 脚本幂等（"已签到"视为正常退出）。**修改 schedule 后的第一晚特别容易丢**，改完当晚建议手动触发一次。
3. **60 天无仓库活动，定时任务被自动禁用**：到 Actions 页面点 "Enable workflow" 恢复，或随便 push 一次 commit。
4. **积分多少与时段有关**：凌晨签积分多，所以点位全部排在 23:00-04:00；白天不设点位。
5. **额度**：免费 2000 分钟/月，本方案用量约 3-12%，无需担心。
6. **本地调试**：不用先推 GitHub，本地 `python3 glados_checkin.py` 配合 `config.json` 就能先验证凭据有效。

## 日常维护（唯一需要人做的事）

每隔几个月 Actions 日志出现"没有权限"时：重新登录网站取一次新的 Cookie 和 UA，更新两个 Secrets。其余情况零维护。
