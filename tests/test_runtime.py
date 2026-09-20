"""Kill leftover listeners on a TCP port without touching this process."""
import os
import shutil
import socket
import subprocess
import sys
import time
import unittest

from src.runtime import free_listen_port, pids_on_port


@unittest.skipUnless(shutil.which("lsof"), "lsof is required")
class FreePortTests(unittest.TestCase):
    def test_kills_listener_on_port(self):
        holder = socket.socket()
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        holder.close()

        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import socket,time;"
                    "s=socket.socket();"
                    "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
                    f"s.bind(('127.0.0.1',{port}));"
                    "s.listen(1);"
                    "time.sleep(30)"
                ),
            ]
        )
        try:
            for _ in range(20):
                if proc.pid in pids_on_port(port):
                    break
                time.sleep(0.05)
            self.assertIn(proc.pid, pids_on_port(port))
            free_listen_port(port)
            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(proc.poll())
            self.assertNotIn(proc.pid, pids_on_port(port))
        finally:
            if proc.poll() is None:
                proc.kill()


class FindBundleTests(unittest.TestCase):
    def test_does_not_claim_this_pid(self):
        from src.runtime import find_app_bundle
        bundle = find_app_bundle()
        self.assertTrue(bundle is None or str(bundle).endswith(".app"))
        self.assertNotIn(os.getpid(), pids_on_port(1))


if __name__ == "__main__":
    unittest.main()
