# Architecture

## 结构

```text
frontend/              Gemini 前端基础上的内容列宽、两行研究方向和主题修订
web_server.py          HTTP接口、会话隔离、数据库维护、脚本后台运行
sjtu_excel_io.py       标准库Excel/CSV读写、任务横幅、虚构示例
sjtu_match_reviewers.py 离线匹配、规则扩展、完整/严格匹配模式
sjtu_query_db.py       院系规范化及原终端工具（Web不依赖终端）
sjtu_*scraper.py       保留的爬虫和补全脚本
entrypoint.py          源码与Windows EXE通用入口，内置自检
data/faculty.db        用户确认可随包发布的现有公开教师库（记录完整保留）
examples/              空白输入模板及虚构学生模板
tools/privacy_check.py 发布包自动去敏检查
JunZhengMatch.spec     Windows原生单文件构建
.github/workflows/     单元测试、Windows验证、Docker构建和Release发布
```

## 数据流

上传 XLSX/CSV → 定位第一张表的表头和学生 → 应用筛选参数 → 加载当前教师库只读快照 → 计算研究方向与课题推荐分 → 返回预览 → 按当前浏览器会话导出 CSV/XLSX。

原始上传的首行任务横幅可读，但导出统一使用无负责人和实际日期的可填写横幅。示例入口和示例模板下载使用同一个虚构数据生成函数，不会读取本机真实学生表。

## 列宽与可读性

短字段用 Canvas 按当前字体测量整份结果中的最长值及表头，然后固定为整数像素宽度。课题等长字段分配剩余空间。分页不重新用当前页缩小短字段。数据库响应提供全部筛选结果的候选最长字段用于同样测量。匹配预览的弹性列按容器剩余宽度收缩，窄屏使用带字段标签的卡片而非横向滚动。学号前三位与匹配方向前四字仅在预览中缩写，title及导出保留完整内容。数据库列宽为姓名最多100px、职称最多112px、院系180px，研究方向至少340px。院系概览与下拉选项使用浏览器 Intl.Collator 的中文拼音排序。

数据库研究方向使用两行 line-clamp；有文本的记录保留两行高度，空值只显示短横线。全文保留在 title 和编辑窗口内。

## 会话与写入边界

同源 JSON 写入；拒绝跨来源POST。结果缓存由256位随机HttpOnly、SameSite=Strict Cookie区分，不共享“最后一次结果”。缓存上限100个会话、闲置24小时失效。非本机绑定需访问密码。上传有请求体及解压大小限制。

数据库维护属于管理员级能力，当前没有细分角色。程序只允许运行白名单脚本；浏览器不能传任意Shell命令。写入前生成SQLite备份，后台脚本运行期间禁止人工写入。公网部署仍需HTTPS、反向代理、网络访问控制及业务数据保护策略。

## 发布边界

生产数据和私有导出留在用户配置的数据目录。Git/Docker/EXE的静态资源只含公开教师库和虚构学生示例。CSV对可能被Excel当作公式的外部文本做转义；XLSX文本使用内联字符串。

Windows runner 构建并运行 EXE 自检；Linux runner 构建、启动 Docker 并检查健康接口。只有这两个任务成功，标签对应的 GitHub Release 才上传可执行文件与镜像归档。
