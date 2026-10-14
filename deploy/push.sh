#!/usr/bin/env bash
# 在开发机上运行: 先跑测试，再把代码送上目标机并切换服务。
# 用法: deploy/push.sh <ssh 主机别名> <docker 网桥 IP>
#   预发 ali2 → 172.19.0.1    生产 ali1 → 172.20.0.1（生产须 owner 授权）
set -euo pipefail
HOST=${1:?ssh 主机别名}; BIND=${2:?网桥 IP}
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m unittest discover -s tests >/dev/null 2>&1 || { echo "测试未通过，不部署"; exit 1; }
ssh "$HOST" 'rm -rf /opt/gugu-channel-adapter/src /opt/gugu-channel-adapter/profiles /opt/gugu-channel-adapter/deploy && mkdir -p /opt/gugu-channel-adapter'
tar -cf - src profiles deploy | ssh "$HOST" 'tar -C /opt/gugu-channel-adapter -xf -'
ssh "$HOST" "bash /opt/gugu-channel-adapter/deploy/install.sh hapi-gemini=$BIND:18770 4router-gemini=$BIND:18771"
