# Antigravity 本地 Token 消耗统计大屏看板

基于 **FastAPI + Vue 3 + Element Plus + ECharts + pywebview** 构建的 Antigravity (反重力 CLI / IDE) 本地真实 Token 消耗与计费大屏桌面小工具。

Token 统计无需联网，本地 SQLite / JSONL 解析，官方配额可选联网同步，自带原生独立桌面软件窗口。


## ✨ 核心功能亮点

1. **原生独立桌面软件窗口与系统托盘常驻 (System Tray)**
   - 默认分辨率精准设定为 **宽 1024 像素 × 高 680 像素**，自带最小缩放保护与响应式自适应。
   - 调用 Windows 10/11 内置 Edge WebView2 渲染内核，以独立的 Windows 桌面客户端呈现。
   - **关闭窗口自动最小化到系统托盘**：点击右上角关闭按钮不退出程序，自动隐藏至 Windows 右下角托盘，不占用底部任务栏，后台静默持续监控。
   - **托盘鼠标悬浮实时指标 (Tooltip)**：显示 Antigravity 近 5H 本地用量，以及最近一次有效查询的官方 Gemini 5H 剩余比例；官方快照失效后提示待查询。
   - **托盘丰富右键菜单**：
     - `📈 打开看板`：一键快速还原前置窗口；
     - `🔄 立即刷新数据`：后台重新扫描 SQLite 数据库并弹窗气泡提示；
     - `🚀 开机自动启动`：一键无感切换 Windows 用户注册表开机自启；
     - `❌ 彻底退出`：平稳释放端口并彻底安全退出。

2. **核心指标卡片：大字 M/B 进位计数 + 小字精准 Token**
   - **大字体**：统一采用 **`M`**（百万）为主要计数单位（如 `119.71 M`、`0.48 M`）；当累计达到 10 亿时**自动自然进位至 `B`**（如 `1.25 B`）。
   - **小字体**：在大字正下方完整展示**精准无误的 Token 整数**（如 `119,714,682 Tokens`）。

3. **按工具与模型配置参考单价**
   - 在「配置模型单价」中为各工具、模型分别填写 USD / 百万 Token 单价和参考汇率。
   - 分别计算未缓存输入、缓存读取、缓存写入与输出（包含思考），概览、会话和 CSV 使用同一计算方法。
   - 未配置价格的模型显示「未配置价格」；只配置部分模型时，金额明确标记为已定价部分。
   - 费用是按所填单价的估算，不含缓存存储费、长上下文或其他阶梯价格，也不代表订阅账单。

4. **官方配额快照与本地用量**
   - 通过本机 `agy -p /usage --output-format json` 获取 Antigravity 官方配额；按服务商返回的模型组分别展示剩余比例与实际重置时间。
   - 配额查询有 120 秒缓存；页面开启自动刷新时定期同步。旧快照、查询失败和重置时间已过都会明确提示。
   - 本地统计按当前选择的工具展示近 5 小时、本周和近 7 天 Token 用量。
   - 最早记录移出本地 5H 窗口不代表官方额度恢复；本周本地统计也不代表官方周配额窗口。
   - 手动填报保留原始剩余比例、记录时间和重置倒计时，不再通过不同工具的 Token 数推算订阅余额。未填报或已过期时不虚构剩余额度。

5. **📈 全宽走势折线图与默认折叠模型分布**
   - **走势折线图**：全宽通栏展示，今日/昨日按小时聚合，周/月/历史按天聚合，支持滚轮缩放与图例筛选。
   - **模型分布分析**：**默认折叠收起**，标题旁带已用模型标签预览（如 `claude-3-7-sonnet: 58.20 M`），点击即刻平滑展开环形饼图。

