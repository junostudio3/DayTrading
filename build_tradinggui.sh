#!/bin/bash
# tradinggui 앱을 빌드하고 배포합니다.

# 스크립트의 현재 디렉토리 저장
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 공통 빌드 스크립트 실행
exec "$SCRIPT_DIR/build_common.sh" tradinggui