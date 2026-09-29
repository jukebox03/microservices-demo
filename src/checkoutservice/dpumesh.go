//go:build dpumesh

package main

import (
	"net"

	"dmeshgo/dmeshgrpc"
	"google.golang.org/grpc"
)

// Built with -tags dpumesh, gRPC runs over DPUMesh when DPUMESH_ENABLE=1.
func dpumeshListen(addr string) (net.Listener, error) { return dmeshgrpc.Listen(addr) }
func dpumeshDialOptions() []grpc.DialOption           { return dmeshgrpc.DialOptions() }
