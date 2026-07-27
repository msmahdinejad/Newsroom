$ErrorActionPreference = "Stop"

python "$PSScriptRoot/bootstrap.py" @args
exit $LASTEXITCODE
