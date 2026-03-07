# SafePill 배포 가이드 (Render / Railway)

## 1) 먼저 알아둘 점
- 현재 프로젝트는 SQLite(`safepill.db`)를 사용합니다.
- **Render Free 웹 서비스는 로컬 파일시스템 변경사항을 보존하지 않습니다.** 즉, 회원/약통 데이터가 재배포나 재시작 뒤 유지되지 않을 수 있습니다.
- Render에서 SQLite를 유지하려면 **Persistent Disk가 필요하고, 이는 유료 플랜에서만 가능합니다.**
- Railway는 Docker 배포가 쉽고, 볼륨을 붙이면 파일 유지가 가능합니다.

## 2) 가장 현실적인 추천
### 발표/테스트용 빠른 배포
- **Railway + Dockerfile**
- 현재 코드 그대로 올리기 쉬움

### 무료로 공개 URL만 빨리 확인
- **Render Free + Dockerfile**
- 단, `safepill.db` 변경내용(회원/약통 저장)은 영구 보존되지 않을 수 있음

## 3) GitHub에 올릴 때
- `SafePill` 폴더 **안의 파일들**을 repo 루트에 올리는 것을 추천합니다.
- 즉, repo 최상단에 다음 파일들이 보이게 하면 편합니다.
  - `main.py`
  - `index_v2.html`
  - `services/`
  - `static/`
  - `safepill.db`
  - `Dockerfile`
  - `requirements.txt`
  - `render.yaml`

## 4) Render 배포
1. GitHub에 프로젝트 업로드
2. Render 대시보드에서 **New +** → **Web Service**
3. GitHub repo 연결
4. Dockerfile을 자동 감지하면 그대로 진행
5. Health Check Path는 `/healthz`
6. 배포 완료 후 공개 URL 접속

### 주의
- Free 웹 서비스는 15분 정도 유휴 상태면 절전(spin down)될 수 있습니다.
- 첫 접속이 조금 느릴 수 있습니다.

## 5) Railway 배포
1. GitHub에 프로젝트 업로드
2. Railway → **New Project** → GitHub repo 선택
3. Dockerfile 자동 인식되면 그대로 배포
4. Deploy 완료 후 제공 URL 접속

### 권장
- Railway에서 **Volume**을 추가하면 SQLite 유지에 유리합니다.
- Volume을 쓴다면 `safepill.db` 경로를 고정하는 추가 작업이 필요할 수 있습니다.

## 6) 배포 후 접속 방식
- PC / 휴대폰 모두 **공개 URL**로 접속
- 휴대폰 브라우저에서 **홈 화면에 추가**하면 앱처럼 사용 가능

## 7) 지금 파일 중 꼭 필요한 배포용 파일
- `Dockerfile`
- `requirements.txt`
- `render.yaml`
- `.dockerignore`

## 8) 로컬 테스트는 기존대로 가능
```bash
python run_server.py
```
또는
```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

## 9) 실제 배포용 실행은 Dockerfile 안에서 자동 처리
```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```
