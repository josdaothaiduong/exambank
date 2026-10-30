@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   ExamBank AI - Sua loi [ban 2: tu ghi file]
echo ============================================
echo.

if not exist 0001.b64.txt (
  echo [LOI] Thieu file 0001.b64.txt - hay bo file do vao cung
  echo thu muc voi file .bat nay roi chay lai.
  pause
  exit /b 1
)

echo [1/5] Tu ghi file cai dat chuan vao dung cho...
echo ===== ghi file 0001 + kiem chung ===== > fix-log.txt
powershell -NoProfile -Command "[IO.File]::WriteAllBytes('apps\api\migrations\versions\0001_initial.py', [Convert]::FromBase64String((Get-Content '0001.b64.txt' -Raw)))"
findstr /C:"ti le do kho" apps\api\migrations\versions\0001_initial.py >nul
if errorlevel 1 (
  echo Ghi file THAT BAI - file van chua dung >> fix-log.txt
  echo [LOI] Khong ghi duoc file moi. Gui fix-log.txt cho Muse.
  pause
  exit /b 1
)
echo Da ghi file moi va kiem chung OK >> fix-log.txt
certutil -hashfile apps\api\migrations\versions\0001_initial.py MD5 >> fix-log.txt 2>&1

echo [2/5] Xoa cache dung cu + tat he thong...
echo ===== docker builder prune + compose down ===== >> fix-log.txt
docker builder prune -f >> fix-log.txt 2>&1
docker compose down >> fix-log.txt 2>&1

echo [3/5] Dung lai phan xu ly tu code moi...
echo ===== docker compose build --no-cache api worker ===== >> fix-log.txt
docker compose build --no-cache api worker >> fix-log.txt 2>&1
if errorlevel 1 (
  echo [LOI] Buoc dung lai that bai. Gui fix-log.txt cho Muse.
  pause
  exit /b 1
)

echo [4/5] Khoi dong lai toan bo he thong...
echo ===== docker compose up -d ===== >> fix-log.txt
docker compose up -d >> fix-log.txt 2>&1

echo [5/5] Cho API san sang [co the toi vai phut]...
powershell -NoProfile -Command "$ok=$false; 1..120 | ForEach-Object { if(-not $ok){ try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/health; if($r.StatusCode -eq 200){ $ok=$true } } catch { Start-Sleep -Seconds 2 } } }; if($ok){ exit 0 } else { exit 1 }"
set HEALTH=%ERRORLEVEL%

echo ===== docker compose ps -a ===== >> fix-log.txt
docker compose ps -a >> fix-log.txt 2>&1
echo ===== docker compose logs api --tail 80 ===== >> fix-log.txt
docker compose logs api --tail 80 >> fix-log.txt 2>&1

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
  echo   Hay gui file fix-log.txt trong thu muc nay cho Muse.
  echo ============================================
)
pause
