//go:build dpumesh

package main

import (
	"dmeshgo/dmeshgrpc"
	"google.golang.org/grpc"
)

// Built with -tags dpumesh, gRPC runs over DPUMesh when DPUMESH_ENABLE=1.
func dpumeshDialOptions() []grpc.DialOption { return dmeshgrpc.DialOptions() }
