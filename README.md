# 采蘑菇自动签到机

采蘑菇论坛（caimogu.cc）自动签到工具，每天自动在指定板块回复帖子，获取活跃度。

## 功能

- 自动登录采蘑菇论坛并回复帖子
- 支持 OpenAI 兼容 API 生成评论，或本地模板模式
- 自动跳过置顶帖和水帖
- 防重复机制：同一天多次运行不会重复回复，跨天 30 天内不重复
- 评论质量评分（0-100 分，六维度评估）
- 评论重复检测（n-gram + Jaccard 相似度，对比 7 天历史）
- 状态机管理帖子生命周期
- UNKNOWN 状态自动恢复，过期自动清理
- 关键问题弹窗通知
- 单实例锁，防止多实例并发冲突
- 支持开机自启动
- 随机延迟模拟真人行为

## Windows 日常使用

首次使用按顺序操作：

1. 双击 `启动签到.bat`，输入 `2`，在弹出的浏览器中手动登录采蘑菇论坛。
2. 双击 `设置AI.bat`，按提示设置 Key、接口地址和模型；不使用 AI 可跳过。
3. 双击 `启动签到.bat`，输入 `3`，预览评论生成效果，这一步不会实际发帖。
4. 双击 `启动签到.bat`，输入 `1`，执行自动签到。

确认没问题后，双击 `设置开机自启.bat` 即可开机后台自动签到；双击 `取消开机自启.bat` 可取消。

## 环境要求与安装

源码版需要：

- Windows 10/11
- Python 3.8+
- Playwright + Chromium

安装依赖：

```powershell
pip install -r requirements.txt
playwright install chromium
```

## 命令行使用

```powershell
python caimogu_signin.py             # 执行自动签到
python caimogu_signin.py --login     # 配置登录
python caimogu_signin.py --set-ai    # 设置 Key、接口地址与模型
python caimogu_signin.py --test      # 测试评论生成效果，不会实际发帖
python caimogu_signin.py --help      # 显示帮助
```

## 配置说明

编辑 `config.json`：

```json
{
  "circle_url": "https://www.caimogu.cc/circle/308.html",
  "reply_count": 3,
  "min_delay": 8,
  "max_delay": 20,
  "headless": true,
  "page_timeout_ms": 90000,
  "deepseek_base_url": "https://token.sensenova.cn/v1",
  "deepseek_model": "deepseek-v4-flash"
}
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `circle_url` | 签到板块网址 | 多人运动圈 |
| `reply_count` | 每天回复数量 | 3 |
| `min_delay` / `max_delay` | 每条回复间隔（秒） | 8-20 |
| `headless` | 是否无头模式 | true |
| `page_timeout_ms` | 页面超时时间（毫秒） | 90000 |
| `deepseek_base_url` | OpenAI 兼容 API 地址 | DeepSeek 官方 |
| `deepseek_model` | 模型名 | deepseek-chat |

## 设置 AI 接口

推荐双击 `设置AI.bat`，一次完成 Key、接口地址和模型设置；也可以运行：

```powershell
python caimogu_signin.py --set-ai
```

Key 会使用 Windows DPAPI 加密保存到 `api_key.enc`，绑定当前 Windows 用户。接口地址和模型写入 `config.json`。也可以只设置环境变量：

```powershell
$env:CAIMOGU_DEEPSEEK_API_KEY = "你的Key"
```

环境变量的优先级高于 `api_key.enc`。

### 更换接口和模型

脚本调用 OpenAI 兼容的 `/chat/completions` 接口。只要服务商提供这种接口，填入它的地址和模型名即可，没有固定服务商限制。一个 Key 对应一个 `deepseek_base_url`。

DeepSeek 官方示例：

```json
{
  "deepseek_base_url": "https://api.deepseek.com/v1",
  "deepseek_model": "deepseek-chat"
}
```

商汤日日新示例：

```json
{
  "deepseek_base_url": "https://token.sensenova.cn/v1",
  "deepseek_model": "deepseek-v4-flash"
}
```

## 评论生成机制

- **AI 模式**：根据帖子标题和正文生成自然回复
- **模板模式**：未配置 API Key 时自动使用
- 两种模式都会先判断帖子是否适合回复，`SKIP` 的帖子不会回复

## 防重复

- 每天已回复的数量记录在 `replied_posts.json`
- 同一天多次运行只补剩余数量
- 完成当天目标后自动跳过
- 跨天 30 天内不重复回复同一帖子
- 提交结果无法确认时进入待验证队列，不盲目重复提交

## 文件说明

核心文件：

| 文件 | 用途 |
|------|------|
| `caimogu_signin.py` | 主程序源码 |
| `config.json` | 配置文件 |
| `requirements.txt` | Python 依赖 |
| `启动签到.bat` | 主菜单 |
| `设置AI.bat` | 设置 AI Key、接口地址和模型 |
| `设置开机自启.bat` | 设置开机自启动 |
| `取消开机自启.bat` | 取消开机自启动 |
| `caimogu-auto-signin.spec` | exe 打包配置 |
| `dist\caimogu-auto-signin.exe` | 免安装可执行文件 |

运行生成的数据：

| 文件 | 用途 |
|------|------|
| `auth_state.enc` | 加密登录状态，请勿分享 |
| `api_key.enc` | 加密 API Key |
| `replied_posts.json` | 回复记录与执行详情 |
| `signin_log.txt` | 签到日志 |
| `daily_report.json` | 每日签到报告 |
| `signin.lock` | 单实例锁，运行后自动生成 |

## 常见问题

**登录状态失效怎么办？**

双击 `启动签到.bat`，输入 `2`，重新登录一次。

**如何取消开机自启动？**

双击 `取消开机自启.bat`。

**想改每天回复数量？**

用记事本打开 `config.json`，修改 `reply_count`。

**想改签到板块？**

修改 `config.json` 中的 `circle_url`。

**想看浏览器运行过程？**

把 `config.json` 中的 `headless` 改成 `false`。

**提示未安装 Playwright？**

执行：

```powershell
pip install -r requirements.txt
playwright install chromium
```

**出问题时排查哪些文件？**

优先查看 `signin_log.txt` 和 `daily_report.json`。

**第一次运行很慢？**

第一次需要初始化浏览器内核，之后会快很多。

## 安全与账号保护

- 登录 Cookie 和 API Key 都使用 Windows DPAPI 加密保存。
- 登录 Cookie 精简为站点功能 Cookie 白名单（`cmg_token`、`CAIMOGU`），第三方广告和统计 Cookie 会被过滤。
- 加密文件只允许当前 Windows 用户、SYSTEM 和管理员读取。
- 加密文件绑定当前 Windows 用户和这台电脑，复制到其他电脑或用户后无法解密。
- 如果旧版 `config.json` 仍包含 `deepseek_api_key`，新版首次运行会自动迁移并清空该字段。

## Windows 免安装版

不使用 Python 的用户可以运行 `dist\caimogu-auto-signin.exe`。使用方式与源码版一致：

```powershell
.\dist\caimogu-auto-signin.exe
.\dist\caimogu-auto-signin.exe --login
.\dist\caimogu-auto-signin.exe --set-ai
.\dist\caimogu-auto-signin.exe --test
```

## 免责声明

本工具仅供学习交流使用，请遵守论坛规则，合理使用。使用本工具产生的一切后果由使用者自行承担。

## License

[MIT](LICENSE)
