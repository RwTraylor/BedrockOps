# BedrockOps - Session Prep (Step 0)
#
# What this script does: prepares ONE PowerShell window on Ricket's PC for
# the BedrockOps LIVE-PROOF session, and nothing more. It does NOT run the
# proof, proves nothing live, and never reads, prints, or stores AWS
# credential values (no access keys, no secret keys, no session tokens).
# Your AWS sign-in happens through YOUR browser via `aws configure sso`,
# which this script never drives and never inspects.
#
# NO LIVE CLAIMS: live proof (live: true / persisted: true) happens later,
# at the run, with Soundwave, one command per message. This script only
# makes sure the window is ready.
#
# Requirements: Windows PowerShell 5.1, zero dependencies beyond the
# cmdlets built into Windows plus git, python, and the AWS CLI (each
# checked below, with the exact fix printed if one is missing).
# Idempotent: safe to re-run; it never deletes, overwrites, or forces.
#
# How to run:
#   1. Open Windows PowerShell (Start menu -> Windows PowerShell).
#   2. If Windows refuses to run the file ("running scripts is
#      disabled"), this one line, for this window only:
#         Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   3. cd to the folder holding this file, then run:
#         .\prepare-session.ps1
#   4. Answer the [y/N] prompts. Nothing happens without a yes.
#   5. LEAVE THIS WINDOW OPEN at the end: the env vars live here only.

#Requires -Version 5.1

$ErrorActionPreference = 'Stop'

$RepoUrl   = 'https://github.com/RwTraylor/BedrockOps'
$CloneDir  = Join-Path $HOME 'bedrockops-pc'
$TableName = 'bedrockops-audit-ledger'
$AwsRegion = 'us-east-1'
$ModelId   = 'anthropic.claude-sonnet-5'

function Step($text) { Write-Host ''; Write-Host "== $text ==" -ForegroundColor Cyan }
function Info($text) { Write-Host $text }
function Fail($what, $fix) {
    Write-Host ''
    Write-Host "STOP: $what" -ForegroundColor Red
    Write-Host "REMEDIATION: $fix" -ForegroundColor Yellow
    exit 1
}
function Ask-Yes($question) {
    $answer = Read-Host "$question [y/N]"
    return ($answer -match '^(y|yes)$')
}

# ---------------------------------------------------------------- Step 0
Step '0. Shell check'
if (-not (Get-Variable -Name PSVersionTable -ErrorAction SilentlyContinue)) {
    Fail 'This does not look like PowerShell.' 'Open Windows PowerShell from the Start menu and run: .\prepare-session.ps1'
}
Info ("PowerShell " + $PSVersionTable.PSVersion.ToString() + ' - OK')

# ---------------------------------------------------------------- Step 1
Step '1. Tool check (git, python, AWS CLI)'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'git was not found on PATH.' 'Install Git for Windows from https://git-scm.com/download/win , then close this window, open a fresh PowerShell, and run this script again.'
}
git --version
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail 'python was not found on PATH.' 'Install Python 3.12+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then reopen PowerShell and run this script again.'
}
python --version
if ($LASTEXITCODE -ne 0) {
    Fail 'python exists on PATH but did not run.' 'Reinstall Python 3.12+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), reopen PowerShell, and run this script again.'
}
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Fail 'AWS CLI was not found on PATH.' 'Install AWS CLI v2 from https://aws.amazon.com/cli/ , reopen PowerShell, and run this script again.'
}
aws --version

