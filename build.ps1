#Requires -Version 5.1
<#
    Compila o Sentinel.exe a partir do codigo-fonte, usando o modulo ps2exe.

    O resultado e UM ARQUIVO SO: gui/ e o motor Python (src/ + sentinel.py)
    entram embutidos num payload comprimido (scripts/build-payload.ps1) e sao
    extraidos em %LOCALAPPDATA%\Sentinel\app\<versao> na primeira execucao —
    quem faz isso e o Expand-SentinelPayload, dentro do proprio
    gui/SentinelHost.ps1. Da pra copiar o Sentinel.exe sozinho pra qualquer
    pasta, sem levar nada junto.

    O exe sai em dist/ (isolado das fontes) para provar que roda sem nenhum
    arquivo extra por perto.

    O Python NAO entra no exe: o host procura `py -3`, `python`, `python3` no
    PATH na hora de chamar o motor (mesma politica do Vector). Sem Python a
    janela sobe em modo mock e diz isso na barra de titulo, em vez de morrer.

    Sem elevacao, de proposito: nao ha `-requireAdmin` aqui nem `RunAs` no
    host. O Sentinel age como usuario comum e declara o que nao alcanca.

    Passos daqui:
      1. gera .build/payload.ps1 (assets + motor: zip -> gzip -> base64)
      2. monta .build/Sentinel.ps1 = payload (texto em base64, avaliado em
         runtime) + host
      3. compila esse script unico em dist/Sentinel.exe

    Rodar direto da pasta do projeto continua valendo, sem compilar nada:
    .\gui\SentinelHost.ps1 (janela) e .\gui\sentinel\dev.cmd (preview no browser).
#>

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$OutDir = Join-Path $Root 'dist'
$OutExe = Join-Path $OutDir 'Sentinel.exe'
$BuildDir = Join-Path $Root '.build'

