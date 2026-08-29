!macro NSIS_HOOK_PREINSTALL
  ; 兜底：更新/安装前先杀掉可能残留的 python-backend.exe，避免文件被占用导致“无法写入”
  ; 尽量先按当前用户杀，再全局杀（忽略失败）
  nsis_tauri_utils::KillProcessCurrentUser "python-backend.exe"
  Pop $0
  nsis_tauri_utils::KillProcess "python-backend.exe"
  Pop $0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; 兜底：卸载前先杀掉 sidecar，避免卸载删除/覆盖失败
  nsis_tauri_utils::KillProcessCurrentUser "python-backend.exe"
  Pop $0
  nsis_tauri_utils::KillProcess "python-backend.exe"
  Pop $0
!macroend
