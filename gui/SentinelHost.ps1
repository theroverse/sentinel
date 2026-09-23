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
      PS -> JS : { type: 'host-ready' | 'host-state' | 'engine-reply'
                         | 'not-implemented' | 'bridge-error',
                   payload: <...> }

      `engine-call` carrega { cmd, args, request_id }; a resposta e um unico
      `engine-reply` { cmd, request_id, ok, result | error } — o `result` e o
      JSON do CLI como TEXTO, nao re-serializado. O `request_id` volta igual
      porque a pagina faz varias chamadas em voo e precisa saber a qual cada
      resposta pertence.

      `window-close` NAO encerra o app: esconde a janela para a bandeja e a
      vigia continua (e o que se espera de um residente). `host-state`
      { shown } acompanha cada ida e volta, porque enquanto a janela esta
      escondida a pagina nao tem porque pagar um Python a cada 5 s.

    A UI thread nunca espera o filho Python: o pedido entra numa fila e um
    runspace de trabalho roda o processo; a resposta volta por outra fila, que
    um timer do WinForms drena. Ver "engine worker" abaixo — foi assim que o
    travamento de 1-2 s ao clicar sumiu.
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

# ------------------------------------------------------------------- bandeja --
<#
    Fechar a janela nao fecha o Sentinel: a janela esconde e a vigia continua
    no icone da bandeja. Sair de verdade e o "Sair do Sentinel" do menu do
    icone. Nada aqui e um processo a mais — bandeja e janela sao o mesmo
    processo, ao contrario do SentinelTray.ps1 independente, que saiu do
    escopo (spec do residente, secao 13.1).

    O daemon ja vivia sozinho (processo Python propio, desligado da janela); o
    que faltava era o caminho de volta, e e isso que a bandeja entrega.

    Duas redes de seguranca, ambas aprendidas no Genesis:
      1. NotifyIcon.Visible pode falhar SEM lancar nada (.NET Framework lanca
         Win32Exception, mas o caminho de falha silenciosa ja foi visto aqui);
      2. janela escondida sem icone e janela perdida — some da barra de
         tarefas e nao ha para onde clicar.
    Por isso Hide-ToTray so esconde depois de o icone responder que esta la;
    se nao responder, fechar volta a significar fechar.
#>
$script:Exiting = $false
$script:Shown = $true
$script:TrayHintShown = $false

$script:trayIcon = New-Object System.Windows.Forms.NotifyIcon
# Instancia PROPRIA de Icon, nao $form.Icon: compartilhar o mesmo handle GDI+
# entre a janela e o NotifyIcon e causa conhecida de Shell_NotifyIcon falhar
# calado — nenhuma excecao, o icone so nunca aparece.
$script:trayIconIcon = $null
try {
    if (Test-Path $iconPath) { $script:trayIconIcon = New-Object System.Drawing.Icon($iconPath) }
} catch { }
if (-not $script:trayIconIcon) { $script:trayIconIcon = [System.Drawing.SystemIcons]::Application }
$script:trayIcon.Icon = $script:trayIconIcon
$script:trayIcon.Text = 'Sentinel - vigiando'
$script:trayIcon.Visible = $false

function Show-FromTray {
    $script:Shown = $true
    $script:trayIcon.Visible = $false
    $form.Show()
    if ($form.WindowState -eq 'Minimized') { $form.WindowState = 'Normal' }
    $form.Activate()
    Tell-Window-Shown
}

$trayMenu = New-Object System.Windows.Forms.ContextMenuStrip
$trayMenuOpen = New-Object System.Windows.Forms.ToolStripMenuItem('Abrir console')
$trayMenuOpen.Add_Click({ Show-FromTray })
$trayMenuQuit = New-Object System.Windows.Forms.ToolStripMenuItem('Sair do Sentinel')
$trayMenuQuit.Add_Click({ Stop-Sentinel })
[void]$trayMenu.Items.Add($trayMenuOpen)
[void]$trayMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))
[void]$trayMenu.Items.Add($trayMenuQuit)
$script:trayIcon.ContextMenuStrip = $trayMenu

# Clique esquerdo e duplo restauram a janela. O direito nem passa por aqui: o
# ContextMenuStrip abre sozinho, entao quem nao tem o habito de duplo-clique
# continua com o menu.
$script:trayIcon.Add_Click({ Show-FromTray })
$script:trayIcon.Add_DoubleClick({ Show-FromTray })