if (-not (Get-PackageProvider -Name NuGet -ListAvailable -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando provedor NuGet (necessario pro PowerShellGet baixar modulos)..." -ForegroundColor Cyan
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Scope CurrentUser -Force | Out-Null
}

if (-not (Get-Module -ListAvailable -Name ps2exe)) {
    Write-Host "Instalando modulo ps2exe..." -ForegroundColor Cyan
    Install-Module -Name ps2exe -Scope CurrentUser -Force -AllowClobber
}
Import-Module ps2exe

$iconFile = Join-Path $Root 'gui\Sentinel.ico'
if (-not (Test-Path $iconFile)) {
    Write-Host "Icone nao encontrado, gerando..." -ForegroundColor Cyan
    & (Join-Path $Root 'scripts\make-exe-icon.ps1')
}

# 1) payload embutido --------------------------------------------------------
Write-Host "`n[1/3] Gerando o payload embutido (gui + motor Python)..." -ForegroundColor Cyan
& (Join-Path $Root 'scripts\build-payload.ps1')

# 2) script unico = payload (dados) + host -----------------------------------
# O payload.ps1 NAO e concatenado como codigo: ele e lido aqui como TEXTO,
# convertido pra base64 (linha unica) e avaliado em runtime via
# [ScriptBlock]::Create, DEPOIS que as funcoes ja existem. Dois motivos:
#   a) o SentinelHost.ps1 abre com um bloco param() que so e valido no topo do
#      script - concatenado atras do payload, vira "O termo 'param' nao e
#      reconhecido" e mata o exe na abertura;
#   b) o payload.ps1 contem a linha terminadora '@ do proprio here-string -
#      embuti-lo dentro de outro here-string quebraria o parse.
Write-Host "[2/3] Montando o script unico do exe..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
$singleScript = Join-Path $BuildDir 'Sentinel.ps1'
$payloadFile = Join-Path $BuildDir 'payload.ps1'
$hostFile = Join-Path $Root 'gui\SentinelHost.ps1'

foreach ($part in @($payloadFile, $hostFile)) {
    if (-not (Test-Path $part)) { throw "Parte do script unico nao encontrada: $part" }
}
# ReadAllText(UTF8) ja descarta o BOM: o texto avaliado em runtime comeca
# limpo, e cada parte entra sem BOM no arquivo final (so ele leva BOM).
$payloadSource = [System.IO.File]::ReadAllText($payloadFile, [System.Text.Encoding]::UTF8)
$payloadB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($payloadSource))
$single = New-Object System.Text.StringBuilder
[void]$single.AppendLine('# Gerado pelo build.ps1 - NAO edite. O payload vai EMBUTIDO abaixo em')
[void]$single.AppendLine('# base64 e e avaliado em runtime, NAO como codigo (ver comentario no build).')
[void]$single.AppendLine('$__SentinelPayloadB64 = ''')
[void]$single.AppendLine($payloadB64)
[void]$single.AppendLine('''')
[void]$single.AppendLine('$__SentinelPayloadSource = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($__SentinelPayloadB64))')
[void]$single.AppendLine('. ([ScriptBlock]::Create($__SentinelPayloadSource))')
[void]$single.AppendLine('Remove-Variable -Name __SentinelPayloadB64, __SentinelPayloadSource -Scope Script -ErrorAction SilentlyContinue')

# Do host entra tudo, menos o param() do topo (so e valido como primeiro
# comando do script; atras do payload viraria erro de parse). Diferente do
# Vector, nao ha nada pra reinserir no lugar: o Sentinel nao se eleva, entao
# nao tem -SkipElevationCheck nem checagem de admin que dependa de argumento.
$hostText = [System.IO.File]::ReadAllText($hostFile, [System.Text.Encoding]::UTF8)
$hostBody = $hostText -replace '(?m)^param\(\)\s*\r?$', '# param() removido pelo build.ps1 (ver comentario acima).'
[void]$single.AppendLine($hostBody)
[System.IO.File]::WriteAllText($singleScript, $single.ToString(), (New-Object System.Text.UTF8Encoding($true)))

# 3) compila -----------------------------------------------------------------
# ps2exe escreve o .win32manifest AO LADO do exe de saida: sem a pasta dist/
# criada antes, ele morre com "Nao foi possivel localizar uma parte do caminho".
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Write-Host "[3/3] Compilando com ps2exe (pode demorar um pouco)..." -ForegroundColor Cyan
# ps2exe substitui o exe de saida. Apagar um .exe recem-gerado as vezes e
# negado pelo Windows (handle de antivirus/indexer) MESMO sem ninguem usando:
# por isso o delete aqui e via [System.IO.File]::Delete.
if (Test-Path $OutExe) {
    try { [System.IO.File]::Delete((Resolve-Path $OutExe)) }
    catch {
        Write-Warning "Nao deu pra apagar o Sentinel.exe atual ($($_.Exception.Message)). Feche o exe se estiver aberto e rode o build de novo."
    }
}
Invoke-ps2exe `
    -inputFile $singleScript `
    -outputFile $OutExe `
    -iconFile $iconFile `
    -title 'Sentinel' `
    -description 'Sentinel - vigilancia e autocorrecao guiada, 100% local' `
    -company 'Anthero' `
    -product 'Sentinel - satelite do Theroverse' `
    -version '1.0.0.0' `
    -noConsole `
    -x64

if (-not (Test-Path $OutExe)) {
    throw "ps2exe rodou mas $OutExe nao foi criado - veja a saida acima pro erro real."
}

$size = [math]::Round((Get-Item $OutExe).Length / 1MB, 1)
Write-Host "`nGerado: $OutExe ($size MB)" -ForegroundColor Green
Write-Host "Arquivo unico em dist/: pode copiar o .exe sozinho pra qualquer pasta." -ForegroundColor Yellow
Write-Host "Ele extrai o proprio payload (gui + motor) em %LOCALAPPDATA%\Sentinel\app\<versao>." -ForegroundColor Yellow
Write-Host "Precisa de Python no PATH (py -3 / python / python3) pra falar com o motor." -ForegroundColor Yellow
