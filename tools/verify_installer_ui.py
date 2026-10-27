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


def install(msi,app,data,log,maintenance=False,no_properties=False,edit_paths=False,remove=False,automatic_log=False):
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
                    button='安装';seen.add('setup')
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
                        # A Rich Edit WM_SETTEXT can suppress EN_CHANGE. Replace
                        # the selected text like a user paste so MSI updates its
                        # bound properties, not just the visible control text.
                        for (_,child),value in zip(sorted(edits),[str(app),str(data)]):
                            # MSI Edit properties are committed when the focused
                            # field loses focus. Give each remote control focus
                            # through its own dialog thread before editing it.
                            user.SendMessageW(hwnd,0x0028,child,1)
                            text_buffer=ctypes.create_unicode_buffer(value)
                            user.SendMessageW(child,0x00B1,0,-1)
                            user.SendMessageW(child,0x00C2,1,ctypes.cast(text_buffer,ctypes.c_void_p).value)
                            if edit_text(child).rstrip('\\/').casefold()!=value.rstrip('\\/').casefold():raise RuntimeError('Path edit did not accept user input: '+edit_text(child))
                        user.SendMessageW(hwnd,0x0028,0,0)
                        paths_edited=True
                        time.sleep(.3)
                elif title=='JunZhenMatch 维护':button='卸载程序' if remove else '修复安装';seen.add('maintenance')
                elif title in ('安装完成','操作完成'):button='完成';seen.add('complete')
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
        if process.returncode not in (0,3010) or errors:raise RuntimeError(f'MSI UI failed: {process.returncode}; {errors}')
        expected={'maintenance','complete'} if maintenance else {'setup','complete'}
        if seen!=expected:raise RuntimeError('MSI UI did not complete expected wizard stages: '+repr(seen))
    finally:
        if process.poll() is None:process.kill()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--msi',required=True);parser.add_argument('--app',required=True);parser.add_argument('--data',required=True);parser.add_argument('--log',required=True);parser.add_argument('--maintenance',action='store_true');parser.add_argument('--no-properties',action='store_true');parser.add_argument('--edit-paths',action='store_true');parser.add_argument('--remove',action='store_true');parser.add_argument('--automatic-log',action='store_true');args=parser.parse_args()
    install(args.msi,args.app,args.data,args.log,args.maintenance,args.no_properties,args.edit_paths,args.remove,args.automatic_log)
