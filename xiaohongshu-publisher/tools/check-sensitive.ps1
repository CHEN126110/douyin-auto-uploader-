# 小红书千帆：提交前敏感信息自检（可执行守卫）
#
# 存在理由（2026-10-10 两次踩坑 ✗）：
#   ① 曾把守卫写成"打印一句警告然后继续" → 实际照样提交了，属伪守卫 ✗；
#   ② 曾用 '省.*市.*区' 这类宽松模式 → 把文档里那行模式文本自身也匹配了，假阳性 ✗。
# 因此本脚本：模式用数字/中文级别，且**命中即 exit 1 真正中断** ✓。
#
# 用法（提交前跑，任一文件命中就中止）：
#   powershell -File xiaohongshu-publisher/tools/check-sensitive.ps1 -Paths xiaohongshu-publisher/docs/xx.md
#   powershell -File xiaohongshu-publisher/tools/check-sensitive.ps1 -Paths (git diff --cached --name-only)

param(
  [Parameter(Mandatory = $true)][string[]]$Paths,
  # 手机号（11 位、1 开头）；省市县三级中文地址片段；身份证号
  [string]$Pattern = '1[3-9]\d{9}|省[\u4e00-\u9fa5]{2,}市|[\u4e00-\u9fa5]{2,}(区|县)[\u4e00-\u9fa5]{2,}(街道|路|镇)|\d{17}[\dXx]'
)

$found = @()
foreach ($p in $Paths) {
  if (-not (Test-Path $p)) { continue }
  $item = Get-Item $p
  if ($item.PSIsContainer) { continue }
  $hits = Select-String -Path $p -Pattern $Pattern -Encoding utf8
  foreach ($h in $hits) { $found += ("{0}:{1}" -f $p, $h.LineNumber) }
}

if ($found.Count -gt 0) {
  Write-Host '发现疑似个人信息，已中止 ✗（这些值不应入库，请改成脱敏写法或只记字段结构）'
  $found | ForEach-Object { Write-Host ("  命中 {0}" -f $_) }
  exit 1
}
Write-Host ("未发现个人信息 ✓（已检查 {0} 个路径）" -f $Paths.Count)
exit 0
