#Requires -Version 5.1
<#
    Gera gui/Sentinel.ico (multi-resolucao: 16/32/48/256) desenhando a marca
    do Sentinel direto com GDI+ (.NET puro, sem navegador nem ImageMagick).

    A marca e a mesma geometria de gui/sentinel/assets/sentinel-mark.svg (olho
    de radar varrendo, vermelho vigia) sobre o campo grafite do app. Nos
    tamanhos pequenos ela deliberadamente SIMPLIFICA: anel interno tracejado,
    linha de varredura e pestanas somem e os tracos engrossam, porque copiar a
    grade 64x64 1:1 em 16px vira lama. Icone adaptativo por tamanho, nao
    redimensionamento cego.

    Arquivos .ico modernos podem embutir quadros PNG diretamente — e so isso
    que este script faz: desenha cada tamanho e grapa tudo com um ICONDIR
    escrito a mao (mesma abordagem de vector/scripts/make-exe-icon.ps1).
#>

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$Root = Split-Path -Parent $PSScriptRoot
$outIco = Join-Path $Root 'gui\Sentinel.ico'

# Paleta do Sentinel (DESIGN.md): campo #0B0C0E, vigia #B3121B, brasa #E11D29,
# sombra #7E0C12.
$bgColor     = [System.Drawing.ColorTranslator]::FromHtml('#0b0c0e')
$ringColor   = [System.Drawing.ColorTranslator]::FromHtml('#b3121b')
$sweepColor  = [System.Drawing.ColorTranslator]::FromHtml('#e11d29')
$deepColor   = [System.Drawing.ColorTranslator]::FromHtml('#7e0c12')
$glintColor  = [System.Drawing.ColorTranslator]::FromHtml('#f4f5f7')

$sizes = 16, 32, 48, 256
$pngBlobs = @()

