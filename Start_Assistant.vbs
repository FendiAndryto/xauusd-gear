Option Explicit
' XAUUSD SMC Assistant - zero-CLI silent launcher (ticket T-10)
' Double-click only: installs missing deps once, starts the server hidden,
' waits until it answers, then opens the default browser. No CMD window.

Const URL_APP = "http://localhost:8000"
Const URL_HEALTH = "http://127.0.0.1:8000/api/health"
Const STARTUP_TIMEOUT_SEC = 90

Dim fso, shell, baseDir, pythonExe, logDir, logFile, cmd, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = baseDir & "\.venv\Scripts\python.exe"
logDir = baseDir & "\logs"
logFile = logDir & "\assistant.log"

If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)

If Not fso.FileExists(pythonExe) Then
    MsgBox "Environment Python tidak ditemukan:" & vbCrLf & pythonExe & vbCrLf & vbCrLf & _
           "Sekali saja, jalankan di folder proyek: uv sync --python 3.12", _
           vbCritical, "XAUUSD Assistant"
    WScript.Quit 1
End If

' Sudah berjalan? Cukup buka browser (idempotent, double-click aman).
If ServerReady() Then
    shell.Run URL_APP, 1, False
    WScript.Quit 0
End If

' Dependensi web dipasang hening, sekali saja.
If Not DependenciesInstalled() Then
    cmd = "cmd /c cd /d """ & baseDir & """ && uv pip install --python """ & pythonExe & _
          """ ""fastapi>=0.110.0"" ""uvicorn[standard]>=0.29.0"" >> """ & logFile & """ 2>&1"
    shell.Run cmd, 0, True
End If
If Not DependenciesInstalled() Then
    cmd = "cmd /c cd /d """ & baseDir & """ && """ & pythonExe & _
          """ -m ensurepip --upgrade >> """ & logFile & """ 2>&1"
    shell.Run cmd, 0, True
    cmd = "cmd /c cd /d """ & baseDir & """ && """ & pythonExe & _
          """ -m pip install --disable-pip-version-check ""fastapi>=0.110.0"" " & _
          """uvicorn[standard]>=0.29.0"" >> """ & logFile & """ 2>&1"
    shell.Run cmd, 0, True
End If
If Not DependenciesInstalled() Then
    MsgBox "Gagal memasang FastAPI/Uvicorn." & vbCrLf & vbCrLf & _
           "Detail log: " & logFile, vbCritical, "XAUUSD Assistant"
    WScript.Quit 1
End If

' Server dijalankan tanpa jendela; output ke logs\assistant.log.
cmd = "cmd /c cd /d """ & baseDir & """ && """ & pythonExe & _
      """ -m uvicorn src.assistant.app:app --host 127.0.0.1 --port 8000 >> """ & logFile & """ 2>&1"
shell.Run cmd, 0, False

For i = 1 To STARTUP_TIMEOUT_SEC
    WScript.Sleep 1000
    If ServerReady() Then
        shell.Run URL_APP, 1, False
        WScript.Quit 0
    End If
Next

MsgBox "Server belum siap setelah " & STARTUP_TIMEOUT_SEC & " detik." & vbCrLf & vbCrLf & _
       "Kemungkinan port 8000 dipakai aplikasi lain." & vbCrLf & _
       "Log: " & logFile & vbCrLf & vbCrLf & LogTail(), _
       vbCritical, "XAUUSD Assistant"
WScript.Quit 1

' ---------------------------------------------------------------- helpers

Function ServerReady()
    Dim http
    ServerReady = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number <> 0 Then Exit Function
    http.setTimeouts 400, 400, 400, 400
    http.Open "GET", URL_HEALTH, False
    http.Send
    If Err.Number = 0 Then
        If http.Status = 200 Then ServerReady = True
    End If
    On Error GoTo 0
End Function

' Filesystem check: uv-created venvs on Windows have no pip, so never shell out here.
Function DependenciesInstalled()
    Dim sitePackages
    sitePackages = baseDir & "\.venv\Lib\site-packages\"
    DependenciesInstalled = fso.FolderExists(sitePackages & "fastapi") And _
                            fso.FolderExists(sitePackages & "uvicorn")
End Function

Function LogTail()
    Dim stream, text
    LogTail = "(log kosong)"
    On Error Resume Next
    If fso.FileExists(logFile) Then
        Set stream = fso.OpenTextFile(logFile, 1)
        text = stream.ReadAll
        stream.Close
        If Len(text) > 1500 Then text = "..." & Right(text, 1500)
        If Len(Trim(text)) > 0 Then LogTail = text
    End If
    On Error GoTo 0
End Function
