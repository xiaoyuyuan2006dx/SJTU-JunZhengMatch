# Native Windows build: pyinstaller --clean --noconfirm JunZhengMatch.spec
from pathlib import Path
root=Path(SPECPATH)
assets=[(str(root/'frontend'),'frontend'),(str(root/'data'),'data'),
        (str(root/'README.md'),'.'),(str(root/'ARCHITECTURE.md'),'.'),(str(root/'ASSETS.md'),'.')]
for name in ['sjtu_faculty_scraper.py','sjtu_scrape_research.py','sjtu_fix_college.py','sjtu_web_fix_college.py']:
    assets.append((str(root/name),'.'))
a=Analysis([str(root/'entrypoint.py')],pathex=[str(root)],binaries=[],datas=assets,
           hiddenimports=['requests','bs4'],excludes=['pandas','numpy','sklearn','matplotlib','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='JunZhengMatch',debug=False,bootloader_ignore_signals=False,
        strip=False,upx=False,console=False,disable_windowed_traceback=False)
