param([ValidateSet('auth', 'products', 'orders', 'test')][string]$Service = 'orders')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$PythonExe = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Chay python -m venv .venv; sau do chay .\.venv\Scripts\python.exe -m pip install Flask==3.1.3 PyJWT==2.15.1 PyMySQL==1.2.3 requests==2.34.2 python-dotenv==1.2.4'
}
switch ($Service) {
    'auth' { & $PythonExe auth_service/app.py }
    'products' { & $PythonExe product_service/app.py }
    'orders' { & $PythonExe -m order_service.app }
    'test' { & $PythonExe -m unittest discover -s tests -v }
}
exit $LASTEXITCODE
