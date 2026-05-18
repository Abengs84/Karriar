# Ladda ner finska IP-intervall för lokal utveckling
$data = Join-Path $PSScriptRoot "..\data"
New-Item -ItemType Directory -Force -Path $data | Out-Null
$base = "https://raw.githubusercontent.com/ipverse/rir-ip/master/country/fi"
Invoke-WebRequest -Uri "$base/ipv4-aggregated.txt" -OutFile (Join-Path $data "fi-ipv4.cidr")
Invoke-WebRequest -Uri "$base/ipv6-aggregated.txt" -OutFile (Join-Path $data "fi-ipv6.cidr")
Write-Host "Sparade fi-ipv4.cidr och fi-ipv6.cidr i backend/data"
