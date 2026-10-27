/* CI only: exercise the real MSI error dialog and rollback after RemoveFiles. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <msi.h>
#include <msiquery.h>
__declspec(dllexport) UINT __stdcall TestRollbackError(MSIHANDLE install) {
    MSIHANDLE record=MsiCreateRecord(3);
    MsiRecordSetInteger(record,1,1926);
    MsiRecordSetInteger(record,2,5);
    MsiRecordSetStringW(record,3,L"D:\\Config.Msi\\jz-fixture.rbf");
    MsiProcessMessage(install,INSTALLMESSAGE_ERROR|MB_RETRYCANCEL|MB_ICONWARNING,record);
    MsiCloseHandle(record);
    return ERROR_INSTALL_FAILURE;
}
