"""Generate the concise release body used by CI."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
version=args.version.removeprefix('v')
text=f'''## 修复

- 修复重复打开或修复 MSI 时的2753错误，初始化仅在程序组件计划安装时运行。
- WebView2 下载移出 MSI 安装事务，避免安装进度长时间无说明地停住。

## 调整

- MSI 与 EXE 的发布者信息改为 xiaoyuyuan2006dx。
- MSI 显示实际安装进度和当前步骤，参考耗时约10–30秒。
- 首次启动缺少 WebView2 时，显示下载说明、已等待时间和微软安装进度；通常约1–3分钟，最多等待5分钟，实际取决于网络。
- 保留全部教师库、匹配参数、原格式导出及 v1.1.0 功能。

## 验证

54项回归测试，以及 Windows 可见安装向导、重复打开、强制修复、从v1.1.0升级、原生下载进度窗口、独立窗口、共享后台、卸载数据保留和 Docker 检查。报告位于便携ZIP的 verification 目录。

## 下载使用

| 文件 | 用途 |
|---|---|
| JunZhengMatch-{version}-windows-x64-portable.zip | 解压运行EXE，在浏览器使用 |
| JunZhengMatch-{version}-windows-x64-setup.msi | 安装后使用独立窗口 |
| JunZhengMatch-{version}-docker-amd64.tar.gz | Docker镜像归档 |
| SHA256SUMS.txt | 下载文件校验 |

已安装v1.1.0可直接升级；安装前通过退出贴纸停止后台，用户数据保留。MSI安装不联网下载组件；仅首次启动缺少WebView2时联网补装。网络不通可直接双击安装目录里的JunZhengMatch.exe使用浏览器版。

自带737条网络公开SJTU教师记录，示例学生均为虚构。发布者字段不是数字签名；Windows程序仍未签名。

[使用说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md) · [Windows说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/WINDOWS.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
