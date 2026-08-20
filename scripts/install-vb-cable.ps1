param(
    [switch]$ForceDownload
)

$ErrorActionPreference = "Stop"
$DownloadUrl = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
$ProductPage = "https://vb-audio.com/Cable/"

function Test-VbCableInstalled {
    try {
        $Device = Get-PnpDevice -PresentOnly -ErrorAction Stop |
            Where-Object { $_.FriendlyName -match '^(CABLE Input|CABLE Output).*VB-Audio' } |
            Select-Object -First 1
        return $null -ne $Device
    }
    catch {
        $Names = Get-ChildItem -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio" -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $_.GetValue("{a45c254e-df1c-4efd-8020-67d146a850e0},2") } |
            Where-Object { $_ -match 'CABLE (Input|Output)' }
        return $null -ne $Names
    }
}

if ((Test-VbCableInstalled) -and -not $ForceDownload) {
    Write-Host "VB-CABLE da duoc cai dat tren may." -ForegroundColor Green
    exit 0
}

Write-Host "VB-CABLE la driver am thanh Donationware cua VB-Audio." -ForegroundColor Yellow
Write-Host "Trang san pham va ung ho nha phat trien: $ProductPage"
Write-Host "Bo cai can quyen Administrator va Windows phai khoi dong lai sau khi cai." -ForegroundColor Yellow
Write-Host
$Answer = Read-Host "Tai bo cai chinh thuc va tiep tuc? (Y/N)"
if ($Answer -notmatch '^[Yy]$') {
    Write-Host "Da huy cai dat VB-CABLE."
    exit 0
}

$WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "SpeakBridge-VBCABLE-Pack45"
$ZipPath = Join-Path $WorkRoot "VBCABLE_Driver_Pack45.zip"
$ExtractPath = Join-Path $WorkRoot "driver"
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null

Write-Host "Dang tai VB-CABLE tu download.vb-audio.com..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $ZipPath
}
catch {
    Write-Warning "Khong tai tu dong duoc: $($_.Exception.Message)"
    Write-Host "Dang mo trang tai chinh thuc trong trinh duyet..."
    Start-Process $ProductPage
    throw "Hay tai va cai VB-CABLE tu trang chinh thuc, sau do chay lai muc nay de kiem tra."
}

if (Test-Path -LiteralPath $ExtractPath) {
    Remove-Item -LiteralPath $ExtractPath -Recurse -Force
}
Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractPath -Force

$Candidates = switch ($env:PROCESSOR_ARCHITECTURE) {
    "ARM64" { @("VBCABLE_Setup_arm64.exe", "VBCABLE_Setup_x64.exe") }
    "AMD64" { @("VBCABLE_Setup_x64.exe") }
    default { @("VBCABLE_Setup.exe") }
}

$Installer = $null
foreach ($Name in $Candidates) {
    $Installer = Get-ChildItem -LiteralPath $ExtractPath -Filter $Name -File -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if ($Installer) { break }
}
if (-not $Installer) {
    throw "Khong tim thay bo cai VB-CABLE phu hop trong goi chinh thuc."
}

$Signature = Get-AuthenticodeSignature -LiteralPath $Installer
if ($Signature.Status -ne "Valid") {
    throw "Chu ky so cua bo cai VB-CABLE khong hop le: $($Signature.Status). Khong chay file."
}
$Signer = [string]$Signature.SignerCertificate.Subject
if ($Signer -notmatch 'VB-Audio|BUREL\s+VINCENT|VINCENT\s+BUREL|V\.Burel') {
    throw "Nha phat hanh bo cai khong dung nhu mong doi: $Signer"
}

Write-Host "Dang mo bo cai VB-CABLE voi quyen Administrator..." -ForegroundColor Cyan
$Process = Start-Process -FilePath $Installer -Verb RunAs -Wait -PassThru
if ($Process.ExitCode -ne 0) {
    throw "Bo cai VB-CABLE ket thuc voi ma loi $($Process.ExitCode)."
}

Write-Host
Write-Host "Bo cai da ket thuc. Hay khoi dong lai Windows de hoan tat." -ForegroundColor Green
Write-Host "Sau khi khoi dong lai: SpeakBridge = CABLE Input; Discord/Meet = CABLE Output."
