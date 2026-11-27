#!/bin/sh
set -eu

# 该脚本由 nginx 官方 entrypoint 在 envsubst 之前执行。管理机器凭据只会进入
# nginx 生成后的服务端配置；Basic Auth 密码只会进入 htpasswd 哈希文件。
if [ "${ADMIN_API_TOKEN:-}" = "" ] || [ "${#ADMIN_API_TOKEN}" -lt 24 ]; then
    echo >&2 "ERROR: ADMIN_API_TOKEN must be at least 24 characters"
    exit 1
fi
if [ "${ADMIN_UI_PASSWORD:-}" = "" ] || [ "${#ADMIN_UI_PASSWORD}" -lt 16 ]; then
    echo >&2 "ERROR: ADMIN_UI_PASSWORD must be at least 16 characters"
    exit 1
fi
if [ "$ADMIN_UI_PASSWORD" = "$ADMIN_API_TOKEN" ]; then
    echo >&2 "ERROR: ADMIN_UI_PASSWORD must be different from ADMIN_API_TOKEN"
    exit 1
fi

case "$ADMIN_UI_PASSWORD" in
    *'$'*)
        echo >&2 "ERROR: ADMIN_UI_PASSWORD must not contain a dollar sign"
        exit 1
        ;;
esac

umask 077
htpasswd -bcB /etc/nginx/admin.htpasswd admin "$ADMIN_UI_PASSWORD" >/dev/null
# nginx worker 以 nginx 用户运行，而 umask 077 生成的文件是 root:root 600，worker 读不到，
# 所有后台保存接口会 500 Permission denied。改为 root:nginx + 640：仅放开属组读，保留 077 的安全意图。
chown root:nginx /etc/nginx/admin.htpasswd
chmod 640 /etc/nginx/admin.htpasswd
unset ADMIN_UI_PASSWORD
