"""Generate the release notes for the current maintenance release."""
import argparse
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
text=f'''## 修复

- 修复 MSI 错误窗口的按钮焦点链，避免报错过程中再次触发2814。
- 卸载完成页显示程序已移除、数据已保留，隐藏安装完成提示和启动按钮。
- 卸载及升级移除文件前，检查已有Windows回滚目录权限；失败时提前中止，不更改共享目录权限或关闭回滚。

## 验证

通过62项回归、Windows卸载与失败回滚验证，以及Docker检查。

[完整说明](https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch/blob/{args.version}/README.md)
'''
Path(args.output).write_text(text,encoding='utf-8')
