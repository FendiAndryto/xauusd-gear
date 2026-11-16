Option Explicit
' XAUUSD SMC Assistant - silent stop switch.
' Detaches MT5 gracefully, then terminates only this repo's uvicorn process.
' Never touches other Python processes on the machine.

Const URL_DISCONNECT = "http://127.0.0.1:8000/api/mt5/disconnect"

Dim fso, shell, baseDir, pythonExe, http, svc, procs, proc, stopped
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = baseDir & "\.venv\Scripts\python.exe"

' 1. Let the server detach MT5 first; ignore failures (server may already be gone).
On Error Resume Next
Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
http.setTimeouts 800, 800, 800, 800
http.Open "POST", URL_DISCONNECT, False
http.Send
On Error GoTo 0

' 2. Kill the uvicorn process only if it is this repo's venv python + app module.
stopped = 0
On Error Resume Next
Set svc = GetObject("winmgmts:\\.\root\cimv2")
Set procs = svc.ExecQuery("SELECT ProcessId, ExecutablePath, CommandLine FROM Win32_Process WHERE Name = 'python.exe'")
For Each proc In procs
    If Not IsNull(proc.CommandLine) Then
        If InStr(LCase(proc.CommandLine), "src.assistant.app") > 0 Then
            If Not IsNull(proc.ExecutablePath) Then
                If LCase(proc.ExecutablePath) = LCase(pythonExe) Then
                    proc.Terminate
                    stopped = stopped + 1
                End If
            End If
        End If
    End If
Next
On Error GoTo 0

If stopped > 0 Then
    shell.Popup "Server XAUUSD Assistant dihentikan (" & stopped & " proses).", 4, "XAUUSD Assistant", 64
Else
    shell.Popup "Server XAUUSD Assistant sedang tidak berjalan.", 4, "XAUUSD Assistant", 64
End If
