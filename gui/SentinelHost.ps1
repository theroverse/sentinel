#Requires -Version 5.1
<#
    Casca nativa da interface do Sentinel: uma janela sem moldura do WinForms
    hospedando um WebView2 apontado em gui/sentinel/index.html. Todo o visual
    mora em gui/sentinel/ (HTML/CSS/JS); este arquivo so cuida da janela, do
    alcance e da ponte JS <-> PowerShell.

    FASE 1 (hoje): a interface renderiza dados de exemplo
    (gui/sentinel/mock.js) para aprovar visual e fluxo antes de tocar no
    sistema. Os comandos do motor abaixo sao stubs documentados que respondem
    'not-implemented'.

    FASE 2 (spec docs/superpowers/specs/2026-09-22-sentinel-gui-design.md):
    cada handler vira uma chamada ao CLI no modo maquina (fase 0), ex.:
      python sentinel.py metrics --json
      python sentinel.py events  --json
      python sentinel.py status  --json
      python sentinel.py fix <id> --plan --json
      python sentinel.py kill <pid> --yes --json
    Regras de seguranca (limiar, severidade, lista de protecao, sessao
    nao-interativa) moram no Python e NUNCA sao reimplementadas aqui.

    Protocolo de mensagens (JSON, um objeto por mensagem):
      JS -> PS : { type: 'ready' | 'window-close' | 'window-minimize'
                         | 'window-drag' | 'engine-call',
                   payload: <o que o handler precisa> }
      PS -> JS : { type: 'host-ready' | 'metrics' | 'events-list'
                         | 'daemon-state' | 'tutor-options' | 'kill-result'
                         | 'not-implemented' | 'bridge-error',
                   payload: <...> }
#>

param()

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ------------------------------------------------------------------ payload --
<#
    Sentinel.exe compilado e um arquivo UNICO: gui/ entra embutido em base64
    (ver scripts/build-payload.ps1) e e extraido em
    %LOCALAPPDATA%\Sentinel\app\<versao> na primeira execucao. Rodando direto
    da pasta do projeto (dev, sem compilar) nao ha payload e $Root e a propria
    pasta do projeto. Mesma mecanica do vector/gui/VectorHost.ps1.
#>
function Expand-SentinelPayload {
    param(
        [Parameter(Mandatory)][string]$ExeDir,
        [string]$PayloadBase64 = $Global:SentinelPayloadBase64,
        [string]$PayloadVersion = $Global:SentinelPayloadVersion
    )

    if (-not $PayloadBase64) { return $ExeDir }
    if (-not $PayloadVersion) { $PayloadVersion = 'dev' }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $cacheRoot = Join-Path $env:LOCALAPPDATA 'Sentinel\app'
    $target = Join-Path $cacheRoot $PayloadVersion

    # gui/sentinel/app.js como sentinela: se nao esta la, a extracao nao
    # terminou (ou a pasta foi limpa) e o payload precisa ser descompactado.
    if (-not (Test-Path (Join-Path $target 'gui\sentinel\app.js'))) {
        New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null

        $gzipBytes = [Convert]::FromBase64String($PayloadBase64)
        $input = New-Object System.IO.MemoryStream
        $input.Write($gzipBytes, 0, $gzipBytes.Length)
        $input.Position = 0
        $gzip = New-Object System.IO.Compression.GZipStream($input, [System.IO.Compression.CompressionMode]::Decompress)
        $zipStream = New-Object System.IO.MemoryStream
        $gzip.CopyTo($zipStream)
        $gzip.Dispose()
        $input.Dispose()

        # extrai numa pasta temporaria e so depois promove: nada de cache pela
        # metade se algo falhar no meio.
        $staging = "$target.tmp"
        if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
        New-Item -ItemType Directory -Path $staging -Force | Out-Null

        $tmpZip = Join-Path $cacheRoot 'payload.zip'
        [System.IO.File]::WriteAllBytes($tmpZip, $zipStream.ToArray())
        $zipStream.Dispose()
        try {
            [System.IO.Compression.ZipFile]::ExtractToDirectory($tmpZip, $staging)
        }
        finally {
            Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        }

        Get-ChildItem $cacheRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne $PayloadVersion -and $_.Name -notlike '*.tmp' } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $target) { Remove-Item $target -Recurse -Force -ErrorAction SilentlyContinue }
        Move-Item -Path $staging -Destination $target -Force
    }

    return $target
}

