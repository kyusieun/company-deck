param([string]$pptx, [string]$pdf)
$ErrorActionPreference = "Stop"
$wasRunning = [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)
$pp = New-Object -ComObject PowerPoint.Application
try {
  $pres = $pp.Presentations.Open($pptx, $true, $false, $false)
  $pres.SaveAs($pdf, 32)
  $pres.Close()
  Write-Output "rendered (powerpoint was running before: $wasRunning)"
} finally {
  if (-not $wasRunning) { $pp.Quit() }
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
