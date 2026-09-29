//go:build dpumesh

package main

import (
	"net"

	"dmeshgo/dmeshgrpc"
)

// Built with -tags dpumesh, gRPC runs over DPUMesh when DPUMESH_ENABLE=1.
func dpumeshListen(addr string) (net.Listener, error) { return dmeshgrpc.Listen(addr) }
