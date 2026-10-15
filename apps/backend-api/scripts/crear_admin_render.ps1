<#
Create the first administrator in the hosted CrediFresh API.
Secrets are requested interactively and are not written to a file.
#>

$ErrorActionPreference = 'Stop'

function ConvertFrom-SecurePrompt {
    param([Parameter(Mandatory = $true)][Security.SecureString]$Value)

    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

$apiBase = Read-Host 'URL base de la API de Render [https://credifresh-api-demo.onrender.com]'
if ([string]::IsNullOrWhiteSpace($apiBase)) {
    $apiBase = 'https://credifresh-api-demo.onrender.com'
}
$apiBase = $apiBase.Trim().TrimEnd('/')
if (-not $apiBase.StartsWith('https://')) {
    throw 'Por seguridad, la URL de la API debe usar HTTPS.'
}

$email = (Read-Host 'Correo para el administrador').Trim().ToLowerInvariant()
$tokenSecure = Read-Host 'Token temporal ADMIN_BOOTSTRAP_TOKEN (entrada oculta)' -AsSecureString
$passwordSecure = Read-Host 'Nueva contraseña del administrador (entrada oculta)' -AsSecureString
$confirmationSecure = Read-Host 'Confirma la contraseña (entrada oculta)' -AsSecureString

$token = $null
$password = $null
$confirmation = $null
$body = $null
$payload = $null
$failed = $false
try {
    $token = ConvertFrom-SecurePrompt $tokenSecure
    $password = ConvertFrom-SecurePrompt $passwordSecure
    $confirmation = ConvertFrom-SecurePrompt $confirmationSecure

    if ($token.Length -lt 32) {
        throw 'El token debe tener al menos 32 caracteres. Genera uno aleatorio y vuelve a intentarlo.'
    }
    if ($email -notmatch '^[\w.-]+@[\w.-]+\.\w+$') {
        throw 'El correo no tiene un formato válido.'
    }
    if ($password.Length -lt 12) {
        throw 'La contraseña debe tener al menos 12 caracteres.'
    }
    if ([Text.Encoding]::UTF8.GetByteCount($password) -gt 72) {
        throw 'La contraseña supera el límite seguro de 72 bytes. Usa una contraseña más corta.'
    }
    if ($password -cne $confirmation) {
        throw 'Las contraseñas no coinciden.'
    }

    $payload = @{ email = $email; password = $password }
    $body = ConvertTo-Json -InputObject $payload -Compress
    $null = Invoke-RestMethod `
        -Method Post `
        -Uri "$apiBase/auth/bootstrap-admin" `
        -Headers @{ 'X-Admin-Bootstrap-Token' = $token } `
        -ContentType 'application/json' `
        -Body $body

    Write-Host 'Administrador creado correctamente. Ahora elimina ADMIN_BOOTSTRAP_TOKEN de Render.' -ForegroundColor Green
}
catch {
    Write-Host 'No se pudo crear el administrador. Verifica la URL, que la API esté desplegada y que el token temporal sea el mismo configurado en Render.' -ForegroundColor Red
    $failed = $true
}
finally {
    $token = $null
    $password = $null
    $confirmation = $null
    $body = $null
    $payload = $null
    if ($tokenSecure) { $tokenSecure.Dispose() }
    if ($passwordSecure) { $passwordSecure.Dispose() }
    if ($confirmationSecure) { $confirmationSecure.Dispose() }
}

if ($failed) { exit 1 }