# --------------------------------------------------------------------- boot --
# Dois modos: script (.ps1, dev na pasta do projeto) e exe (ps2exe, com
# payload embutido).
$script:IsScript = [bool]$PSCommandPath
$exeFullPath = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$exeBaseName = [System.IO.Path]::GetFileNameWithoutExtension($exeFullPath)

if ($PSCommandPath -and $exeBaseName -match '^(powershell|pwsh)$') {
    $ExeDir = Split-Path -Parent $PSCommandPath
    $Root = $ExeDir
}
else {
    $ExeDir = Split-Path -Parent $exeFullPath
    $Root = Expand-SentinelPayload -ExeDir $ExeDir
}

$indexPath = Join-Path $Root 'gui\sentinel\index.html'
$iconPath = Join-Path $Root 'gui\Sentinel.ico'

# Elevacao: nao existe. O Sentinel roda inteiro como usuario comum — sem
# prompt, sem `-Verb RunAs`, sem "reiniciar como administrador" (secao 5 do
# spec do residente, decisao de 2026-09-22). A deteccao continua aqui porque
# ela alimenta a declaracao de alcance: o que a escada nao alcanca sem admin
# e dito como limite, nao como convite. Dos ~338 processos da maquina, 143
# sao inalcanaveis sem admin, e a medicao mostra o preco quase nulo disso:
# 86 sao svchost e o resto e interno do kernel ou helper de servico — todos
# na lista protegida, que a escada ja recusa tocar. O gap real e app alheio
# rodado como administrador, e a resposta a ele e a frase acima.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$script:IsAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# --- drag nativo + cantos arredondados (Windows 11) --------------------------
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeDrag {
    [DllImport("user32.dll")] public static extern bool ReleaseCapture();
    [DllImport("user32.dll")] public static extern int SendMessage(IntPtr hWnd, int Msg, int wParam, int lParam);
    [DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    public const int WM_NCLBUTTONDOWN = 0xA1;
    public const int HTCAPTION = 0x2;
    public const int DWMWA_WINDOW_CORNER_PREFERENCE = 33;
    public const int DWMWCP_ROUND = 2;
    // Assinatura com IntPtr (nao Forms.Form): Add-Type sem
    // -ReferencedAssemblies nao compila tipos de System.Windows.Forms e o
    // bloco inteiro falharia, matando tambem o drag da titlebar.
    public static void RoundCorners(IntPtr hwnd) {
        try {
            int pref = DWMWCP_ROUND;
            DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ref pref, 4);
        }
        catch { }
    }
}
'@

# --- assemblies do WebView2 (SDK NuGet em gui/webview2/) -------------------
# O PowerShell nao resolve sozinho: sem estes Add-Type, o New-Object do
# controle morre com "Nao e possivel localizar o tipo
# [Microsoft.Web.WebView2.WinForms.WebView2]". WebView2Loader.dll (nativo) e
# achado via PATH.
$wv2Dir = Join-Path $Root 'gui\webview2'
Add-Type -Path (Join-Path $wv2Dir 'Microsoft.Web.WebView2.Core.dll')
Add-Type -Path (Join-Path $wv2Dir 'Microsoft.Web.WebView2.WinForms.dll')
$env:PATH = "$wv2Dir;$env:PATH"

# ------------------------------------------------------------------ window --
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Sentinel'
$form.Size = New-Object System.Drawing.Size(1240, 800)
$form.MinimumSize = New-Object System.Drawing.Size(900, 620)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'None'
$form.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#0b0c0e')
if (Test-Path $iconPath) {
    try { $form.Icon = New-Object System.Drawing.Icon($iconPath) } catch { }
}

