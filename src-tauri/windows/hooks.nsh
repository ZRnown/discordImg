!macro NSIS_HOOK_PREINSTALL
  ; Stop any running backend sidecar before copying backend-api.exe.
  nsExec::ExecToLog 'taskkill /IM backend-api.exe /F /T'
  Sleep 1000
  Delete "$INSTDIR\backend-api.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; The uninstall path can also fail if the backend is still running.
  nsExec::ExecToLog 'taskkill /IM backend-api.exe /F /T'
  Sleep 1000
!macroend
