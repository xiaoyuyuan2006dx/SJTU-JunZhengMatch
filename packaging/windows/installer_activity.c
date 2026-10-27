/* Native MSI UI helper. Windows APIs only; no runtime or network dependency. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <msi.h>
#include <msiquery.h>
#include <shellapi.h>
#include <math.h>
#include <wchar.h>
#include <aclapi.h>
#include <sddl.h>

static HINSTANCE module;
static DWORD ui_pid;
static const wchar_t *activity_class=L"JZInstallerActivity";
typedef struct { ULONGLONG started; unsigned frames; HFONT font; HWND parent; } Activity;

static BOOL CALLBACK find_progress(HWND window,LPARAM output) {
    DWORD pid=0; wchar_t title[128];
    GetWindowThreadProcessId(window,&pid);
    GetWindowTextW(window,title,128);
    if(pid==ui_pid && IsWindowVisible(window) && (!wcscmp(title,L"正在安装") || !wcscmp(title,L"正在卸载"))) {
        *(HWND*)output=window; return FALSE;
    }
    return TRUE;
}
static BOOL CALLBACK find_finished(HWND window,LPARAM output) {
    DWORD pid=0; wchar_t title[128];
    GetWindowThreadProcessId(window,&pid); GetWindowTextW(window,title,128);
    if(pid==ui_pid && IsWindowVisible(window) &&
       (!wcscmp(title,L"安装完成") || !wcscmp(title,L"卸载完成") || !wcscmp(title,L"安装失败") || !wcscmp(title,L"安装已取消"))) {
        *(BOOL*)output=TRUE; return FALSE;
    }
    return TRUE;
}
static LRESULT CALLBACK activity_proc(HWND window,UINT message,WPARAM wp,LPARAM lp) {
    Activity *state=(Activity*)GetWindowLongPtrW(window,GWLP_USERDATA);
    if(message==WM_NCCREATE) {
        state=(Activity*)((CREATESTRUCTW*)lp)->lpCreateParams;
        SetWindowLongPtrW(window,GWLP_USERDATA,(LONG_PTR)state);
    }
    if(message==WM_TIMER && state) {
        BOOL finished=FALSE; wchar_t title[80];
        EnumWindows(find_finished,(LPARAM)&finished);
        if(!IsWindow(state->parent) || !IsWindowVisible(state->parent) || finished) {DestroyWindow(window);return 0;}
        ++state->frames;
        swprintf_s(title,80,L"JZ_ACTIVITY frames=%u",state->frames);
        SetWindowTextW(window,title); InvalidateRect(window,NULL,FALSE); return 0;
    }
    if(message==WM_PAINT && state) {
        PAINTSTRUCT paint; RECT area; HDC screen=BeginPaint(window,&paint);
        GetClientRect(window,&area);
        HDC dc=CreateCompatibleDC(screen); HBITMAP bitmap=CreateCompatibleBitmap(screen,area.right,area.bottom);
        HGDIOBJ old_bitmap=SelectObject(dc,bitmap);
        HBRUSH background=CreateSolidBrush(RGB(255,252,247));FillRect(dc,&area,background);DeleteObject(background);
        double t=(GetTickCount64()-state->started)/1000.0;
        COLORREF colors[]={RGB(239,173,188),RGB(177,157,207),RGB(131,196,179),RGB(246,198,111)};
        int radius=max(4,area.bottom/7),gap=radius*4;
        for(int i=0;i<4;i++) {
            int x=radius+4+i*gap,y=area.bottom/2-(int)(sin(t*5-i*.85)*radius*1.5);
            HBRUSH brush=CreateSolidBrush(colors[i]);HGDIOBJ old_brush=SelectObject(dc,brush),old_pen=SelectObject(dc,GetStockObject(NULL_PEN));
            Ellipse(dc,x-radius,y-radius,x+radius,y+radius);
            SelectObject(dc,old_brush);SelectObject(dc,old_pen);DeleteObject(brush);
        }
        wchar_t text[100]; unsigned seconds=(unsigned)t;
        DWORD_PTR response=0;
        BOOL responsive=(BOOL)SendMessageTimeoutW(state->parent,WM_NULL,0,0,SMTO_ABORTIFHUNG|SMTO_BLOCK,100,&response);
        swprintf_s(text,100,responsive?L"正在处理  ·  %02u:%02u":L"正在等待安装器响应  ·  %02u:%02u",seconds/60,seconds%60);
        RECT label={gap*4+8,0,area.right,area.bottom};
        HGDIOBJ old_font=SelectObject(dc,state->font);SetBkMode(dc,TRANSPARENT);SetTextColor(dc,RGB(144,123,145));
        DrawTextW(dc,text,-1,&label,DT_SINGLELINE|DT_VCENTER|DT_NOPREFIX);
        SelectObject(dc,old_font);BitBlt(screen,0,0,area.right,area.bottom,dc,0,0,SRCCOPY);
        SelectObject(dc,old_bitmap);DeleteObject(bitmap);DeleteDC(dc);EndPaint(window,&paint);return 0;
    }
    if(message==WM_ERASEBKGND)return 1;
    if(message==WM_DESTROY) {KillTimer(window,1);PostQuitMessage(0);return 0;}
    return DefWindowProcW(window,message,wp,lp);
}
static DWORD WINAPI activity_thread(void *unused) {
    HWND parent=NULL; MSG message; RECT area; Activity state={0};
    (void)unused;
    for(int i=0;i<30 && !parent;i++) {EnumWindows(find_progress,(LPARAM)&parent);if(!parent)Sleep(50);}
    if(!parent)return 0;
    WNDCLASSW wc={0};wc.lpfnWndProc=activity_proc;wc.hInstance=module;wc.lpszClassName=activity_class;
    RegisterClassW(&wc);GetClientRect(parent,&area);
    state.started=GetTickCount64();state.parent=parent;
    HDC parent_dc=GetDC(parent);int dpi=GetDeviceCaps(parent_dc,LOGPIXELSY);ReleaseDC(parent,parent_dc);
    state.font=CreateFontW(-MulDiv(9,dpi,72),0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Microsoft YaHei UI");
    HWND window=CreateWindowExW(0,activity_class,L"JZ_ACTIVITY frames=0",WS_CHILD|WS_VISIBLE|WS_CLIPSIBLINGS,
        area.right*20/640,area.bottom*258/342,area.right*380/640,area.bottom*23/342,parent,NULL,module,&state);
    if(window) {
        SetWindowPos(window,HWND_TOP,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE);
        SetTimer(window,1,33,NULL);
        while(GetMessageW(&message,NULL,0,0)>0) {TranslateMessage(&message);DispatchMessageW(&message);}
    }
    DeleteObject(state.font);return 0;
}
static BOOL CALLBACK lower_background(HWND child,LPARAM parent_rect) {
    RECT child_rect;RECT *area=(RECT*)parent_rect;GetWindowRect(child,&child_rect);
    if(child_rect.right-child_rect.left>=(area->right-area->left)*9/10 &&
       child_rect.bottom-child_rect.top>=(area->bottom-area->top)*9/10) {
        LONG_PTR style=GetWindowLongPtrW(child,GWL_STYLE);
        if(GetWindow(child,GW_HWNDNEXT)!=NULL || !(style&WS_CLIPSIBLINGS)) {
            SetWindowLongPtrW(child,GWL_STYLE,style|WS_CLIPSIBLINGS);
            SetWindowPos(child,HWND_BOTTOM,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_ASYNCWINDOWPOS);
            RedrawWindow(GetParent(child),NULL,NULL,RDW_INVALIDATE|RDW_ALLCHILDREN);
        }
    }
    return TRUE;
}
static BOOL CALLBACK style_dialog(HWND window,LPARAM unused) {
    DWORD pid=0;RECT area;(void)unused;GetWindowThreadProcessId(window,&pid);
    if(pid==ui_pid && IsWindowVisible(window)) {
        GetClientRect(window,&area);MapWindowPoints(window,NULL,(POINT*)&area,2);
        EnumChildWindows(window,lower_background,(LPARAM)&area);
    }
    return TRUE;
}
static DWORD WINAPI style_thread(void *unused) {
    HANDLE client=OpenProcess(SYNCHRONIZE,FALSE,ui_pid);BOOL activity_started=FALSE;(void)unused;
    ULONGLONG deadline=GetTickCount64()+1800000;
    while((!client || WaitForSingleObject(client,40)==WAIT_TIMEOUT) && GetTickCount64()<deadline) {
        EnumWindows(style_dialog,0);
        if(!activity_started) {
            HWND progress=NULL;EnumWindows(find_progress,(LPARAM)&progress);
            if(progress) {
                HANDLE worker=CreateThread(NULL,0,activity_thread,NULL,0,NULL);
                if(worker) {CloseHandle(worker);activity_started=TRUE;}
            }
        }
        if(!client)Sleep(40);
    }
    if(client)CloseHandle(client);return 0;
}
__declspec(dllexport) UINT __stdcall StartActivity(MSIHANDLE install) {
    HMODULE pinned=NULL;wchar_t client[40]={0};DWORD length=39;
    MsiGetPropertyW(install,L"CLIENTPROCESSID",client,&length);
    ui_pid=client[0]?wcstoul(client,NULL,10):GetCurrentProcessId();
    MSIHANDLE record=MsiCreateRecord(2);
    MsiRecordSetStringW(record,0,L"JZ animation: helper PID [1], UI PID [2]");
    MsiRecordSetInteger(record,1,(int)GetCurrentProcessId());MsiRecordSetInteger(record,2,(int)ui_pid);
    MsiProcessMessage(install,INSTALLMESSAGE_INFO,record);MsiCloseHandle(record);
    /* MSI may unload an immediate-action DLL. Pin this UI-only helper until
       its client process exits so the animation thread never executes freed code. */
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,(LPCWSTR)&StartActivity,&pinned);
    HANDLE thread=CreateThread(NULL,0,style_thread,NULL,0,NULL);
    if(thread)CloseHandle(thread);
    return ERROR_SUCCESS; /* Decorative UI must never fail an installation. */
}
__declspec(dllexport) UINT __stdcall DetectRelatedVersion(MSIHANDLE install) {
    wchar_t related[2048]={0},code[40]={0},version[100]={0};DWORD length=2047;
    MsiGetPropertyW(install,L"WIX_DOWNGRADE_DETECTED",related,&length);
    if(!related[0]) {length=2047;MsiGetPropertyW(install,L"WIX_UPGRADE_DETECTED",related,&length);}
    wchar_t *start=wcschr(related,L'{');
    if(start && wcslen(start)>=38) {
        wcsncpy_s(code,40,start,38);length=99;
        if(MsiGetProductInfoW(code,INSTALLPROPERTY_VERSIONSTRING,version,&length)==ERROR_SUCCESS) {
            MsiSetPropertyW(install,L"JZRELATEDPRODUCT",code);MsiSetPropertyW(install,L"JZINSTALLEDVERSION",version);
        }
    }
    return ERROR_SUCCESS;
}
__declspec(dllexport) UINT __stdcall OpenExistingMaintenance(MSIHANDLE install) {
    wchar_t code[40]={0},package[32768]={0},program[MAX_PATH]={0},args[32800];DWORD length=39;
    MsiGetPropertyW(install,L"JZRELATEDPRODUCT",code,&length);length=32767;
    if(MsiGetProductInfoW(code,INSTALLPROPERTY_LOCALPACKAGE,package,&length)!=ERROR_SUCCESS || GetFileAttributesW(package)==INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL,L"找不到已安装版本的安装包。请下载该版本安装包，打开后选择修复或卸载。",L"维护已安装版本",MB_OK|MB_ICONINFORMATION);return ERROR_SUCCESS;
    }
    GetSystemDirectoryW(program,MAX_PATH);wcscat_s(program,MAX_PATH,L"\\msiexec.exe");
    swprintf_s(args,32800,L"/i \"%ls\"",package);
    SHELLEXECUTEINFOW info={sizeof(info)};info.lpFile=program;info.lpParameters=args;info.nShow=SW_SHOWNORMAL;
    if(!ShellExecuteExW(&info))MessageBoxW(NULL,L"无法打开维护页面，请重新打开已安装版本的安装包。",L"维护已安装版本",MB_OK|MB_ICONINFORMATION);
    return ERROR_SUCCESS;
}
/* Diagnostic only: this token is not necessarily the installer engine token.
   Never alter a shared Config.Msi ACL or another installer's rollback files. */
