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
      PS -> JS : { type: 'host-ready' | 'engine-reply'
                         | 'not-implemented' | 'bridge-error',
                   payload: <...> }

      `engine-call` carrega { cmd, args, request_id }; a resposta e um unico
      `engine-reply` { cmd, request_id, ok, result | error } — o `result` e o
      JSON do CLI como TEXTO, nao re-serializado. O `request_id` volta igual
      porque a pagina faz varias chamadas em voo e precisa saber a qual cada
      resposta pertence.
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
    Fase 2: cada comando abaixo e UMA chamada ao CLI no modo maquina (fase 0),
    e a resposta JSON dele vai adiante sem reinterpretacao. A lista de
    comandos permitidos existe so para o host nunca virar canonicalizador de
    comando arbitrario: quem decide limiar, severidade, lista de protecao e
    recusa e sempre o Python (`src/sentinel/api.py` + os modulos que ele chama).

    O resultado viaja como TEXTO, nao como objeto: re-serializar um
    ConvertFrom-Json pelo ConvertTo-Json do 5.1 e exatamente onde arrays
    viram {"value":[...],"Count":N} e o acento vira escape. Assim o JSON que o
    Python escreveu e o JSON que a pagina recebe, byte por byte.

    Sem Python no PATH nada quebra: o host diz engineAvailable=false na
    primeira mensagem e a pagina continua em mock.js, com a barra de titulo
    dizendo isso.
#>
$AllowedEngineCommands = @(
    'metrics',      # python sentinel.py metrics --json
    'events',       # python sentinel.py events --json      (JSONL -> array)
    'status',       # python sentinel.py status  --json
    'fix-plan',     # python sentinel.py fix <id> --plan --json
    'fix-resolve',  # python sentinel.py fix <id> --resolve <outcome> --key K --json
    'kill',         # python sentinel.py kill <pid> --yes --json
    'daemon'        # python sentinel.py start|stop|pause|resume --json
)

# Quanto esperar por um filho Python. Um `metrics` custa ~0,6 s de medicao e o
# resto e importa do interpretador; 15 s e folgado o bastante para um disco
# ocupado sem deixar a janela pendurada para sempre.
$EngineTimeoutMs = 15000

function Resolve-EnginePython {
    foreach ($c in @(
        @{ Exe = 'py';      Prefix = @('-3') },
        @{ Exe = 'python';  Prefix = @() },
        @{ Exe = 'python3'; Prefix = @() })) {
        if (Get-Command $c.Exe -ErrorAction SilentlyContinue) { return $c }
    }
    return $null
}

<#
    Onde fica o territorio `.sentinel/` que esta instancia vigia. A ordem e a
    do portavel:

      1. SENTINEL_DIR, se voce disse qual e;
      2. a pasta onde o exe/script esta (Sentinel.exe em D:\Ferramentas ->
         D:\Ferramentas\.sentinel: o app e a pasta andam juntos);
      3. %LOCALAPPDATA%\Sentinel\data, se a pasta do exe nao grava (midia
         somente-leitura, Program Files sem permissao): melhor avisar do que
         abrir uma janela que nao consegue escrever nada.
#>
function Resolve-DataRoot {
    param([string]$ExeDir)
    if ($env:SENTINEL_DIR) { return [pscustomobject]@{ Root = $env:SENTINEL_DIR; Why = 'SENTINEL_DIR' } }
    $probe = Join-Path $ExeDir '.sentinel\bridge-probe'
    try {
        New-Item -ItemType Directory -Path (Split-Path -Parent $probe) -Force -ErrorAction Stop | Out-Null
        Set-Content -Path $probe -Value 'x' -Encoding ASCII -ErrorAction Stop
        Remove-Item $probe -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{ Root = $ExeDir; Why = 'pasta do aplicativo' }
    }
    catch {
        $fallback = Join-Path $env:LOCALAPPDATA 'Sentinel\data'
        try { New-Item -ItemType Directory -Path $fallback -Force -ErrorAction Stop | Out-Null } catch { }
        return [pscustomobject]@{ Root = $fallback; Why = 'pasta do aplicativo e somente leitura; usando %LOCALAPPDATA%\Sentinel\data' }
    }
}

