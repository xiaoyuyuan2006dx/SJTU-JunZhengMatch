# 发布前审阅记录

审阅日期：2026-10-26。范围包括前端预览与文档、Excel/CSV读写、匹配约束、教师维护与增量合并、后台脚本入口、持久数据目录、Docker及Windows发布流程。

## 本次修复

- 更新和删除明确区分数据库主键与教师编号，避免编号碰撞时定位或删除错误记录。
- 同名教师增量合并优先找到同院系记录，避免只检查首条同名记录后重复追加。
- 维护写入与脚本启动串行化；已有脚本运行时拒绝新的维护写入。
- 有效学生行缺少姓名、课题或导师时报出所在行，空白模板不能直接进行全库补位。
- 限制XLSX极端稀疏列及矩形展开大小，避免少量异常单元格放大内存占用。
- 教师库CSV导出同样使用公式文本转义；上传Base64、参数对象和合并策略增加校验。
- 本机服务验证Host；密码认证、跨站写入拒绝及会话隔离有回归验证。
- 院系卡片通过data属性传值，避免把院系名嵌入JavaScript字符串。
- 无控制台入口初始化标准流，后台脚本使用UTF-8输出管道；打包显式收集四个动态爬虫模块及其依赖。
- Windows构建增加真实EXE启动、页面资源、文档、匹配和两种导出验证；公开Release前先上传至草稿。
- 更新README、ARCHITECTURE、Windows说明，增加网页发布指南；当前背景图片按用户提供版本说明来源。

## 已完成的本地验证

- 30项单元与接口回归测试通过。
- 内置自检通过：6名虚构学生、18个评审位置、固定合并表任务横幅；四个爬虫模块可导入。
- 实际启动源码服务后验证页面、PNG、两份文档、数据库统计、示例模板、匹配、CSV和XLSX导出。
- 模拟标准输出/错误流不可用时，入口自检通过；Windows原生行为仍由Windows CI验证。
- Python源码解析、JavaScript语法、工作流YAML解析、差异空白及发布数据检查通过。
- 发布种子库保留737条公开教师记录；学生示例均为虚构，真实学生文件、日志及凭据未加入发布源码。

## 云端验证与发布结果

GitHub授权恢复后，源码已提交。首次Windows构建通过内部自检，但真实服务HTTP检查失败，因此未发布该构建。修复重定向输出编码、补充启动诊断及编码回归测试后，30项测试、Windows EXE内部自检、真实EXE服务匹配与导出检查、Docker构建和容器健康检查全部通过。

正式发行版为v1.0.1，对应构建提交1c3e1cf42103bfeff9fffb4827352ff1c888500b。验证工作流：https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/actions/runs/40302790686 。下载页面：https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/releases/tag/v1.0.1 。后续文档及发布脚本修订不会改写这个已发布版本标签。

没有对生产教师库执行全量爬取；仅检查脚本依赖、参数入口和运行路径。外部网站可用性、抓取完整性及研究方向的人工相关性仍需要实际业务确认。完整匹配模式允许低置信补位，相近分数不是经人工标注验证的准确率。

## 维护者参考

- PyInstaller无控制台模式：https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
- GitHub CLI发布命令：https://cli.github.com/manual/gh_release_create
- 本工程发布步骤：RELEASING.md

## v1.0.2内置图标验证

构建提交a53bf49109f26938c22308849c765e1d0c77b535，Windows构建的7份RT_ICON图像负载与用户所选ICO逐一匹配；内部自检、真实EXE服务匹配与导出及Docker检查全部通过。验证工作流：https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/actions/runs/40305345808 。
