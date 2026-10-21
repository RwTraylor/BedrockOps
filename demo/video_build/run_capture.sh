#!/bin/bash
set -u
cd ~/workspace/BedrockOps
export AWS_EC2_METADATA_DISABLED=true
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY
PY=.venv/bin/python
echo "=== TESTS ===" > demo/video_build/capture.txt
$PY -m unittest tests/test_mcp.py >> demo/video_build/capture.txt 2>&1
echo "TEST_EXIT=$?" >> demo/video_build/capture.txt
$PY server.py > demo/video_build/server.log 2>&1 &
SRV=$!
echo "server pid $SRV"
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then echo "health ok $i"; break; fi
  sleep 0.5
done
curl -s http://127.0.0.1:8000/health || true
echo ""
$PY demo/demo_client.py > demo/video_build/demo_output.txt 2>&1
echo "DEMO_EXIT=$?" >> demo/video_build/demo_output.txt
kill $SRV 2>/dev/null || true
wait $SRV 2>/dev/null || true
cat demo/video_build/demo_output.txt
