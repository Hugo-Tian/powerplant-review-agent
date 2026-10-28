@echo off
docker exec -i power-plant-final-db-1 psql -U ims_user -d power_plant_ims < "%~dp0demo_data.sql"
echo Done.
pause
