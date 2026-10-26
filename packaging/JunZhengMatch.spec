# Build from repository root: pyinstaller --clean --noconfirm packaging/JunZhengMatch.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
root=Path(SPECPATH).parent
assets=[(str(root/'src/junzheng_match/web'),'web'),(str(root/'data'),'data'),(str(root/'assets'),'assets')]
assets.extend((str(root/name),'.') for name in ['README.md','ARCHITECTURE.md','ASSETS.md','RELEASING.md','WINDOWS.md'])
assets.extend(collect_data_files('webview'))
if (root/'build/version.txt').exists():assets.append((str(root/'build/version.txt'),'.'))
crawlers=['junzheng_match.crawlers.'+name for name in ['sjtu_faculty_scraper','sjtu_scrape_research','sjtu_fix_college','sjtu_web_fix_college']]
a=Analysis([str(root/'packaging/launcher.py')],pathex=[str(root/'src')],binaries=[],datas=assets,
 hiddenimports=['requests','bs4','concurrent.futures','webview','webview.platforms.winforms']+crawlers,
 excludes=['pandas','numpy','sklearn','matplotlib','tkinter','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='JunZhengMatch',debug=False,bootloader_ignore_signals=False,
 version=str(root/'build/version_info.txt') if (root/'build/version_info.txt').exists() else None,icon=str(root/'assets/app.ico'),strip=False,upx=False,console=False,disable_windowed_traceback=False)
