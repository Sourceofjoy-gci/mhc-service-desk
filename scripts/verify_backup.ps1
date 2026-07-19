# verify_backup.ps1 — Windows-friendly backup round-trip verification
# Uses a real side DB and asserts row counts match. Mirrors verify_backup.sh
# (Linux/macOS operator script).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2])
        }
    }
}

$postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "mhc" }
$postgresDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "mhc" }
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ").ToLower()
$verifyDb = "mhc_verify_$timestamp"
$outDir = Join-Path $PSScriptRoot "..\backups\verify-$timestamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$countTables = @(
    "ticket", "ticket_message", "ticket_note", "ticket_link",
    "workflow_status", "workflow_transition", "workflow_transition_history",
    "sla_instance", "sla_policy",
    "catalogue_service", "catalogue_request_type",
    "contact", "org_office",
    "auditevent", "file_attachment",
    "integrationevent", "whatsapp_message", "knowledge_article"
)

function Get-Counts($db) {
    $rows = @()
    foreach ($t in $countTables) {
        $cmd = "SELECT count(*) FROM $t"
        $count = docker compose exec -T -e PGPASSWORD=$env:POSTGRES_PASSWORD postgres psql -U $postgresUser -d $db -t -A -F'|' -c $cmd 2>&1
        $count = ($count | Out-String).Trim()
        if ($count -match '^\d+$') {
            $rows += "$t|$count"
        } else {
            $rows += "$t|0"
        }
    }
    return $rows
}

Write-Host "[verify] collecting live row counts"
$liveCounts = Get-Counts $postgresDb
$liveCounts | Out-File (Join-Path $outDir "live_counts.txt") -Encoding utf8

Write-Host "[verify] creating fresh backup"
$dumpName = "db_$timestamp.dump"
$dumpPathInContainer = "/tmp/$dumpName"
docker compose exec -T postgres pg_dump -U $postgresUser -Fc $postgresDb -f $dumpPathInContainer
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

Write-Host "[verify] provisioning side database $verifyDb"
docker compose exec -T postgres psql -U $postgresUser -d postgres -c "DROP DATABASE IF EXISTS $verifyDb" | Out-Null
docker compose exec -T postgres createdb -U $postgresUser $verifyDb
docker compose exec -T postgres pg_restore -U $postgresUser -d $verifyDb --no-owner --no-privileges $dumpPathInContainer
docker compose exec -T postgres psql -U $postgresUser -d $verifyDb -c "ANALYZE" | Out-Null
docker compose exec -T postgres rm -f $dumpPathInContainer

Write-Host "[verify] collecting restored row counts"
$restCounts = Get-Counts $verifyDb
$restCounts | Out-File (Join-Path $outDir "restored_counts.txt") -Encoding utf8

Write-Host "[verify] diffing counts"
$diff = Compare-Object $liveCounts $restCounts
if ($null -eq $diff) {
    Write-Host "[verify] PASS: row counts match"
    $liveCounts | ForEach-Object { Write-Host "  $_" }
    docker compose exec -T postgres psql -U $postgresUser -d postgres -c "DROP DATABASE $verifyDb" | Out-Null
    Write-Host "[verify] evidence in $outDir"
    exit 0
} else {
    Write-Host "[verify] FAIL: row counts differ"
    $diff | Format-Table | Out-Host
    Write-Host "[verify] side DB $verifyDb kept for inspection"
    exit 1
}
