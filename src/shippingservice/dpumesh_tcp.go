//go:build !dpumesh

package main

import "net"

func dpumeshListen(addr string) (net.Listener, error) { return net.Listen("tcp", addr) }