# ---------------------------------------------------------------- Step 2
Step '2. Local clone of the repo'
if (Test-Path (Join-Path $CloneDir '.git')) {
    Info "Existing clone found at $CloneDir - updating (fast-forward only, never forced)."
    git -C $CloneDir pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Fail 'git pull failed (local changes or diverged history).' 'Do NOT force anything and do NOT delete the folder. Stop and show Soundwave the git error text above (it contains no secrets).'
    }
}
elseif (Test-Path $CloneDir) {
    Fail "$CloneDir exists but is not a git clone." 'Rename or move that folder yourself in Explorer, then run this script again. This script never deletes folders.'
}
else {
    if (Ask-Yes "Clone $RepoUrl into $CloneDir now?") {
        git clone $RepoUrl $CloneDir
        if ($LASTEXITCODE -ne 0) {
            Fail 'git clone failed.' 'Check the network connection (and sign in to GitHub if it asks), then run this script again.'
        }
    }
    else {
        Fail 'Clone declined, so there is nothing to prepare.' 'Re-run this script when ready, or cd into your own clone and follow prepare-session.md by hand.'
    }
}

# ---------------------------------------------------------------- Step 3
Step '3. AWS identity - the script never touches credential values'
Info 'Expectation: after YOUR sign-in, this command succeeds and prints'
Info 'Account, UserId, and Arn for your account. It never prints keys:'
Info '    aws sts get-caller-identity'
Info ''
aws sts get-caller-identity 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Info 'Not signed in yet, or the session expired. This part is yours:'
    Info '    aws configure sso'
    Info 'It opens YOUR browser for YOUR AWS sign-in. Credentials go to AWS'
    Info 'only - never into this chat, this script, or any file it writes.'
    Read-Host 'Press Enter AFTER aws configure sso finishes in your browser'
    aws sts get-caller-identity
    if ($LASTEXITCODE -ne 0) {
        Fail 'aws sts get-caller-identity still fails.' 'Finish the browser SSO sign-in first. If unsure which profile is active, run: aws configure list - then run this script again.'
    }
}
else {
    aws sts get-caller-identity
}
Info 'Identity check: OK.'

# ---------------------------------------------------------------- Step 4
Step '4. Bedrock model access (console - your clicks, your words)'
Info "Open: https://console.aws.amazon.com/bedrock/  and set the region picker to US East (N. Virginia) - us-east-1."
Info "Left nav: Model access. Find: $ModelId"
Info 'Its status must read: Access granted.'
Info 'If it says Request access, submit it - Anthropic asks for a one-time'
Info 'use-case form. That form is yours: your name, your use case, your click.'
Read-Host "Press Enter when Model access shows Access granted for $ModelId"

# ---------------------------------------------------------------- Step 5
Step "5. Audit table $TableName (SessionId String HASH, Timestamp Number RANGE, on-demand)"
$describeOut = aws dynamodb describe-table --table-name $TableName --region $AwsRegion 2>&1
if ($LASTEXITCODE -eq 0) {
    Info "Table $TableName already exists - nothing to create."
}
elseif ("$describeOut" -match 'ResourceNotFoundException') {
    if (-not (Ask-Yes "Table $TableName does not exist yet. Create it now?")) {
        Fail 'Table creation declined by you.' 'Create it later using prepare-session.md (console or CLI path), then run this script again before the live run.'
    }
    if (Get-Command terraform -ErrorAction SilentlyContinue) {
        Info 'terraform found - Terraform path (creates the table AND the least-privilege IAM policy: PutItem + Query on this one table only).'
        $tfDir = Join-Path $CloneDir 'terraform'
        Push-Location $tfDir
        terraform init
        $tfInit = $LASTEXITCODE
        terraform plan
        $tfPlan = $LASTEXITCODE
        Pop-Location
        if ($tfInit -ne 0 -or $tfPlan -ne 0) {
            Fail 'terraform init/plan failed.' 'Show Soundwave the terraform error text. Do NOT paste terraform.tfstate anywhere - it is not needed and it is not a chat artifact.'
        }
        Info 'Read the plan output above before answering. It should create ONLY: one DynamoDB table + one IAM policy.'
        if (-not (Ask-Yes 'Apply the plan you just reviewed?')) {
            Fail 'Apply declined by you - nothing was applied.' 'Re-run this script when ready; terraform will plan again before any apply.'
        }
        Push-Location $tfDir
        terraform apply
        $tfApply = $LASTEXITCODE
        Pop-Location
        if ($tfApply -ne 0) {
            Fail 'terraform apply failed.' 'Show Soundwave the terraform error text (not terraform.tfstate).'
        }
        Info 'Terraform apply finished.'
    }
    else {
        Info 'terraform not found - AWS CLI path (same table, same key schema, on-demand billing).'
        Info 'Note: this path creates the table only. The Terraform IAM policy stays unapplied until a terraform run - that is expected and is stated honestly in the repo.'
        aws dynamodb create-table --table-name $TableName --attribute-definitions AttributeName=SessionId,AttributeType=S AttributeName=Timestamp,AttributeType=N --key-schema AttributeName=SessionId,KeyType=HASH AttributeName=Timestamp,KeyType=RANGE --billing-mode PAY_PER_REQUEST --region $AwsRegion
        if ($LASTEXITCODE -ne 0) {
            Fail 'aws dynamodb create-table failed.' 'Show Soundwave the error text above (it contains no secrets). The table can also be created in the DynamoDB console - see prepare-session.md.'
        }
        aws dynamodb wait table-exists --table-name $TableName --region $AwsRegion
        if ($LASTEXITCODE -ne 0) {
            Fail 'The table did not reach ACTIVE in time.' 'Open the DynamoDB console (region us-east-1), check the table status, then run this script again.'
        }
        Info "Table $TableName is ACTIVE."
    }
}
else {
    Fail "describe-table failed for a reason other than 'table missing': $describeOut" 'If it mentions credentials, redo step 3 (aws configure sso). Otherwise show Soundwave this error text (it contains no secrets).'
}

