#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Local, read-only frontend fixture. It never connects to or writes a device."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BOARD_DATA = [("ubi_Config", 0x60e000), ("ubi_fpga", 0x41e000),
              ("ubi_DTB0", 0x5d000), ("ubi_DTB1", 0x5d000)]


class Preview(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/":
            variant = parse_qs(path.query).get("variant", ["4ge"])[0]
            body = (ROOT / "overlay/net/lwip/httpd-page.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", f"variant={variant if variant == '2p5g' else '4ge'}; SameSite=Strict")
        else:
            variant = "2p5g" if "variant=2p5g" in self.headers.get("Cookie", "") else "4ge"
            board_data = [{"kind": "ubi", "target": n, "size": s} for n, s in BOARD_DATA]
            responses = {
                "/api/device": {"model": "Tianyi TYFZA1",
                                "ports": "2.5GE + 3×GE" if variant == "2p5g" else "4×GE",
                                "version": "U-Boot 2026.07 (Sep 30 2026 - 15:00:05 +0000) TYFZA1 1.5",
                                "project_version": "1.5", "build_commit": "b6b04e4",
                                "ram_bytes": 0x20000000,
                                "flash_bytes": 0x10000000, "ubi": True, "rebuild": True,
                                "board_data": board_data},
                "/api/storage": {"targets": [
                    {"kind": "mtd", "name": "nand0", "size": 0x10000000, "whole": True},
                    {"kind": "mtd", "name": "boot", "size": 0x200000, "whole": False},
                    *[{"kind": "ubi", "name": n, "size": s, "whole": False} for n, s in BOARD_DATA]]},
                "/api/task": {"busy": False, "phase": "idle", "state": "idle", "output": "", "id": 1},
            }
            if path.path not in responses:
                self.send_error(404)
                return
            body = json.dumps(responses[path.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.send_error(405, "Read-only frontend fixture")


if __name__ == "__main__":
    print("Read-only UI fixture: http://127.0.0.1:8924/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8924), Preview).serve_forever()
