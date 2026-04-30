@echo off
REM Wrapper invocado pelo Windows Task Scheduler para rodar 1 ciclo do pipeline.
REM Logs do wrapper (incluindo erros de bootstrap antes do logger Python iniciar)
REM vao para logs\task_scheduler_wrapper.log; logs do pipeline ficam em
REM logs\scheduler.log (escritos por run_scheduled_pipeline em scheduler.py).

cd /d "C:\Users\Lucas\Documents\automation\automation_nanobot"

set PYTHONIOENCODING=utf-8

REM Executa via venv local.
".venv\Scripts\python.exe" -m ufpr_automation --schedule --once >> "logs\task_scheduler_wrapper.log" 2>&1

exit /b %ERRORLEVEL%
