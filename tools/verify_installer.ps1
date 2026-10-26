param([Parameter(Mandatory=$true)][string]$Msi,[string]$Report='installer-test.json')
$ErrorActionPreference='Stop'
$msiPath=(Resolve-Path $Msi).Path
$root=Join-Path $env:RUNNER_TEMP ('jz-install-'+[guid]::NewGuid().ToString('N'))
$app=Join-Path $root 'Installed program'
$data=Join-Path $root 'Chosen data'
New-Item -ItemType Directory -Force $root | Out-Null
$installer=New-Object -ComObject WindowsInstaller.Installer
$database=$installer.OpenDatabase($msiPath,0)
$view=$database.OpenView('SELECT `Property` FROM `Control` WHERE `Dialog_`=''StorageSetupDlg'' AND `Control`=''DataPath''')
$view.Execute();$record=$view.Fetch()
if (!$record -or $record.StringData(1) -ne 'JZDATADIR') { throw 'Installer is missing its storage selection field' }
$view.Close()
$installed=$false
try {
  $process=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$msiPath+'"'),'/qn','/norestart',('INSTALLFOLDER="'+$app+'"'),('JZDATADIR="'+$data+'"'),'/L*v',('"'+(Join-Path $root 'install.log')+'"')) -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010)) { Get-Content (Join-Path $root 'install.log') -Tail 100;throw "MSI install failed: $($process.ExitCode)" }
  $installed=$true
  $exe=Join-Path $app 'JunZhengMatch.exe'
  if (!(Test-Path $exe)) { throw 'Installed EXE is missing' }
  $config=Get-Content (Join-Path $env:USERPROFILE 'JunZhenMatch/preferences.json') | ConvertFrom-Json
  if ([IO.Path]::GetFullPath($config.data_dir).TrimEnd('\') -ne [IO.Path]::GetFullPath($data).TrimEnd('\')) { throw 'Installer did not save the selected data directory' }
  $shell=New-Object -ComObject WScript.Shell
  $shortcutPath=Join-Path ([Environment]::GetFolderPath('Programs')) 'JunZhenMatch/䇹政导师匹配.lnk'
  if (!(Test-Path $shortcutPath)) { throw 'Start menu shortcut is missing' }
  $shortcut=$shell.CreateShortcut($shortcutPath)
  if ($shortcut.Arguments -ne '--desktop') { throw 'Shortcut does not launch the independent window' }
  python tools/verify_runtime.py --exe $exe --desktop --report installed-runtime-test.json
  if ($LASTEXITCODE -ne 0) { throw 'Installed desktop/runtime verification failed' }
  New-Item -ItemType Directory -Force $data | Out-Null
  'preserve-user-data' | Set-Content (Join-Path $data 'user-data-marker.txt')
  $process=Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart','/L*v',('"'+(Join-Path $root 'uninstall.log')+'"')) -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010)) { Get-Content (Join-Path $root 'uninstall.log') -Tail 80;throw "MSI uninstall failed: $($process.ExitCode)" }
  $installed=$false
  if (!(Test-Path (Join-Path $data 'user-data-marker.txt'))) { throw 'Uninstall removed user data' }
  if (Test-Path $exe) { throw 'Uninstall did not remove program files' }
  @{status='ok';storage_selection=$true;native_shortcut=$true;installed_runtime=$true;uninstall_preserves_data=$true} | ConvertTo-Json | Set-Content -Encoding utf8 $Report
}
finally {
  if ($installed) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart') -Wait | Out-Null }
}
