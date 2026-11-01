#!/bin/sh
# Rebuild only pinned Toolbox Oracle source/tool, with pure-Go driver and bounded transport.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
GO_IMAGE=golang:1.26.2-bookworm@sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19
TOOLBOX_COMMIT=b0010060a939455d91e4f8ba62dc3e72b1892469
BUILD_NAME=fs-oracle-build-20261101-$$
trap 'docker rm -f "$BUILD_NAME" >/dev/null 2>&1 || true' EXIT
docker run --name "$BUILD_NAME" --cpus 1 --memory 2g --label flow-steward.audit=oracle-20261101 \
 -e PATCH_CONTENT="$(cat "$ROOT/scripts/patches/0001-flowsteward-oracle-safety.patch")" \
 -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -e GO_IMAGE="$GO_IMAGE" -e TOOLBOX_COMMIT="$TOOLBOX_COMMIT" \
 -v flow-steward-db-batch-go-cache:/go/pkg/mod -v flow-steward-db-batch-build-cache:/root/.cache/go-build \
 "$GO_IMAGE" sh -c '
 set -eu
 git clone --quiet --filter=blob:none --branch v1.3.0 --depth 1 https://github.com/googleapis/mcp-toolbox.git /src
 test "$(git -C /src rev-parse HEAD)" = "$TOOLBOX_COMMIT"
 cd /src
 printf "%s\n" "$PATCH_CONTENT" > /tmp/oracle.patch
 git apply /tmp/oracle.patch
 awk '\''/internal\/(sources|tools)\// { if ($2 ~ /github.com\/googleapis\/mcp-toolbox\/internal\/(sources\/oracle|tools\/oracle\/oraclesql)\"$/) print; next } {print}'\'' cmd/internal/imports.go > /tmp/imports.go
 test "$(grep -c "internal/\(sources\|tools\)/" /tmp/imports.go)" = 2
 mv /tmp/imports.go cmd/internal/imports.go
 gofmt -w internal/sources/oracle/*.go internal/tools/oracle/oraclesql/*.go
 go test -p 1 ./internal/sources/oracle ./internal/tools/oracle/oraclesql
 export SOURCE_DATE_EPOCH=1779400183
 for arch in amd64 arm64; do
  mkdir -p "/out/bin/linux-$arch"
  CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -p 1 -trimpath -buildvcs=false -ldflags "-s -w -buildid= -X github.com/googleapis/mcp-toolbox/cmd.buildType=flowsteward.oracle -X github.com/googleapis/mcp-toolbox/cmd.commitSha=$TOOLBOX_COMMIT" -o "/out/bin/linux-$arch/toolbox" .
  chmod 0755 "/out/bin/linux-$arch/toolbox"
  chown "$HOST_UID:$HOST_GID" "/out/bin/linux-$arch/toolbox"
  echo "[PASS] linux-$arch native build"
 done
 '
mkdir -p "$ROOT/bin"
docker cp "$BUILD_NAME:/out/bin/." "$ROOT/bin/"
python3 "$ROOT/scripts/provenance.py"
