# Підпис зібраного exe самопідписаним сертифікатом.
#
# Чого це НЕ робить: не прибирає попередження SmartScreen на чужих машинах —
# воно будується на репутації файлу, а не на наявності підпису, і для цього
# потрібен комерційний сертифікат. Тут мета скромніша: прибрати «Невідомий
# видавець» на цій машині й дати файлу перевірювану цілісність.

$ErrorActionPreference = 'Stop'

$exe = (Resolve-Path (Join-Path $PSScriptRoot '..\dist\media-library\media-library.exe')).Path
$subject = 'CN=media-library (local build)'

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $subject } |
        Select-Object -First 1

if (-not $cert) {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
    Write-Output ('Створено сертифікат: ' + $cert.Thumbprint)
} else {
    Write-Output ('Сертифікат уже є: ' + $cert.Thumbprint)
}

# Довіра на рівні користувача — прав адміністратора не потребує.
$root = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
$root.Open('ReadWrite')
if (-not ($root.Certificates | Where-Object { $_.Thumbprint -eq $cert.Thumbprint })) {
    $root.Add($cert)
    Write-Output 'Додано в довірені кореневі (CurrentUser)'
} else {
    Write-Output 'Уже в довірених кореневих'
}
$root.Close()

$result = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
Write-Output ('Підписано: ' + $result.Status)

$check = Get-AuthenticodeSignature $exe
Write-Output ('Перевірка: ' + $check.Status)
Write-Output ('Видавець:  ' + $check.SignerCertificate.Subject)
