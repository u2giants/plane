# ClickUp Webhook Creator
# Run: .\scripts\create_webhook.ps1

$CLICKUP_TOKEN = $env:CLICKUP_TOKEN
$WORKSPACE_ID = "2298436"
$ENDPOINT = "https://plane-integrations.u2giants.workers.dev/clickup/webhook"

$EVENTS = @(
    "taskCreated", "taskUpdated", "taskDeleted", "taskMoved",
    "taskCommentPosted", "taskCommentUpdated", "taskAssigneeUpdated",
    "taskStatusUpdated", "taskTimeEstimateUpdated", "taskTimeTrackedUpdated",
    "taskPriorityUpdated", "taskDueDateUpdated", "taskTagUpdated",
    "taskAttachmentUpdated", "taskChecklistItemCompleted",
    "taskChecklistItemDeleted", "taskLinkedTasksUpdated",
    "listCreated", "listUpdated", "listDeleted",
    "folderCreated", "folderUpdated", "folderDeleted",
    "spaceCreated", "spaceUpdated", "spaceDeleted"
)

$BODY = @{
    endpoint = $ENDPOINT
    events = $EVENTS
} | ConvertTo-Json -Compress

$HEADERS = @{
    "Authorization" = $CLICKUP_TOKEN
    "Content-Type" = "application/json"
}

$URL = "https://api.clickup.com/api/v2/team/$WORKSPACE_ID/webhook"

Write-Host "Creating ClickUp webhook..."
Write-Host "Endpoint: $ENDPOINT"
Write-Host ""

try {
    $RESPONSE = Invoke-RestMethod -Uri $URL -Method POST -Headers $HEADERS -Body $BODY
    Write-Host "✅ Webhook created successfully!" -ForegroundColor Green
    Write-Host "Webhook ID: $($RESPONSE.id)"
    Write-Host "Secret: $($RESPONSE.secret)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "IMPORTANT: Save this secret! You need it for CLICKUP_WEBHOOK_SECRET"
    Write-Host "Run: gh secret set CLICKUP_WEBHOOK_SECRET --repo u2giants/plane --body `"$($RESPONSE.secret)`""
} catch {
    Write-Host "❌ Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Response: $($_.ErrorDetails.Message)"
}
