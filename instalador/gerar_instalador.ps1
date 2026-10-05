# Gera o instalador do Zandonadi Radar (ZandonadiRadarSetup.exe):
#   1) PyInstaller empacota o app (main_web.py + web/) numa pasta com o .exe;
#   2) Inno Setup transforma essa pasta no instalador.
# Os arquivos temporários do build ficam em %TEMP%\zandonadi_build — fora da
# pasta do projeto, que é sincronizada pelo Google Drive.
#
# Uso:  .\instalador\gerar_instalador.ps1
# A versão vem de VERSAO_APP em config.py (é a mesma que o app compara com a
# última release do GitHub pra avisar de atualização).

param([string]$PastaBuild = (Join-Path $env:TEMP "zandonadi_build"))

# "Continue" de propósito: PyInstaller e ISCC escrevem progresso no stderr, que o
# PowerShell 5.1 trataria como erro com "Stop". O sucesso é checado em $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot

$linhaVersao = Select-String -Path (Join-Path $raiz "config.py") -Pattern '^VERSAO_APP\s*=\s*"([^"]+)"'
if (-not $linhaVersao) { throw "Nao achei VERSAO_APP em config.py" }
$versao = $linhaVersao.Matches[0].Groups[1].Value
Write-Host "Versao: $versao"

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 nao encontrado." }

Write-Host "1/2  PyInstaller..."
python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $PastaBuild "dist") `
    --workpath (Join-Path $PastaBuild "work") `
    (Join-Path $PSScriptRoot "ZandonadiRadar.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

Write-Host "2/2  Inno Setup..."
& $iscc "/DMyAppVersion=$versao" `
    "/DSourceDistDir=$(Join-Path $PastaBuild 'dist\ZandonadiRadar')" `
    "/DOutputDir=$(Join-Path $PastaBuild 'output')" `
    (Join-Path $PSScriptRoot "ZandonadiRadarSetup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }

Write-Host ""
Write-Host "Pronto: $(Join-Path $PastaBuild 'output\ZandonadiRadarSetup.exe')"
