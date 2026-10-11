$config = Join-Path $PSScriptRoot '.gx10-ssh-config'

if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    [Console]::Error.WriteLine('Missing .gx10-ssh-config. See the Windows GX10 shortcut section in docs/DEVELOPMENT.md.')
    exit 1
}

& ssh -F $config hachi-gx10 @args
exit $LASTEXITCODE