# ---------------------------------------------------------------- Step 6
Step '6. Python environment (inside the clone)'
$venvReady = $false
if (Ask-Yes 'Create/refresh the Python venv and install requirements.txt now? (idempotent)') {
    Push-Location $CloneDir
    python -m venv .venv
    $venvExit = $LASTEXITCODE
    if ($venvExit -eq 0) {
        & (Join-Path $CloneDir '.venv\Scripts\python.exe') -m pip install -r requirements.txt
        $pipExit = $LASTEXITCODE
    }
    else {
        $pipExit = 1
    }
    Pop-Location
    if ($venvExit -ne 0 -or $pipExit -ne 0) {
        Fail 'venv creation or pip install failed.' 'Show Soundwave the error text above (no secrets in it), or skip this step and install requirements in the session window by hand per prepare-session.md.'
    }
    $venvReady = $true
    Info 'venv ready at .venv inside the clone.'
}
else {
    Info 'Skipped. Install requirements before the run (see prepare-session.md).'
}

# ---------------------------------------------------------------- Step 7
Step '7. Session environment - THIS WINDOW ONLY'
$env:BEDROCKOPS_LIVE  = '1'
$env:AUDIT_TABLE_NAME = $TableName
$env:AWS_REGION       = $AwsRegion
$env:BEDROCK_MODEL_ID = $ModelId
Info "BEDROCKOPS_LIVE  = $($env:BEDROCKOPS_LIVE)"
Info "AUDIT_TABLE_NAME = $($env:AUDIT_TABLE_NAME)"
Info "AWS_REGION       = $($env:AWS_REGION)"
Info "BEDROCK_MODEL_ID = $($env:BEDROCK_MODEL_ID)"
Info ''
Info 'These four variables live only in THIS PowerShell window.'
Info 'Close the window and they are gone - just re-run this script.'

Step 'DONE - window prepared. NO live proof has happened yet.'
Info 'Next, with Soundwave, one command per message, in THIS window:'
if ($venvReady) {
    Info '    .\.venv\Scripts\Activate.ps1'
}
Info '    python -m unittest discover -s tests -v'
Info '    python server.py'
Info '    then open http://127.0.0.1:8000/console'
Info ''
Info 'live: true and persisted: true are earned at that run, not before.'
Info 'Screenshots: see prepare-session.md - and eyeball every frame for keys first.'
