"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
text=f'''## 更新

- 跳过本程序安装的额外整机还原点，修复开始阶段长时间等待；保留安装失败回滚。
- 恢复轻量安装包，已有 WebView2 时直接使用。
- 完善管理员维护助手的名称、图标和描述。

通过回归及 Windows 安装、修复、卸载和数据保留验证。

[完整说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
