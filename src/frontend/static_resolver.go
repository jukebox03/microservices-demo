// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/resolver"
)

// A service address may list several backends, "host:port,host:port,...".
// The client then round-robins requests over them (mustConnGRPC), as it does
// over the pods of a headless Service. A single address is used unchanged.
const staticScheme = "static"

// staticTarget returns the gRPC target for addr and, for a list, the dial
// options it needs: the default :authority would be the whole list, which is
// not a valid HTTP/2 authority, so the first backend is used instead.
func staticTarget(addr string) (string, []grpc.DialOption) {
	if !strings.Contains(addr, ",") {
		return addr, nil
	}
	first := strings.TrimSpace(strings.SplitN(addr, ",", 2)[0])
	return staticScheme + ":///" + addr, []grpc.DialOption{grpc.WithAuthority(first)}
}

type staticBuilder struct{}

func (staticBuilder) Scheme() string { return staticScheme }

func (staticBuilder) Build(t resolver.Target, cc resolver.ClientConn, _ resolver.BuildOptions) (resolver.Resolver, error) {
	var addrs []resolver.Address
	for _, a := range strings.Split(t.Endpoint(), ",") {
		if a = strings.TrimSpace(a); a != "" {
			addrs = append(addrs, resolver.Address{Addr: a})
		}
	}
	return staticResolver{}, cc.UpdateState(resolver.State{Addresses: addrs})
}

type staticResolver struct{}

func (staticResolver) ResolveNow(resolver.ResolveNowOptions) {}
func (staticResolver) Close()                                {}

func init() { resolver.Register(staticBuilder{}) }
