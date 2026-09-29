import webview
import os
import sys
import ctypes
from ctypes import wintypes
import traceback
import datetime
import time  # added for retry delay

# ----------------------------------------------------------------------
# Python API exposed to JavaScript
# ----------------------------------------------------------------------
class Api:
    def log_to_file(self, message: str):
        """
        Append a timestamped message to python_log.txt next to this script.
        Never raises, so logging cannot break the main flow.
        """
        try:
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python_log.txt")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def send_pipe_command(self, command: str) -> str:
        """
        Connect to the named pipe created by the injected DLL and send a command.
        Retries up to 5 times with 1 second delay.
        Returns the reply from the DLL or an error message.
        """
        kernel32 = ctypes.windll.kernel32

        # ---- Set proper prototypes to avoid handle truncation and string issues ----
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,                          # lpFileName
            ctypes.c_uint32,                           # dwDesiredAccess
            ctypes.c_uint32,                           # dwShareMode
            ctypes.c_void_p,                           # lpSecurityAttributes
            ctypes.c_uint32,                           # dwCreationDisposition
            ctypes.c_uint32,                           # dwFlagsAndAttributes
            ctypes.c_void_p                            # hTemplateFile
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p  # HANDLE (64-bit safe)

        kernel32.WriteFile.argtypes = [
            ctypes.c_void_p,                           # hFile
            ctypes.c_void_p,                           # lpBuffer
            ctypes.c_uint32,                           # nNumberOfBytesToWrite
            ctypes.POINTER(ctypes.c_uint32),           # lpNumberOfBytesWritten
            ctypes.c_void_p                            # lpOverlapped
        ]
        kernel32.WriteFile.restype = ctypes.c_int

        kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,                           # hFile
            ctypes.c_void_p,                           # lpBuffer
            ctypes.c_uint32,                           # nNumberOfBytesToRead
            ctypes.POINTER(ctypes.c_uint32),           # lpNumberOfBytesRead
            ctypes.c_void_p                            # lpOverlapped
        ]
        kernel32.ReadFile.restype = ctypes.c_int

        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        # --------------------------------------------------------------------

        pipe_name = r"\\.\pipe\MyInjectedDLLPipe"
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        max_attempts = 5
        handle = None
        err_msg = ""

        # Attempt to connect with retries
        for attempt in range(1, max_attempts + 1):
            self.log_to_file(f"Attempt {attempt}: Connecting to pipe...")
            handle = kernel32.CreateFileW(
                pipe_name,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                0,
                None
            )

            if handle != INVALID_HANDLE_VALUE:
                self.log_to_file(f"Attempt {attempt}: Connected successfully. Handle = {handle}")
                break

            err = kernel32.GetLastError()
            try:
                err_msg = ctypes.FormatError(err)
            except Exception:
                err_msg = f"Error {err}"
            self.log_to_file(f"Attempt {attempt} failed: {err_msg}")

            if attempt < max_attempts:
                time.sleep(1)
        else:
            # Loop completed without break -> all attempts failed
            self.log_to_file("All connection attempts failed.")
            return f"❌ Could not connect to pipe after {max_attempts} attempts. Last error: {err_msg}"

        # We have a valid handle if we get here
        # Send command
        self.log_to_file(f"Writing command '{command}' to pipe...")
        command_bytes = command.encode('utf-16-le')
        send_buffer = ctypes.create_string_buffer(command_bytes)
        bytes_written = wintypes.DWORD(0)

        ok_write = kernel32.WriteFile(
            handle,
            send_buffer,
            len(command_bytes),
            ctypes.byref(bytes_written),
            None
        )

        if not ok_write:
            err = kernel32.GetLastError()
            try:
                err_text = ctypes.FormatError(err)
            except Exception:
                err_text = f"Error {err}"
            self.log_to_file(f"WriteFile failed: {err_text}")
            kernel32.CloseHandle(handle)
            return f"❌ Failed to write to pipe. Error {err}: {err_text}"

        self.log_to_file("Write successful. Waiting for reply...")

        # Read reply
        buffer = ctypes.create_unicode_buffer(1024)
        bytes_read = wintypes.DWORD(0)
        ok_read = kernel32.ReadFile(
            handle,
            buffer,
            1024 * ctypes.sizeof(ctypes.c_wchar),
            ctypes.byref(bytes_read),
            None
        )

        if ok_read:
            self.log_to_file(f"Reply received: {buffer.value}")
            kernel32.CloseHandle(handle)
            return f"✅ Command sent. Reply: {buffer.value}"
        else:
            err = kernel32.GetLastError()
            try:
                err_text = ctypes.FormatError(err)
            except Exception:
                err_text = f"Error {err}"
            self.log_to_file(f"ReadFile failed: {err_text}")
            kernel32.CloseHandle(handle)
            return f"✅ Command sent, but no reply. Error {err}: {err_text}"

    def read_api_log(self) -> str:
        """
        Read the C++ log from the public path.
        The C++ uses std::ofstream with plain ASCII, so we read as UTF-8.
        """
        try:
            log_path = r"C:\Users\Public\API.txt"
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return "API.txt not found."
        except Exception as e:
            return f"Could not read API.txt: {e}"

    def send_command(self, command: str) -> dict:
        """
        Send a command (Run/Start) through the named pipe and return the result.
        """
        self.log_to_file(f"send_command called with: {command}")
        try:
            self.log_to_file(f"Validating command: {command}")
            if command not in ("Run", "Start"):
                self.log_to_file("Invalid command rejected.")
                return {"status": "error", "message": "❌ Invalid command. Use 'Run' or 'Start'."}

            self.log_to_file("Calling send_pipe_command...")
            result = self.send_pipe_command(command)
            self.log_to_file(f"send_pipe_command returned: {result}")

            if "✅" in result:
                self.log_to_file("Command succeeded. Reading C++ log...")
                api_log = self.read_api_log()
                self.log_to_file(f"C++ log read. Length: {len(api_log)} characters.")
                return {
                    "status": "success",
                    "message": result + "\n\n📄 C++ Log:\n" + api_log
                }
            else:
                self.log_to_file(f"Command failed: {result}")
                return {"status": "error", "message": result}
        except Exception as e:
            self.log_to_file(f"Unexpected error: {e}\n{traceback.format_exc()}")
            return {"status": "error", "message": f"❌ Unexpected error: {e}"}


