$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8077/api/migrations"
$headers = @{ "X-Account-Email" = "smoke-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())@apitransfer.local" }

Write-Host "== diagnose =="
$proj = @{
    appName        = "leaky"
    files          = @("package.json", "server.js")
    packageJson    = @{ dependencies = @{ express = "^4" } }
    environment    = @{ API_KEY = "sk_live_SUPERSECRETVALUE123"; DEBUG = "true" }
    secrets        = @()
    targetProvider = "fly"
    requestedBy    = "tester"
} | ConvertTo-Json -Depth 6
$d = Invoke-RestMethod -Uri "$base/diagnose" -Method Post -Headers $headers -Body $proj -ContentType "application/json"
$d.report.summary | ConvertTo-Json -Compress
$leak = ($d | ConvertTo-Json -Depth 10) -match "SUPERSECRETVALUE"
Write-Host "Diagnose leak (expect False): $leak"

Write-Host "== diagnose/fix =="
$fix = Invoke-RestMethod -Uri "$base/diagnose/fix" -Method Post -Headers $headers -Body (@{ project = ($proj | ConvertFrom-Json) } | ConvertTo-Json -Depth 8) -ContentType "application/json"
Write-Host ("applied=" + $fix.result.applied.Count + " residualHealth=" + $fix.result.residualReport.summary.healthScore)

Write-Host "== discover =="
$disc = Invoke-RestMethod -Uri "$base/discover" -Method Post -Headers $headers -Body (@{ provider = "fly"; appIdentifier = "demo-app" } | ConvertTo-Json) -ContentType "application/json"
Write-Host ("spec.appName=" + $disc.spec.appName)

# Inject a real secret + start command so the plan seals it and apply hydrates it.
$spec = $disc.spec
$spec.services[0].startCommand = "node server.js"
$spec.services[0].secrets = @(@{ key = "DATABASE_URL"; value = "postgres://u:PLAINTEXT_SECRET_VALUE@host/db" })

Write-Host "== plan =="
$plan = Invoke-RestMethod -Uri "$base/plan" -Method Post -Headers $headers -Body (@{ spec = $spec } | ConvertTo-Json -Depth 12) -ContentType "application/json"
Write-Host ("plan.summary=" + $plan.plan.summary + " risk=" + $plan.plan.riskScore)
$planLeak = ($plan | ConvertTo-Json -Depth 12) -match "PLAINTEXT_SECRET_VALUE"
Write-Host "Plan plaintext-secret leak (expect False): $planLeak"

Write-Host "== apply =="
$apply = Invoke-RestMethod -Uri "$base/apply" -Method Post -Headers $headers -Body (@{ spec = $spec; plan = $plan.plan; approvedBy = "tester-admin" } | ConvertTo-Json -Depth 12) -ContentType "application/json"
Write-Host ("apply.succeeded=" + $apply.succeeded + " hydrated=" + $apply.vaultHydrationCount)
$applyLeak = ($apply | ConvertTo-Json -Depth 12) -match "PLAINTEXT_SECRET_VALUE"
Write-Host "Apply plaintext-secret leak (expect False): $applyLeak"

Write-Host "== terraform/plan =="
$tf = Invoke-RestMethod -Uri "$base/terraform/plan" -Method Post -Headers $headers -Body (@{ spec = $spec; currentState = @() } | ConvertTo-Json -Depth 12) -ContentType "application/json"
Write-Host ("tf.summary=" + $tf.plan.summary)

Write-Host "== deploy =="
$dep = Invoke-RestMethod -Uri "$base/deploy" -Method Post -Headers $headers -Body (@{ appName = "demo"; targetProvider = "fly"; files = @("package.json", "next.config.js"); packageJson = @{ dependencies = @{ next = "^14" } }; requestedBy = "tester"; enableStripe = $true; enableMonitoring = $true } | ConvertTo-Json -Depth 6) -ContentType "application/json"
Write-Host ("framework=" + $dep.result.framework.framework + " succeeded=" + $dep.result.succeeded + " url=" + $dep.result.liveUrl)
$deployLeak = ($dep | ConvertTo-Json -Depth 12) -match "whsec_simulated"
Write-Host "Deploy plaintext-secret leak (expect False): $deployLeak"

Write-Host "== audit =="
$a = Invoke-RestMethod -Uri "$base/audit" -Method Get -Headers $headers
Write-Host ("entries=" + $a.entries.Count + " valid=" + $a.valid)

Write-Host "== index page =="
$page = Invoke-WebRequest -Uri "http://127.0.0.1:8077/" -UseBasicParsing
Write-Host ("index status=" + $page.StatusCode + " hasStatic=" + ($page.Content -match "/static/app.js"))
