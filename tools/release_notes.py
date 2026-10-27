"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
version=args.version.removeprefix('v')
text=f'''## 修复与调整

- 明确安装程序文件，升级不继承旧版只有登记、没有本地EXE的功能状态。
- 再次打开MSI进入“修复安装／卸载程序”，修复可恢复丢失的EXE和快捷方式。
- 修复保留现有教师库、数据位置和用户设置，隔离配置不再覆盖安装器的位置记录。
- 安装助手出错时记录错误并退出，避免隐藏错误窗口使MSI一直等待。
- 安装完成页显示程序完整路径，提供“打开程序文件夹”；完成和失败页提供“查看安装日志”。
- 保留原有进度说明、发布者信息、匹配参数、教师库及CSV / XLSX导出格式。

## 验证

58项回归，以及Windows真实默认双击安装、界面修改路径、删除EXE后的图形修复、旧版空登记状态升级、数据库哈希保留、快捷方式、实际原生窗口、共享后台、安装助手失败退出、卸载和Docker检查。测试报告位于便携ZIP的 verification 目录。

## 下载使用

| 文件 | 用途 |
|---|---|
| JunZhengMatch-{version}-windows-x64-portable.zip | 解压后运行EXE，在浏览器使用 |
| JunZhengMatch-{version}-windows-x64-setup.msi | 安装后使用独立窗口 |
| JunZhengMatch-{version}-docker-amd64.tar.gz | Docker镜像归档 |
| SHA256SUMS.txt | 下载文件校验 |

已安装旧版或旧版显示完成却找不到EXE时，下载新版MSI进行升级。安装前先通过退出贴纸停止后台；旧教师数据保留。新版再次打开可直接选择修复安装，无需清理注册表。

默认程序位置为 %LOCALAPPDATA%\\Programs\\JunZhenMatch\\JunZhengMatch.exe；也可使用完成页的“打开程序文件夹”。如仍有异常，点击“查看安装日志”保留具体诊断信息。

自带737条网络公开SJTU教师记录，学生示例均为虚构。MSI安装不联网下载组件；首次启动缺少WebView2时显示联网安装进度。发布者字段为xiaoyuyuan2006dx；程序仍未作可信代码签名，浏览器的“不常下载”信誉提示仍可能出现。

[使用说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md) · [Windows说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/WINDOWS.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