6. **每轮 Token 生成速度 (Tokens/s) 与耗时统计**
   - 提取 Protobuf 内部纳秒级生命周期时间戳，计算每一轮调用的端到端耗时与**生成速度 (Output Tokens/s)**。
   - 会话抽屉中逐轮清晰展示 `⏱ 耗时: 2.6s`、`⚡ 速率: 480.2 tok/s`、`🚀 首字: 0.8s`。

7. **时间维度快速筛选**
   - **今日**（当天 00:00 至今）
   - **昨日**（昨日 00:00 至 23:59）
   - **近 7 天**（含今日的 7 个自然日）
   - **近 30 天**（含今日的 30 个自然日）
   - **历史总计**（所有可用会话）
   - **自定义日期**（自由指定起止日期）

8. **会话与轮次明细数据表**
   - 关联 `conversation_summaries.db` 展示真实会话标题。
   - 关键词搜索、分页切换、按活跃时间倒序排列。
   - 一键导出 UTF-8 BOM CSV 报表（包含耗时、速率与单会话预估费用）。

---

## 🚀 快速启动

### 依赖安装
```bash
pip install -r requirements.txt
```

### 启动方式

#### 方式 1：双击运行原生独立桌面应用（强烈推荐，彻底零黑框）
在文件夹内双击运行以下任一文件即可打开独立客户端：
- 👉 **`启动大屏(无黑框).vbs`** 或 **`start_desktop.vbs`** *(调用 Windows 原生 GUI 解释器 wscript，绝对零黑框、零闪现，毫秒级静默直启)*
- 👉 **`start_desktop.bat`** *(批处理方式，兼容命令行环境运行)*

*(以 1024x680 原生独立 Windows 客户端窗口运行，具备独立任务栏图标、系统托盘常驻与关闭最小化)*

#### 方式 2：双击以浏览器模式运行
在文件夹内双击运行：
👉 **`start.bat`**
*(后台运行并在系统默认浏览器中打开 `http://127.0.0.1:8765`)*

#### 方式 3：命令行启动
```powershell
# 启动独立桌面客户端
python desktop.py

# 或启动浏览器模式
python run.py
```

---

## 📦 打包为独立 EXE 或 Windows 安装包

本项目支持将 Python 源码、FastAPI 服务、pywebview 与全部前端离线库完整打包为 **无需安装 Python 即可在任何 Windows 电脑运行的独立 EXE** 或 **标准 Windows 安装包向导（Setup.exe）**。

### 方式 1：一键自动打包单文件 EXE（最简单）

项目根目录已内置打包配置与脚本，双击或在终端中运行：
👉 **`build_exe.bat`**

脚本会自动安装 `pyinstaller`，并根据预设的 `AntigravityDashboard.spec` 规格文件进行编译构建：
- 自动内嵌 `static/` 离线前端库与单文件 HTML；
- 自动补充 `uvicorn`、`fastapi`、`pywebview` 等异步与 GUI 隐式依赖；
- 自动配置无控制台黑框运行；
- 生成产物位于 **`dist/AntigravityDashboard.exe`**，可直接拷贝分享给他人双击使用。

---

### 方式 2：命令行手动使用 PyInstaller 打包

如果习惯使用命令行，可以按需选择以下两种模式：

#### 模式 A：单文件绿色版（便于分发单个文件）
```powershell
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 执行一键编译
pyinstaller AntigravityDashboard.spec --clean
```
构建成功后，在 `dist/` 目录下即可找到单一的 `AntigravityDashboard.exe`。

#### 模式 B：绿色目录版（启动更快，<0.5秒秒开）
若希望启动更迅速（省去每次启动时解压到临时目录的时间）：
```powershell
pyinstaller --onedir --noconsole --name AntigravityDashboard `
  --add-data "static;static" `
  --add-data "data;data" `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.h11_impl `
  --hidden-import uvicorn.lifespan.on `
  --hidden-import clr `
  --hidden-import pythonnet `
  desktop.py
