"""Exercise the visible MSI wizard on the Windows CI desktop."""
import argparse
import ctypes
import json
import os
import re
from ctypes import wintypes as w
from pathlib import Path
import subprocess
import shutil
import sys
import time

sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')


def install(msi,app,data,log,maintenance=False,no_properties=False,edit_paths=False,remove=False,automatic_log=False,reject_paths=False,cancel_upgrade=False,expect_newer=False,open_existing=False,direct_uninstall=False,expect_error=False,verify_data_folder=False,admin_host=None):
    user=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.IsWindowVisible.argtypes=[w.HWND]
    user.IsWindowEnabled.argtypes=[w.HWND]
    user.EnumWindows.argtypes=[callback,w.LPARAM]
    user.EnumChildWindows.argtypes=[w.HWND,callback,w.LPARAM]
    user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
    user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
    user.GetWindowLongPtrW.argtypes=[w.HWND,ctypes.c_int];user.GetWindowLongPtrW.restype=ctypes.c_ssize_t
    user.WindowFromPoint.argtypes=[w.POINT];user.WindowFromPoint.restype=w.HWND
    user.IsChild.argtypes=[w.HWND,w.HWND]
    class MouseInput(ctypes.Structure):
        _fields_=[('dx',w.LONG),('dy',w.LONG),('mouseData',w.DWORD),('dwFlags',w.DWORD),('time',w.DWORD),('dwExtraInfo',ctypes.c_size_t)]
    class KeyInput(ctypes.Structure):
        _fields_=[('wVk',w.WORD),('wScan',w.WORD),('dwFlags',w.DWORD),('time',w.DWORD),('dwExtraInfo',ctypes.c_size_t)]
    class InputUnion(ctypes.Union):
        _fields_=[('mi',MouseInput),('ki',KeyInput)]
    class Input(ctypes.Structure):
        _anonymous_=('data',)
        _fields_=[('type',w.DWORD),('data',InputUnion)]
    user.SendInput.argtypes=[w.UINT,ctypes.POINTER(Input),ctypes.c_int]
    user.SetForegroundWindow.argtypes=[w.HWND]
    def type_path(dialog,control,value):
        # Use real mouse/keyboard input: MSI's bound Edit properties are updated
        # by the normal control event loop, not arbitrary remote text messages.
        rect=w.RECT();user.GetWindowRect(control,ctypes.byref(rect))
        user.SetForegroundWindow(dialog)
        user.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
        user.mouse_event(0x0002,0,0,0,0);user.mouse_event(0x0004,0,0,0,0)
        time.sleep(.15)
        keys=[]
        def key(vk=0,scan=0,flags=0):
            item=Input();item.type=1;item.ki=KeyInput(vk,scan,flags,0,0);keys.append(item)
        key(0x11);key(0x41);key(0x41,flags=2);key(0x11,flags=2)
        encoded=value.encode('utf-16-le')
        for offset in range(0,len(encoded),2):
            scan=int.from_bytes(encoded[offset:offset+2],'little')
            key(scan=scan,flags=4);key(scan=scan,flags=6)
        inputs=(Input*len(keys))(*keys)
        if user.SendInput(len(inputs),inputs,ctypes.sizeof(Input))!=len(inputs):raise RuntimeError('Windows rejected installer keyboard input')
        input_deadline=time.monotonic()+10
        while edit_text(control).rstrip('\\/').casefold()!=value.rstrip('\\/').casefold():
            if time.monotonic()>=input_deadline:raise RuntimeError('Path edit did not accept keyboard input: '+edit_text(control))
            time.sleep(.1)
        keys.clear();key(0x09);key(0x09,flags=2)
        inputs=(Input*len(keys))(*keys)
        if user.SendInput(len(inputs),inputs,ctypes.sizeof(Input))!=len(inputs):raise RuntimeError('Windows rejected installer Tab input')
        time.sleep(.2)
    def caption(hwnd):
        buffer=ctypes.create_unicode_buffer(4096);user.GetWindowTextW(hwnd,buffer,4096);return buffer.value
    def edit_text(hwnd):
        # GetWindowText deliberately does not retrieve another process's Edit
        # contents. WM_GETTEXT is the supported cross-process control query.
        buffer=ctypes.create_unicode_buffer(32768)
        user.SendMessageW(hwnd,0x000D,len(buffer),ctypes.cast(buffer,ctypes.c_void_p).value)
        return buffer.value
    def windows(parent=None,include_hidden=False):
        found=[]
        @callback
        def collect(hwnd,_):
            if include_hidden or user.IsWindowVisible(hwnd):found.append((hwnd,caption(hwnd)))
            return True
        if parent:user.EnumChildWindows(parent,collect,0)
        else:user.EnumWindows(collect,0)
        return found
    values=[str(Path(msi).resolve()),str(app),str(data),str(log)]
    if any('"' in value for value in values):raise ValueError('MSI test paths cannot contain quotes')
    # msiexec parses PROPERTY="value with spaces" itself. list2cmdline would
    # quote the entire PROPERTY=value token and can open its command help UI.
    properties='' if no_properties else f' INSTALLFOLDER="{values[1]}" JZDATADIR="{values[2]}"'
    logging='' if automatic_log else f' /L*v "{values[3]}"'
    if admin_host:
        sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
        host_args=[str(admin_host),sid,values[0]]
        if direct_uninstall:host_args+=['0','remove']
        process=subprocess.Popen(host_args);automatic_log=True
    else:process=subprocess.Popen(f'msiexec.exe {"/x" if direct_uninstall else "/i"} "{values[0]}" /norestart{properties}{logging}')
    deadline=time.monotonic()+180;clicked={};seen=set();errors=[]
    paths_edited=False
    edit_wait_started=None
    discovered_log=None
    stages=set();positions=set();activity_frames=set();upgrade_text=''
    existing_pid=None;existing_cancelled=False;existing_finished=False
    folder_requested=False;folder_checked=False
    screenshots=Path('installer-ui-preview');screenshots.mkdir(exist_ok=True)
    def capture(hwnd,name):
        path=screenshots/(name+'.png')
        if path.exists():return
        from PIL import ImageGrab
        time.sleep(.25)  # Capture after the native dialog has completed painting.
        rect=w.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
        ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom)).save(path)
        controls=[]
        for child,text in windows(hwnd,include_hidden=True):
            klass=ctypes.create_unicode_buffer(128);user.GetClassNameW(child,klass,128)
            bounds=w.RECT();user.GetWindowRect(child,ctypes.byref(bounds))
            controls.append(dict(title=text,kind=klass.value,style=hex(user.GetWindowLongPtrW(child,-16)),rect=[bounds.left,bounds.top,bounds.right,bounds.bottom]))
        path.with_suffix('.json').write_text(json.dumps(controls,ensure_ascii=False),encoding='utf-8')
    try:
        while (process.poll() is None or (open_existing and not existing_finished)) and time.monotonic()<deadline:
            for hwnd,title in windows():
                if title in ('正在安装','正在卸载'):
                    for child,text in windows(hwnd):
                        if text in {'正在检查安装条件','正在复制程序文件','正在创建快捷方式','正在写入安装信息','正在保存数据位置','正在保留原有设置','正在移除旧版本','正在卸载程序文件','正在完成安装'}:stages.add(text)
                        name=ctypes.create_unicode_buffer(128);user.GetClassNameW(child,name,128)
                        if 'progress' in name.value.lower():positions.add(user.SendMessageW(child,0x0408,0,0))
                        if name.value=='JZInstallerActivity':
                            value=re.search(r'frames=(\d+)',text)
                            if value:
                                activity_frames.add(int(value[1]))
                                if len(activity_frames)>=2:capture(hwnd,'progress')
                if title in ('安装完成','卸载完成','安装失败'):
                    for _,text in windows(hwnd,include_hidden=True):
                        if text.startswith('安装日志：') and text[len('安装日志：'):].strip():discovered_log=Path(text[len('安装日志：'):].strip())
                button=None
                if direct_uninstall and title=='Windows Installer':
                    texts=' '.join(text for _,text in windows(hwnd))
                    # /x uses Windows' own confirmation/basic progress UI.
                    # Its transient preparation window is not a second prompt.
                    if 'confirm' in seen and not any(code in texts for code in ('1926','2753','2814')):
                        if 'preparing to remove' in texts.lower() or any(text.replace('&','') in ('Cancel','取消') for _,text in windows(hwnd)):
                            continue
                    if 'are you sure you want to uninstall' not in texts.lower() and '确定要卸载' not in texts:
                        raise RuntimeError('Unexpected Windows uninstall prompt: '+texts)
                    buttons=[text.replace('&','') for _,text in windows(hwnd)]
                    button=next((text for text in buttons if text in ('Yes','是','是(Y)')),None)
                    if not button:raise RuntimeError('No confirmation button: '+texts)
                    capture(hwnd,'uninstall-confirm');seen.add('confirm')
                elif expect_error and title in ('JunZhenMatch 安装错误','JunZhenMatch','JunZhengMatch'):
                    texts=' '.join(text for _,text in windows(hwnd))
                    if 'jz-fixture.rbf' not in texts:raise RuntimeError('Unexpected MSI error: '+texts)
                    capture(hwnd,'permission-error');seen.add('expected-error');button='取消'
                elif expect_error and title=='安装失败':
                    capture(hwnd,'uninstall-failed');seen.add('failure');button='关闭'
                elif title=='JunZhenMatch 安装':
                    capture(hwnd,'setup')
                    button='取消' if reject_paths and 'invalid' in seen else '安装';seen.add('setup')
                    if edit_paths and not paths_edited:
                        edits=[];controls=[]
                        for child,text in windows(hwnd):
                            name=ctypes.create_unicode_buffer(128);user.GetClassNameW(child,name,128)
                            controls.append((name.value,text))
                            if 'edit' in name.value.lower():
                                rect=w.RECT();user.GetWindowRect(child,ctypes.byref(rect));edits.append((rect.top,child))
                        if len(edits)!=2:
                            if edit_wait_started is None:edit_wait_started=time.monotonic()
                            if time.monotonic()-edit_wait_started>10:raise RuntimeError('Path fields did not become ready: '+repr(controls))
                            continue
                        for (_,child),value in zip(sorted(edits),[str(app),str(data)]):
                            type_path(hwnd,child,value)
                        paths_edited=True
                        time.sleep(.3)
                elif title=='请调整数据目录':button='返回修改';seen.add('invalid')
                elif title=='发现已有版本':
                    capture(hwnd,'upgrade');seen.add('upgrade');button='取消' if cancel_upgrade else '升级'
                    upgrade_text=' '.join(text for _,text in windows(hwnd))
                    if '是否升级到 v' not in upgrade_text:raise RuntimeError('Upgrade versions were not displayed')
                elif title=='已安装较新版本':
                    capture(hwnd,'newer');seen.add('newer');button='修复或卸载' if open_existing else '取消'
                    if not expect_newer:errors.append('Unexpected newer version dialog')
                elif title=='JunZhenMatch 安装错误':
                    errors.append(' '.join(text for _,text in windows(hwnd)))
                    button='确定'
                elif title=='JunZhenMatch 维护':
                    capture(hwnd,'maintenance')
                    if open_existing:
                        pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));existing_pid=pid.value
                        if not any('v99.0.0' in text for _,text in windows(hwnd)):raise RuntimeError('Maintenance opened the wrong installed version')
                        if process.poll() is None:continue
                        seen.add('existing-maintenance');button='取消'
                    else:button='卸载程序' if remove else '修复安装';seen.add('maintenance')
                elif title in ('安装完成','卸载完成'):
                    texts=' '.join(text for _,text in windows(hwnd))
                    if remove or direct_uninstall:
                        assert title=='卸载完成' and '程序和快捷方式已移除' in texts,texts
                        assert '立即打开' not in texts and '程序文件夹' not in texts and '双击桌面' not in texts,texts
                        assert str(data).rstrip('\\').casefold() in texts.casefold(),texts
                        assert '打开数据文件夹' in texts,texts
                        capture(hwnd,'uninstalled')
                    else:assert title=='安装完成',title;capture(hwnd,'complete')
                    button='完成';seen.add('complete')
                    if verify_data_folder and not folder_checked:
                        if not folder_requested:button='打开数据文件夹'
                        else:
                            script='''$deadline=(Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
  $shell=New-Object -ComObject Shell.Application
  foreach ($window in @($shell.Windows())) {
    try { if ($window.Document.Folder.Self.Path -eq $env:JZ_EXPECTED_RETAINED) { $window.Quit(); exit 0 } } catch {}
  }
  Start-Sleep -Milliseconds 200
}
exit 1'''
                            result=subprocess.run(['powershell','-NoProfile','-Command',script],env={**os.environ,'JZ_EXPECTED_RETAINED':str(data)},capture_output=True,timeout=25)
                            assert result.returncode==0,'Retained data folder did not open in Explorer: '+result.stderr.decode(errors='replace')
                            folder_checked=True
                elif title=='安装已取消' and (reject_paths or cancel_upgrade or expect_newer):
                    button='关闭';seen.add('cancelled')
                    pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if existing_pid and pid.value==existing_pid:existing_cancelled=True
                elif title in ('安装失败','安装已取消'):button='关闭';errors.append(title)
                elif title=='JunZhenMatch':
                    texts=' '.join(text for _,text in windows(hwnd))
                    if '2753' in texts:errors.append(texts);button='确定'
                retry_close=button in ('完成','关闭','取消','返回修改') and time.monotonic()-clicked.get((hwnd,button),0)>1
                if button and user.IsWindowEnabled(hwnd) and ((hwnd,button) not in clicked or retry_close):
                    for child,text in windows(hwnd):
                        if text.replace('&','')==button:
                            rect=w.RECT();user.GetWindowRect(child,ctypes.byref(rect))
                            user.SetForegroundWindow(hwnd)
                            point=w.POINT((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                            hit=user.WindowFromPoint(point)
                            if hit!=child and not user.IsChild(child,hit):break
                            user.SetCursorPos(point.x,point.y)
                            user.mouse_event(0x0002,0,0,0,0);user.mouse_event(0x0004,0,0,0,0)
                            if button=='打开数据文件夹':folder_requested=True
                            clicked[(hwnd,button)]=time.monotonic();print('MSI UI: '+title+' / '+button,flush=True);break
                    # Refresh the window list after an action changes modal
                    # ownership instead of clicking a stale parent immediately.
                    break
            if open_existing and existing_cancelled and process.poll() is not None:
                matching=False
                for hwnd,_ in windows():
                    pid=w.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==existing_pid:matching=True
                existing_finished=not matching
            time.sleep(.05)
        if process.poll() is None or (open_existing and not existing_finished):raise RuntimeError('Visible installer timed out; wizard stages: '+repr(seen)+'; windows: '+repr([title for _,title in windows() if title]))
        if automatic_log:
            if not discovered_log or not discovered_log.exists():raise RuntimeError('Automatic MSI log path is missing from completion/failure page')
            shutil.copyfile(discovered_log,log)
        if expect_error:
            assert process.returncode==1603 and seen=={'maintenance','expected-error','failure'},(process.returncode,seen,errors)
            text=Path(log).read_text(encoding='utf-16')
            for code in ('2814','2835'):
                assert 'Error '+code not in text and 'Note: 1: '+code not in text,text[-4000:]
            return
        if reject_paths:
            if process.returncode!=1602 or errors or seen!={'setup','invalid','cancelled'}:raise RuntimeError(f'Invalid path was not rejected before installation: {process.returncode}; {seen}; {errors}')
            return
        if cancel_upgrade or expect_newer:
            expected={'cancelled','newer' if expect_newer else 'upgrade'}
            if open_existing:expected.add('existing-maintenance')
            if process.returncode!=1602 or errors or seen!=expected:raise RuntimeError(f'Version confirmation did not cancel cleanly: {process.returncode}; {seen}; {errors}')
            return
        if process.returncode not in (0,3010) or errors:raise RuntimeError(f'MSI UI failed: {process.returncode}; {errors}')
        if direct_uninstall:
            assert seen in ({'confirm'},{'confirm','complete'},{'complete'}),seen
            return
        expected={'maintenance','complete'} if maintenance else {'setup','complete'}
        if seen-{'upgrade','confirm'}!=expected:raise RuntimeError('MSI UI did not complete expected wizard stages: '+repr(seen))
        Path(log).with_suffix('.progress.json').write_text(json.dumps(dict(status='ok',stages=sorted(stages),positions=sorted(positions),activity_frames=sorted(activity_frames),upgrade_text=upgrade_text),ensure_ascii=False),encoding='utf-8')
    finally:
        if process.poll() is None:process.kill()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('msi','app','data','log'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--admin-host')
    for name in ('maintenance','no-properties','edit-paths','remove','automatic-log','reject-paths','cancel-upgrade','expect-newer','open-existing','direct-uninstall','expect-error','verify-data-folder'):parser.add_argument('--'+name,action='store_true')
    install(**vars(parser.parse_args()))
