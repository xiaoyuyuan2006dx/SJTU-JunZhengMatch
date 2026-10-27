"""Show dependency setup status without blocking the MSI transaction."""
import subprocess
import threading
import time


def progress_text(elapsed,timeout=300):
    seconds=max(0,int(elapsed))
    waited=f'已等待 {seconds//60}分{seconds%60:02d}秒'
    if seconds<180:return waited+' · 通常约10–60秒，正在本地安装'
    return waited+f' · 本地安装较慢，最多再等待{max(0,int(timeout)-seconds)}秒'


def run_setup(command,timeout=300):
    """Use indeterminate progress: the offline component installer owns its progress."""
    import ctypes
    from ctypes import wintypes as w
    user=ctypes.windll.user32;common=ctypes.windll.comctl32
    class CommonControls(ctypes.Structure):
        _fields_=[('size',w.DWORD),('classes',w.DWORD)]
    controls=CommonControls(ctypes.sizeof(CommonControls),0x20)
    common.InitCommonControlsEx(ctypes.byref(controls))
    user.CreateWindowExW.restype=w.HWND
    user.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p]
    user.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR]
    user.DestroyWindow.argtypes=[w.HWND]
    user.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.PeekMessageW.argtypes=[ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT,w.UINT]
    user.TranslateMessage.argtypes=[ctypes.POINTER(w.MSG)]
    user.DispatchMessageW.argtypes=[ctypes.POINTER(w.MSG)]
    width,height=620,215
    window=user.CreateWindowExW(0,'STATIC','正在准备独立窗口组件',0x90C00000,
        (user.GetSystemMetrics(0)-width)//2,(user.GetSystemMetrics(1)-height)//2,width,height,None,None,None,None)
    # If the status window is unavailable, Microsoft's visible installer remains
    # usable. Setup errors still propagate to the application error message.
    if not window:return subprocess.run(command,check=True,timeout=timeout)
    labels=[]
    try:
        labels.append(user.CreateWindowExW(0,'STATIC','正在准备独立窗口所需的运行组件\r\n使用安装包内的离线组件，通常约10–60秒。\r\n准备完成后将打开程序。',0x50000000,22,18,570,65,window,None,None,None))
        bar=user.CreateWindowExW(0,'msctls_progress32','',0x50000008,22,96,570,18,window,None,None,None)
        user.SendMessageW(bar,0x040A,1,30)
        status=user.CreateWindowExW(0,'STATIC',progress_text(0,timeout),0x50000000,22,130,570,35,window,None,None,None)
        labels.append(status)
        ctypes.windll.gdi32.GetStockObject.restype=w.HANDLE
        font=ctypes.windll.gdi32.GetStockObject(17)
        for label in labels:user.SendMessageW(label,0x0030,font,1)
        done=threading.Event();outcome={}
        def install():
            try:outcome['result']=subprocess.run(command,check=True,timeout=timeout)
            except Exception as error:outcome['error']=error
            finally:done.set()
        threading.Thread(target=install,daemon=True).start()
        started=time.monotonic();message=w.MSG()
        while not done.is_set():
            while user.PeekMessageW(ctypes.byref(message),None,0,0,1):
                user.TranslateMessage(ctypes.byref(message));user.DispatchMessageW(ctypes.byref(message))
            user.SetWindowTextW(status,progress_text(time.monotonic()-started,timeout))
            done.wait(.2)
        if 'error' in outcome:raise outcome['error']
        return outcome['result']
    finally:user.DestroyWindow(window)
