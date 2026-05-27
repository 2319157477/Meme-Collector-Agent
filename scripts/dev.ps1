$ErrorActionPreference = "Stop"
$hostName = if ($env:APP_HOST) { $env:APP_HOST } else { "0.0.0.0" }
$port = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }
python -m uvicorn meme_collector_app.main:create_app --factory --host $hostName --port $port
