' wsl-keepalive.vbs -- hold the WSL2 VM open, with no window on the taskbar.
'
' WSL2 stops the VM after about 60 seconds of idle, and only wsl.exe client
' sessions count as activity -- SSH traffic does not (provision/README.md 3-1).
' The scheduled task "WSL-keepalive-Ubuntu-24-04" runs this at logon, and this
' script holds one such session open for as long as it lives.
'
' Running wsl.exe straight from the task opened a visible console window. It
' sat on the taskbar looking like an ordinary terminal, and closing it by
' mistake took the VM down -- and the task is onlogon, so nothing brought it
' back. WScript.Shell.Run with window style 0 keeps the same client session
' without the window.
'
' The exit code is propagated on purpose: the task's restart-on-failure rule
' can then see an abnormal end (wsl --shutdown kills the client with
' STATUS_CONTROL_C_EXIT) and start it again by itself.

Dim sh
Set sh = CreateObject("WScript.Shell")
WScript.Quit sh.Run("C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u root --exec /usr/bin/sleep infinity", 0, True)
