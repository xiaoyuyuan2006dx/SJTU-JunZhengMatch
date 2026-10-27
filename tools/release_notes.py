"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
text=f'''## 修复

- 补齐错误窗口图标，修复权限报错时出现的2835。
- 回滚目录探测改为只记录诊断，避免误拦截修复和卸载。
- 增加同账户管理员重试，授权账户不一致时停止操作。

## 验证

通过62项回归、Windows受限令牌维护、管理员重试和失败回滚验证，以及Docker检查。

[完整说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