```
构建产物位于 `dist/AntigravityDashboard/` 文件夹中。

---

### 方式 3：制作专业 Windows 安装向导包（Setup.exe）

若需要发布给普通用户，提供类似商业软件的桌面快捷方式、开始菜单图标与控制面板卸载功能：

1. 先执行 `build_exe.bat` 生成 `dist/AntigravityDashboard.exe`；
2. 下载并安装免费开源的 [Inno Setup 6](https://jrsoftware.org/isdl.php)；
3. 用 Inno Setup 打开项目中的 **`installer/setup.iss`** 脚本；
4. 点击顶部菜单 **`Build` -> `Compile`**（或快捷键 `Ctrl + F9`）；
5. 编译完成后，将在 `dist_installer/` 目录生成 **`Antigravity_Token_Dashboard_Setup_v1.0.0.exe`** 标准中文安装包向导。

---

## 📂 项目结构

```text
antigravity_token_dashboard/
├── backend/
│   ├── app.py             # FastAPI 核心服务端与路由（内置 PyInstaller 冻结路径自适应）
│   ├── scanner.py         # SQLite 扫描解析、时序聚合、滑动释放计算与费用核算
│   └── parser.py          # 会话明细、纳秒耗时与速率提取引擎
├── static/
│   ├── libs/              # 内置离线前端库（Vue 3, Element Plus, ECharts 等）
│   └── index.html         # Vue 3 + Element Plus + ECharts 单文件响应式前端
├── data/
│   └── .gitkeep           # 本地持久化配置目录
├── tests/
│   └── test_all.py        # 覆盖前后端与脚本的 自动化测试集
├── installer/
│   └── setup.iss          # Inno Setup 6 Windows 安装向导配置文件
├── AntigravityDashboard.spec # PyInstaller 规范打包配置文件
├── build_exe.bat          # 一键编译生成独立 EXE 批处理
├── desktop.py             # pywebview 桌面端包装（1024x680 独立窗口、无黑框与端口管理）
├── desktop_tray.py        # Windows 原生系统托盘管理器（关闭防退出、实时Tooltip指标、开机自启）
├── run.py                 # 网页模式启动器
├── requirements.txt       # Python 依赖清单
├── start_desktop.vbs      # 原生极简静默桌面启动器（零黑框）
├── start_desktop.bat      # Windows 桌面版一键启动脚本
├── start.bat              # Windows 网页版一键启动脚本
└── README.md              # 项目文档
```

---

## 数据与计算口径

- Antigravity：`~/.gemini/antigravity-cli/conversations/*.db`，标题来自 `conversation_summaries.db`；缓存同时跟踪 SQLite 主文件与 WAL 的修改时间和大小。
- Codex：`~/.codex/sessions/` 和 `~/.codex/archived_sessions/`，支持 `.jsonl` / `.jsonl.zst`。缓存读取和写入属于输入的子集，思考属于输出的子集；累计用量有缺口时保留可恢复的增量，这类记录可能汇总多次调用。
- Claude Code：`~/.claude/projects/**/*.jsonl`，包括子代理日志。同一消息 ID 的流式文本、工具内容块共享用量，只累计一次，并保留各项最大用量。
- 两种 JSONL 的 UTC 时间均先转为本地时间，再用于日期筛选和小时分组。
- 默认目录可用 `GEMINI_CLI_HOME`、`CODEX_HOME`、`CLAUDE_CONFIG_DIR`（兼容 `CLAUDE_HOME`）指定。
- 总 Token = 未缓存输入 + 缓存读取 + 缓存写入 + 输出；输出已包含思考，不重复相加。
- `data/quota_config.json` 保存手动配额快照；`data/pricing_config.json` 保存每个工具/模型的自定义单价。两者均不提交到 Git。

安装测试依赖并运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

测试的配置写入使用临时目录，不覆盖用户的本地配置。JavaScript 语法检查在安装 Node.js 时运行。

## 📄 开源许可

[MIT License](LICENSE)
