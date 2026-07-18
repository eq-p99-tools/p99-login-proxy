# WebView2 Evergreen bootstrapper

Embedded in the portable Windows executable so first launch can install WebView2 when
the runtime is missing.

| Field | Value |
|-------|-------|
| File | `MicrosoftEdgeWebview2Setup.exe` |
| Source | [Evergreen Bootstrapper x64](https://go.microsoft.com/fwlink/p/?LinkId=2124703) |
| License | [Microsoft Software License Terms](https://www.microsoft.com/en-us/legal/terms-of-use) |

## Refreshing the vendored copy

```powershell
Invoke-WebRequest `
  -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
  -OutFile "src-tauri/resources/webview2/MicrosoftEdgeWebview2Setup.exe"
```

Release CI downloads this file before building. The binary is listed in `.gitignore` and
is not committed to the repository.

## Runtime behavior

On startup, if `tauri::webview_version()` fails, the app extracts the embedded bootstrapper
to a temporary file and runs:

```text
MicrosoftEdgeWebview2Setup.exe /silent /install
```

First-time installation requires internet access. Windows 10 1809+ is required.
