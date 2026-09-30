#!/usr/bin/env python3
"""chunked_get_probe.py [host:port] [path]: why upstream Locust adds ~40 ms.

geventhttpclient 2.4 sends a GET's headers and an empty chunked body in two
writes. Go's HTTP server reads that body before it writes its reply, so the
second write, held by Nagle until the first is ACKed, waits for the server's
delayed ACK. Prints the round trip of 8 such GETs on one connection: sent in
one write, split with Nagle, and split with TCP_NODELAY.
"""
import socket
import sys
import time

ADDR = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:18080"
PATH = sys.argv[2] if len(sys.argv) > 2 else "/product/OLJCESPC7Z"
HOST, PORT = ADDR.rsplit(":", 1)


def run(split, nodelay):
    s = socket.create_connection((HOST, int(PORT)))
    if nodelay:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    head = f"GET {PATH} HTTP/1.1\r\nHost: {ADDR}\r\nTransfer-Encoding: chunked\r\n\r\n".encode()
    times = []
    for _ in range(8):
        t = time.perf_counter()
        if split:
            s.sendall(head)
            s.sendall(b"0\r\n\r\n")
        else:
            s.sendall(head + b"0\r\n\r\n")
        buf = b""
        while not buf.endswith(b"0\r\n\r\n"):
            buf += s.recv(65536)
        times.append((time.perf_counter() - t) * 1e3)
    s.close()
    print(f"split={split!s:5s} nodelay={nodelay!s:5s}: " + " ".join(f"{x:.0f}" for x in times) + " ms")


run(False, False)
run(True, False)
run(True, True)