# ----------------------------------------------------------------------
# HTML + CSS + JavaScript (updated with two buttons)
# ----------------------------------------------------------------------
html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pipe Command Dashboard</title>
    <style>
        :root {
            --bg-primary: #0a0a12;
            --bg-secondary: #12121e;
            --bg-card: rgba(255, 255, 255, 0.04);
            --border: rgba(255, 255, 255, 0.08);
            --text-primary: #eaeaea;
            --text-secondary: #a0a0b8;
            --accent: #6c5ce7;
            --accent-hover: #7d6ef0;
            --success: #2ecc71;
            --error: #e74c3c;
            --radius: 16px;
            --transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', 'Inter', system-ui, -apple-system, sans-serif;
            background: radial-gradient(ellipse at 20% 20%, #1a1a2e 0%, var(--bg-primary) 70%);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            overflow: hidden;
        }

        body::before {
            content: '';
            position: fixed;
            top: -20%;
            left: -20%;
            width: 60%;
            height: 60%;
            background: radial-gradient(circle, rgba(108, 92, 231, 0.15) 0%, transparent 70%);
            animation: floatGlow 12s infinite alternate;
            pointer-events: none;
            z-index: 0;
        }

        @keyframes floatGlow {
            0% { transform: translate(0, 0) scale(1); }
            100% { transform: translate(30%, 20%) scale(1.2); }
        }

        .dashboard {
            width: 100%;
            max-width: 640px;
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 2rem;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
            position: relative;
            z-index: 1;
            transition: var(--transition);
        }

        .dashboard:hover {
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.6);
        }

        .header {
            margin-bottom: 2rem;
            text-align: center;
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 600;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #fff 0%, #b0a8f0 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }

        .header p {
            color: var(--text-secondary);
            font-size: 0.95rem;
        }

        .button-group {
            display: flex;
            gap: 12px;
            margin-bottom: 1.5rem;
            justify-content: center;
        }

        .btn {
            padding: 0.9rem 1.8rem;
            border-radius: 12px;
            border: none;
            cursor: pointer;
            font-weight: 600;
            font-size: 1rem;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap;
        }

        .btn-primary {
            background: var(--accent);
            color: white;
        }

        .btn-primary:hover {
            background: var(--accent-hover);
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(108, 92, 231, 0.35);
        }

        .btn-primary:active {
            transform: translateY(0);
            box-shadow: 0 4px 10px rgba(108, 92, 231, 0.3);
        }

        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none !important;
        }

        .output-area {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 12px;
            border: 1px solid var(--border);
            padding: 1rem;
            min-height: 150px;
            max-height: 250px;
            overflow-y: auto;
            font-family: 'Cascadia Code', 'Fira Code', monospace;
            font-size: 0.9rem;
            line-height: 1.5;
            position: relative;
        }

        .output-area .placeholder {
            color: #555;
            font-style: italic;
        }

        .output-area .log {
            margin-bottom: 0.5rem;
            word-wrap: break-word;
        }

        .output-area .log.error {
            color: var(--error);
        }

        .output-area .log.success {
            color: var(--success);
        }

        .output-area .log.info {
            color: var(--text-secondary);
        }

        .copy-btn {
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 6px 12px;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 0.8rem;
            transition: var(--transition);
        }

        .copy-btn:hover {
            background: rgba(255, 255, 255, 0.15);
            color: var(--text-primary);
        }

        .spinner {
            display: inline-block;
            width: 18px;
            height: 18px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .output-area::-webkit-scrollbar {
            width: 6px;
        }
        .output-area::-webkit-scrollbar-track {
            background: transparent;
        }
        .output-area::-webkit-scrollbar-thumb {
            background: rgba(255,255,255,0.2);
            border-radius: 3px;
        }

        @media (max-width: 500px) {
            .dashboard { padding: 1.5rem; }
            .button-group { flex-direction: column; }
            .btn { justify-content: center; }
        }
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>⚡ Pipe Command Dashboard</h1>
            <p>Send commands to the injected DLL via named pipe.</p>
        </div>

        <div class="button-group">
            <button class="btn btn-primary" id="runBtn">▶ Run</button>
            <button class="btn btn-primary" id="startBtn">▶ Start</button>
        </div>

        <div class="output-area" id="outputArea">
            <div class="placeholder">Console output will appear here...</div>
            <button class="copy-btn" id="copyBtn" title="Copy to clipboard">📋 Copy</button>
        </div>
    </div>

    <script>
        const outputArea = document.getElementById('outputArea');
        const runBtn = document.getElementById('runBtn');
        const startBtn = document.getElementById('startBtn');
        const copyBtn = document.getElementById('copyBtn');

        function addLog(message, type = 'info') {
            const logDiv = document.createElement('div');
            logDiv.className = `log ${type}`;
            logDiv.textContent = message;
            const placeholder = outputArea.querySelector('.placeholder');
            if (placeholder) placeholder.remove();
            outputArea.appendChild(logDiv);
            outputArea.scrollTop = outputArea.scrollHeight;
        }

        function clearOutput() {
            outputArea.innerHTML = '<button class="copy-btn" id="copyBtn" title="Copy to clipboard">📋 Copy</button>';
            document.getElementById('copyBtn').addEventListener('click', copyToClipboard);
        }

        async function copyToClipboard() {
            const logs = Array.from(outputArea.querySelectorAll('.log')).map(el => el.textContent).join('\n');
            if (!logs) {
                alert('Nothing to copy yet.');
                return;
            }
            try {
                await navigator.clipboard.writeText(logs);
                copyBtn.textContent = '✅ Copied!';
                setTimeout(() => { copyBtn.textContent = '📋 Copy'; }, 2000);
            } catch (err) {
                const textarea = document.createElement('textarea');
                textarea.value = logs;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                copyBtn.textContent = '✅ Copied!';
                setTimeout(() => { copyBtn.textContent = '📋 Copy'; }, 2000);
            }
        }

        async function sendCommand(command) {
            // Disable both buttons
            runBtn.disabled = true;
            startBtn.disabled = true;

            // Show loading state on the clicked button (optional, we'll just add a spinner in the log)
            addLog(`📡 Sending command "${command}"...`, 'info');

            try {
                const result = await window.pywebview.api.send_command(command);
                if (result.status === 'success') {
                    addLog(result.message, 'success');
                } else {
                    addLog(result.message, 'error');
                }
            } catch (err) {
                addLog(`❌ JavaScript error: ${err.message}`, 'error');
            } finally {
                runBtn.disabled = false;
                startBtn.disabled = false;
            }
        }

        runBtn.addEventListener('click', () => sendCommand('Run'));
        startBtn.addEventListener('click', () => sendCommand('Start'));

        copyBtn.addEventListener('click', copyToClipboard);
    </script>
</body>
</html>
"""

# ----------------------------------------------------------------------
# Create and start the PyWebView window
# ----------------------------------------------------------------------
if __name__ == "__main__":
    api = Api()
    webview.create_window(
        title="Pipe Command Dashboard",
        html=html,
        js_api=api,
        width=800,
        height=600,
        min_size=(600, 400),
        background_color="#0a0a12"
    )
    webview.start(debug=False)