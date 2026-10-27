param([Parameter(Mandatory=$true)][string]$Msi,[string]$PreviousMsi,[string]$Report='installer-test.json')
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
$view=$database.OpenView('SELECT `Text` FROM `Control` WHERE `Dialog_`=''StorageSetupDlg'' AND `Control`=''Artwork''')
$view.Execute();$record=$view.Fetch()
if (!$record -or $record.StringData(1) -ne 'InstallerArtwork') { throw 'Installer artwork is missing from the setup page' }
$view.Close()
$view=$database.OpenView('SELECT `Name` FROM `Binary` WHERE `Name`=''InstallerArtwork''')
$view.Execute();if (!$view.Fetch()) { throw 'Installer artwork is not embedded in MSI' };$view.Close()
$view=$database.OpenView('SELECT `Value` FROM `Property` WHERE `Property`=''Manufacturer''')
$view.Execute();if ($view.Fetch().StringData(1) -ne 'xiaoyuyuan2006dx') { throw 'Unexpected MSI publisher' };$view.Close()

$installed=$false
$previousInstalled=$false
$baseline2753=$false
try {
  if ($PreviousMsi) {
    $previousPath=(Resolve-Path $PreviousMsi).Path
    $previousApp=Join-Path $root 'Previous program';$previousData=Join-Path $root 'Previous data'
    # Advertising selects the feature without installing its EXE. Record the
    # old action's response, then install locally for the real upgrade test.
    $process=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$previousPath+'"'),'ADVERTISE=Complete','/qn','/norestart',('INSTALLFOLDER="'+$previousApp+'"'),('JZDATADIR="'+$previousData+'"'),'/L*v',('"'+(Join-Path $root 'previous-not-local.log')+'"')) -Wait -PassThru
    $baseline2753=[bool](Select-String -Path (Join-Path $root 'previous-not-local.log') -Pattern '2753')
    Write-Host "Previous non-local component exit: $($process.ExitCode); reproduced 2753: $baseline2753"
    $process=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$previousPath+'"'),'ADDLOCAL=Complete','/qn','/norestart',('INSTALLFOLDER="'+$previousApp+'"'),('JZDATADIR="'+$previousData+'"'),'/L*v',('"'+(Join-Path $root 'previous-install.log')+'"')) -Wait -PassThru
    if ($process.ExitCode -notin @(0,3010)) { throw 'Previous release baseline install failed' }
    $previousInstalled=$true
    'preserve-previous-data' | Set-Content (Join-Path $previousData 'upgrade-marker.txt')
    python tools/verify_installer_ui.py --msi $previousPath --app $previousApp --data $previousData --log (Join-Path $root 'previous-reopen.log') --maintenance
    $baselineExit=$LASTEXITCODE
    Write-Host "Previous release reopen exit: $baselineExit; reproduced 2753: $baseline2753"
  }
  python tools/verify_installer_ui.py --msi $msiPath --app $app --data $data --log (Join-Path $root 'install.log')
  if ($LASTEXITCODE -ne 0) { throw 'Visible MSI install failed' }
  $installed=$true
  if ($PreviousMsi) {
    if (Test-Path (Join-Path $previousApp 'JunZhengMatch.exe')) { throw 'Upgrade left the previous program installed' }
    if (!(Test-Path (Join-Path $previousData 'upgrade-marker.txt'))) { throw 'Upgrade removed previous user data' }
    $previousInstalled=$false
  }
  $exe=Join-Path $app 'JunZhengMatch.exe'
  if (!(Test-Path $exe)) { throw 'Installed EXE is missing' }
  $config=Get-Content (Join-Path $env:USERPROFILE 'JunZhenMatch/preferences.json') | ConvertFrom-Json
  if ([IO.Path]::GetFullPath($config.data_dir).TrimEnd('\') -ne [IO.Path]::GetFullPath($data).TrimEnd('\')) { throw "Installer data directory mismatch. Expected: $data; actual: $($config.data_dir)" }
  $originalConfig=Get-Content (Join-Path $env:USERPROFILE 'JunZhenMatch/preferences.json') -Raw
  foreach ($operation in @('reopen','repair')) {
    if ($operation -eq 'reopen') {
      python tools/verify_installer_ui.py --msi $msiPath --app $app --data $data --log (Join-Path $root 'reopen.log') --maintenance
      if ($LASTEXITCODE -ne 0) { throw 'Visible MSI reopen failed' }
    } else {
      $arguments=@('/fa',('"'+$msiPath+'"'),'/qn','/norestart','/L*v',('"'+(Join-Path $root 'repair.log')+'"'))
      $process=Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
      if ($process.ExitCode -notin @(0,3010)) { Get-Content (Join-Path $root 'repair.log') -Tail 100;throw "MSI repair failed: $($process.ExitCode)" }
    }
  }
  if ((Get-Content (Join-Path $env:USERPROFILE 'JunZhenMatch/preferences.json') -Raw) -ne $originalConfig) { throw 'Reopen or repair changed user settings' }
  $shortcutPath=[IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('Programs')) 'JunZhenMatch/䇹政导师匹配.lnk'))
  if (!(Test-Path $shortcutPath)) { throw 'Start menu shortcut is missing' }
  New-Item -ItemType Directory -Force installer-diagnostics | Out-Null
  Copy-Item -LiteralPath $shortcutPath -Destination installer-diagnostics/
  python tools/verify_shortcut.py --path $shortcutPath --expected-target $exe
  if ($LASTEXITCODE -ne 0) { throw 'Installed shortcut verification failed' }
  python tools/verify_runtime.py --exe $exe --desktop --report installed-runtime-test.json
  if ($LASTEXITCODE -ne 0) { throw 'Installed desktop/runtime verification failed' }
  Write-Host 'Installed runtime passed; checking uninstall'
  New-Item -ItemType Directory -Force $data | Out-Null
  'preserve-user-data' | Set-Content (Join-Path $data 'user-data-marker.txt')
  $process=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$msiPath+'"'),'REMOVE=Complete','/qn','/norestart','/L*v',('"'+(Join-Path $root 'component-maintenance.log')+'"')) -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010)) { throw 'Component maintenance repeated the old 2753 failure' }
  if (Test-Path $exe) { throw 'Component maintenance did not remove its EXE' }
  if (!(Test-Path (Join-Path $data 'user-data-marker.txt'))) { throw 'Component maintenance removed user data' }
  $process=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$msiPath+'"'),'ADDLOCAL=Complete','/qn','/norestart',('INSTALLFOLDER="'+$app+'"'),('JZDATADIR="'+$data+'"'),'/L*v',('"'+(Join-Path $root 'component-restore.log')+'"')) -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010) -or !(Test-Path $exe)) { throw 'Component restoration failed' }
  $process=Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart','/L*v',('"'+(Join-Path $root 'uninstall.log')+'"')) -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010)) { Get-Content (Join-Path $root 'uninstall.log') -Tail 80;throw "MSI uninstall failed: $($process.ExitCode)" }
  $installed=$false
  if (!(Test-Path (Join-Path $data 'user-data-marker.txt'))) { throw 'Uninstall removed user data' }
  if (Test-Path $exe) { throw 'Uninstall did not remove program files' }
  @{status='ok';publisher='xiaoyuyuan2006dx';visible_wizard=$true;upgrade_from_v110=[bool]$PreviousMsi;baseline_2753=$baseline2753;component_maintenance=$true;reopen=$true;repair=$true;storage_selection=$true;embedded_artwork=$true;native_shortcut=$true;installed_runtime=$true;uninstall_preserves_data=$true} | ConvertTo-Json | Set-Content -Encoding utf8 $Report
}
finally {
  New-Item -ItemType Directory -Force installer-diagnostics | Out-Null
  Copy-Item (Join-Path $root '*.log') installer-diagnostics/ -ErrorAction SilentlyContinue
  if ($installed) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart') -Wait | Out-Null }
  if ($previousInstalled) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$previousPath+'"'),'/qn','/norestart') -Wait | Out-Null }
}
