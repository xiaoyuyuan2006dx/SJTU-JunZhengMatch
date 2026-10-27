"""Check the actual native guard against a disposable directory with denied writes."""
import ctypes
import json
from pathlib import Path
import subprocess
import tempfile

helper=ctypes.WinDLL(str(Path('build/InstallerUi.dll').resolve()))
check=helper.JzRollbackDirectoryAccess
check.argtypes=[ctypes.c_wchar_p];check.restype=ctypes.c_ulong
sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
with tempfile.TemporaryDirectory() as root:
    folder=Path(root)/'simulated rollback';folder.mkdir()
    assert check(str(folder))==0
    assert list(folder.iterdir())==[], 'Permission check left a temporary file'
    subprocess.run(['icacls',str(folder),'/deny',f'*{sid}:(W)'],check=True,capture_output=True)
    try:
        assert check(str(folder))==5, 'Denied rollback directory was accepted'
        assert list(folder.iterdir())==[], 'Rejected probe left a file'
    finally:
        subprocess.run(['icacls',str(folder),'/remove:d',f'*{sid}'],check=True,capture_output=True)
    assert check(str(folder))==0, 'Probe changed directory permissions'
report=dict(status='ok',writable_directory_passes=True,denied_directory_rejected=True,no_acl_changes=True,no_temporary_files=True)
Path('rollback-access-test.json').write_text(json.dumps(report),encoding='utf-8')
print(json.dumps(report))
