$ErrorActionPreference = "Stop"

$ProjectName = if ($env:PROJECT_NAME) { $env:PROJECT_NAME } else { "meme-collector-smoke" }
$ServiceUrl = if ($env:SERVICE_URL) { $env:SERVICE_URL } else { "http://127.0.0.1:8000/health" }
$VolumeName = "${ProjectName}_meme_collector_data"

try {
    docker compose -p $ProjectName build
    docker compose -p $ProjectName up -d

    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $ServiceUrl | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) {
        throw "Service did not become healthy at $ServiceUrl"
    }

    Invoke-WebRequest -UseBasicParsing -Uri $ServiceUrl | Out-Null
    docker run --rm -v "${VolumeName}:/data" busybox test -f /data/meme_collector.sqlite3

    docker compose -p $ProjectName restart meme-collector
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $ServiceUrl | Out-Null
            $healthy = $true
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) {
        throw "Service did not become healthy after restart at $ServiceUrl"
    }

    Write-Host "Docker smoke verification passed for $ProjectName."
} finally {
    docker compose -p $ProjectName down | Out-Null
}
