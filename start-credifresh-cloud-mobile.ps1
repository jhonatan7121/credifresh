$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$mobilePath = Join-Path $projectRoot "apps\client-mobile"
$env:EXPO_PUBLIC_API_BASE_URL = "https://credifresh-api-demo.onrender.com"

Write-Host "CrediFresh móvil usará la API de Render: $env:EXPO_PUBLIC_API_BASE_URL" -ForegroundColor Cyan
Write-Host "Iniciando Expo Go por la red local. El computador y el iPhone deben estar en la misma Wi-Fi; deja esta ventana abierta." -ForegroundColor Yellow

Push-Location $mobilePath
try {
    npm.cmd run start -- --clear --lan
} finally {
    Pop-Location
}
