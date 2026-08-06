# 采蘑菇自动签到机

采蘑菇论坛（caimogu.cc）自动签到工具，每天自动在指定板块回复帖子，获取活跃度。

## 功能

- 自动登录采蘑菇论坛并回复帖子
- 支持 AI 生成评论（DeepSeek / 商汤日日新）或模板模式
- 自动跳过置顶帖和水帖
- 防重复机制：同一天多次运行不会重复回复
- 支持开机自启动
- 随机延迟模拟真人行为

## 快速开始

### 环境要求

- Python 3.8+
- Playwright + Chromium

### 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

### 使用

```bash
# 1. 配置登录（首次使用）
python caimogu_signin.py --login

# 2. 测试评论生成效果（不会实际发帖）
python caimogu_signin.py --test

# 3. 执行签到
python caimogu_signin.py

# 查看帮助
python caimogu_signin.py --help
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
  "deepseek_api_key": "",
  "deepseek_base_url": "https://api.deepseek.com/v1",
  "deepseek_model": "deepseek-chat"
}
```

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `circle_url` | 签到板块网址 | 多人运动圈 |
| `reply_count` | 每天回复数量 | 3 |
| `min_delay` / `max_delay` | 回复间隔（秒） | 8-20 |
| `headless` | 是否无头模式 | true |
| `deepseek_api_key` | AI API Key（留空则用模板模式） | 空 |
| `deepseek_base_url` | API 地址 | DeepSeek 官方 |
| `deepseek_model` | 模型名 | deepseek-chat |

### 使用商汤日日新免费额度

```json
{
  "deepseek_api_key": "你的商汤Key",
  "deepseek_base_url": "https://token.sensenova.cn/v1",
  "deepseek_model": "deepseek-v4-flash"
}
```

## 评论生成机制

- **AI 模式**（推荐）：填入 API Key 后，根据帖子标题和正文生成自然回复
- **模板模式**：无 API Key 时自动使用，根据帖子类型匹配模板
- 两种模式都会先判断帖子是否适合回复（REPLY/SKIP），SKIP 的帖子不会被回复

## 防重复

- 每天已回复的数量记录在 `replied_posts.json`
- 同一天多次运行只补剩余数量
- 完成当天目标后自动跳过

## Windows 免安装版

不想装 Python 的用户可以使用打包好的 exe 版本：

1. 下载 Release 中的 ZIP 包
2. 解压后双击 `启动签到.bat`
3. 按提示操作

## 免责声明

本工具仅供学习交流使用，请遵守论坛规则，合理使用。使用本工具产生的一切后果由使用者自行承担。

## License

[MIT](LICENSE)
