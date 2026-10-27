"""Exercise the visible MSI wizard on the Windows CI desktop."""
import argparse
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import subprocess
import shutil
import sys
import time

sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')


def install(msi,app,data,log,maintenance=False,no_properties=False,edit_paths=False,remove=False,automatic_log=False,reject_paths=False):
    user=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.IsWindowVisible.argtypes=[w.HWND]
    user.EnumWindows.argtypes=[callback,w.LPARAM]
    user.EnumChildWindows.argtypes=[w.HWND,callback,w.LPARAM]
    user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
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
        time.sleep(.2)
        if edit_text(control).rstrip('\\/').casefold()!=value.rstrip('\\/').casefold():raise RuntimeError('Path edit did not accept keyboard input: '+edit_text(control))
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
    def windows(parent=None):
        found=[]
        @callback
        def collect(hwnd,_):
            if user.IsWindowVisible(hwnd):found.append((hwnd,caption(hwnd)))
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
    process=subprocess.Popen(f'msiexec.exe /i "{values[0]}" /norestart{properties}{logging}')
    deadline=time.monotonic()+180;clicked=set();seen=set();errors=[]
    paths_edited=False
    edit_wait_started=None
    discovered_log=None
    try:
        while process.poll() is None and time.monotonic()<deadline:
            for hwnd,title in windows():
                if title in ('操作完成','安装失败'):
                    for _,text in windows(hwnd):
                        if text.startswith('安装日志：') and text[len('安装日志：'):].strip():discovered_log=Path(text[len('安装日志：'):].strip())
                button=None
                if title=='JunZhenMatch 安装':
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
                elif title=='JunZhenMatch 维护':button='卸载程序' if remove else '修复安装';seen.add('maintenance')
                elif title in ('安装完成','操作完成'):button='完成';seen.add('complete')
                elif title=='安装已取消' and reject_paths:button='关闭';seen.add('cancelled')
                elif title in ('安装失败','安装已取消'):button='关闭';errors.append(title)
                elif title=='JunZhenMatch':
                    texts=' '.join(text for _,text in windows(hwnd))
                    if '2753' in texts:errors.append(texts);button='确定'
                if button and (hwnd,button) not in clicked:
                    for child,text in windows(hwnd):
                        if text.replace('&','')==button:
                            user.PostMessageW(child,0x00F5,0,0);clicked.add((hwnd,button));print('MSI UI: '+title+' / '+button,flush=True);break
            time.sleep(.2)
        if process.poll() is None:raise RuntimeError('Visible installer timed out; wizard stages: '+repr(seen)+'; windows: '+repr([title for _,title in windows() if title]))
        if automatic_log:
            if not discovered_log or not discovered_log.exists():raise RuntimeError('Automatic MSI log path is missing from completion/failure page')
            shutil.copyfile(discovered_log,log)
        if reject_paths:
            if process.returncode!=1602 or errors or seen!={'setup','invalid','cancelled'}:raise RuntimeError(f'Invalid path was not rejected before installation: {process.returncode}; {seen}; {errors}')
            return
        if process.returncode not in (0,3010) or errors:raise RuntimeError(f'MSI UI failed: {process.returncode}; {errors}')
        expected={'maintenance','complete'} if maintenance else {'setup','complete'}
        if seen!=expected:raise RuntimeError('MSI UI did not complete expected wizard stages: '+repr(seen))
    finally:
        if process.poll() is None:process.kill()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--msi',required=True);parser.add_argument('--app',required=True);parser.add_argument('--data',required=True);parser.add_argument('--log',required=True);parser.add_argument('--maintenance',action='store_true');parser.add_argument('--no-properties',action='store_true');parser.add_argument('--edit-paths',action='store_true');parser.add_argument('--remove',action='store_true');parser.add_argument('--automatic-log',action='store_true');parser.add_argument('--reject-paths',action='store_true');args=parser.parse_args()
    install(args.msi,args.app,args.data,args.log,args.maintenance,args.no_properties,args.edit_paths,args.remove,args.automatic_log,args.reject_paths)
