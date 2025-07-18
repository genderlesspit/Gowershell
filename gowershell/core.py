import json
import subprocess
import time
from contextlib import contextmanager
from typing import Any, Optional, Dict, Union, List

from loguru import logger as log
from singleton_decorator import singleton

from gowershell import exe

DEBUG = True

def extract_json_blobs(content: str, verbose: bool = DEBUG) -> List[Dict[str, Any]]:
    """Extract JSON objects from content string with optional verbose logging"""
    if verbose:
        log.debug(f"Starting synchronous extraction from content of length {len(content)}")

    results = []
    i = 0
    while i < len(content):
        if content[i] == '{':
            if verbose:
                log.debug(f"Found opening brace at position {i}")
            for j in range(len(content) - 1, i, -1):
                if content[j] == '}':
                    try:
                        json_str = content[i:j+1]
                        parsed = json.loads(json_str)
                        results.append(parsed)
                        if verbose:
                            log.debug(f"Successfully parsed JSON blob: {json_str[:50]}...")
                        i = j
                        break
                    except json.JSONDecodeError as e:
                        if verbose:
                            log.debug(f"Failed to parse JSON at {i}:{j+1} - {e}")
                        pass
        i += 1

    if verbose:
        log.debug(f"Extraction complete. Found {len(results)} JSON blobs")
    return results