function New-RoundedRectPath([int]$size, [int]$radius) {
    $rect = New-Object System.Drawing.Rectangle(0, 0, ($size - 1), ($size - 1))
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $radius * 2
    $path.AddArc($rect.X, $rect.Y, $d, $d, 180, 90)
    $path.AddArc($rect.Right - $d, $rect.Y, $d, $d, 270, 90)
    $path.AddArc($rect.Right - $d, $rect.Bottom - $d, $d, $d, 0, 90)
    $path.AddArc($rect.X, $rect.Bottom - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

foreach ($sizeItem in $sizes) {
    $size = [int]$sizeItem
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

    # fundo: quadrado arredondado na cor do campo do app (legivel na barra de
    # tarefas clara ou escura).
    $radius = [Math]::Max(2, [int]($size * 0.22))
    $path = New-RoundedRectPath $size $radius
    $g.FillPath((New-Object System.Drawing.SolidBrush($bgColor)), $path)

    $scale = $size / 64.0
    $center = $size / 2.0
    $isSmall = $size -le 32
    $boost = if ($isSmall) { 1.6 } else { 1.0 }

    $ringPen = New-Object System.Drawing.Pen($ringColor, [Math]::Max(1, [int](3.0 * $scale * $boost)))
    $sweepPen = New-Object System.Drawing.Pen($sweepColor, [Math]::Max(1, [int](2.5 * $scale * $boost)))
    $sweepPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $sweepPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round

    # anel externo do radar
    $ringRect = New-Object System.Drawing.RectangleF(
        ($center - 25 * $scale), ($center - 25 * $scale), (50 * $scale), (50 * $scale))
    $g.DrawEllipse($ringPen, $ringRect)

    # marcas N/S/L/O
    $tickPen = New-Object System.Drawing.Pen($ringColor, [Math]::Max(1, [int](2.5 * $scale * $boost)))
    $tickPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $tickPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $gapIn = 25 * $scale
    $gapOut = 31.5 * $scale
    $g.DrawLine($tickPen, $center, ($center - $gapOut), $center, ($center - $gapIn))
    $g.DrawLine($tickPen, $center, ($center + $gapIn), $center, ($center + $gapOut))
    $g.DrawLine($tickPen, ($center - $gapOut), $center, ($center - $gapIn), $center)
    $g.DrawLine($tickPen, ($center + $gapIn), $center, ($center + $gapOut), $center)
    $tickPen.Dispose()

    # anel tracejado interno + linha de varredura: so nos tamanhos grandes.
    if (-not $isSmall) {
        $innerPen = New-Object System.Drawing.Pen($deepColor, [Math]::Max(1, [int](2.5 * $scale)))
        $innerPen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
        $innerRect = New-Object System.Drawing.RectangleF(
            ($center - 14 * $scale), ($center - 14 * $scale), (28 * $scale), (28 * $scale))
        $g.DrawEllipse($innerPen, $innerRect)
        $innerPen.Dispose()

        $g.DrawLine($sweepPen, $center, $center, ($center + 18 * $scale), ($center - 15 * $scale))
    }
    else {
        # em 16/32px a varredura vira um cabo curto e legivel
        $g.DrawLine($sweepPen, ($center + 2 * $scale), ($center - 2 * $scale),
            ($center + 15 * $scale), ($center - 13 * $scale))
    }

    #iris + pupila (o "olho" que vigia)
    $pupilRect = New-Object System.Drawing.RectangleF(
        ($center - 5.5 * $scale), ($center - 5.5 * $scale), (11 * $scale), (11 * $scale))
    $g.FillEllipse((New-Object System.Drawing.SolidBrush($ringColor)), $pupilRect)
    if (-not $isSmall) {
        $eyePen = New-Object System.Drawing.Pen($sweepColor, [Math]::Max(1, [int](2.5 * $scale)))
        $eyePen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
        # almond das pestanas (aproximacao cubica do par de quadraticas do SVG)
        $upper = New-Object System.Drawing.Drawing2D.GraphicsPath
        $upper.AddBezier(
            ($center - 15 * $scale), $center,
            ($center - 8 * $scale), ($center - 10.5 * $scale),
            ($center + 8 * $scale), ($center - 10.5 * $scale),
            ($center + 15 * $scale), $center)
        $g.DrawPath($eyePen, $upper)
        $lower = New-Object System.Drawing.Drawing2D.GraphicsPath
        $lower.AddBezier(
            ($center + 15 * $scale), $center,
            ($center + 8 * $scale), ($center + 10.5 * $scale),
            ($center - 8 * $scale), ($center + 10.5 * $scale),
            ($center - 15 * $scale), $center)
        $g.DrawPath($eyePen, $lower)
        $upper.Dispose(); $lower.Dispose(); $eyePen.Dispose()

        # reflexo na pupila
        $glintRect = New-Object System.Drawing.RectangleF(
            ($center + 1.2 * $scale), ($center - 3.4 * $scale), (3.2 * $scale), (3.2 * $scale))
        $g.FillEllipse((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(220, 244, 245, 247))), $glintRect)
    }

    $sweepPen.Dispose()
    $ringPen.Dispose()
    $path.Dispose()
    $g.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngBlobs += , $ms.ToArray()
    $ms.Dispose()
    $bmp.Dispose()
}

# ICONDIR (6 bytes) + um ICONDIRENTRY (16 bytes) por quadro, depois os PNGs.
$headerSize = 6
$entrySize = 16
$offset = $headerSize + ($entrySize * $sizes.Count)

$stream = New-Object System.IO.MemoryStream
$writer = New-Object System.IO.BinaryWriter($stream)

$writer.Write([uint16]0)          # reservado
$writer.Write([uint16]1)          # tipo: 1 = icone
$writer.Write([uint16]$sizes.Count)

for ($i = 0; $i -lt $sizes.Count; $i++) {
    $size = [int]$sizes[$i]
    $blob = $pngBlobs[$i]
    $byteSize = if ($size -eq 256) { 0 } else { $size }   # 256 encoda como 0
    $writer.Write([byte]$byteSize)
    $writer.Write([byte]$byteSize)
    $writer.Write([byte]0)
    $writer.Write([byte]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]32)
    $writer.Write([uint32]$blob.Length)
    $writer.Write([uint32]$offset)
    $offset += $blob.Length
}
foreach ($blob in $pngBlobs) { $writer.Write($blob) }

$writer.Flush()
[System.IO.File]::WriteAllBytes($outIco, $stream.ToArray())
$writer.Dispose()
$stream.Dispose()

Write-Host "Gerado: $outIco ($($sizes -join '/')px)" -ForegroundColor Green
