"""Generate the concise release body used by CI."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
version=args.version.removeprefix('v')
text=f'''## 新增

- Windows 独立窗口安装版（MSI），安装时可设置数据目录。
- 偏好设置：数据迁移、备份恢复、导出目录和默认匹配参数。
- 教师使用次数上限，默认每次任务最多2次；候选不足留空并说明。

## 调整

- 浏览器版与安装版使用相同数据目录时共用后台。
- 默认数据目录为 `%USERPROFILE%\\JunZhenMatch`，与程序分开，升级和卸载保留数据。
- 关闭标签页或窗口只关闭当前界面；右上角“退出程序”停止共享后台。
- 整理源码目录和文档，统一发行文件命名与校验。

## 验证

通过回归、实际HTTP与多进程检查、Windows EXE及独立窗口检查、MSI安装和卸载数据保留检查、Docker构建及启动检查。详细报告位于便携ZIP的 verification 目录。

## 下载使用

| 文件 | 用途 |
|---|---|
| JunZhengMatch-{version}-windows-x64-portable.zip | 解压运行EXE，在浏览器使用 |
| JunZhengMatch-{version}-windows-x64-setup.msi | 安装后使用独立窗口 |
| JunZhengMatch-{version}-docker-amd64.tar.gz | Docker镜像归档 |
| SHA256SUMS.txt | 下载文件校验 |

自带737条网络公开SJTU教师记录，无需Python。示例学生信息均为虚构。安装版缺少WebView2时会联网补装。Windows程序未作商业代码签名。

[使用说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md) · [Windows说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/WINDOWS.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
