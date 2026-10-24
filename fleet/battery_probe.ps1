# Brownout laptop power test. Can this Windows laptop be a real site in the fleet?
# It reads the battery's own power reading (WMI BatteryStatus.DischargeRate, milliwatts) once a second:
# 20 s with the laptop idle, then 20 s with every core busy. It changes nothing on the laptop and needs no
# admin rights. The battery only reports its draw while the laptop runs on battery, so unplug it first.
#
#   powershell -ExecutionPolicy Bypass -File fleet\battery_probe.ps1
#
# The last lines are a summary to paste into team/status/<n>-<name>.md.
$ErrorActionPreference = "Stop"
$IdleS = 20
$LoadS = 20

function Read-Battery {
    $all = @(Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus)
    if ($all.Count -eq 0) { return $null }
    $mw = ($all | Measure-Object -Property DischargeRate -Sum).Sum
    $plugged = @($all | Where-Object { $_.PowerOnline }).Count -gt 0
    [pscustomobject]@{ T = Get-Date; Mw = [int]$mw; Plugged = $plugged }
}

function Measure-Phase([string]$name, [int]$seconds) {
    $rows = @()
    for ($i = 0; $i -lt $seconds; $i++) {
        $r = Read-Battery
        if ($null -eq $r) { throw "no battery reported by WMI BatteryStatus" }
        $rows += [pscustomobject]@{ Phase = $name; T = $r.T; Mw = $r.Mw; Plugged = $r.Plugged }
        Write-Host ("{0:HH:mm:ss}  {1,-5} draining {2,6} mW  plugged in: {3}" -f $r.T, $name, $r.Mw, $r.Plugged)
        Start-Sleep -Milliseconds 1000
    }
    return ,$rows
}

$arch = $env:PROCESSOR_ARCHITECTURE
$cores = [Environment]::ProcessorCount
$py = try { (& python --version) 2>&1 } catch { "not found" }
"Brownout battery probe on $env:COMPUTERNAME ($arch, $cores cores, Windows $([Environment]::OSVersion.Version), Python: $py)"

try {
    $idle = Measure-Phase "idle" $IdleS
    Write-Host "-- now loading every core for $LoadS s --"
    $null = 1..$cores | ForEach-Object {
        Start-Job -ArgumentList $LoadS -ScriptBlock {
            param($s)
            $end = (Get-Date).AddSeconds($s + 3)
            $x = 0.0
            while ((Get-Date) -lt $end) { for ($k = 0; $k -lt 100000; $k++) { $x = [Math]::Sqrt($x + $k) } }
        }
    }
    Start-Sleep -Seconds 2
    $load = Measure-Phase "load" $LoadS
} catch {
    "RESULT: NO READING ($($_.Exception.Message)). This laptop cannot be a measured site."
    exit 1
} finally {
    Get-Job | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}

$rows = @($idle) + @($load)
$changes = @()
for ($i = 1; $i -lt $rows.Count; $i++) {
    if ($rows[$i].Mw -ne $rows[$i - 1].Mw) { $changes += $rows[$i].T }
}
$gaps = @()
for ($i = 1; $i -lt $changes.Count; $i++) { $gaps += ($changes[$i] - $changes[$i - 1]).TotalSeconds }
$medianGap = if ($gaps.Count) { ($gaps | Sort-Object)[[int][Math]::Floor($gaps.Count / 2)] } else { $null }
$idleMw = ($idle | Measure-Object -Property Mw -Average).Average
$loadMw = ($load | Measure-Object -Property Mw -Average).Average
$plugged = @($rows | Where-Object { $_.Plugged }).Count -gt 0

""
"== SUMMARY: $env:COMPUTERNAME ($arch, $cores cores), Python: $py"
"idle average:  {0:N0} mW" -f $idleMw
"load average:  {0:N0} mW" -f $loadMw
"reading changed {0} times in {1} s; typical time between changes: {2}" -f $changes.Count, $rows.Count, $(if ($null -ne $medianGap) { "{0:N1} s" -f $medianGap } else { "never changed" })
if ($plugged) {
    "RESULT: PLUGGED IN. The battery reports its draw only on battery: unplug and run again."
} elseif ($loadMw -le 0 -and $idleMw -le 0) {
    "RESULT: NO READING. The battery reports 0 mW: this laptop cannot be a measured site."
} elseif ($null -ne $medianGap -and $medianGap -le 3 -and ($loadMw - $idleMw) -ge 2000) {
    "RESULT: GOOD. Updates about every {0:N1} s and rises {1:N1} W under load: it can be a real site." -f $medianGap, (($loadMw - $idleMw) / 1000)
} elseif ($null -ne $medianGap -and $medianGap -gt 3) {
    "RESULT: SLOW. The reading changes only every {0:N1} s: usable for minutes-long plans, too slow for a live trace." -f $medianGap
} else {
    "RESULT: UNCLEAR. The reading barely moved under load ({0:N1} W): paste the full output for machine 1." -f (($loadMw - $idleMw) / 1000)
}
