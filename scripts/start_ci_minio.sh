#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP must point to the disposable CI directory}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"

# Upstream no longer distributes the community container or binary releases.
export GOBIN="$RUNNER_TEMP/minio-bin"
go install github.com/minio/minio@RELEASE.2024-07-31T05-46-26Z

nohup "$GOBIN/minio" server "$RUNNER_TEMP/minio-data" \
  --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 \
  > "$RUNNER_TEMP/minio.log" 2>&1 &
minio_pid=$!
echo "$minio_pid" > "$RUNNER_TEMP/minio.pid"

for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:9000/minio/health/ready; then
    echo "MinIO is ready."
    exit 0
  fi
  if ! kill -0 "$minio_pid" 2>/dev/null; then
    break
  fi
  sleep 2
done

cat "$RUNNER_TEMP/minio.log"
exit 1
