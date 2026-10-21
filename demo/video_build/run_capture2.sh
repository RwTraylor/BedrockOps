#!/bin/bash
set -u
cd ~/workspace/BedrockOps
export AWS_EC2_METADATA_DISABLED=true
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export no_proxy="127.0.0.1,localhost"
export NO_PROXY="127.0.0.1,localhost"
PY=.venv/bin/python
$PY -u server.py > demo/video_build/server2.log 2>&1 &
SRV=$!
echo "server pid $SRV"
for i in $(seq 1 40); do
  if $PY -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read().decode())" 2>/dev/null; then echo "health ok $i"; break; fi
  sleep 0.5
done
$PY -u demo/demo_client.py > demo/video_build/demo_output2.txt 2>&1
echo "DEMO_EXIT=$?" >> demo/video_build/demo_output2.txt
kill $SRV 2>/dev/null || true
wait $SRV 2>/dev/null || true
cat demo/video_build/demo_output2.txt
