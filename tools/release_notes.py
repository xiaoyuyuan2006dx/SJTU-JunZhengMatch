"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
text=f'''## 更新

- 维护时自动申请所需权限，移除手动管理员按钮。
- MSI 内置 WebView2 完整离线组件，已有环境时跳过安装。
- 调整安装引导配色、文字层次和底色，加入左下角水印。

通过回归及 Windows 安装、修复、卸载和数据保留验证。

[完整说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