__declspec(dllexport) DWORD __stdcall JzRollbackDirectoryAccess(const wchar_t *directory) {
    DWORD attributes=GetFileAttributesW(directory);
    if(attributes==INVALID_FILE_ATTRIBUTES) {
        DWORD error=GetLastError();
        return error==ERROR_FILE_NOT_FOUND || error==ERROR_PATH_NOT_FOUND ? ERROR_SUCCESS : error;
    }
    if(!(attributes&FILE_ATTRIBUTE_DIRECTORY))return ERROR_DIRECTORY;
    static volatile LONG sequence=0;wchar_t file[32768];
    swprintf_s(file,32768,L"%ls\\jz-permission-check-%lu-%llu-%ld.tmp",directory,GetCurrentProcessId(),GetTickCount64(),InterlockedIncrement(&sequence));
    HANDLE probe=CreateFileW(file,GENERIC_READ|GENERIC_WRITE|DELETE|READ_CONTROL|WRITE_DAC,0,NULL,CREATE_NEW,
        FILE_ATTRIBUTE_TEMPORARY|FILE_FLAG_DELETE_ON_CLOSE,NULL);
    if(probe==INVALID_HANDLE_VALUE)return GetLastError();
    PACL dacl=NULL;PSECURITY_DESCRIPTOR descriptor=NULL;
    DWORD error=GetSecurityInfo(probe,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,NULL,NULL,&dacl,NULL,&descriptor);
    if(error==ERROR_SUCCESS)error=SetSecurityInfo(probe,SE_FILE_OBJECT,DACL_SECURITY_INFORMATION,NULL,NULL,dacl,NULL);
    if(descriptor)LocalFree(descriptor);
    CloseHandle(probe);return error;
}
__declspec(dllexport) UINT __stdcall CheckRollbackAccess(MSIHANDLE install) {
    const wchar_t *properties[]={L"INSTALLFOLDER",L"PREVIOUSINSTALLFOLDER"};
    for(int i=0;i<2;i++) {
        wchar_t path[32768]={0},volume[32768]={0},directory[32768];DWORD length=32767;
        MsiGetPropertyW(install,properties[i],path,&length);
        if(!path[0] || !GetVolumePathNameW(path,volume,32768))continue;
        swprintf_s(directory,32768,L"%lsConfig.Msi",volume);
        DWORD error=JzRollbackDirectoryAccess(directory);
        MSIHANDLE record=MsiCreateRecord(2);
        MsiRecordSetStringW(record,0,L"JZ rollback diagnostic: [1]; access result [2]. Informational only; Windows Installer performs the operation in its own security context.");
        MsiRecordSetStringW(record,1,directory);MsiRecordSetInteger(record,2,(int)error);
        MsiProcessMessage(install,INSTALLMESSAGE_INFO,record);MsiCloseHandle(record);

    }
    return ERROR_SUCCESS;
}
__declspec(dllexport) UINT __stdcall CaptureRetainedDataLocation(MSIHANDLE install) {
    wchar_t folder[32768]={0};DWORD bytes=sizeof(folder);
    /* PreferenceStore mirrors every committed data_dir change here. Capture it
       in the UI session before MSI removes product registry entries/files. */
    if(RegGetValueW(HKEY_CURRENT_USER,L"Software\\TaroDeluxe\\JunZhenMatch",L"DataDir",RRF_RT_REG_SZ,NULL,folder,&bytes)!=ERROR_SUCCESS) {
        DWORD length=32767;MsiGetPropertyW(install,L"JZDATADIR",folder,&length);
    }
    MsiSetPropertyW(install,L"JZRETAINEDDATADIR",folder);
    return ERROR_SUCCESS;
}
__declspec(dllexport) UINT __stdcall OpenRetainedDataFolder(MSIHANDLE install) {
    wchar_t folder[32768]={0};DWORD length=32767;
    MsiGetPropertyW(install,L"JZRETAINEDDATADIR",folder,&length);
    DWORD attributes=GetFileAttributesW(folder);
    if(attributes==INVALID_FILE_ATTRIBUTES || !(attributes&FILE_ATTRIBUTE_DIRECTORY)) {
        MessageBoxW(NULL,L"数据目录不存在或暂时无法访问，请按完成页显示的路径检查。",L"打开数据文件夹",MB_OK|MB_ICONINFORMATION);
        return ERROR_SUCCESS;
    }
    if((INT_PTR)ShellExecuteW(NULL,L"open",folder,NULL,NULL,SW_SHOWNORMAL)<=32)
        MessageBoxW(NULL,L"无法打开数据目录，请按完成页显示的路径，在文件资源管理器中打开。",L"打开数据文件夹",MB_OK|MB_ICONINFORMATION);
    return ERROR_SUCCESS;
}
__declspec(dllexport) UINT __stdcall RestartElevated(MSIHANDLE install) {
    wchar_t package[32768]={0},client[40]={0};DWORD length=32767;
    MsiSetPropertyW(install,L"JZELEVATIONHANDOFF",L"");
    MsiGetPropertyW(install,L"OriginalDatabase",package,&length);length=39;
    MsiGetPropertyW(install,L"CLIENTPROCESSID",client,&length);
    HANDLE process=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,wcstoul(client,NULL,10)),token=NULL;
    if(!process || !OpenProcessToken(process,TOKEN_QUERY,&token)) {
        if(process)CloseHandle(process);
        MessageBoxW(NULL,L"无法确认当前安装账户，请关闭后重新打开安装包。",L"管理员维护",MB_OK|MB_ICONINFORMATION);return ERROR_SUCCESS;
    }
    TOKEN_ELEVATION elevation={0};DWORD size=0;
    GetTokenInformation(token,TokenElevation,&elevation,sizeof(elevation),&size);
    if(elevation.TokenIsElevated) {
        MessageBoxW(NULL,L"当前已使用管理员权限。若仍报目录权限错误，请保留安装日志，由管理员检查该目录权限。",L"管理员维护",MB_OK|MB_ICONINFORMATION);
        CloseHandle(token);CloseHandle(process);return ERROR_SUCCESS;
    }
    GetTokenInformation(token,TokenUser,NULL,0,&size);
    TOKEN_USER *user=(TOKEN_USER*)LocalAlloc(LPTR,size);LPWSTR sid=NULL;
    BOOL identity=user && GetTokenInformation(token,TokenUser,user,size,&size) && ConvertSidToStringSidW(user->User.Sid,&sid);
    CloseHandle(token);CloseHandle(process);if(user)LocalFree(user);
    if(!identity) {MessageBoxW(NULL,L"无法确认当前安装账户，请关闭后重新打开安装包。",L"管理员维护",MB_OK|MB_ICONINFORMATION);return ERROR_SUCCESS;}
    /* Extract a dedicated native host. It checks the SID again after UAC,
       before launching msiexec, so alternate credentials cannot target HKCU
       belonging to a different account. Nothing changes shared directory ACLs. */
    MSIHANDLE database=MsiGetActiveDatabase(install),view=0,record=0;
    wchar_t temp[MAX_PATH],base[MAX_PATH],host[MAX_PATH+8],parameters[33000];
    BOOL ok=FALSE;HANDLE output=INVALID_HANDLE_VALUE;
    if(GetTempPathW(MAX_PATH,temp) && GetTempFileNameW(temp,L"jzm",0,base)) {
        swprintf_s(host,MAX_PATH+8,L"%ls.exe",base);DeleteFileW(base);
        output=CreateFileW(host,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
    }
    if(output!=INVALID_HANDLE_VALUE && MsiDatabaseOpenViewW(database,L"SELECT `Data` FROM `Binary` WHERE `Name`='MaintenanceHost'",&view)==ERROR_SUCCESS &&
       MsiViewExecute(view,0)==ERROR_SUCCESS && MsiViewFetch(view,&record)==ERROR_SUCCESS) {
        char bytes[8192];DWORD count=sizeof(bytes),written=0;UINT status;
        ok=TRUE;
        while((status=MsiRecordReadStream(record,1,bytes,&count))==ERROR_SUCCESS && count) {
            if(!WriteFile(output,bytes,count,&written,NULL) || written!=count) {ok=FALSE;break;}
            count=sizeof(bytes);
        }
        if(status!=ERROR_SUCCESS)ok=FALSE;
    }
    if(output!=INVALID_HANDLE_VALUE)CloseHandle(output);
    if(record)MsiCloseHandle(record);if(view)MsiCloseHandle(view);if(database)MsiCloseHandle(database);
    if(ok) {
        swprintf_s(parameters,33000,L"%ls \"%ls\"",sid,package);
        SHELLEXECUTEINFOW request={sizeof(request)};request.lpVerb=L"runas";request.lpFile=host;request.lpParameters=parameters;request.nShow=SW_SHOWNORMAL;
        if(ShellExecuteExW(&request))MsiSetPropertyW(install,L"JZELEVATIONHANDOFF",L"1");
        else {
            if(GetLastError()!=ERROR_CANCELLED)MessageBoxW(NULL,L"未能打开管理员维护，请保留安装日志。",L"管理员维护",MB_OK|MB_ICONINFORMATION);
            DeleteFileW(host);
        }
    } else MessageBoxW(NULL,L"未能准备管理员维护，请重新下载完整安装包。",L"管理员维护",MB_OK|MB_ICONINFORMATION);
    if(!ok && output!=INVALID_HANDLE_VALUE)DeleteFileW(host);
    LocalFree(sid);return ERROR_SUCCESS;
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)reserved;if(reason==DLL_PROCESS_ATTACH)module=instance;return TRUE;
}
