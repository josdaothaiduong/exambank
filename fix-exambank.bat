@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   ExamBank AI - Sua loi khoi dong [tu dong]
echo ============================================
echo.
echo Qua trinh nay mat khoang 3-6 phut. Dung dong cua so giua chung.
echo Moi buoc deu duoc ghi vao file fix-log.txt de gui Muse neu can.
echo.

echo [1/4] Xoa cac container cu...
echo ===== docker compose down ===== > fix-log.txt
docker compose down >> fix-log.txt 2>&1

echo [2/4] Dung lai phan xu ly tu code moi [khong dung cache]...
echo ===== docker compose build --no-cache api worker ===== >> fix-log.txt
docker compose build --no-cache api worker >> fix-log.txt 2>&1
if errorlevel 1 (
  echo.
  echo [LOI] Buoc dung lai that bai. Hay gui file fix-log.txt
  echo trong thu muc nay cho Muse xem giup.
  pause
  exit /b 1
)

echo [3/4] Khoi dong lai toan bo he thong...
echo ===== docker compose up -d ===== >> fix-log.txt
docker compose up -d >> fix-log.txt 2>&1

echo [4/4] Cho API san sang [toi da 3 phut]...
powershell -NoProfile -Command "$ok=$false; 1..90 | ForEach-Object { if(-not $ok){ try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/health; if($r.StatusCode -eq 200){ $ok=$true } } catch { Start-Sleep -Seconds 2 } } }; if($ok){ exit 0 } else { exit 1 }"
set HEALTH=%ERRORLEVEL%

echo ===== docker compose ps ===== >> fix-log.txt
docker compose ps >> fix-log.txt 2>&1
echo ===== docker compose logs api --tail 80 ===== >> fix-log.txt
docker compose logs api --tail 80 >> fix-log.txt 2>&1
echo ===== docker compose logs worker --tail 20 ===== >> fix-log.txt
docker compose logs worker --tail 20 >> fix-log.txt 2>&1

if "%HEALTH%"=="0" (
  echo.
  echo ============================================
  echo   THANH CONG! API da san sang.
  echo   Dang mo trang http://localhost:3000 ...
  echo ============================================
  start http://localhost:3000
) else (
  echo.
  echo ============================================
  echo   API van chua len duoc.
  echo   Hay gui file fix-log.txt trong thu muc nay
  echo   cho Muse - moi thong tin can thiet deu o trong do.
  echo ============================================
)
pause
