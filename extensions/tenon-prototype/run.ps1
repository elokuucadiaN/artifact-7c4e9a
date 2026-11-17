param(
    [string]$Output = "E:\learn\benchmark\output\tenon-prototype-run",
    [int]$Runs = 3,
    [int]$Rounds = 100,
    [int]$LegacyIterations = 50
)
$ErrorActionPreference = "Stop"
function Convert-ToWslPath([string]$Path) {
    $AbsolutePath = [IO.Path]::GetFullPath($Path)
    if ($AbsolutePath -notmatch '^([A-Za-z]):[\\/](.*)$') {
        throw "Expected a Windows drive path: $AbsolutePath"
    }
    return '/mnt/' + $Matches[1].ToLowerInvariant() + '/' + $Matches[2].Replace('\', '/')
}
$LinuxScript = '/home/zyc/eunobench/src/artifact-7c4e9a/extensions/tenon-prototype/prototype.py'
$LinuxOutput = Convert-ToWslPath $Output
$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$NativeOutput = '/home/zyc/eunobench/runs/' + $RunId
# Direct argv passing avoids interpolating user paths into a shell command.
Write-Output "Running entirely inside WSL: $NativeOutput"
& wsl.exe --cd /home/zyc/eunobench -e /home/zyc/eunobench/.venv/bin/python -B $LinuxScript run --output $NativeOutput --runs $Runs --rounds $Rounds --legacy-iterations $LegacyIterations
if ($LASTEXITCODE -ne 0) { throw "Prototype validation failed; inspect the output logs (exit $LASTEXITCODE)." }
& wsl.exe --cd /home/zyc/eunobench -e /home/zyc/eunobench/.venv/bin/python -B $LinuxScript export --input $NativeOutput --output $LinuxOutput
if ($LASTEXITCODE -ne 0) { throw "Completed capture remains at $NativeOutput; Windows export failed (exit $LASTEXITCODE)." }
