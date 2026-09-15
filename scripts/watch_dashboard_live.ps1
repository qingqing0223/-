$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8765"
Write-Host "Watching Suqi realtime backend every 5 seconds. Ctrl+C to stop." -ForegroundColor Cyan

function Value-OrDefault($value, $default) {
    if ($null -ne $value -and "$value" -ne "") { return $value }
    return $default
}

while ($true) {
    try {
        $b = Invoke-RestMethod "$base/api/bootstrap"
        $top = $b.topStats
        $live = $b.live
        $latest = $null
        if ($live.incidents -and $live.incidents.Count -gt 0) { $latest = $live.incidents[0] }

        $cumulative = Value-OrDefault $top.cumulativeInfo $top.totalOpinions
        $recent10m = Value-OrDefault $top.recent10mInfo 0
        $regionCount = Value-OrDefault $top.detectedRegionCount "-"
        $platformCount = Value-OrDefault $top.detectedPlatformCount "-"
        $liveTotal = Value-OrDefault $live.counts.total 0

        Clear-Host
        Write-Host ("Time: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -ForegroundColor Yellow
        Write-Host ("Cumulative: {0}" -f $cumulative)
        Write-Host ("Recent 10m: {0}" -f $recent10m)
        Write-Host ("Support: {0}" -f $top.supportCount)
        Write-Host ("Detected regions: {0}" -f $regionCount)
        Write-Host ("Detected platforms: {0}" -f $platformCount)
        Write-Host ("Live accepted total: {0}" -f $liveTotal)
        if ($latest) {
            Write-Host ""
            Write-Host "Latest incident:" -ForegroundColor Cyan
            Write-Host ("  id={0} platform={1} region={2} collectedAt={3}" -f $latest.id,$latest.platform,$latest.region,$latest.collectedAt)
            Write-Host ("  {0}" -f $latest.text)
        }
    }
    catch {
        Clear-Host
        Write-Host "Dashboard backend unavailable: $($_.Exception.Message)" -ForegroundColor Red
    }
    Start-Sleep -Seconds 5
}
