"""Check real PE identity resources for the executable shown in UAC."""
import json
from pathlib import Path
import pefile
from verify_icon import verify

host=Path('build/MaintenanceHost.exe')
icon=verify(host,'assets/app.ico')
values={}
with pefile.PE(str(host)) as pe:
    for group in pe.FileInfo:
        for item in group:
            for table in getattr(item,'StringTable',[]):
                values.update({k.decode('utf-8'):v.decode('utf-8') for k,v in table.entries.items()})
assert values['FileDescription']=='䇹政导师匹配 — 安装维护'
assert values['CompanyName']=='xiaoyuyuan2006dx'
assert values['OriginalFilename']=='䇹政导师匹配-安装维护.exe'
assert values['ProductVersion']==Path('build/version.txt').read_text().strip()
report=dict(status='ok',file_description=values['FileDescription'],company=values['CompanyName'],original_filename=values['OriginalFilename'],embedded_icon=icon['exact_icon_payloads'])
Path('maintenance-host-test.json').write_text(json.dumps(report),encoding='utf-8')
print(json.dumps(report))
