# The upstream Online Boutique user without think time: each user issues its
# next request as soon as the last one returns.
#
# geventhttpclient 2.4 sends a GET's headers and an empty chunked body in two
# writes. With Nagle on, the second write waits for the frontend's delayed
# ACK, and Go's HTTP server reads that body before writing its reply, so every
# GET page gains ~40 ms that no service spends. The client sockets therefore
# set TCP_NODELAY; LOCUST_NODELAY=0 keeps the upstream behavior.
import os
import socket
import sys

import geventhttpclient.connectionpool as pool

sys.path.insert(0, os.environ["OB_LOCUST_DIR"])
from locustfile import UserBehavior  # noqa: E402
from locust import FastHttpUser, constant  # noqa: E402

if os.environ.get("LOCUST_NODELAY", "1") == "1":
    _create = pool.ConnectionPool._create_tcp_socket

    def _create_nodelay(self, family, socktype, protocol):
        sock = _create(self, family, socktype, protocol)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    pool.ConnectionPool._create_tcp_socket = _create_nodelay


class ClosedLoopUser(FastHttpUser):
    tasks = [UserBehavior]
    wait_time = constant(0)