class Response(dict):
    """Enhanced response object with attribute access and verbose logging support"""
    output: str
    error: str
    duration_ms: str
    debug: str
    json: List[Dict[str, Any]]
    str: str

    def __init__(self, verbose: bool = DEBUG, **kwargs):
        super().__init__()
        self._verbose = verbose

        # Set default values
        self.setdefault('output', None)
        self.setdefault('error', None)
        self.setdefault('duration_ms', None)
        self.setdefault('debug', None)

        # Update with provided kwargs
        for key, value in kwargs.items():
            self[key] = value

        if "output" in self:
            self.json = extract_json_blobs(self["output"], verbose=verbose)
            if verbose:
                log.debug(self.json)

    def __getattr__(self, name):
        """Allow attribute access to dictionary items"""
        if name == "str":
            return self["output"]
        if name in self:
            return self[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        """Allow attribute setting to dictionary items"""
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self[name] = value

    @property
    def success(self) -> bool:
        """Check if command executed successfully"""
        return self.error is None or self.error == ""

    def log_if_verbose(self, message: str, level: str = "INFO"):
        """Log message if verbose mode is enabled"""
        if self._verbose:
            getattr(log, level.lower())(message)


@singleton
class Gowershell:
    """Synchronous Gowershell wrapper with enhanced features"""

    def __init__(self, verbose: bool = DEBUG, executable: str = exe):
        self.verbose = verbose
        self.executable = executable
        self.proc: Optional[subprocess.Popen] = None

        if self.verbose:
            log.success(f"Successfully initialized Gowershell with executable: {executable}")

    def __enter__(self):
        """Context manager entry"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def start(self):
        """Start the Gowershell process"""
        if self.proc is not None:
            if self.verbose:
                log.warning("Gowershell process already running")
            return

        if self.verbose:
            log.info("Starting Gowershell process")

        try:
            self.proc = subprocess.Popen(
                [self.executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )

            if self.verbose:
                log.success("Gowershell process started successfully")

        except Exception as e:
            log.error(f"Failed to start Gowershell process: {e}")
            raise

    def execute(
            self,
            command: str,
            cmd_type: str = "cmd",
            headless: bool = True,
            persist_window: bool = False,
            verbose: Optional[bool] = None,
            timeout: float = 30.0
    ) -> Response:
        """Execute a command synchronously"""

        # Use instance verbose setting if not specified
        if verbose is None:
            verbose = self.verbose

        # Ensure process is started
        if self.proc is None:
            self.start()

        request = {
            "command": command,
            "type": cmd_type,
            "headless": headless,
            "persist_window": persist_window,
            "verbose": verbose
        }

        if verbose:
            window_mode = "headless" if headless else f"headed ({'persistent' if persist_window else 'auto-close'})"
            log.info(f"Executing command: {command} (type: {cmd_type}, mode: {window_mode})")

        try:
            # Send request
            request_json = json.dumps(request) + "\n"
            self.proc.stdin.write(request_json)
            self.proc.stdin.flush()

            # Wait for response with timeout
            start_time = time.time()
            response_line = ""

            while time.time() - start_time < timeout:
                if self.proc.stdout.readable():
                    line = self.proc.stdout.readline()
                    if line:
                        response_line = line.strip()
                        break
                time.sleep(0.01)  # Small delay to prevent busy waiting

            if not response_line:
                raise TimeoutError(f"Command timed out after {timeout} seconds")

            response_data = json.loads(response_line)
            response = Response(verbose=verbose, **response_data)

            if verbose:
                if response.success:
                    log.success(f"Command completed in {response.duration_ms}ms")
                else:
                    log.error(f"Command failed: {response.error}")

                if response.debug:
                    log.debug(f"Debug info: {response.debug}")

            return response

        except TimeoutError:
            error_msg = f"Command timed out: {command}"
            if verbose:
                log.error(error_msg)
            return Response(verbose=verbose, error=error_msg)

        except Exception as e:
            error_msg = f"Failed to execute command: {e}"
            if verbose:
                log.error(error_msg)
            return Response(verbose=verbose, error=error_msg)

    def execute_batch(
            self,
            commands: list[Union[str, Dict[str, Any]]],
            concurrent: bool = False
    ) -> list[Response]:
        """Execute multiple commands sequentially (concurrent flag ignored in sync version)"""

        if concurrent and self.verbose:
            log.warning("Concurrent execution not supported in synchronous version, executing sequentially")

        results = []
        for cmd in commands:
            if isinstance(cmd, str):
                result = self.execute(cmd)
            else:
                result = self.execute(**cmd)
            results.append(result)
        return results

    # Convenience methods for common use cases
    def cmd(self, command: str, headless: bool = True, persist: bool = False) -> Response:
        """Execute a cmd command"""
        return self.execute(command, "cmd", headless, persist)

    def ps(self, command: str, headless: bool = True, persist: bool = False) -> Response:
        """Execute a PowerShell command"""
        return self.execute(command, "powershell", headless, persist)

    def wsl(self, command: str, headless: bool = True, persist: bool = False) -> Response:
        """Execute a WSL command"""
        return self.execute(command, "wsl", headless, persist)

    # Window control convenience methods
    def show_cmd(self, command: str, persist: bool = True) -> Response:
        """Execute cmd command in visible window"""
        return self.cmd(command, headless=False, persist=persist)

    def show_ps(self, command: str, persist: bool = True) -> Response:
        """Execute PowerShell command in visible window"""
        return self.ps(command, headless=False, persist=persist)

    def quick_window(self, command: str, cmd_type: str = "cmd") -> Response:
        """Show command output briefly then close window"""
        return self.execute(command, cmd_type, headless=False, persist_window=False)

    def close(self):
        """Close the Gowershell process"""
        if self.verbose:
            log.info("Closing Gowershell process")

        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()

                # Wait for process to terminate with timeout
                start_time = time.time()
                while self.proc.poll() is None and time.time() - start_time < 5.0:
                    time.sleep(0.1)

                if self.proc.poll() is None:
                    if self.verbose:
                        log.warning("Process didn't terminate gracefully, killing...")
                    self.proc.kill()

            except Exception as e:
                if self.verbose:
                    log.error(f"Error closing process: {e}")
            finally:
                self.proc = None

    def __del__(self):
        """Cleanup on deletion"""
        if self.proc:
            try:
                self.proc.terminate()
            except:
                pass


@contextmanager
def gowershell(verbose: bool = DEBUG, executable: str = exe):
    """Context manager for Gowershell"""
    shell = Gowershell(verbose=verbose, executable=executable)
    try:
        shell.start()
        yield shell
    finally:
        shell.close()