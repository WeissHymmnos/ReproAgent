import logging
import subprocess
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

class LlamaServerManager:
    def __init__(self, model_path: str, port: int = 8080, host: str = "127.0.0.1"):
        self.model_path = model_path
        self.port = port
        self.host = host
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if self.process is not None:
            return

        cmd = [
            "llama-server",
            "-m", self.model_path,
            "--port", str(self.port),
            "--host", self.host,
            "--no-mmproj-offload",
            "-ngl", "0"
        ]

        logger.info(f"Starting llama-server: {' '.join(cmd)}")
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        self._wait_for_health()

    def stop(self) -> None:
        if self.process is not None:
            logger.info("Stopping llama-server")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _wait_for_health(self, timeout: int = 30) -> None:
        start_time = time.time()
        url = f"http://{self.host}:{self.port}/health"

        while time.time() - start_time < timeout:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(f"llama-server exited prematurely with code {self.process.returncode}")

            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=1) as response:
                    if response.status == 200:
                        logger.info("llama-server is healthy")
                        return
            except (urllib.error.URLError, ConnectionError) as e:
                logger.debug("Health check failed: %s", e)

            time.sleep(1)

        raise TimeoutError("llama-server failed to become healthy within timeout")
