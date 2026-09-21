"""Client for the released AutoHDR YOLOv7 detector executable."""

from __future__ import annotations

import pickle
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


class DetectorModelClient:
    """Run the released detector process and exchange tensors over localhost."""

    def __init__(self, executable_path: str | Path, port: int = 12345, max_retries: int = 5):
        self.executable_path = Path(executable_path)
        self.port = port
        self.max_retries = max_retries
        self.process: subprocess.Popen[bytes] | None = None
        self.sock: socket.socket | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        if not self.executable_path.is_file():
            raise FileNotFoundError(f"Detector executable not found: {self.executable_path}")
        self.process = subprocess.Popen([str(self.executable_path), str(self.port)])
        time.sleep(1)
        if self.process.poll() is not None:
            raise RuntimeError(f"Detector process exited with code {self.process.returncode}")
        for _ in range(self.max_retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect(("localhost", self.port))
                self.running = True
                return
            except ConnectionRefusedError:
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                time.sleep(2)
        self.close()
        raise RuntimeError("Could not connect to the detector process")

    def __call__(self, value: Any, mode: int) -> Any:
        if not self.running:
            self.start()
        if self.sock is None:
            raise RuntimeError("Detector socket is unavailable")
        payload = pickle.dumps({"x": value, "mode": mode})
        try:
            self.sock.sendall(len(payload).to_bytes(4, byteorder="big"))
            self.sock.sendall(payload)
            result = self._receive()
        except Exception:
            self.close()
            raise
        if "error" in result:
            raise RuntimeError(f"Detector server error: {result['error']}")
        if mode == 1:
            return result["stride"]
        if mode == 2:
            return result["tensor"]
        raise ValueError(f"Unsupported detector mode: {mode}")

    def _receive(self) -> dict[str, Any]:
        if self.sock is None:
            raise RuntimeError("Detector socket is unavailable")
        size_bytes = self.sock.recv(4)
        if not size_bytes:
            raise RuntimeError("Detector server closed the connection")
        size = int.from_bytes(size_bytes, byteorder="big")
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("Detector server closed the connection")
            chunks.extend(chunk)
        return pickle.loads(chunks)

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        self.running = False

    def __enter__(self) -> "DetectorModelClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
