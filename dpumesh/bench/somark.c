/* LD_PRELOAD for the hostproxy baseline (perf.sh): mark linkerd2-proxy's own
 * outbound TCP connections so the namespace's REDIRECT rule skips them. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/socket.h>

int connect(int fd, const struct sockaddr *addr, socklen_t len) {
    static int (*real_connect)(int, const struct sockaddr *, socklen_t);
    if (!real_connect) real_connect = dlsym(RTLD_NEXT, "connect");
    if (addr && (addr->sa_family == AF_INET || addr->sa_family == AF_INET6)) {
        int mark = 0x2102;
        setsockopt(fd, SOL_SOCKET, SO_MARK, &mark, sizeof(mark));
    }
    return real_connect(fd, addr, len);
}
