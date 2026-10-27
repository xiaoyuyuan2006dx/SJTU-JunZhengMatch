param([Parameter(Mandatory=$true)][string]$Msi,[string]$PreviousMsi,[string]$FutureMsi,[string]$CurrentMsi,[string]$Report='installer-test.json')
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
  $null=$view.Execute();$record=$view.Fetch();$value=$record.StringData(1);$null=$view.Close();return [string]$value
}
$publisher=Get-MsiProperty 'Manufacturer'
if ($publisher -ne 'xiaoyuyuan2006dx') { throw "Unexpected MSI publisher: $($publisher | Out-String)" }
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
function Invoke-Wizard($package,$app,$data,$name,[switch]$Maintenance,[switch]$EditPaths,[switch]$Remove,[switch]$AutomaticLog,[switch]$RejectPaths,[switch]$CancelUpgrade,[switch]$ExpectNewer,[switch]$OpenExisting,[switch]$DirectUninstall,[switch]$ExpectError) {
  $arguments=@('tools/verify_installer_ui.py','--msi',$package,'--app',$app,'--data',$data,'--log',(Join-Path $root ($name+'.log')),'--no-properties')
  if ($Maintenance) {$arguments+='--maintenance'}
  if ($EditPaths) {$arguments+='--edit-paths'}
  if ($Remove) {$arguments+='--remove'}
  if ($AutomaticLog) {$arguments+='--automatic-log'}
  if ($RejectPaths) {$arguments+='--reject-paths'}
  if ($CancelUpgrade) {$arguments+='--cancel-upgrade'}
  if ($ExpectNewer) {$arguments+='--expect-newer'}
  if ($OpenExisting) {$arguments+='--open-existing'}
  if ($DirectUninstall) {$arguments+='--direct-uninstall'}
  if ($ExpectError) {$arguments+='--expect-error'}
  & python @arguments
  if ($LASTEXITCODE -ne 0) { throw "Visible MSI $name failed" }
}
function Assert-RejectedQuiet($package,$app,$data,$name) {
  $log=Join-Path $root ($name+'.log')
  $arguments=@('/i',('"'+$package+'"'),'/qn','/norestart',('INSTALLFOLDER="'+$app+'"'),('JZDATADIR="'+$data+'"'),'/L*v',('"'+$log+'"'))
  $process=Start-Process msiexec.exe -ArgumentList $arguments -Wait -PassThru
  if ($process.ExitCode -ne 1603) { throw 'Quiet invalid storage path was not rejected' }
  $text=Get-Content -LiteralPath $log -Raw
  if ($text -notmatch 'RejectInvalidDataLocation' -or $text -match 'Executing op: CustomActionSchedule\(Action=ConfigureStorage') { throw 'Invalid storage validation ran too late' }
}
function Assert-Program($app) {
  $exe=Join-Path $app 'JunZhengMatch.exe'
  if (!(Test-Path -LiteralPath $exe)) { throw "Installer reported success without an EXE: $exe" }
  if (!(Test-Path -LiteralPath (Join-Path $app 'desktop-mode'))) { throw 'MSI desktop launch marker is missing' }
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
  if (Test-Path $configPath) { throw 'Default user preferences are not clean before first install' }
  foreach ($kind in @('same','nested')) {
    $badApp=Join-Path $root ('invalid-'+$kind)
    $badData=if ($kind -eq 'same') {$badApp} else {Join-Path $badApp 'data'}
    Invoke-Wizard $msiPath $badApp $badData ('reject-'+$kind) -EditPaths -RejectPaths
    if (Test-Path (Join-Path $badApp 'JunZhengMatch.exe')) { throw 'Invalid directory choice copied program files' }
    if (Test-Path $configPath) { throw 'Invalid directory choice changed user configuration' }
    Assert-RejectedQuiet $msiPath $badApp $badData ('quiet-reject-'+$kind)
    if (Test-Path $configPath) { throw 'Quiet invalid directory choice changed user configuration' }
    $cases+=('reject_'+$kind+'_data_before_install')
  }
  Invoke-Wizard $msiPath $defaultApp $defaultData 'fresh-default' -AutomaticLog
  $installed=$true;$exe=Assert-Program $defaultApp
  Assert-DataPath $defaultData
  $progress=Get-Content (Join-Path $root 'fresh-default.progress.json') -Raw | ConvertFrom-Json
  if ($progress.stages.Count -lt 1 -or @($progress.positions | Where-Object {$_ -gt 0}).Count -lt 1) { throw 'MSI did not display actual stage/progress updates' }
  if ($progress.activity_frames.Count -lt 2) { throw 'Installer particle animation did not advance' }
  Copy-Item (Join-Path $root 'fresh-default.progress.json') "$pwd/installer-progress-test.json"
  Test-Program $exe "$pwd/fresh-install-test.json"
  $chosen=Get-DataPath;$hash=Mark-Data $chosen;$settings=Get-Content $configPath -Raw
  $cases+='fresh_default_exe_runs';$cases+='automatic_install_log'
  $cases+='independent_particle_animation_updates'

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

  # Reproduce a registered-but-advertised state for this same product/version.
  # A repair must install absent components, not request Reinstall of them.
  $emptyApp=$defaultApp
  $emptyData=$defaultData
  # The shipping package disallows advertising during normal installation.
  # A CI-only fixture relaxes that UI attribute to reproduce the abnormal
  # feature state in the user's log. All repair events/sequences stay intact.
  $fixture=Join-Path $root 'advertised-state-fixture.msi'
  Copy-Item -LiteralPath $msiPath -Destination $fixture
  $fixtureDb=$installer.OpenDatabase($fixture,1)
  $fixtureView=$fixtureDb.OpenView('UPDATE `Feature` SET `Attributes`=0 WHERE `Feature`=''Complete''')
  $null=$fixtureView.Execute();$null=$fixtureView.Close();$null=$fixtureDb.Commit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($fixtureView)
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($fixtureDb)
  Invoke-Wizard $fixture $emptyApp $emptyData 'same-version-base'
  Invoke-Quiet $fixture '/i' 'same-version-advertised' @('ADVERTISE=Complete')
  $installed=$true
  if (Test-Path (Join-Path $emptyApp 'JunZhengMatch.exe')) { throw 'Same version empty registration unexpectedly copied the EXE' }
  $emptyHash=Mark-Data $emptyData
  # Keep the fixture source consistent: Windows SecureRepair correctly rejects
  # swapping in a byte-different MSI under the same package identity.
  Invoke-Wizard $fixture $emptyApp $emptyData 'same-version-empty-repair' -Maintenance
  $exe=Assert-Program $emptyApp
  Test-Program $exe "$pwd/empty-registration-repair-test.json"
  Assert-Data $emptyData $emptyHash
  $cases+='same_version_advertised_repair_installs_components'
  Invoke-Wizard $fixture $emptyApp $emptyData 'same-version-uninstall' -Maintenance -Remove
  $installed=$false
  Assert-Data $emptyData $emptyHash

  # Enter paths through the actual edit controls rather than command properties.
  $customRoot=if (Test-Path D:\) {Join-Path D:\ ('jz-secondary-drive-'+[guid]::NewGuid().ToString('N'))} else {$root}
  $customApp=Join-Path $customRoot '手动选择 program';$customData=Join-Path $root '手动选择 data'
  Invoke-Wizard $msiPath $customApp $customData 'fresh-edited-paths' -EditPaths
  $installed=$true;$exe=Assert-Program $customApp
  Assert-DataPath $customData
  $customHash=Mark-Data $customData
  Test-Program $exe "$pwd/custom-install-test.json"
  $cases+='fresh_gui_edited_paths'
  if ($customRoot -ne $root) { $cases+='secondary_drive_install_uninstall_and_failure_rollback' }
  Invoke-Wizard $msiPath $customApp $customData 'custom-uninstall' -DirectUninstall
  $cases+='direct_uninstall_has_separate_completion'
  $installed=$false
  if (Test-Path $exe) { throw 'GUI uninstall left the custom EXE behind' }
  Assert-Data $customData $customHash

  # CI-only error injection after RemoveFiles: exercise the actual 1926-style
  # error dialog and verify rollback restores the EXE instead of claiming success.
  $errorMsi=Join-Path $root 'uninstall-error-fixture.msi'
  Copy-Item -LiteralPath $msiPath -Destination $errorMsi
  $errorDb=$installer.OpenDatabase($errorMsi,1)
  $stream=$installer.CreateRecord(2)
  $stream.StringData(1)='TestErrorBinary'
  $stream.SetStream(2,(Resolve-Path build/InstallerErrorFixture.dll).Path)
  $v=$errorDb.OpenView('INSERT INTO `Binary` (`Name`,`Data`) VALUES (?,?)')
  $v.Execute($stream);$v.Close()
  $v=$errorDb.OpenView('INSERT INTO `CustomAction` (`Action`,`Type`,`Source`,`Target`) VALUES (''TestRollbackError'',1025,''TestErrorBinary'',''TestRollbackError'')')
  $v.Execute();$v.Close()
  $v=$errorDb.OpenView('SELECT `Sequence` FROM `InstallExecuteSequence` WHERE `Action`=''RemoveFiles''')
  $v.Execute();$seq=$v.Fetch().IntegerData(1)+1;$v.Close()
  $v=$errorDb.OpenView(('INSERT INTO `InstallExecuteSequence` (`Action`,`Condition`,`Sequence`) VALUES (''TestRollbackError'',''REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'',{0})' -f $seq))
  $v.Execute();$v.Close();$errorDb.Commit()
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($v)
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($errorDb)
  Invoke-Wizard $errorMsi $customApp $customData 'error-fixture-install' -EditPaths
  $installed=$true;$exe=Assert-Program $customApp
  $errorHash=Mark-Data $customData
  Invoke-Wizard $errorMsi $customApp $customData 'error-fixture-uninstall' -Maintenance -Remove -ExpectError
  $exe=Assert-Program $customApp
  Assert-Data $customData $errorHash
  $cases+='permission_error_dialog_without_2814'
  $cases+='failed_uninstall_rolls_back_program_and_keeps_data'
  # Remove the fixture trigger through a supported public MSI property only in
  # this disposable package so the CI machine can finish cleaning up.
  Invoke-Quiet $errorMsi '/x' 'error-fixture-cleanup' @('UPGRADINGPRODUCTCODE=1')
  $installed=$false

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
    $invalidUpgrade=Join-Path $root 'Invalid upgrade'
    Assert-RejectedQuiet $msiPath $invalidUpgrade $invalidUpgrade 'reject-upgrade-before-removal'
    $null=$installer.ProductInfo($legacyCode,'VersionString')
    Assert-Data $previousData $legacyHash
    $cases+='invalid_upgrade_preserves_existing_registration'
    $app=Join-Path $root 'Recovered program'
    $data=$previousData
    Invoke-Wizard $msiPath $app $data 'cancel-upgrade' -CancelUpgrade
    $null=$installer.ProductInfo($legacyCode,'VersionString')
    Assert-Data $previousData $legacyHash
    $cases+='upgrade_confirmation_cancel_preserves_old_version'
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
  if ($CurrentMsi) {
    $currentPath=(Resolve-Path $CurrentMsi).Path
    $currentApp=Join-Path $root 'v120 program';$currentData=Join-Path $root 'v120 data'
    Invoke-Quiet $currentPath '/i' 'v120-baseline' @(('INSTALLFOLDER="'+$currentApp+'"'),('JZDATADIR="'+$currentData+'"'))
    $currentHash=Mark-Data $currentData
    Invoke-Wizard $msiPath $currentApp $currentData 'v120-upgrade'
    $installed=$true;$exe=Assert-Program $currentApp
    Assert-Data $currentData $currentHash
    Invoke-Wizard $msiPath $currentApp $currentData 'v120-upgrade-uninstall' -Maintenance -Remove
    $installed=$false
    if (Test-Path $exe) { throw 'Upgrade from v1.2.0 did not uninstall' }
    Assert-Data $currentData $currentHash
    $cases+='v120_upgrade_then_gui_uninstall'
  }
  if ($FutureMsi) {
    $futurePath=(Resolve-Path $FutureMsi).Path
    $futureApp=Join-Path $root 'Newer version program';$futureData=Join-Path $root 'Newer version data'
    Invoke-Wizard $futurePath $futureApp $futureData 'future-install' -EditPaths
    $installed=$true
    $futureExe=Assert-Program $futureApp;$futureHash=Mark-Data $futureData
    Invoke-Wizard $msiPath $futureApp $futureData 'newer-version-cancel' -ExpectNewer
    if (!(Test-Path $futureExe)) { throw 'Older package removed the installed newer version' }
    Assert-Data $futureData $futureHash
    $cases+='newer_installed_version_offers_maintenance_without_downgrade'
    Invoke-Wizard $msiPath $futureApp $futureData 'open-related-maintenance' -ExpectNewer -OpenExisting
    if (!(Test-Path $futureExe)) { throw 'Opening installed maintenance removed its EXE' }
    Assert-Data $futureData $futureHash
    $cases+='related_version_maintenance_opens_correct_package'
    Invoke-Wizard $futurePath $futureApp $futureData 'future-uninstall' -Maintenance -Remove
    $installed=$false
    Assert-Data $futureData $futureHash
  }
  @{status='ok';publisher='xiaoyuyuan2006dx';version=$expectedVersion;no_cli_install_overrides=$true;legacy_empty_registration=$legacyEmpty;advertised_state_fixture='Feature.Attributes=0; production repair events and sequences unchanged';cases=$cases;uninstall_preserves_database=$true} | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $Report
}
finally {
  New-Item -ItemType Directory -Force installer-diagnostics | Out-Null
  Copy-Item (Join-Path $root '*.log') installer-diagnostics/ -ErrorAction SilentlyContinue
  if ($installed) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$msiPath+'"'),'/qn','/norestart') -Wait | Out-Null }
  if ($previousInstalled) { Start-Process msiexec.exe -ArgumentList @('/x',('"'+$previousPath+'"'),'/qn','/norestart') -Wait | Out-Null }
}
