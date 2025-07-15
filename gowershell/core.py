import asyncio
import subprocess
import json
from dataclasses import dataclass
from typing import Any, Optional, Dict, Union
from loguru import logger as log
import threading
import queue
from contextlib import asynccontextmanager

DEBUG = True

try:
    from singleton_decorator import singleton
except ImportError:
    # Fallback singleton implementation
    def singleton(cls):
        instances = {}
        def get_instance(*args, **kwargs):
            if cls not in instances:
                instances[cls] = cls(*args, **kwargs)
            return instances[cls]
        return get_instance

class Response(dict):
    """Enhanced response object with attribute access and verbose logging support"""

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

    def __getattr__(self, name):
        """Allow attribute access to dictionary items"""
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
    """Async-capable Gowershell wrapper with enhanced features"""

    def __init__(self, verbose: bool = DEBUG, executable: str = "./gowershell.exe"):
        self.verbose = verbose
        self.executable = executable
        self.proc: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._response_queue = queue.Queue()
        self._reader_thread = None
        self._is_running = False

        if self.verbose:
            log.info(f"Initializing Gowershell with executable: {executable}")

    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def start(self):
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

            # Start reader thread
            self._is_running = True
            self._reader_thread = threading.Thread(target=self._read_responses, daemon=True)
            self._reader_thread.start()

            if self.verbose:
                log.success("Gowershell process started successfully")

        except Exception as e:
            log.error(f"Failed to start Gowershell process: {e}")
            raise

    def _read_responses(self):
        """Background thread to read responses from the process"""
        while self._is_running and self.proc:
            try:
                line = self.proc.stdout.readline()
                if line:
                    self._response_queue.put(line.strip())
                elif self.proc.poll() is not None:
                    break
            except Exception as e:
                if self.verbose:
                    log.error(f"Error reading response: {e}")
                break

    async def execute(
        self,
        command: str,
        cmd_type: str = "cmd",
        headless: bool = True,
        verbose: Optional[bool] = None
    ) -> Response:
        """Execute a command asynchronously"""

        # Use instance verbose setting if not specified
        if verbose is None:
            verbose = self.verbose

        # Ensure process is started
        if self.proc is None:
            await self.start()

        async with self._lock:
            request = {
                "command": command,
                "type": cmd_type,
                "headless": headless,
                "verbose": verbose
            }

            if verbose:
                log.info(f"Executing command: {command} (type: {cmd_type}, headless: {headless})")

            try:
                # Send request
                request_json = json.dumps(request) + "\n"
                self.proc.stdin.write(request_json)
                self.proc.stdin.flush()

                # Wait for response with timeout
                response_line = await asyncio.wait_for(
                    self._get_response(),
                    timeout=30.0
                )

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

            except asyncio.TimeoutError:
                error_msg = f"Command timed out: {command}"
                if verbose:
                    log.error(error_msg)
                return Response(verbose=verbose, error=error_msg)

            except Exception as e:
                error_msg = f"Failed to execute command: {e}"
                if verbose:
                    log.error(error_msg)
                return Response(verbose=verbose, error=error_msg)

    async def _get_response(self) -> str:
        """Get response from queue asynchronously"""
        while True:
            try:
                return self._response_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting

    async def execute_batch(
        self,
        commands: list[Union[str, Dict[str, Any]]],
        concurrent: bool = False
    ) -> list[Response]:
        """Execute multiple commands, optionally concurrently"""

        if concurrent:
            tasks = []
            for cmd in commands:
                if isinstance(cmd, str):
                    task = self.execute(cmd)
                else:
                    task = self.execute(**cmd)
                tasks.append(task)

            return await asyncio.gather(*tasks)
        else:
            results = []
            for cmd in commands:
                if isinstance(cmd, str):
                    result = await self.execute(cmd)
                else:
                    result = await self.execute(**cmd)
                results.append(result)
            return results

    async def close(self):
        """Close the Gowershell process"""
        if self.verbose:
            log.info("Closing Gowershell process")

        self._is_running = False

        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.terminate()

                # Wait for process to terminate
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process()),
                    timeout=5.0
                )

            except asyncio.TimeoutError:
                if self.verbose:
                    log.warning("Process didn't terminate gracefully, killing...")
                self.proc.kill()
            except Exception as e:
                if self.verbose:
                    log.error(f"Error closing process: {e}")
            finally:
                self.proc = None

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

    async def _wait_for_process(self):
        """Wait for process to terminate"""
        while self.proc and self.proc.poll() is None:
            await asyncio.sleep(0.1)

    def __del__(self):
        """Cleanup on deletion"""
        if self.proc:
            try:
                self.proc.terminate()
            except:
                pass

@asynccontextmanager
async def gowershell(verbose: bool = DEBUG, executable: str = "./gowershell.exe"):
    """Async context manager for Gowershell"""
    shell = Gowershell(verbose=verbose, executable=executable)
    try:
        await shell.start()
        yield shell
    finally:
        await shell.close()

# Usage examples
async def main():
    """Example usage of the enhanced Gowershell"""

    # Method 1: Direct usage
    shell = Gowershell(verbose=True)

    try:
        # Single command
        result = await shell.execute("echo Hello, World!", "cmd", headless=False)
        print(f"Output: {result.output}")

        # Command with visible window
        result = await shell.execute("az login", "cmd", headless=False)

        # PowerShell command
        result = await shell.execute("Get-Process", "powershell", verbose=True)

        # Batch execution
        commands = [
            "dir",
            {"command": "echo Batch command", "cmd_type": "cmd", "headless": True},
            "powershell -Command Get-Date"
        ]
        results = await shell.execute_batch(commands, concurrent=True)

    finally:
        await shell.close()

    # Method 2: Using context manager
    async with gowershell(verbose=True) as shell:
        result = await shell.execute("echo Context manager!", "cmd")
        print(f"Result: {result.output}")

if __name__ == "__main__":
    asyncio.run(main())