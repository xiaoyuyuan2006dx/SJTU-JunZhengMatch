"""Produce safe release labels and Windows version resources without importing the app."""
import argparse,os,re
from pathlib import Path
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--version',default='');args=parser.parse_args()
    tag=args.version or 'v1.1.1'
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag):raise ValueError('版本号须为v1.1.0格式。')
    version=tag[1:];parts=tuple(map(int,version.split('.')))+(0,)
    if any(n>65535 for n in parts):raise ValueError('版本段不能超过65535。')
    root=Path(__file__).resolve().parent.parent;folder=root/'build';folder.mkdir(exist_ok=True)
    (folder/'version.txt').write_text(version,encoding='utf-8')
    text=f'''VSVersionInfo(ffi=FixedFileInfo(filevers={parts},prodvers={parts},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','xiaoyuyuan2006dx'),StringStruct('FileDescription','JunZhenMatch'),StringStruct('FileVersion','{version}'),StringStruct('InternalName','JunZhengMatch'),StringStruct('OriginalFilename','JunZhengMatch.exe'),StringStruct('ProductName','JunZhenMatch'),StringStruct('ProductVersion','{version}')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])'''
    (folder/'version_info.txt').write_text(text,encoding='utf-8')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as handle:handle.write(f'version={version}\ntag={tag}\n')
    print(version)
