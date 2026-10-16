package main

import (
	"os"
	"strconv"

	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// traceSampler: TRACE_SAMPLE_RATIO=<0..1> samples that fraction of new traces
// and follows the caller's decision otherwise; unset keeps AlwaysSample.
func traceSampler() sdktrace.Sampler {
	if v := os.Getenv("TRACE_SAMPLE_RATIO"); v != "" {
		if r, err := strconv.ParseFloat(v, 64); err == nil {
			return sdktrace.ParentBased(sdktrace.TraceIDRatioBased(r))
		}
	}
	return sdktrace.AlwaysSample()
}
