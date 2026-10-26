"""Desktop window and native Windows helpers; business logic stays in the service."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
from . import paths, runtime


def pick_directory():
    if os.name!='nt':raise ValueError('此平台请直接填写数据目录路径。')
    import ctypes
    from ctypes import wintypes
    class BrowseInfo(ctypes.Structure):
        _fields_=[('hwndOwner',wintypes.HWND),('pidlRoot',ctypes.c_void_p),('pszDisplayName',wintypes.LPWSTR),('lpszTitle',wintypes.LPCWSTR),('ulFlags',wintypes.UINT),('lpfn',ctypes.c_void_p),('lParam',ctypes.c_ssize_t),('iImage',ctypes.c_int)]
    ctypes.windll.ole32.OleInitialize(None)
    try:
        display=ctypes.create_unicode_buffer(260);info=BrowseInfo(None,None,display,'请选择数据存储文件夹',0x41,None,0,0)
        shell=ctypes.windll.shell32;shell.SHBrowseForFolderW.restype=ctypes.c_void_p
        item=shell.SHBrowseForFolderW(ctypes.byref(info))
        if not item:return ''
        try:
            buffer=ctypes.create_unicode_buffer(32768)
            if not shell.SHGetPathFromIDListW(ctypes.c_void_p(item),buffer):raise ValueError('未选择有效目录。')
            return buffer.value
        finally:ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(item))
    finally:ctypes.windll.ole32.OleUninitialize()


def ensure_webview2():
    if os.name!='nt':return
    import winreg
    key=r'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for flag in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive,key,0,winreg.KEY_READ|flag) as handle:
                    version=winreg.QueryValueEx(handle,'pv')[0]
                    if version and version!='0.0.0.0':return
            except OSError:pass
    installer=Path(sys.executable).parent/'MicrosoftEdgeWebview2Setup.exe'
    if not installer.exists():raise RuntimeError('未找到WebView2环境，请运行安装包完成依赖安装。')
    subprocess.run([str(installer),'/silent','/install'],check=True,timeout=300)


class DesktopBridge:
    def __init__(self):self.window=None
    def choose_data_dir(self):
        import webview
        selected=self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return selected[0] if selected else ''
    def save_export(self,filename,encoded):
        import webview
        suffix=Path(filename).suffix.lower()
        if suffix not in ('.csv','.xlsx','.db'):raise ValueError('不支持的导出类型。')
        content=base64.b64decode(encoded,validate=True)
        if len(content)>25*1024*1024:raise ValueError('导出文件过大。')
        chosen=self.window.create_file_dialog(webview.FileDialog.SAVE,save_filename=Path(filename).name,file_types=('导出文件 (*'+suffix+')',))
        if not chosen:return dict(saved=False)
        target=Path(chosen[0]);target.write_bytes(content)
        return dict(saved=True,path=str(target))
    def close_window(self):self.window.destroy()


def open_desktop(instance,profile,smoke_report=None):
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.settings['ALLOW_FILE_URLS']=False
    bridge=DesktopBridge()
    window=webview.create_window('䇹政导师匹配',instance['url']+'/?interface=desktop',js_api=bridge,width=1320,height=900,min_size=(850,600),background_color='#fffdf9')
    bridge.window=window
    result={}
    if smoke_report:
        def exercise():
            try:
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if window.evaluate_js('document.readyState')=='complete' and window.evaluate_js('!!window.JZReady'):break
                    time.sleep(.2)
                else:raise RuntimeError('独立窗口页面加载超时。')
                check=window.evaluate_js("({title:document.title,preferences:!!document.getElementById('page-preferences'),bridge:!!window.pywebview.api})")
                if not check.get('preferences') or not check.get('bridge'):raise RuntimeError('独立窗口未加载设置页面或本机桥接。')
                result.update(status='ok',native_window=True,webview_bridge=True,preferences_page=True,instance_id=instance['instance_id'])
            except Exception as error:result.update(status='error',error=str(error))
            finally:window.destroy()
        window.events.loaded+=lambda:threading.Thread(target=exercise,daemon=True).start()
    gui='edgechromium' if os.name=='nt' else None
    webview.start(gui=gui,storage_path=str(Path(profile)/'webview'),private_mode=False,icon=str(paths.RESOURCE_ROOT/'assets/app.ico'))
    if smoke_report:
        Path(smoke_report).write_text(json.dumps(result),encoding='utf-8')
        if result.get('status')!='ok':raise RuntimeError(result.get('error','独立窗口验证失败'))
