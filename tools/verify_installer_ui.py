"""Exercise the visible MSI wizard on the Windows CI desktop."""
import argparse
import ctypes
from ctypes import wintypes as w
from pathlib import Path
import subprocess
import time


def install(msi,app,data,log):
    user=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    user.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    user.IsWindowVisible.argtypes=[w.HWND]
    user.EnumWindows.argtypes=[callback,w.LPARAM]
    user.EnumChildWindows.argtypes=[w.HWND,callback,w.LPARAM]
    user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    def caption(hwnd):
        buffer=ctypes.create_unicode_buffer(4096);user.GetWindowTextW(hwnd,buffer,4096);return buffer.value
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
    process=subprocess.Popen(f'msiexec.exe /i "{values[0]}" /norestart INSTALLFOLDER="{values[1]}" JZDATADIR="{values[2]}" /L*v "{values[3]}"')
    deadline=time.monotonic()+180;clicked=set();seen=set();errors=[]
    try:
        while process.poll() is None and time.monotonic()<deadline:
            for hwnd,title in windows():
                button=None
                if title=='JunZhenMatch 安装':button='安装';seen.add('setup')
                elif title=='安装完成':button='完成';seen.add('complete')
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
        if process.returncode not in (0,3010) or errors:raise RuntimeError(f'MSI UI failed: {process.returncode}; {errors}')
        if seen!={'setup','complete'}:raise RuntimeError('MSI UI did not complete expected wizard stages: '+repr(seen))
    finally:
        if process.poll() is None:process.kill()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--msi',required=True);parser.add_argument('--app',required=True);parser.add_argument('--data',required=True);parser.add_argument('--log',required=True);args=parser.parse_args()
    install(args.msi,args.app,args.data,args.log)
