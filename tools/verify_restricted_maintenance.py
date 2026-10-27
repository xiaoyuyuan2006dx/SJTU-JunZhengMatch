"""Real maintenance with a standard account and same-SID admin retry on an isolated NTFS VHD.

Never changes the host's Config.Msi ACL. The full token retries against the same
per-user product; this tests the security-context distinction behind issue 5.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import shutil
import secrets
import traceback
import subprocess
import sys
import tempfile


def logon_run(arguments, name, password):
    adv=c.WinDLL('advapi32',use_last_error=True);kernel=c.WinDLL('kernel32',use_last_error=True)
    class STARTUP(c.Structure):
        _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
                  ('x',w.DWORD),('y',w.DWORD),('xs',w.DWORD),('ys',w.DWORD),('xc',w.DWORD),('yc',w.DWORD),
                  ('fill',w.DWORD),('flags',w.DWORD),('show',w.WORD),('reserved2',w.WORD),('ptr',c.c_void_p),
                  ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
    class PROCESS(c.Structure):_fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
    kernel.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)]
    adv.CreateProcessWithLogonW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.DWORD,w.LPCWSTR,w.LPWSTR,w.DWORD,c.c_void_p,w.LPCWSTR,c.POINTER(STARTUP),c.POINTER(PROCESS)]
    startup=STARTUP();startup.cb=c.sizeof(startup);process=PROCESS()
    command=c.create_unicode_buffer(subprocess.list2cmdline(arguments))
    if not adv.CreateProcessWithLogonW(name,'.',password,1,None,command,0x08000000,None,None,c.byref(startup),c.byref(process)):raise c.WinError(c.get_last_error())
    kernel.CloseHandle(process.thread)
    try:
        if kernel.WaitForSingleObject(process.process,180000)!=0:raise RuntimeError('Test-user maintenance timed out')
        code=w.DWORD();kernel.GetExitCodeProcess(process.process,c.byref(code));return code.value
    finally:kernel.CloseHandle(process.process)


def set_user_environment():
    # CreateProcessWithLogon loads HKCU, but a NULL environment inherits the
    # parent variables. Resolve the actual profile from the new process token.
    adv=c.WinDLL('advapi32',use_last_error=True);kernel=c.WinDLL('kernel32');profiles=c.WinDLL('userenv')
    kernel.GetCurrentProcess.restype=w.HANDLE;adv.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]
    profiles.GetUserProfileDirectoryW.argtypes=[w.HANDLE,w.LPWSTR,c.POINTER(w.DWORD)];kernel.CloseHandle.argtypes=[w.HANDLE]
    token=w.HANDLE();assert adv.OpenProcessToken(kernel.GetCurrentProcess(),8,c.byref(token))
    try:
        size=w.DWORD(32768);buffer=c.create_unicode_buffer(size.value)
        assert profiles.GetUserProfileDirectoryW(token,buffer,c.byref(size));profile=Path(buffer.value)
    finally:kernel.CloseHandle(token)
    os.environ.update(USERPROFILE=str(profile),HOMEDRIVE=profile.drive,HOMEPATH=str(profile)[len(profile.drive):],
                      LOCALAPPDATA=str(profile/'AppData/Local'),APPDATA=str(profile/'AppData/Roaming'),
                      TEMP=str(profile/'AppData/Local/Temp'),TMP=str(profile/'AppData/Local/Temp'))
    Path(os.environ['TEMP']).mkdir(parents=True,exist_ok=True)


def worker(root,stage):
    set_user_environment()
    data=root/'user-data';app=root/'user-program';package=root/'package.msi'
    if stage=='install':
        result=subprocess.run(['msiexec.exe','/i',str(package),'/qn','/norestart',f'INSTALLFOLDER={app}',f'JZDATADIR={data}','/L*v',str(data/'install.log')],timeout=120)
        assert result.returncode in (0,3010),result.returncode
        return
    helper=c.WinDLL(str(root/'InstallerUi.dll'))
    probe=helper.JzRollbackDirectoryAccess;probe.argtypes=[w.LPCWSTR];probe.restype=w.DWORD
    denied=probe(str(root/'Config.Msi'))
    if stage=='repair':
        assert denied==5,denied
        msi=c.WinDLL('msi');session=w.UINT()
        msi.MsiOpenPackageW.argtypes=[w.LPCWSTR,c.POINTER(w.UINT)];msi.MsiSetPropertyW.argtypes=[w.UINT,w.LPCWSTR,w.LPCWSTR]
        check=helper.CheckRollbackAccess;check.argtypes=[w.UINT];check.restype=w.UINT
        assert msi.MsiOpenPackageW(str(package),c.byref(session))==0
        try:
            assert msi.MsiSetPropertyW(session,'INSTALLFOLDER',str(app))==0
            assert check(session)==0,'Caller-token probe still blocks maintenance'
        finally:msi.MsiCloseHandle(session)
        result=subprocess.run(['msiexec.exe','/fa',str(package),'/qn','/norestart','/L*v',str(data/'standard-repair.log')],timeout=120)
        log=(data/'standard-repair.log').read_text(encoding='utf-16',errors='replace')
        assert result.returncode in (0,3010) or (result.returncode==1603 and '1926' in log),result.returncode
        assert 'CustomAction CheckRollbackAccess returned actual error code 1603' not in log
        (data/'result.json').write_text(json.dumps(dict(status='ok',caller_probe=denied,diagnostic_return=0,engine_exit=result.returncode)))
    else:
        assert denied==0,'New logon did not receive administrator permissions'
        sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
        host=str(root/'MaintenanceHost.exe')
        assert subprocess.run([host,'--verify-identity',sid]).returncode==0
        assert subprocess.run([host,'--verify-identity','S-1-5-18']).returncode==5
        for operation,name in (('/fa','admin-repair'),('/x','admin-uninstall')):
            result=subprocess.run(['msiexec.exe',operation,str(package),'/qn','/norestart','/L*v',str(data/(name+'.log'))],timeout=120)
            assert result.returncode in (0,3010),(name,result.returncode)
            if operation=='/fa':assert hashlib.sha256((app/'JunZhengMatch.exe').read_bytes()).digest()==hashlib.sha256((root/'reference.exe').read_bytes()).digest()
        assert not (app/'JunZhengMatch.exe').exists()


def main(msi):
    from verify_installer_ui import install
    name='JzMaint'+secrets.token_hex(4);password='Jz!'+secrets.token_hex(20)+'Aa9'
    letter=next(x for x in 'RSTUVWXYZ' if not Path(x+':/').exists());root=Path(letter+':/')
    account_created=False;runner_installed=False
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        disk=Path(temp)/'maintenance.vhd';script=Path(temp)/'diskpart.txt'
        script.write_text(f'create vdisk file="{disk}" maximum=256 type=expandable\nselect vdisk file="{disk}"\nattach vdisk\ncreate partition primary\nformat fs=ntfs quick\nassign letter={letter}\n',encoding='ascii')
        result=subprocess.run(['diskpart','/s',str(script)],capture_output=True,timeout=60)
        assert root.exists(),result.stdout.decode(errors='replace')
        try:
            result=subprocess.run(['net','user',name,password,'/add'],capture_output=True,timeout=30)
            assert result.returncode==0,'Could not create disposable CI account'
            account_created=True
            subprocess.run(['sc.exe','start','seclogon'],capture_output=True)
            env={**os.environ,'JZ_TEST_ACCOUNT':name}
            sid=subprocess.check_output(['powershell','-NoProfile','-Command',"([System.Security.Principal.NTAccount]::new($env:COMPUTERNAME,$env:JZ_TEST_ACCOUNT)).Translate([System.Security.Principal.SecurityIdentifier]).Value"],env=env,text=True).strip()
            shutil.copy2(msi,root/'package.msi')
            for source in ('build/InstallerUi.dll','build/MaintenanceHost.exe','dist/JunZhengMatch.exe'):
                shutil.copy2(source,root/('reference.exe' if source.endswith('JunZhengMatch.exe') else Path(source).name))
            shutil.copy2(__file__,root/'worker.py')
            subprocess.run(['icacls',str(root),'/grant',f'*{sid}:(OI)(CI)RX'],check=True,capture_output=True)
            for folder in ('user-program','user-data','runner-program','runner-data','Config.Msi'):(root/folder).mkdir()
            for folder in ('user-program','user-data'):
                subprocess.run(['icacls',str(root/folder),'/grant',f'*{sid}:(OI)(CI)F'],check=True,capture_output=True)
            def rollback_acl(access):
                (root/'Config.Msi').mkdir(exist_ok=True)
                subprocess.run(['icacls',str(root/'Config.Msi'),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F',f'*{sid}:(OI)(CI){access}'],check=True,capture_output=True)
            def user_stage(stage):
                result=logon_run([sys.executable,str(root/'worker.py'),'--worker',str(root),'--stage',stage],name,password)
                error=root/'user-data/worker-error.txt'
                assert result==0,(stage,result,error.read_text() if error.exists() else 'No worker traceback')
            rollback_acl('F');user_stage('install');rollback_acl('RX')
            shutil.copy2('data/faculty.db',root/'user-data/sjtu_faculty_data.db')
            expected=hashlib.sha256((root/'user-data/sjtu_faculty_data.db').read_bytes()).hexdigest()
            user_stage('repair');report=json.loads((root/'user-data/result.json').read_text())
            # Promotion is confined to the disposable CI account.
            result=subprocess.run(['net','localgroup','Administrators',name,'/add'],capture_output=True,timeout=30)
            assert result.returncode==0,'Could not grant CI test account administrator membership'
            user_stage('admin')
            assert hashlib.sha256((root/'user-data/sjtu_faculty_data.db').read_bytes()).hexdigest()==expected
            result=subprocess.run(['msiexec.exe','/i',str(root/'package.msi'),'/qn','/norestart',f'INSTALLFOLDER={root/"runner-program"}',f'JZDATADIR={root/"runner-data"}','/L*v',str(root/'runner-install.log')],timeout=120)
            assert result.returncode in (0,3010),result.returncode;runner_installed=True
            host=str(Path('build/MaintenanceHost.exe').resolve())
            install(root/'package.msi',root/'runner-program',root/'runner-data',root/'runner-repair.log',maintenance=True,no_properties=True,admin_host=host)
            assert hashlib.sha256((root/'runner-program/JunZhengMatch.exe').read_bytes()).digest()==hashlib.sha256((root/'reference.exe').read_bytes()).digest()
            install(root/'package.msi',root/'runner-program',root/'runner-data',root/'runner-uninstall.log',maintenance=True,remove=True,no_properties=True,admin_host=host)
            runner_installed=False
            assert not (root/'runner-program/JunZhengMatch.exe').exists()
            report.update(real_standard_account=True,same_user_admin_retry_succeeded=True,other_account_rejected=True,data_preserved=True,isolated_secondary_volume=True)
            Path('restricted-maintenance-test.json').write_text(json.dumps(report),encoding='utf-8');print(json.dumps(report))
        finally:
            Path('installer-diagnostics').mkdir(exist_ok=True)
            for log in list(root.glob('*.log'))+list((root/'user-data').glob('*.log'))+list((root/'user-data').glob('*error.txt')):
                shutil.copy2(log,Path('installer-diagnostics')/('account-'+log.name))
            if runner_installed:subprocess.run(['msiexec.exe','/x',str(root/'package.msi'),'/qn','/norestart'],timeout=120)
            if account_created:subprocess.run(['net','user',name,'/delete'],capture_output=True,timeout=30)
            script.write_text(f'select vdisk file="{disk}"\ndetach vdisk\n',encoding='ascii')
            subprocess.run(['diskpart','/s',str(script)],capture_output=True,timeout=60)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--msi');parser.add_argument('--worker');parser.add_argument('--stage',choices=['install','repair','admin']);args=parser.parse_args()
    if args.worker:
        try:worker(Path(args.worker),args.stage)
        except Exception:
            (Path(args.worker)/'user-data/worker-error.txt').write_text(traceback.format_exc(),encoding='utf-8');raise
    else:main(Path(args.msi).resolve())
