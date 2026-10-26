# GLaDOS 自动签到

每天自动完成 [glados.rocks/console/checkin](https://glados.rocks/console/checkin) 的签到，无需手动打开网站。

**原理**：你点击"签到"按钮时，浏览器实际是向 `https://glados.rocks/api/user/checkin` 发了一个 POST 请求。本脚本带上你登录后的 Cookie 复现这次请求，签到结果和手动点击完全一样。

## 第一步：获取 Cookie 和 User-Agent（只需 2 分钟）

1. 用浏览器登录 [glados.rocks](https://glados.rocks)
2. 按 `F12` 打开开发者工具，切换到 **Application**（应用）→ **Cookies** → `https://glados.rocks`
3. 找到 `koa:sess` 和 `koa:sess.sig` 两项，复制各自的值，拼成一行：
   ```
   koa:sess=值1; koa:sess.sig=值2
   ```
   （如果列表里还有 `gld:sess` / `gld:sess.sig`，也一并拼进去，用 `; ` 分隔）
4. 获取 User-Agent：在开发者工具的 **Console**（控制台）输入 `navigator.userAgent` 回车，复制输出
   ⚠️ GLaDOS 会校验请求的 UA 是否与登录浏览器一致，不一致会返回"没有权限"
5. 复制 `config.example.json` 为 `config.json`，把上面两个值填进去

## 第二步：手动验证一次

```bash
python3 glados_checkin.py
```

看到 `签到成功` 或 `今日已签到过` 以及剩余天数即表示配置正确。

## 第三步：定时自动执行（三选一）

### 方案 A：ZCode 定时任务（推荐，零配置）

直接告诉 ZCode"帮我每天 XX 点跑签到脚本"，它会用内置的定时自动化每天自动执行本目录的脚本，不需要你保留任何东西。前提：已完成第一步的 `config.json`。

### 方案 B：GitHub Actions（电脑不用开机）

1. 把本目录推到一个 **私有** GitHub 仓库（cookie 是敏感信息，切勿公开）
2. 仓库 Settings → Secrets and variables → Actions 添加两个 Secret：
   - `GLADOS` = 你的完整 cookie
   - `GLADOS_UA` = 你的 User-Agent
3. 仓库已带 `.github/workflows/checkin.yml`，每天北京时间 00:10 自动运行，Actions 页面可手动触发验证

### 方案 C：本地 cron（有一台常开的 Linux 机器）

```bash
crontab -e
# 添加一行（路径改成实际位置，每天 00:10 执行，日志写入 checkin.log）：
10 0 * * * /usr/bin/python3 /path/to/glados_checkin.py >> /path/to/checkin.log 2>&1
```

macOS 用 `launchd` 或同样用 crontab；Windows 用"任务计划程序"每天运行该命令。

## 常见问题

- **返回"没有权限"（code=-2）**：Cookie 过期，或浏览器大版本更新导致 UA 变了。重新登录网站，更新 `config.json` 里的两个值即可。Cookie 通常能用几个月。
- **GitHub Actions 没有准点运行**：Actions 的 schedule 普遍有几分钟到几十分钟延迟，属正常现象，不影响签到。
- **Actions 突然不跑了（超过 60 天没动过仓库）**：GitHub 会自动禁用长期无活动仓库的定时任务，到仓库 Actions 页面点 "Enable workflow" 重新启用即可。
- **签到结果显示 "Get 0 day"**：正常，是签到奖励的概率机制，签到本身已成功。
- **多账号**：每份 cookie + UA 各建一个 `config.json` 所在目录，分别运行脚本即可。

## 文件说明

| 文件 | 用途 |
|---|---|
| `glados_checkin.py` | 签到脚本（纯 Python 标准库，无需安装依赖） |
| `config.example.json` | 配置模板，复制为 `config.json` 后填写 |
| `.github/workflows/checkin.yml` | 方案 B 的 GitHub Actions 工作流 |
