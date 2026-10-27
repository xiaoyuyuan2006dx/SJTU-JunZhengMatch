param([Parameter(Mandatory=$true)][string]$Msi,[string]$PreviousMsi,[string]$Report='installer-test.json')
$ErrorActionPreference='Stop'
$msiPath=(Resolve-Path $Msi).Path
$root=Join-Path $env:RUNNER_TEMP ('jz-install-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $root | Out-Null
$configPath=Join-Path $env:USERPROFILE 'JunZhenMatch/preferences.json'
$defaultApp=Join-Path $env:LOCALAPPDATA 'Programs/JunZhenMatch'
$defaultData=Join-Path $env:USERPROFILE 'JunZhenMatch'
$installer=New-Object -ComObject WindowsInstaller.Installer
$database=$installer.OpenDatabase($msiPath,0)
function Get-MsiProperty($name) {
  $view=$database.OpenView(('SELECT `Value` FROM `Property` WHERE `Property`=''{0}''' -f $name))
  $view.Execute();$record=$view.Fetch();$value=$record.StringData(1);$view.Close();return $value
}
if ((Get-MsiProperty 'Manufacturer') -ne 'xiaoyuyuan2006dx') { throw 'Unexpected MSI publisher' }
$expectedVersion=Get-MsiProperty 'ProductVersion'
$view=$database.OpenView('SELECT `Text` FROM `Control` WHERE `Dialog_`=''StorageSetupDlg'' AND `Control`=''Artwork''')
$view.Execute();if ($view.Fetch().StringData(1) -ne 'InstallerArtwork') { throw 'Installer artwork missing' };$view.Close()

function Invoke-Quiet($package,$operation,$name,$extra=@()) {
  $arguments=@($operation,('"'+$package+'"'),'/qn','/norestart')+$extra+@('/L*v',('"'+(Join-Path $root ($name+'.log'))+'"'))
  $process=Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
  if ($process.ExitCode -notin @(0,3010)) {
    Get-Content (Join-Path $root ($name+'.log')) -Tail 80
    throw "MSI $name failed: $($process.ExitCode)"
  }
}
function Invoke-Wizard($package,$app,$data,$name,[switch]$Maintenance,[switch]$EditPaths,[switch]$Remove) {
  $arguments=@('tools/verify_installer_ui.py','--msi',$package,'--app',$app,'--data',$data,'--log',(Join-Path $root ($name+'.log')),'--no-properties')
  if ($Maintenance) {$arguments+='--maintenance'}
  if ($EditPaths) {$arguments+='--edit-paths'}
  if ($Remove) {$arguments+='--remove'}
  & python @arguments
  if ($LASTEXITCODE -ne 0) { throw "Visible MSI $name failed" }
}
function Assert-Program($app) {
  $exe=Join-Path $app 'JunZhengMatch.exe'
  if (!(Test-Path -LiteralPath $exe)) { throw "Installer reported success without an EXE: $exe" }
  if ((Get-Item -LiteralPath $exe).VersionInfo.ProductVersion -ne $expectedVersion) { throw 'Installed program version mismatch' }
  return $exe
}
function Get-DataPath {
  return (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).data_dir
}
function Assert-DataPath($expected) {
  if ([IO.Path]::GetFullPath((Get-DataPath)).TrimEnd('\') -ne [IO.Path]::GetFullPath($expected).TrimEnd('\')) { throw "Data selection mismatch: $(Get-DataPath); expected $expected" }
}
function Mark-Data($data) {
  New-Item -ItemType Directory -Force $data | Out-Null
  $db=Join-Path $data 'sjtu_faculty_data.db'
  if (!(Test-Path -LiteralPath $db)) { Copy-Item -LiteralPath data/faculty.db -Destination $db }
  'preserve-user-data' | Set-Content -LiteralPath (Join-Path $data 'user-data-marker.txt')
  return (Get-FileHash -LiteralPath $db -Algorithm SHA256).Hash
}
function Assert-Data($data,$hash) {
  if (!(Test-Path -LiteralPath (Join-Path $data 'user-data-marker.txt'))) { throw 'User data marker was removed' }
  if ((Get-FileHash -LiteralPath (Join-Path $data 'sjtu_faculty_data.db') -Algorithm SHA256).Hash -ne $hash) { throw 'User database changed during maintenance' }
}
function Test-Program($exe,$reportPath) {
  $process=Start-Process -FilePath $exe -ArgumentList @('--self-test','--report',('"'+$reportPath+'"')) -Wait -PassThru
  if ($process.ExitCode -ne 0 -or (Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json).status -ne 'ok') { throw 'Installed EXE cannot run' }
}
$installed=$false;$previousInstalled=$false;$cases=@()
try {
  # Fresh default installation, exactly like double-clicking. No INSTALLFOLDER,
  # JZDATADIR, ADDLOCAL or REINSTALL properties are injected into the MSI.
  if (Test-Path (Join-Path $defaultApp 'JunZhengMatch.exe')) { throw 'Windows test machine is not clean' }
  Invoke-Wizard $msiPath $defaultApp $defaultData 'fresh-default'
  $installed=$true;$exe=Assert-Program $defaultApp
  Test-Program $exe "$pwd/fresh-install-test.json"
  $chosen=Get-DataPath;$hash=Mark-Data $chosen;$settings=Get-Content $configPath -Raw
  $cases+='fresh_default_exe_runs'

  # Reproduce the user's visible state: registered as installed, EXE gone.
  Remove-Item -LiteralPath $exe -Force
  $stale=Join-Path $root 'stale-registry-location'
  Set-ItemProperty -Path 'HKCU:\Software\TaroDeluxe\JunZhenMatch' -Name DataDir -Value $stale
  Invoke-Wizard $msiPath $defaultApp $chosen 'repair-missing-exe' -Maintenance
  $exe=Assert-Program $defaultApp
  Test-Program $exe "$pwd/fresh-repair-test.json"
  if ((Get-Content $configPath -Raw) -ne $settings) { throw 'Repair rewrote user preferences' }
  if (Test-Path $stale) { throw 'Repair switched to a stale registry data directory' }
  Assert-Data $chosen $hash
  $cases+='missing_exe_repaired';$cases+='repair_preserves_settings_and_database'
  Invoke-Wizard $msiPath $defaultApp $chosen 'default-uninstall' -Maintenance -Remove
  $installed=$false
  if (Test-Path $exe) { throw 'GUI uninstall left the default EXE behind' }
  Assert-Data $chosen $hash
  $cases+='gui_uninstall_preserves_data'

  # Enter paths through the actual edit controls rather than command properties.
  $customApp=Join-Path $root '手动选择 program';$customData=Join-Path $root '手动选择 data'
  Invoke-Wizard $msiPath $customApp $customData 'fresh-edited-paths' -EditPaths
  $installed=$true;$exe=Assert-Program $customApp
  Assert-DataPath $customData
  $customHash=Mark-Data $customData
  Test-Program $exe "$pwd/custom-install-test.json"
  $cases+='fresh_gui_edited_paths'
  Invoke-Wizard $msiPath $customApp $customData 'custom-uninstall' -Maintenance -Remove
  $installed=$false
  if (Test-Path $exe) { throw 'GUI uninstall left the custom EXE behind' }
  Assert-Data $customData $customHash

  # An old advertised registration has a valid MSI product registration but no
  # local EXE. Upgrading must not inherit that missing-file feature state.
  $legacyEmpty=$false
  if ($PreviousMsi) {
    $previousPath=(Resolve-Path $PreviousMsi).Path
    $legacyDatabase=$installer.OpenDatabase($previousPath,0)
    $legacyView=$legacyDatabase.OpenView('SELECT `Value` FROM `Property` WHERE `Property`=''ProductCode''')
    $legacyView.Execute();$legacyCode=$legacyView.Fetch().StringData(1);$legacyView.Close()
    $previousApp=Join-Path $root 'Legacy empty program'
    $previousData=Join-Path $root 'Legacy teacher data'
    $legacyHash=Mark-Data $previousData
    Invoke-Quiet $previousPath '/i' 'legacy-empty-registration' @('ADVERTISE=Complete',('INSTALLFOLDER="'+$previousApp+'"'),('JZDATADIR="'+$previousData+'"'))
    $previousInstalled=$true
    $legacyEmpty=!(Test-Path (Join-Path $previousApp 'JunZhengMatch.exe'))
    if (!$legacyEmpty) { throw 'Legacy registration case unexpectedly installed an EXE' }
    $app=Join-Path $root 'Recovered program'
    $data=$previousData
    Invoke-Wizard $msiPath $app $data 'recover-empty-upgrade' -EditPaths
    $installed=$true;$previousInstalled=$false;$exe=Assert-Program $app
    $legacyRegistered=$false
    try {$null=$installer.ProductInfo($legacyCode,'VersionString');$legacyRegistered=$true} catch {}
    if ($legacyRegistered) { throw 'Upgrade left the old empty product registration behind' }
    Assert-DataPath $data;Assert-Data $data $legacyHash
    $cases+='upgrade_recovers_empty_v111_registration';$cases+='old_registration_removed'
  } else {
    $app=Join-Path $root 'Final program';$data=Join-Path $root 'Final data'
    Invoke-Wizard $msiPath $app $data 'final-install' -EditPaths
    $installed=$true;$exe=Assert-Program $app;$legacyHash=Mark-Data $data
  }
  $shortcut=[IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('Programs')) 'JunZhenMatch/䇹政导师匹配.lnk'))
  python tools/verify_shortcut.py --path $shortcut --expected-target $exe
  if ($LASTEXITCODE -ne 0) { throw 'Installed shortcut points to the wrong program' }
  $settings=Get-Content $configPath -Raw
  python tools/verify_runtime.py --exe $exe --desktop --report installed-runtime-test.json
  if ($LASTEXITCODE -ne 0) { throw 'Installed native/shared runtime failed' }
  Assert-DataPath $data;Assert-Data $data $legacyHash
  Invoke-Wizard $msiPath $app $data 'reopen-repair' -Maintenance
  $exe=Assert-Program $app
  Invoke-Quiet $msiPath '/fa' 'external-repair'
  $exe=Assert-Program $app
  if ((Get-Content $configPath -Raw) -ne $settings) { throw 'Reopen or external repair changed user settings' }
  Assert-Data $data $legacyHash
  $cases+='native_shortcut_and_shared_runtime';$cases+='gui_and_external_repair'
  Invoke-Wizard $msiPath $app $data 'final-uninstall' -Maintenance -Remove
  $installed=$false
  if (Test-Path $exe) { throw 'Final uninstall did not remove program files' }
  Assert-Data $data $legacyHash
  @{status='ok';publisher='xiaoyuyuan2006dx';version=$expectedVersion;no_cli_install_overrides=$true;legacy_empty_registration=$legacyEmpty;cases=$cases;uninstall_preserves_database=$true} | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $Report
}
finally {
  New-Item -ItemType Directory -Force installer-diagnostics | Out-Null
  Copy-Item (Join-Path $root '*.log') installer-diagnostics/ -ErrorAction SilentlyContinue
  if ($installed) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart') -Wait | Out-Null }
  if ($previousInstalled) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$previousPath+'"'),'/qn','/norestart') -Wait | Out-Null }
}
