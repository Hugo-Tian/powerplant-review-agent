@echo off
docker exec power-plant-final-db-1 psql -U ims_user -d power_plant_ims -c "TRUNCATE TABLE push_results, push_configs, user_profiles, user_behaviors, nlp_extract_jobs, event_tags, event_attachments, events, tags, users, departments, units, plants, device_models CASCADE;"
echo Done.
pause
