#!/usr/bin/env bash
# 在目标机上（root）运行，代码已由 push.sh 放进 /opt/gugu-channel-adapter。
# 用法: install.sh <profile>=<bind>:<port>[@<socks5 host>:<port>] ...
#   例: install.sh hapi-gemini=172.19.0.1:18770 4router-gemini=172.19.0.1:18771
#       install.sh glm-gateway=172.19.0.1:18772@172.19.0.1:18443   # 上游只能经这个 SOCKS5 出口到达
# 逐个实例切换；某个实例探测失败 → 立刻把旧 shim 服务拉回来并退出非 0。
set -euo pipefail
ROOT=/opt/gugu-channel-adapter
ETC=/etc/gugu-channel-adapter
# 迁移期：profile → 旧的手工 shim 服务名（用完这张表可删）
declare -A LEGACY=( [hapi-gemini]=gugu-gemini-shim [4router-gemini]=gugu-gemini-shim-4router )

install -m 644 "$ROOT/deploy/gugu-channel-adapter@.service" /etc/systemd/system/gugu-channel-adapter@.service
mkdir -p "$ETC"
systemctl daemon-reload

probe() { # bind port → 0 表示适配器能把请求带到上游并拿回响应（非 5xx）
  python3 - "$1" "$2" <<'PY'
import http.client, sys
c = http.client.HTTPConnection(sys.argv[1], int(sys.argv[2]), timeout=15)
c.request("GET", "/v1/models", headers={"Authorization": "Bearer probe"})
s = c.getresponse().status
print("   探测 HTTP", s)
sys.exit(0 if s < 500 else 1)
PY
}

for spec in "$@"; do
  prof=${spec%%=*}; rest=${spec#*=}; addr=${rest%%@*}; bind=${addr%:*}; port=${addr##*:}
  socks=; [ "$rest" = "$addr" ] || socks=${rest#*@}
  [ -f "$ROOT/profiles/$prof.json" ] || { echo "没有 profile: $prof"; exit 2; }
  printf 'BIND=%s\nPORT=%s\n' "$bind" "$port" > "$ETC/$prof.env"
  [ -z "$socks" ] || printf 'UPSTREAM_SOCKS5=%s\n' "$socks" >> "$ETC/$prof.env"
  old=${LEGACY[$prof]:-}
  echo "[$prof] $bind:$port"
  if [ -n "$old" ] && systemctl is-active --quiet "$old"; then
    echo "   停旧服务 $old（保留单元文件，可回滚）"; systemctl disable --now "$old"
  fi
  systemctl enable "gugu-channel-adapter@$prof"
  systemctl restart "gugu-channel-adapter@$prof"   # 已在跑的实例也要重启才会加载新代码
  sleep 1
  if ! systemctl is-active --quiet "gugu-channel-adapter@$prof" || ! probe "$bind" "$port"; then
    echo "   ✗ 失败，回滚"; systemctl disable --now "gugu-channel-adapter@$prof" || true
    [ -n "$old" ] && systemctl enable --now "$old"
    exit 1
  fi
  echo "   ✓ gugu-channel-adapter@$prof active"
done
