"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
version=args.version.removeprefix('v')
text=f'''## 修复

- 修复 MSI 错误窗口的按钮焦点链，避免报错过程中再次触发2814。
- 卸载完成页显示程序已移除、数据已保留，隐藏安装完成提示和启动按钮。
- 卸载及升级移除文件前，检查已有Windows回滚目录权限；失败时提前中止，不更改共享目录权限或关闭回滚。

## 验证

62项回归；Windows维护页卸载和直接卸载、卸载中注入1926错误后的程序回滚恢复、拒绝写入目录、版本分流、中文路径、修复及数据保留，以及Docker检查。机器验证报告在便携ZIP的 verification 目录。

## 下载使用

| 文件 | 用途 |
|---|---|
| JunZhengMatch-{version}-windows-x64-portable.zip | 解压后运行EXE，在浏览器使用 |
| JunZhengMatch-{version}-windows-x64-setup.msi | 安装后使用独立窗口 |
| JunZhengMatch-{version}-docker-amd64.tar.gz | Docker镜像归档 |
| SHA256SUMS.txt | 下载文件校验 |

已安装旧版或旧版显示完成却找不到EXE时，下载新版MSI进行升级。安装前先通过退出贴纸停止后台；旧教师数据保留。新版再次打开可直接选择修复安装，无需清理注册表。

默认程序位置为 %LOCALAPPDATA%\\Programs\\JunZhenMatch\\JunZhengMatch.exe；也可使用完成页的“打开程序文件夹”。如仍有异常，点击“查看安装日志”保留具体诊断信息。Config.Msi 的权限问题需要按日志检查Windows目录权限；本版提前检测并中止，不会擅自更改系统权限。

程序和数据请选择分开的文件夹。安装版直接双击EXE或使用快捷方式均打开独立窗口；便携版打开浏览器。

自带737条网络公开SJTU教师记录，学生示例均为虚构。MSI安装不联网下载组件；首次启动缺少WebView2时显示组件准备状态，已有环境不显示该步骤。发布者字段为xiaoyuyuan2006dx；程序仍未作可信代码签名，浏览器的“不常下载”信誉提示仍可能出现。

[使用说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md) · [Windows说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/WINDOWS.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
