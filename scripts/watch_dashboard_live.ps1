$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8765"
Write-Host "Watching Suqi realtime backend every 5 seconds. Ctrl+C to stop." -ForegroundColor Cyan

while ($true) {
    try {
        $b = Invoke-RestMethod "$base/api/bootstrap"
        $top = $b.topStats
        $live = $b.live
        $latest = $null
        if ($live.incidents -and $live.incidents.Count -gt 0) { $latest = $live.incidents[0] }

        Clear-Host
        Write-Host ("Time: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -ForegroundColor Yellow
        Write-Host ("Cumulative: {0}" -f ($top.cumulativeInfo ?? $top.totalOpinions))
        Write-Host ("Recent 10m: {0}" -f ($top.recent10mInfo ?? 0))
        Write-Host ("Support: {0}" -f $top.supportCount)
        Write-Host ("Detected regions: {0}" -f ($top.detectedRegionCount ?? "-"))
        Write-Host ("Detected platforms: {0}" -f ($top.detectedPlatformCount ?? "-"))
        Write-Host ("Live accepted total: {0}" -f ($live.counts.total ?? 0))
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
