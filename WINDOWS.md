# Windows 使用说明

1. 从 [Release](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/releases/latest) 下载 portable.zip 或 setup.msi。
2. 便携版解压后双击 EXE，浏览器首次提示数据目录；安装版在安装界面选择数据目录，从快捷方式打开独立窗口。
3. 上传填写好的模板，匹配预览，导出 CSV 或合并单元格 XLSX。无需安装 Python。

默认数据目录是 `%USERPROFILE%\JunZhenMatch`，程序自带737条网络公开教师记录。后续修改保存在外部目录，不会打进 EXE。安装版可能联网安装微软 WebView2 环境。

两版使用相同目录时共用后台及教师库。关闭标签页或窗口只关闭界面；右上角“退出程序”停止共享服务，多界面在线时会提示确认，任务运行期间不可退出。退出后再次打开快捷方式或 EXE 即可启动。

“偏好设置”可选择路径、迁移数据、导入导出教师数据及保存匹配默认参数。移动数据前等待任务完成；迁移保留原文件。不保留上传原表，导出文件保存在 `exports`。卸载安装版保留数据目录，需删除时请自行备份后处理。

旧版数据目录通常为 `%LOCALAPPDATA%\SJTU-JunZhengMatch`；可以在偏好设置选择旧数据目录（确认后自动使用已有库），或将其中 `sjtu_faculty_data.db` 作为备份恢复到新目录。

端口冲突会自动使用可用端口。需指定端口可在快捷方式目标后添加 `--port 8080`。独立窗口版快捷方式带 `--desktop`；便携 EXE 默认打开浏览器。

程序未作商业代码签名。可用 PowerShell `Get-FileHash 文件名 -Algorithm SHA256` 与 Release 中 SHA256SUMS.txt 核对。发布步骤见 [RELEASING.md](RELEASING.md)。
