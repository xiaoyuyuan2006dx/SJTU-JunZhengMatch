"""Produce safe release labels and Windows version resources without importing the app."""
import argparse,os,re
from pathlib import Path
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--version',default='');args=parser.parse_args()
    tag=args.version or 'v1.2.4'
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag):raise ValueError('版本号须为v1.1.0格式。')
    version=tag[1:];parts=tuple(map(int,version.split('.')))+(0,)
    if any(n>65535 for n in parts):raise ValueError('版本段不能超过65535。')
    root=Path(__file__).resolve().parent.parent;folder=root/'build';folder.mkdir(exist_ok=True)
    (folder/'version.txt').write_text(version,encoding='utf-8')
    text=f'''VSVersionInfo(ffi=FixedFileInfo(filevers={parts},prodvers={parts},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','xiaoyuyuan2006dx'),StringStruct('FileDescription','JunZhenMatch'),StringStruct('FileVersion','{version}'),StringStruct('InternalName','JunZhengMatch'),StringStruct('OriginalFilename','JunZhengMatch.exe'),StringStruct('ProductName','JunZhenMatch'),StringStruct('ProductVersion','{version}')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])'''
    (folder/'version_info.txt').write_text(text,encoding='utf-8')
    resource=fr'''#include <windows.h>
1 ICON "{(root/'assets/app.ico').as_posix()}"
1 VERSIONINFO
FILEVERSION {','.join(map(str,parts))}
PRODUCTVERSION {','.join(map(str,parts))}
FILEFLAGSMASK 0x3fL
FILEFLAGS 0
FILEOS VOS_NT_WINDOWS32
FILETYPE VFT_APP
BEGIN
 BLOCK "StringFileInfo"
 BEGIN
  BLOCK "040904B0"
  BEGIN
   VALUE "CompanyName", "xiaoyuyuan2006dx\0"
   VALUE "FileDescription", "䇹政导师匹配 — 安装维护\0"
   VALUE "FileVersion", "{version}\0"
   VALUE "ProductName", "䇹政导师匹配\0"
   VALUE "ProductVersion", "{version}\0"
   VALUE "InternalName", "JunZhengMatchMaintenance\0"
   VALUE "OriginalFilename", "䇹政导师匹配-安装维护.exe\0"
  END
 END
 BLOCK "VarFileInfo"
 BEGIN
  VALUE "Translation", 0x409, 1200
 END
END
'''
    (folder/'maintenance-host.rc').write_text(resource,encoding='utf-8')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as handle:handle.write(f'version={version}\ntag={tag}\n')
    print(version)