$script:DataRoot = Resolve-DataRoot -ExeDir $ExeDir
$script:EnginePython = Resolve-EnginePython
$EngineCli = Join-Path $Root 'sentinel.py'

function Engine-Available {
    return [bool]($script:EnginePython -and (Test-Path $EngineCli))
}

function Invoke-EngineCli {
    <#
        Roda `python sentinel.py --dir <territorio> <args...>` e devolve o
        stdout como texto. Codigo de saida != 0 NAO e falha do bridge: um
        `kill` recusado responde JSON com ok:false, e a verdade daquela
        recusa mora no Python.
    #>
    param([string[]]$Words)

    if (-not (Engine-Available)) {
        if ($script:EnginePython) { throw "nao encontrei o entry-point do motor em $EngineCli" }
        throw 'Python nao esta no PATH (py -3 / python / python3).'
    }

    $py = $script:EnginePython
    $argList = @($py.Prefix) + @($EngineCli, '--dir', $script:DataRoot.Root) + $Words
    $argString = ($argList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '

    # UTF-8 forcado nos dois lados: sem isto, no Windows o filho escreve acento
    # em cp1252 na pipe e a pagina recebe `?` no lugar do portugues.
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')

    $tmp = Join-Path $env:TEMP ('sentinel-bridge-' + [guid]::NewGuid().ToString('N'))
    $outFile = "$tmp.out.txt"
    $errFile = "$tmp.err.txt"
    try {
        $proc = Start-Process -FilePath $py.Exe -ArgumentList $argString `
            -WorkingDirectory $Root -NoNewWindow -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        if (-not $proc.WaitForExit($EngineTimeoutMs)) {
            try { $proc.Kill() } catch { }
            throw "o motor nao respondeu em $([math]::Round($EngineTimeoutMs/1000)) s ($($Words[0]))."
        }
        $text = ''
        if (Test-Path $outFile) {
            # ReadAllText + UTF8 explicito: Get-Content do 5.1 chuta a codificacao
            # pelo BOM, e sem BOM ele le cp1252 e quebra o acento.
            $text = [System.IO.File]::ReadAllText($outFile, [System.Text.Encoding]::UTF8)
        }
        $err = ''
        if (Test-Path $errFile) {
            $err = [System.IO.File]::ReadAllText($errFile, [System.Text.Encoding]::UTF8)
        }
        $text = $text.Trim()
        if (-not $text) {
            if ($err) { throw ($err.Trim() -split "`r?`n" | Select-Object -Last 1) }
            throw "o motor nao respondeu nada ($($Words[0]), codigo $($proc.ExitCode))."
        }
        return $text
    }
    finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# Resposta de maquina em texto cru: `value` ja e JSON valido (veio do Python),
# entao entra como valor, nao como string escapada.
function Send-EngineReply {
    param([string]$Cmd, $RequestId, [string]$ValueJson, [string]$Error)
    $id = if ($null -eq $RequestId) { 'null' } else { ConvertTo-Json -InputObject $RequestId -Compress }
    $msg = if ($Error) {
        '{"type":"engine-reply","payload":{"cmd":' + (ConvertTo-Json -InputObject $Cmd -Compress) +
        ',"request_id":' + $id + ',"ok":false,"error":' + (ConvertTo-Json -InputObject $Error -Compress) + '}}'
    } else {
        '{"type":"engine-reply","payload":{"cmd":' + (ConvertTo-Json -InputObject $Cmd -Compress) +
        ',"request_id":' + $id + ',"ok":true,"result":' + $ValueJson + '}}'
    }
    $webView.CoreWebView2.PostWebMessageAsJson($msg)
}

# `events --json` e JSONL (uma linha por evento, do jeito que agentes ja leem):
# vira array aqui, sem tocar no conteudo de cada linha.
$EngineJsonlCommands = @('events')

function Engine-Args {
    <#
        Traduz o pedido da pagina na linha de comando do motor. Nada aqui
        decide regra: so passa parametro. Os valores vem de [string] do JS,
        entao um pid/option que nao seja numero simplesmente nao vira opcao
        (e o argparse do Python reclama antes de qualquer coisa).
    #>
    param([string]$Cmd, $P)

    switch ($Cmd) {
        'metrics' {
            $w = @('metrics', '--json')
            if ($P.history) { $w += @('--history', [string]$P.history) }
            if ($P.limit) { $w += @('--limit', [string]$P.limit) }
            if ($P.log) { $w += @('--log', [string]$P.log) }
            return $w
        }
        'events' { return @('events', '--json') }
        'status' { return @('status', '--json') }
        'fix-plan' {
            if (-not $P.id) { throw 'fix-plan precisa do id da anomalia.' }
            return @('fix', [string]$P.id, '--plan', '--json')
        }
        'fix-resolve' {
            if (-not $P.id) { throw 'fix-resolve precisa do id da anomalia.' }
            $outcome = [string]$P.outcome
            if ($outcome -notin @('fixed', 'not_fixed', 'dismissed')) {
                throw "desfecho nao permitido: $outcome"
            }
            $w = @('fix', [string]$P.id, '--resolve', $outcome, '--json')
            if ($P.option) { $w += @('--option', [string]$P.option) }
            if ($P.key) { $w += @('--key', [string]$P.key) }
            if ($P.source) { $w += @('--source', [string]$P.source) }
            if ($P.note) { $w += @('--note', [string]$P.note) }
            return $w
        }
        'kill' {
            if (-not $P.pid) { throw 'kill precisa de um pid.' }
            $w = @('kill', [string]$P.pid, '--yes', '--json')
            if ($P.tree) { $w += '--tree' }
            return $w
        }
        'daemon' {
            $action = [string]$P.action
            if ($action -notin @('start', 'stop', 'pause', 'resume', 'status')) {
                throw "acao de daemon nao permitida: $action"
            }
            return @($action, '--json')
        }
    }
    throw "comando sem traducao para o CLI: $Cmd"
}

function Handle-Message {
    param($Msg)

    switch ($Msg.type) {
        'ready' {
            # A interface avisou que carregou. engineAvailable diz se ela vai
            # pedir dados ao motor ou continuar no mock.js — e `why` explica o
            # motivo, porque "sem ponte" sem causa nao e diagnostico, e enfeite.
            $ok = Engine-Available
            $why = if ($ok) { '' }
            elseif (-not $script:EnginePython) { 'Python nao encontrado no PATH: a pagina segue com dados de exemplo.' }
            else { "entry-point do motor ausente em $EngineCli." }
            Send-ToJs -Type 'host-ready' -Payload @{
                app             = 'sentinel'
                phase           = $(if ($ok) { 'engine' } else { 'mock' })
                root            = $Root
                data_root       = $script:DataRoot.Root
                data_root_from  = $script:DataRoot.Why
                engineAvailable = $ok
                elevated        = [bool]$script:IsAdmin
                notice          = $why
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
            $reqId = $Msg.payload.request_id
            if ($AllowedEngineCommands -notcontains $cmd) {
                Send-EngineReply -Cmd $cmd -RequestId $reqId -Error "comando nao permitido: $cmd"
                return
            }
            try {
                $json = Invoke-EngineCli -Words (Engine-Args -Cmd $cmd -P $Msg.payload)
                if ($EngineJsonlCommands -contains $cmd) {
                    $json = '[' + ((($json -split "`r?`n") | Where-Object { $_.Trim() }) -join ',') + ']'
                }
                Send-EngineReply -Cmd $cmd -RequestId $reqId -ValueJson $json
            }
            catch {
                Send-EngineReply -Cmd $cmd -RequestId $reqId -Error $_.Exception.Message
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
