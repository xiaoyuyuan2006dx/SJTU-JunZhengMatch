/* Elevated retry host: keep the same user identity for this per-user MSI. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <sddl.h>
#include <msi.h>
#include <wchar.h>

static BOOL same_user(const wchar_t *expected) {
    HANDLE token=NULL;DWORD size=0;BOOL matches=FALSE;LPWSTR sid=NULL;
    if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token))return FALSE;
    GetTokenInformation(token,TokenUser,NULL,0,&size);
    TOKEN_USER *user=(TOKEN_USER*)LocalAlloc(LPTR,size);
    if(user && GetTokenInformation(token,TokenUser,user,size,&size) && ConvertSidToStringSidW(user->User.Sid,&sid)) {
        matches=!wcscmp(sid,expected);LocalFree(sid);
    }
    if(user)LocalFree(user);CloseHandle(token);return matches;
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,LPWSTR command,int show) {
    int count=0;LPWSTR *args=CommandLineToArgvW(GetCommandLineW(),&count);
    (void)instance;(void)previous;(void)command;(void)show;
    if(!args || count<3)return ERROR_INVALID_PARAMETER;
    BOOL check=!wcscmp(args[1],L"--verify-identity");
    const wchar_t *sid=check?args[2]:args[1];
    if(!same_user(sid)) {
        if(!check)MessageBoxW(NULL,L"管理员授权使用了不同账户。为保护原账户的安装和数据，本次未执行维护。请使用原账户的管理员权限重试。",L"维护账户不一致",MB_OK|MB_ICONWARNING);
        LocalFree(args);return ERROR_ACCESS_DENIED;
    }
    if(check) {LocalFree(args);return ERROR_SUCCESS;}
    if(count!=3 && count!=4 && count!=5) {LocalFree(args);return ERROR_INVALID_PARAMETER;}
    if(count>=4) {
        HANDLE previous_client=OpenProcess(SYNCHRONIZE,FALSE,wcstoul(args[3],NULL,10));
        if(previous_client) {
            DWORD waited=WaitForSingleObject(previous_client,30000);CloseHandle(previous_client);
            if(waited!=WAIT_OBJECT_0) {
                MessageBoxW(NULL,L"原安装窗口尚未关闭。请关闭后重新打开安装包。",L"管理员维护",MB_OK|MB_ICONINFORMATION);
                LocalFree(args);return ERROR_BUSY;
            }
        }
    }
    if(MsiVerifyPackageW(args[2])!=ERROR_SUCCESS) {LocalFree(args);return ERROR_INSTALL_PACKAGE_INVALID;}
    wchar_t program[MAX_PATH],parameters[33000];
    GetSystemDirectoryW(program,MAX_PATH);wcscat_s(program,MAX_PATH,L"\\msiexec.exe");
    swprintf_s(parameters,33000,L"\"%ls\" %ls \"%ls\"",program,count==5 && !wcscmp(args[4],L"remove")?L"/x":L"/i",args[2]);
    STARTUPINFOW startup={sizeof(startup)};PROCESS_INFORMATION process={0};DWORD result;
    if(!CreateProcessW(program,parameters,NULL,NULL,FALSE,0,NULL,NULL,&startup,&process))result=GetLastError();
    else {
        CloseHandle(process.hThread);WaitForSingleObject(process.hProcess,INFINITE);
        GetExitCodeProcess(process.hProcess,&result);CloseHandle(process.hProcess);
    }
    LocalFree(args);return (int)result;
}
