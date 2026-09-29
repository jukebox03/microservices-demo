//go:build !dpumesh

package main

import "google.golang.org/grpc"

func dpumeshDialOptions() []grpc.DialOption { return nil }
