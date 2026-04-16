#!/bin/bash
## npm과 nginx가 설치되어 있다고 가정
## 설치 되어 있지 않다면 sudo apt update && sudo apt install -y nodejs npm

# 이 스크립트 파일은 sudo 권한으로 실행되면 안된다
# sudo 권한으로 실행되었다면 종료
if [ "$EUID" -eq 0 ]; then
  echo "Do not run as root"
  exit
fi

# 앱 이름을 인자로 받음
APP_NAME=$1

if [ -z "$APP_NAME" ]; then
  echo "Usage: $0 <app_name>"
  exit 1
fi

# 앱 디렉토리로 이동
cd "$APP_NAME"

# 빌드
npm install
npm run build

# 기존 빌드된 파일 삭제 및 새로 빌드된 파일 복사
sudo rm -rf /var/www/react/"$APP_NAME"
sudo mkdir -p /var/www/react/"$APP_NAME"
sudo cp -r dist/* /var/www/react/"$APP_NAME"

# 설정파일은 /etc/nginx/sites-available/react에 위치 (필요시 직접 수정 필요)
# 설정 활성화
sudo rm -f /etc/nginx/sites-enabled/react
sudo ln -s /etc/nginx/sites-available/react /etc/nginx/sites-enabled/

# Nginx 재시작
sudo systemctl restart nginx

echo "Build and deployment completed for $APP_NAME"
