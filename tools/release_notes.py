"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
version=args.version.removeprefix('v')
text=f'''## 修复与调整

- 修复程序与数据选在同一目录时，直到初始化才报1722并回退的问题。现在点击安装即提示返回修改，数据也不能位于程序目录内部。
- 静默安装同样提前校验冲突路径，在卸载旧版或复制文件之前停止，保护已有安装。
- 默认浏览器启动返回失败时显示明确提示和本地访问地址，避免无提示退出。
- 保留修复安装、程序文件夹入口、自动日志、既有教师数据及CSV / XLSX格式。

## 验证

60项回归，以及Windows真实同目录／子目录选择提示、静默拒绝、无效升级保留旧版登记、默认安装、中文路径、删除EXE后修复、旧版空登记升级、数据库哈希保留、快捷方式、原生窗口、共享后台、卸载和Docker检查。测试报告位于便携ZIP的 verification 目录。

## 下载使用

| 文件 | 用途 |
|---|---|
| JunZhengMatch-{version}-windows-x64-portable.zip | 解压后运行EXE，在浏览器使用 |
| JunZhengMatch-{version}-windows-x64-setup.msi | 安装后使用独立窗口 |
| JunZhengMatch-{version}-docker-amd64.tar.gz | Docker镜像归档 |
| SHA256SUMS.txt | 下载文件校验 |

已安装旧版或旧版显示完成却找不到EXE时，下载新版MSI进行升级。安装前先通过退出贴纸停止后台；旧教师数据保留。新版再次打开可直接选择修复安装，无需清理注册表。

默认程序位置为 %LOCALAPPDATA%\\Programs\\JunZhenMatch\\JunZhengMatch.exe；也可使用完成页的“打开程序文件夹”。如仍有异常，点击“查看安装日志”保留具体诊断信息。

程序和数据请选择分开的文件夹。直接双击EXE打开浏览器；桌面或开始菜单的“䇹政导师匹配”快捷方式带有 --desktop 参数，打开独立窗口。

自带737条网络公开SJTU教师记录，学生示例均为虚构。MSI安装不联网下载组件；首次启动缺少WebView2时显示联网安装进度。发布者字段为xiaoyuyuan2006dx；程序仍未作可信代码签名，浏览器的“不常下载”信誉提示仍可能出现。

[使用说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md) · [Windows说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/WINDOWS.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