function Tell-Window-Shown {
    # A pagina para de pollar escondida (see startPolling in app.js): janela
    # fechada nao precisa pagar um Python a cada 5 segundos.
    Send-ToJs -Type 'host-state' -Payload @{ shown = [bool]$script:Shown }
}

function Hide-ToTray {
    <#
        Devolve $true quando a janela esta escondida e a bandeja a segura.
        $false e o caso que nao se pode fingir que deu certo: sem icone nao ha
        para onde esconder, e ai fechar e fechar mesmo.
    #>
    if ($script:Shown -eq $false) { return $true }
    try { $script:trayIcon.Visible = $true } catch { }
    if (-not $script:trayIcon.Visible) { return $false }
    $script:Shown = $false
    $form.Hide()
    if (-not $script:TrayHintShown) {
        # Uma vez so, e exatamente na hora em que a pessoa aprende o gesto:
        # 'escondido' nao e 'morto', e a seta ^ do Windows esconde icones.
        $script:TrayHintShown = $true
        try {
            $script:trayIcon.ShowBalloonTip(5000, 'Sentinel continua vigiando',
                'A janela esta escondida na bandeja. Clique no icone para abrir de novo; "Sair do Sentinel" e que encerra esta interface.',
                [System.Windows.Forms.ToolTipIcon]::Info)
        } catch { }
    }
    Tell-Window-Shown
    return $true
}

function Stop-Sentinel {
    # A unica saida real desta janela. O daemon nao vai junto: ele vigia
    # sozinho, e o que faz do Sentinel um residente.
    $script:Exiting = $true
    $form.Close()
}

# Alt+F4 e qualquer $form.Close() passam TODOS por aqui — o X da titlebar
# customizada manda 'window-close', que cai no mesmo Hide-ToTray. Um unico
# ponto de decisao para "fechar quer dizer o que".
$form.Add_FormClosing({
    param($s, $e)
    if ($script:Exiting) { return }
    if (Hide-ToTray) { $e.Cancel = $true } else { $script:Exiting = $true }
})
$form.Add_FormClosed({
    $script:trayIcon.Visible = $false
    $script:trayIcon.Dispose()
})

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
    # Antes de o CoreWebView2 existir nao ha para quem falar: um Alt+F4 na
    # janela de inicializacao passa por aqui (Hide-ToTray) e nao pode virar
    # excecao em cima de um controle que ainda nao tem nucleo.
    if (-not $webView.CoreWebView2) { return }
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

<#
    Um filho Python sem janela de console, nem por um instante.

    `Start-Process -NoNewWindow` nao bastou: este exe e compilado com
    `-noConsole` do ps2exe, entao o pai NAO tem console nenhum para o filho
    herdar, e o Windows aloca um novo a cada chamada — uma janela de terminal
    piscando no ritmo do poll (5 s). O caminho deterministico e o
    ProcessStartInfo com CreateNoWindow, e `WindowStyle Hidden` junto porque o
    `py.exe` da Microsoft lanca o interpretador de verdade como NETO, e o neto
    herda o SHOWWINDOW do avo, nunca o CREATE_NO_WINDOW.

    A fonte desta funcao vive num TEXTO e nao direto no arquivo porque o mesmo
    codigo precisa rodar em dois lugares: na UI thread (a pergunta `py -3` do
    startup) e no runspace de trabalho (o poll de cada 5 s), e um runspace novo
    nao herda funcao nenhuma de quem o criou. Uma definicao, dois destinos:
    copiar o CreateNoWindow para la seria o jeito exato de deixar uma das duas
    copias desatualizada e a janela de terminal voltar.
#>
$EngineSpawnSource = @'
function Invoke-EngineProcess {
    param([string]$Exe, [string]$Arguments, [string]$WorkDir, [int]$TimeoutMs)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkDir
    # Sem UseShellExecute=false o redirect e o CreateNoWindow sao ignorados em
    # silencio, e e exatamente ai que a janela volta a aparecer.
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    # UTF-8 dos dois lados: sem isto, no Windows o filho escreve acento em
    # cp1252 na pipe e a pagina recebe '?' no lugar do portugues.
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    try {
        # Os dois canis leidos em tarefa, nunca um atras do outro: a pipe enche
        # em ~4 KB, e um traceback longo travaria a leitura do stdout para
        # sempre num processo que ja morreu.
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $errTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($TimeoutMs)) {
            try { $proc.Kill() } catch { }
            throw "o motor nao respondeu em $([math]::Round($TimeoutMs/1000)) s."
        }
        [void]$proc.WaitForExit()
        return [pscustomobject]@{
            Text = ([string]$outTask.Result).Trim()
            Err  = ([string]$errTask.Result).Trim()
            Code = $proc.ExitCode
        }
    }
    finally {
        $proc.Dispose()
    }
}
'@
. ([ScriptBlock]::Create($EngineSpawnSource))

