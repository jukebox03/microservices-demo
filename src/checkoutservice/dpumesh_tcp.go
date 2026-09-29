//go:build !dpumesh

package main

import (
	"net"

	"google.golang.org/grpc"
)

func dpumeshListen(addr string) (net.Listener, error) { return net.Listen("tcp", addr) }
func dpumeshDialOptions() []grpc.DialOption           { return nil }
