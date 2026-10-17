# Antigravity 本地 Token 消耗统计大屏看板

基于 **FastAPI + Vue 3 + Element Plus + ECharts + pywebview** 构建的 Antigravity (反重力 CLI / IDE) 本地真实 Token 消耗与计费大屏桌面小工具。

无需联网调用外部脆弱接口，100% 本地 SQLite 深度解析，离线秒开，自带原生独立桌面软件窗口。


## ✨ 核心功能亮点

1. **原生独立桌面软件窗口与系统托盘常驻 (System Tray)**
   - 默认分辨率精准设定为 **宽 1024 像素 × 高 680 像素**，自带最小缩放保护与响应式自适应。
   - 调用 Windows 10/11 内置 Edge WebView2 渲染内核，以独立的 Windows 桌面客户端呈现。
   - **关闭窗口自动最小化到系统托盘**：点击右上角关闭按钮不退出程序，自动隐藏至 Windows 右下角托盘，不占用底部任务栏，后台静默持续监控。
   - **托盘鼠标悬浮实时指标 (Tooltip)**：光标悬停即可直接预览当前 5H 水位与下批释放倒计时（如 `⚡ 5H已用: 12.5M (92%) | ⏳ 42分后释放 1.8M`）。
   - **托盘丰富右键菜单**：
     - `📈 打开看板`：一键快速还原前置窗口；
     - `🔄 立即刷新数据`：后台重新扫描 SQLite 数据库并弹窗气泡提示；
     - `🚀 开机自动启动`：一键无感切换 Windows 用户注册表开机自启；
     - `❌ 彻底退出`：平稳释放端口并彻底安全退出。

2. **核心指标卡片：大字 M/B 进位计数 + 小字精准 Token**
   - **大字体**：统一采用 **`M`**（百万）为主要计数单位（如 `119.71 M`、`0.48 M`）；当累计达到 10 亿时**自动自然进位至 `B`**（如 `1.25 B`）。
   - **小字体**：在大字正下方完整展示**精准无误的 Token 整数**（如 `119,714,682 Tokens`）。

3. **💰 商业 API 费用预估与 Prompt Caching 节省分析 (默认折叠)**
   - 折叠态仅占极窄高度，标题旁带精炼的预估总额与节省预览标签（如 `预估: $10.05 | 缓存已省: $81.69 (-89.0%)`）。
   - 支持**促销期（2026年底前）**与**标准期（2027年起）**官方费率无缝切换。
   - 支持**美元 ($)** 与 **人民币 (¥)** 双币种换算（USD/CNY ≈ 7.23）。
   - 四项拆分核算：未缓存新增输入、Prompt 缓存命中费（仅原价 5%）、输出与深度思考推理费、Prompt 缓存累计节省总额。

4. **🛡️ 5小时滑动释放 & 自然周限额监控中心**
   - **⏱️ 5小时滑动窗口 (5H Rolling Window)**：
     - 实时统计过去 5 小时内各模型真实总吞吐与调用轮次。
     - **⏳ 下批额度释放倒计时（本地真实计算）**：根据滑动窗口原理，精准预测最早一批消耗将在几分几秒后滑出 5H 窗口，预计恢复多少 Token。
   - **📅 自然周限额与日均燃烧率 (Weekly Limit)**：
     - 统计本周一 00:00 至今的累计真实消耗。
     - **🔥 过去 7 天日均燃烧率**：滑动评估平均每日使用强度。
     - **🔄 自然周重置倒计时**：精确倒数至下周一 00:00 重置时刻。
   - **✏️ 手动校准 / 填报配额**：
     - 支持填入官方剩余百分比与重置时间描述，一键快捷设定 1~5 小时。
     - 设定自动开启秒表实时倒计时，并持久化保存在本地。

5. **📈 全宽走势折线图与默认折叠模型分布**
   - **走势折线图**：全宽通栏展示，今日/昨日按小时聚合，周/月/历史按天聚合，支持滚轮缩放与图例筛选。
   - **模型分布分析**：**默认折叠收起**，标题旁带已用模型标签预览（如 `claude-3-7-sonnet: 58.20 M`），点击即刻平滑展开环形饼图。

6. **每轮 Token 生成速度 (Tokens/s) 与耗时统计**
   - 提取 Protobuf 内部纳秒级生命周期时间戳，计算每一轮调用的端到端耗时与**生成速度 (Output Tokens/s)**。
   - 会话抽屉中逐轮清晰展示 `⏱ 耗时: 2.6s`、`⚡ 速率: 480.2 tok/s`、`🚀 首字: 0.8s`。

7. **时间维度快速筛选**
   - **今日**（当天 00:00 至今）
   - **昨日**（昨日 00:00 至 23:59）
   - **本周**（近 7 天滑动窗口）
   - **本月**（近 30 天滑动窗口）
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

#### 方式 1：双击运行原生独立桌面应用（强烈推荐）
在文件夹内双击运行：
👉 **`start_desktop.vbs`** *(纯静默启动，零黑框、零闪现，最推荐)*
或
👉 **`start_desktop.bat`** *(自动隐藏黑框后台运行)*
*(以 1024x680 原生独立 Windows 客户端窗口运行，像一个真正的桌面软件)*

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
│   └── test_all.py        # 覆盖前后端与脚本的 17 项全量自动化测试集
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

## 📄 开源许可

[MIT License](LICENSE)