function Resolve-EnginePython {
    foreach ($c in @(
        @{ Exe = 'py';      Prefix = @('-3') },
        @{ Exe = 'python';  Prefix = @() },
        @{ Exe = 'python3'; Prefix = @() })) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        # `py -3` e um lancador, nao o interpretador: cada chamada dele cria DOIS
        # processos. Uma pergunta no startup troca o lancador pelo python real, e
        # o poll deixa de passar pelo lancador para sempre.
        if ($c.Prefix.Count) {
            try {
                $probe = Invoke-EngineProcess -Exe $c.Exe `
                    -Arguments '-3 -c "import sys; print(sys.executable)"' `
                    -WorkDir $Root -TimeoutMs $EngineTimeoutMs
                $real = ($probe.Text -split "`r?`n" | Where-Object { $_.Trim() } |
                    Select-Object -Last 1).Trim()
                if ($real -and (Test-Path -LiteralPath $real)) {
                    return @{ Exe = $real; Prefix = @() }
                }
            } catch { }   # sem resposta vale o lancador mesmo: ele funciona
        }
        return $c
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

function Engine-ArgString {
    <#
        A linha de comando do motor: `python sentinel.py --dir <territorio>
        <args...>`, com aspas onde o caminho tem espaco. So texto, nenhum
        processo — por isso fica na UI thread junto da traducao do pedido.
    #>
    param([string[]]$Words)

    $py = $script:EnginePython
    $argList = @($py.Prefix) + @($EngineCli, '--dir', $script:DataRoot.Root) + $Words
    return ($argList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
}

# ------------------------------------------------------------- engine worker --
<#
    Porque existe uma fila: `metrics` leva de 0,6 a 2 s no disco. Rodando na UI
    thread, como rodava, a janela para de responder durante esse tempo — e o
    clique em "fechar" fica pendurado atras do filho que comecou 0,1 s antes.
    E isso que aparecia como "uns segundos travado".

    Agora o pedido entra em $EngineRequests, um runspace roda o processo la
    fora, e a resposta sai por $EngineReplies para a UI thread drenar no passo
    do timer. Nenhuma decisao muda de lado: o que vale continua sendo o JSON
    que o Python escreveu, e o worker nao interpreta nada — so transporta.

    Codigo de saida != 0 NAO e falha da ponte: um `kill` recusado responde JSON
    com ok:false, e a verdade daquela recusa mora no Python.
#>
$EngineRequests = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
$EngineReplies = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
$script:EngineWorker = $null

$EngineWorkerSource = @'
param($Cfg)
. ([ScriptBlock]::Create($Cfg.SpawnSource))

while ($true) {
    $job = $null
    if (-not $Cfg.Requests.TryDequeue([ref]$job)) { Start-Sleep -Milliseconds 30; continue }
    if ($job.Exit) { return }
    try {
        $r = Invoke-EngineProcess -Exe $Cfg.Py -Arguments $job.Args `
            -WorkDir $Cfg.Root -TimeoutMs $Cfg.TimeoutMs
        $Cfg.Replies.Enqueue([pscustomobject]@{
            Id = $job.Id; Cmd = $job.Cmd; Text = $r.Text; Err = $r.Err; Code = $r.Code
        })
    }
    catch {
        $Cfg.Replies.Enqueue([pscustomobject]@{
            Id = $job.Id; Cmd = $job.Cmd; Error = $_.Exception.Message
        })
    }
}
'@

function Start-EngineWorker {
    param([switch]$Force)
    if ($script:EngineWorker) { return }
    if (-not $Force -and -not (Engine-Available)) { return }

    $cfg = @{
        SpawnSource = $EngineSpawnSource
        Requests    = $EngineRequests
        Replies     = $EngineReplies
        Py          = $script:EnginePython.Exe
        Root        = $Root
        TimeoutMs   = $EngineTimeoutMs
    }
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [PowerShell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($EngineWorkerSource).AddArgument($cfg)
    # BeginInvoke e o que POE o worker para andar: sem esta linha o objeto
    # existe, o runspace esta aberto, a fila aceita pedidos e nunca chega
    # resposta nenhuma — e a janela fica muda em perfeito silencio.
    $script:EngineWorker = @{ Runspace = $rs; PS = $ps; Async = $ps.BeginInvoke() }
}

function Stop-EngineWorker {
    if (-not $script:EngineWorker) { return }
    try { [void]$script:EngineRequests.Enqueue(@{ Exit = $true }) } catch { }
    # Pede para parar e NAO espera: o filho em voo pode estar no meio de um
    # `kill` que a pessoa acabou de confirmar, e o processo ja esta morrendo
    # mesmo — a thread do runspace e de fundo e vai junto.
    try { $script:EngineWorker.PS.BeginStop($null, $null) } catch { }
    $script:EngineWorker = $null
}

function Request-Engine {
    param([string]$Cmd, [string[]]$Words, $RequestId)

    if (-not $script:EngineWorker) {
        Send-EngineReply -Cmd $Cmd -RequestId $RequestId `
            -Error 'nao ha motor rodando nesta janela (sem Python no PATH ou entry-point ausente).'
        return
    }
    [void]$script:EngineRequests.Enqueue(@{
        Id   = $RequestId
        Cmd  = $Cmd
        Args = (Engine-ArgString -Words $Words)
    })
}

function Pump-EngineReplies {
    <#
        Drena o que o worker respondeu, na UI thread, e manda para a pagina.
        Roda no tick do timer: uma passada por resposta pendurada, e sai quando
        a fila esvazia — nunca fica segurando a janela.
    #>
    $job = $null
    while ($script:EngineReplies.TryDequeue([ref]$job)) {
        if ($job.Error) {
            Send-EngineReply -Cmd $job.Cmd -RequestId $job.Id -Error $job.Error
            continue
        }
        if (-not $job.Text) {
            $why = if ($job.Err) { ($job.Err -split "`r?`n" | Select-Object -Last 1) }
                   else { "o motor nao respondeu nada ($($job.Cmd), codigo $($job.Code))." }
            Send-EngineReply -Cmd $job.Cmd -RequestId $job.Id -Error $why
            continue
        }
        $text = $job.Text
        if ($EngineJsonlCommands -contains $job.Cmd) {
            # `events --json` e JSONL (uma linha por evento, do jeito que os
            # agentes ja leem): vira array aqui, sem tocar no conteudo.
            $text = '[' + ((($text -split "`r?`n") | Where-Object { $_.Trim() }) -join ',') + ']'
        }
        Send-EngineReply -Cmd $job.Cmd -RequestId $job.Id -ValueJson $text
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
            # Fechar = escondido na bandeja, com a vigia continuando. So vira
            # saida de verdade se o icone nao aparecer (ver Hide-ToTray).
            if (-not (Hide-ToTray)) { Stop-Sentinel }
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
                # A traducao do pedido e imediata (e pura mentoria de
                # parametro); o processo Python vai para a fila e a resposta
                # volta pelo Pump-EngineReplies, no tick do timer.
                Request-Engine -Cmd $cmd -RequestId $reqId `
                    -Words (Engine-Args -Cmd $cmd -P $Msg.payload)
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
        # Stop-Sentinel, nao $form.Close(): sem o aviso de saida o FormClosing
        # ia cancelar o fechamento e esconder na bandeja uma janela que nao tem
        # interface nenhuma — um icone sem console seria para sempre.
        Stop-Sentinel
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
# O worker e o relogio de respostas comecam aqui, e nao no topo do arquivo:
# o runspace precisa de $Root/$EngineCli/$script:EnginePython de pe, e o timer
# so tem onde pingar quando a bomba de mensagens da janela existir.
Start-EngineWorker

# 40 ms: invisivel ao lado dos ~700 ms que um filho Python leva, e nao acorda
# a UI thread mais vezes do que o preciso. Se uma resposta nao chegar (motor
# morto no meio do caminho), o tick nao bloqueia nada — so nao tem o que
# drenar.
$script:EnginePump = New-Object System.Windows.Forms.Timer
$script:EnginePump.Interval = 40
$script:EnginePump.Add_Tick({
    try { Pump-EngineReplies }
    catch {
        # Chegar aqui e quase sempre "a janela ja fechou e nao tem para quem
        # responder". Parar o relogio e o unico final honesto.
        $script:EnginePump.Stop()
    }
})
$script:EnginePump.Start()
$form.Add_FormClosed({
    $script:EnginePump.Stop()
    Stop-EngineWorker
})

$webView.Source = [Uri]::new($indexPath)

[void]$form.ShowDialog()
