@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   ExamBank AI - Khoi dong he thong
echo ============================================
echo.

docker --version >nul 2>&1
if errorlevel 1 (
  echo [LOI] Chua tim thay Docker. Hay cai Docker Desktop truoc:
  echo       https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [LOI] Docker Desktop chua chay. Hay mo Docker Desktop,
  echo       doi icon ca voi ngung nhay [trang thai Running] roi chay lai file nay.
  pause
  exit /b 1
)

if not exist .env (
  echo Tao file cau hinh .env tu ban mau...
  copy .env.example .env >nul
  echo Da tao .env - mac dinh chay duoc ngay [AI o che do demo].
  echo Muon AI giai de that bang Gemini: mo file .env va dien AI_API_KEY
  echo theo huong dan trong RUN-ON-WINDOWS.md, muc 5.
  echo.
)

echo Dang dung va khoi dong he thong [lan dau co the mat 5-10 phut]...
docker compose up -d --build
if errorlevel 1 (
  echo [LOI] Khoi dong that bai. Chup man hinh loi nay gui cho Muse xem giup.
  pause
  exit /b 1
)

echo.
echo Cho he thong san sang...
timeout /t 15 /nobreak >nul
echo Mo trinh duyet tai http://localhost:3000 ...
start http://localhost:3000
echo.
echo ============================================
echo   Da xong! He thong chay tai http://localhost:3000
echo   Tat he thong: chay file stop-exambank.bat
echo   [Du lieu van duoc giu nguyen khi tat/mo lai]
echo ============================================
pause
