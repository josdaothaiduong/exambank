@echo off
chcp 65001 >nul
cd /d %~dp0
echo Dang tat ExamBank AI [du lieu ngan hang de van duoc giu nguyen]...
docker compose down
echo Da tat xong. Mo lai bang start-exambank.bat bat cu luc nao.
pause
