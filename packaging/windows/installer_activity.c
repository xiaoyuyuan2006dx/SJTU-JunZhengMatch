/* Native MSI UI helper. Windows APIs only; no runtime or network dependency. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <msi.h>
#include <msiquery.h>
#include <shellapi.h>
#include <math.h>
#include <wchar.h>

static HINSTANCE module;
static DWORD ui_pid;
static const wchar_t *activity_class=L"JZInstallerActivity";
typedef struct { ULONGLONG started; unsigned frames; HFONT font; HWND parent; } Activity;

static BOOL CALLBACK find_progress(HWND window,LPARAM output) {
    DWORD pid=0; wchar_t title[128];
    GetWindowThreadProcessId(window,&pid);
    GetWindowTextW(window,title,128);
    if(pid==ui_pid && IsWindowVisible(window) && !wcscmp(title,L"正在安装")) {
        *(HWND*)output=window; return FALSE;
    }
    return TRUE;
}
static BOOL CALLBACK find_finished(HWND window,LPARAM output) {
    DWORD pid=0; wchar_t title[128];
    GetWindowThreadProcessId(window,&pid); GetWindowTextW(window,title,128);
    if(pid==ui_pid && IsWindowVisible(window) &&
       (!wcscmp(title,L"操作完成") || !wcscmp(title,L"安装失败") || !wcscmp(title,L"安装已取消"))) {
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
        int radius=max(3,area.bottom/9),gap=radius*4;
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
        SetTimer(window,1,33,NULL);
        while(GetMessageW(&message,NULL,0,0)>0) {TranslateMessage(&message);DispatchMessageW(&message);}
    }
    DeleteObject(state.font);return 0;
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
    HANDLE thread=CreateThread(NULL,0,activity_thread,NULL,0,NULL);
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
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)reserved;if(reason==DLL_PROCESS_ATTACH)module=instance;return TRUE;
}
