# 䇹政盲审导师匹配

浏览器中的课题评审匹配与教师库维护工具。支持上传、匹配预览、横式 CSV 和合并单元格 Excel 导出。

TaroDeluxe · Codex & SJTU ZhuXueBu & CTP

## 使用

Windows 发行文件由 GitHub Actions 构建并验证。发布后，在 [Releases](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/releases) 下载 `JunZhengMatch.exe` 或 Windows ZIP 包，双击 EXE 后在浏览器中操作，无需安装 Python。若暂时没有发行附件，可以先运行源码：

```bash
python -m pip install -r requirements.txt
python entrypoint.py
```

默认地址 `http://127.0.0.1:8765`。`--port 8080` 可更换端口，`--no-open` 适合后台启动。

## 输入格式

可直接在页面下载空白 XLSX/CSV 模板，或点击“下载示例模板”。示例学生使用张三、李四、王五、赵六、孙七、周八，学号以 `52x` 开头，导师为陈老师等虚构信息；发布自带现有网络公开教师库，解压运行即可匹配。

表头如下，列顺序可以调整：

| 列名 | 要求 |
|---|---|
| 序号 | 必须保留列名；值可留空自动编号 |
| 课题类别 | 选填 |
| 学生姓名 | 必填 |
| 学生学号 | 选填，建议将整列设为文本 |
| 课题中文 | 必填，也接受“课题” |
| 导师姓名 | 必填，用于回避指导老师 |
| 导师院系 | 选填，也接受“导师学院” |

示例课题类别沿用原表的五类：人文社科类、信息技术类、机械控制自动化类、生农医药类、能源化工材料类。上传文件的类别原样保留，不自动生成类别。

空白模板只有一行表头，没有真实学生记录；填写后再上传。学生姓名、课题中文和导师姓名缺失会报出所在行，避免缺少导师信息导致无法回避。

支持单横行名单和首行带任务说明、每人占三行的合并表。XLSX最多读取10000行、256列及200万个矩形单元格，解压内容上限100MB。仅读取第一张工作表；公式字段需要 Excel 已保存的计算结果，不会执行公式或宏。仅支持 `.xlsx` 和 `.csv`；请保持学生姓名、课题和导师姓名在同一数据行。

## 两种导出

- **横式 CSV**：每位学生一行，前七列保持学生信息，随后按“评审1…K”展开姓名、学院、职称、电话、邮箱、研究方向、匹配方向和相近程度。不含“是否人工核验”列。UTF-8 BOM，方便 Excel 打开。
- **合并单元格 XLSX**：保留原来成品表的十三列结构，每位学生的前七列纵向合并，评审逐行展开。首行始终使用可填写的任务说明模板，负责人和截止日期保留占位，不继承上传成品中的真实负责人或时间。

相近程度是程序的综合推荐分，不是经标注验证的正确率。匹配预览中学号显示前三位加省略号，匹配方向显示前四字，悬停可查看完整值；导出保留完整内容。桌面表格按可用宽度分配列宽，窄窗口改为带字段标签的卡片，无需横向滚动。教师库姓名、职称、院系列收窄，研究方向留出更多空间并显示两行。院系概览按拼音 A–Z 排序。背景装饰图来源见 ASSETS.md。

## 匹配参数

保留全部学生、序号范围、单个序号和姓名关键词筛选；支持 `--pick`、`--pool`、`--strategy top/weighted`、`--seed`、`--min-score`、`--relative-score`、`--strict`、`--allow-unknown-title` 对应的页面参数。

默认每人三位、自动补齐，回避指导老师、明确正高和职称不明记录。不同学生可以复用相关教师；同一学生不重复。严格模式只返回通过阈值的候选，可能不足人数。

## 教师数据库与增量维护

“数据库维护”页面支持检索、新增、编辑、删除、院系统计，以及教师表的增量合并。增量合并可先预览，再执行；院系缺失时支持保留更丰富记录、跳过或追加。

保留四个爬取入口和原参数：教师基本信息爬取、研究方向增量爬取、主页补扫院系、网络搜索补院系。覆盖已有数据需要勾选对应选项。运行维护脚本时暂不允许人工写入；写入前会保留最多二十份本地数据库备份。爬取依赖公开站点的可用性，不保证每次获取完整数据。

## 数据与去敏

发布包保留 `data/faculty.db` 中现有网络公开教师记录和联系方式，下载后即可匹配；仅学生示例为虚构。不含学生原表、上传记录、旧负责人/截止日期、运行日志或凭据。程序首次运行将公开教师库复制到可写数据目录，也可在数据库页继续维护。

数据目录可由 `JZ_DATA_DIR` 指定。Windows 默认 `%LOCALAPPDATA%\SJTU-JunZhengMatch`，macOS 默认 `~/Library/Application Support/SJTU-JunZhengMatch`，Linux 默认 `$XDG_DATA_HOME/SJTU-JunZhengMatch`（未设置则使用 `~/.local/share`）。原桌面工程已有的 `sjtu_faculty_data` 数据目录仍兼容。

匹配结果在内存中按浏览器随机会话隔离，闲置24小时后失效，服务重启清空；真实上传内容不写入发布目录。

## Docker

```bash
JZ_PASSWORD='请改为至少12字符的实际密码' docker compose up -d --build
```

Compose 默认仅映射主机本地端口，并持久化 `/data`。服务器对非本机地址监听时必须设置至少12字符的 `JZ_PASSWORD`，浏览器使用 HTTP Basic 登录（用户名可任意填写）。公网访问应由管理员配置 HTTPS 反向代理。

发布工作流成功后，Release 同时提供经过构建和启动检查的 Docker 镜像归档，可使用 `docker load -i SJTU-JunZhengMatch-Docker.tar.gz` 导入。不向未知 Docker Hub 账户推送镜像。

## Windows EXE 与 CI

GitHub Actions 在原生 Windows x64 runner 上使用 PyInstaller 生成单文件、无控制台 EXE，程序包含 Python 运行时、前端和737条公开教师记录。构建后执行内置自检，并启动真实 EXE，检查页面、图片、文档、示例匹配和两种导出。Linux runner 构建并验证 Docker 镜像。

只有测试、Windows 和 Docker 三部分全部成功，工作流才先上传附件到草稿 Release，再公开发布；失败时保留构建日志。推送 `v*` 标签可触发，也可直接在 GitHub 的 Actions 页面选择版本号发布，无需本地 Windows 环境。具体点击步骤见 [发布指南](RELEASING.md)，日常使用见 [Windows 使用说明](WINDOWS.md)。

开发验证：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python entrypoint.py --self-test --report self-test.json
python tools/privacy_check.py
python tools/verify_app.py --report http-self-test.json
```

## 视觉说明

保留暖米白与浅杏风格，加入金色星结、奶油金按钮，以及用户选定的琴音小人图片。图片原样随前端打包，不需要联网加载；来源说明见 [ASSETS.md](ASSETS.md)。

装饰位于页面侧边背景，使用淡化和正片叠底，不接受鼠标点击。窗口宽度不足1480px时隐藏，避免遮挡表格。右下角水印为 `TaroDeluxe · Codex & SJTU ZhuXueBu & CTP`。
