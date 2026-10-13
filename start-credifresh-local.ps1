$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$mobilePath = Join-Path $projectRoot "apps\client-mobile"
$mobileEnvPath = Join-Path $mobilePath ".env"

try {
    $candidateAddresses = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.AddressState -eq "Preferred" -and
                $_.IPAddress -notmatch "^(127\.|169\.254\.)" -and
                $_.InterfaceAlias -notmatch "(?i)WSL|vEthernet|Docker|VirtualBox|VMware|Bluetooth|Loopback|Default Switch"
            } |
            Sort-Object @{ Expression = { if ($_.InterfaceAlias -match "(?i)Wi-?Fi|WLAN|Wireless") { 0 } else { 1 } } }, InterfaceIndex
    )
} catch {
    Write-Host "No pude detectar la IP local automáticamente. Comprueba que el Wi-Fi esté conectado." -ForegroundColor Red
    exit 1
}

if ($candidateAddresses.Count -eq 0) {
    Write-Host "No encontré una dirección IPv4 local activa. Conecta el computador a la misma red que el iPhone y vuelve a intentarlo." -ForegroundColor Red
    exit 1
}

$apiAddress = $candidateAddresses[0].IPAddress
$apiUrl = "http://$apiAddress`:8000"
$env:API_BASE_URL = $apiUrl
$expoPort = 8081
$expoPortInUse = $true
while ($expoPort -le 8090) {
    $expoPortInUse = [bool](Get-NetTCPConnection -State Listen -LocalPort $expoPort -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $expoPortInUse) { break }
    $expoPort++
}
if ($expoPortInUse) {
    Write-Host "Los puertos 8081 a 8090 ya están ocupados. Cierra otro servidor Expo y vuelve a intentarlo." -ForegroundColor Red
    exit 1
}
$env:RESET_PASSWORD_URL = "http://$apiAddress`:3000/reset-password.html"
$env:ALLOWED_ORIGINS = "http://$apiAddress`:3000,http://localhost:3000,http://127.0.0.1:3000"
$apiEnvLine = "EXPO_PUBLIC_API_BASE_URL=$apiUrl"
$envContent = if (Test-Path -LiteralPath $mobileEnvPath) {
    [System.IO.File]::ReadAllText($mobileEnvPath)
} else {
    ""
}

if ($envContent -match "(?m)^EXPO_PUBLIC_API_BASE_URL=.*$") {
    $envContent = [System.Text.RegularExpressions.Regex]::Replace(
        $envContent,
        "(?m)^EXPO_PUBLIC_API_BASE_URL=.*$",
        [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $apiEnvLine }
    )
} else {
    if ($envContent.Length -gt 0 -and -not $envContent.EndsWith("`n")) { $envContent += "`r`n" }
    $envContent += $apiEnvLine + "`r`n"
}

[System.IO.File]::WriteAllText($mobileEnvPath, $envContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "API móvil configurada en $apiUrl" -ForegroundColor Cyan

Push-Location $projectRoot
try {
    Write-Host "Iniciando PostgreSQL, API y portal de administración..." -ForegroundColor Cyan
    docker compose up -d --build postgres backend-api admin-portal
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No pude iniciar Docker. Abre Docker Desktop y vuelve a ejecutar este iniciador." -ForegroundColor Red
        exit 1
    }

    $databaseReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker compose exec -T postgres pg_isready -U credifresh_user -d credifresh_db *> $null
        if ($LASTEXITCODE -eq 0) {
            $databaseReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $databaseReady) {
        Write-Host "PostgreSQL no quedó listo. Revisa Docker Desktop y los logs del contenedor credifresh-postgres." -ForegroundColor Red
        exit 1
    }

    Write-Host "Aplicando migraciones de base de datos..." -ForegroundColor Cyan
    docker compose run --rm --no-deps backend-api alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No pude actualizar la base de datos. Revisa Docker Desktop y vuelve a iniciar el proyecto." -ForegroundColor Red
        exit 1
    }

    $apiReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
            if ($health.status -eq "healthy") {
                $apiReady = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $apiReady) {
        Write-Host "El API no respondió como saludable. Revisa Docker Desktop y los logs de backend-api." -ForegroundColor Red
        docker compose logs --tail 30 backend-api
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "API saludable. Iniciando Expo en el puerto $expoPort; deja esta ventana abierta y escanea el QR con Expo Go." -ForegroundColor Green
Push-Location $mobilePath
try {
    npm.cmd run start -- --clear --port $expoPort
} finally {
    Pop-Location
}
