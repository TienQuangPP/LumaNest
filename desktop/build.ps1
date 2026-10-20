$ErrorActionPreference = 'Stop'
$appRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler is required on Windows.' }
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /utf8output `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    "/win32icon:$appRoot\fsmart\static\lumanest.ico" "/out:$appRoot\LumaNest.exe" "$PSScriptRoot\LumaNest.cs"
if ($LASTEXITCODE -ne 0) { throw 'LumaNest launcher compilation failed.' }
Write-Host "Built $appRoot\LumaNest.exe"