# Rede de seguranca: payload corrompido ou runtime do WebView2 ausente
# matavam o processo sem aviso. "break" sai daqui com estado inteiro no log.
trap {
    $crashMsg = "Sentinel falhou ao iniciar:`n`n$($_.Exception.Message)`n`n$($_.ScriptStackTrace)"
    try {
        $logDir = Join-Path $env:LOCALAPPDATA 'Sentinel\logs'
        New-Item -ItemType Directory -Path $logDir -Force -ErrorAction SilentlyContinue | Out-Null
        $crashMsg | Out-File (Join-Path $logDir "crash-startup-$(Get-Date -Format 'yyyyMMdd-HHmmss').log") -Encoding utf8
    }
    catch { }
    [System.Windows.Forms.MessageBox]::Show($crashMsg, 'Sentinel', 'OK', 'Error')
    break
}

if (-not (Test-Path $indexPath)) {
    [System.Windows.Forms.MessageBox]::Show(
        "Nao encontrei a interface em:`n$indexPath`n`nRode da pasta do projeto (gui\SentinelHost.ps1) ou recompile com build.ps1.",
        'Sentinel', 'OK', 'Error')
    exit 1
}

$webView = New-Object Microsoft.Web.WebView2.WinForms.WebView2
$webView.Dock = 'Fill'
$webView.DefaultBackgroundColor = [System.Drawing.ColorTranslator]::FromHtml('#0b0c0e')

# Sem isto, o init preguicoso do WebView2 cria "<nome do exe>.WebView2"
# (cache, cookies) DO LADO do exe na primeira execucao — sujeira na pasta de
# instalacao. Definir CreationProperties antes da primeira navegacao manda
# esses dados para %LOCALAPPDATA%, como qualquer outro app.
$creationProps = New-Object Microsoft.Web.WebView2.WinForms.CoreWebView2CreationProperties
$creationProps.UserDataFolder = Join-Path $env:LOCALAPPDATA 'Sentinel\WebView2'
$webView.CreationProperties = $creationProps

$form.Controls.Add($webView)
$form.Add_Shown({ [NativeDrag]::RoundCorners($form.Handle) })

# ------------------------------------------------------------------ bridge --
# Cast para [array]: o ConvertTo-Json do Windows PowerShell 5.1 transforma um
# array puro em {"value":[...],"Count":N} quando ele chega como propriedade
# aninhada — o wrapper abaixo e exatamente o lugar onde isso aconteceria.
function Send-ToJs {
    param([string]$Type, $Payload)
    if (($Payload -is [array] -or $Payload -is [System.Collections.ICollection]) -and
        $Payload -isnot [System.Collections.IDictionary]) {
        $Payload = [array]$Payload
    }
    $msg = @{ type = $Type; payload = $Payload } | ConvertTo-Json -Depth 8 -Compress
    $webView.CoreWebView2.PostWebMessageAsJson($msg)
}

# ------------------------------------------------------------------ engine --
<#
    Fase 2: cada comando abaixo vira uma chamada ao CLI no modo maquina, com
    a saida JSON repassada sem reinterpretacao. A lista de comandos permitidos
    existe so para o host nunca virar canonicalizador de comando arbitrario.
#>
$AllowedEngineCommands = @(
    'metrics',      # python sentinel.py metrics --json
    'events',       # python sentinel.py events --json
    'status',       # python sentinel.py status  --json
    'fix-plan',     # python sentinel.py fix <id> --plan --json
    'fix-resolve',  # python sentinel.py fix <id> --resolve --option N --outcome ... --json
    'kill',         # python sentinel.py kill <pid> --yes --json
    'daemon'        # python sentinel.py start|stop  (recusa em sessao nao-interativa)
)

function Invoke-EngineCli {
    param([string]$Cmd, [hashtable]$Args)
    # Stub honesto da fase 1: nem tentamos fingir que executamos. A GUI segue
    # em modo mock e mostra 'not-implemented' como demonstração.
    throw "A ponte com o motor chega na fase 2 (spec docs/superpowers/specs/2026-09-22-sentinel-gui-design.md); comando '$Cmd' ainda nao ligado."
}

