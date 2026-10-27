# Windows 使用说明

1. 从 [Release](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/releases/latest) 下载 portable.zip 或 setup.msi。
2. 便携版解压后双击 EXE，浏览器首次提示数据目录；安装版在安装界面选择数据目录，从快捷方式打开独立窗口。
3. 上传填写好的模板，匹配预览，导出 CSV 或合并单元格 XLSX。无需安装 Python。

安装或升级前，请通过退出贴纸停止正在运行的服务，再运行安装包。

默认数据目录是 `%USERPROFILE%\JunZhenMatch`，程序自带737条网络公开教师记录。后续修改保存在外部目录，不会打进 EXE。

MSI 安装本身不下载组件，显示实际进度和当前步骤，通常约10–30秒。缺少 WebView2 时，首次启动独立窗口会显示组件下载说明、已等待时间及微软安装进度；通常约1–3分钟，网络较慢时最多等待5分钟。失败可检查网络后重试，或运行安装目录中的 `MicrosoftEdgeWebview2Setup.exe`。直接双击 `JunZhengMatch.exe` 可使用浏览器，不依赖 WebView2。

v1.1.1 修复重复打开或修复 MSI 时的2753错误；已经安装v1.1.0可直接升级，数据目录保留。发布者字段为 `xiaoyuyuan2006dx`；这不等于数字签名。

两版使用相同目录时共用后台及教师库。关闭标签页或窗口只关闭界面；右上角“退出程序”停止共享服务，多界面在线时会提示确认，任务运行期间不可退出。退出后再次打开快捷方式或 EXE 即可启动。

“偏好设置”可选择路径、迁移数据、导入导出教师数据及保存匹配默认参数。移动数据前等待任务完成；迁移保留原文件。不保留上传原表，导出文件保存在 `exports`。卸载安装版保留数据目录，需删除时请自行备份后处理。

旧版数据目录通常为 `%LOCALAPPDATA%\SJTU-JunZhengMatch`；可以在偏好设置选择旧数据目录（确认后自动使用已有库），或将其中 `sjtu_faculty_data.db` 作为备份恢复到新目录。

端口冲突会自动使用可用端口。需指定端口可在快捷方式目标后添加 `--port 8080`。独立窗口版快捷方式带 `--desktop`；便携 EXE 默认打开浏览器。

程序未作商业代码签名。可用 PowerShell `Get-FileHash 文件名 -Algorithm SHA256` 与 Release 中 SHA256SUMS.txt 核对。发布步骤见 [RELEASING.md](RELEASING.md)。

浏览器的“不常下载／请确认信任此文件”属于下载信誉提示，不等同于病毒检测结论。更改发布者字段不能替代可信代码签名；即使正规签名的新程序也可能需要积累信誉。当前版本未签名，因此不能保证消除此提示。原理见 [微软说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)；若提示明确检测到病毒或恶意软件，应进一步排查，不能与“不常下载”混为一谈。