function Handle-Message {
    param($Msg)

    switch ($Msg.type) {
        'ready' {
            # A interface avisou que carregou. Fase 1: engineAvailable=false faz
            # a GUI ficar em mock.js e dizer isso na barra de titulo.
            Send-ToJs -Type 'host-ready' -Payload @{
                app             = 'sentinel'
                phase           = 'mock'
                root            = $Root
                engineAvailable = $false
                elevated        = [bool]$script:IsAdmin
                notice          = 'Dados de exemplo: a ponte com o CLI e a fase 2 da spec.'
            }
        }
        'window-close' {
            $form.Close()
        }
        'window-minimize' { $form.WindowState = 'Minimized' }
        'window-drag' {
            [NativeDrag]::ReleaseCapture() | Out-Null
            [NativeDrag]::SendMessage($form.Handle, [NativeDrag]::WM_NCLBUTTONDOWN, [NativeDrag]::HTCAPTION, 0) | Out-Null
        }
        'engine-call' {
            $cmd = [string]$Msg.payload.cmd
            if ($AllowedEngineCommands -notcontains $cmd) {
                Send-ToJs -Type 'engine-reply' -Payload @{
                    cmd = $cmd; ok = $false; error = "comando nao permitido: $cmd" }
                return
            }
            try {
                $extra = @{}
                if ($Msg.payload) {
                    foreach ($k in @('id', 'pid', 'option', 'outcome', 'action')) {
                        if ($Msg.payload.$k) { $extra[$k] = [string]$Msg.payload.$k }
                    }
                }
                $result = Invoke-EngineCli -Cmd $cmd -Args $extra
                Send-ToJs -Type 'engine-reply' -Payload @{ cmd = $cmd; ok = $true; result = $result }
            }
            catch {
                Send-ToJs -Type 'engine-reply' -Payload @{
                    cmd = $cmd; ok = $false; error = $_.Exception.Message }
            }
        }
        default {
            Send-ToJs -Type 'not-implemented' -Payload @{ type = [string]$Msg.type }
        }
    }
}

# --------------------------------------------------------------------- wire --
$webView.add_CoreWebView2InitializationCompleted({
    param($s, $e)
    if (-not $e.IsSuccess) {
        # 0x800700AA = ERROR_BUSY: a pasta de dados do WebView2
        # (%LOCALAPPDATA%\Sentinel\WebView2) esta travada por OUTRA instancia
        # aberta — nao e falta de runtime, e nao dava para saber isso da
        # mensagem generica de baixo.
        $msg = if ($e.InitializationException.HResult -eq -2147024726) {
            "Ja existe outra instancia do Sentinel aberta (ou travada em segundo plano).`n`nFeche-a (Gerenciador de Tarefas, se preciso) e abra de novo."
        }
        else {
            "WebView2 nao inicializou: $($e.InitializationException.Message)`n`nO Runtime do WebView2 (vem com o Windows 11) pode estar faltando."
        }
        [System.Windows.Forms.MessageBox]::Show($msg, 'Sentinel', 'OK', 'Error')
        $form.Close()
        return
    }
    $webView.CoreWebView2.add_WebMessageReceived({
        # NUNCA nomeie o 2o parametro de $args: o PowerShell ja tem essa
        # variavel automatica, e sombrear aqui faz o objeto real de
        # WebMessageReceivedEventArgs chegar como Object[] (bug aprendido no
        # Genesis e repetido no Vector).
        param($sender, $webMsgArgs)
        try {
            $json = $webMsgArgs.TryGetWebMessageAsString()
            $msg = $json | ConvertFrom-Json
            Handle-Message -Msg $msg
        }
        catch {
            Send-ToJs -Type 'bridge-error' -Payload @{ error = $_.Exception.Message }
        }
    })
})
$webView.Source = [Uri]::new($indexPath)

[void]$form.ShowDialog()
