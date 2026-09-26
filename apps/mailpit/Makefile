.DEFAULT_GOAL := help

.PHONY: help config preload up verify smoke logs status down

help:
	@printf '%s\n' \
	  'Secure MOM Mailpit commands:' \
	  '  make config   Validate the Compose configuration.' \
	  '  make preload  Download the pinned image while online.' \
	  '  make up       Start Mailpit without pulling an image.' \
	  '  make verify   Start and verify local Mailpit readiness.' \
	  '  make smoke    Send a non-sensitive SMTP test message.' \
	  '  make logs     Show recent Mailpit logs.' \
	  '  make status   Show container status.' \
	  '  make down     Stop Mailpit while retaining captured mail.'

config:
	docker compose config

preload:
	docker compose pull
	docker image inspect axllent/mailpit:v1.31.2 >/dev/null

up:
	docker compose up -d --pull never

verify:
	sh ./scripts/verify.sh

smoke:
	python3 ./scripts/send_smoke_email.py

logs:
	docker compose logs --tail=100 mailpit

status:
	docker compose ps

down:
	docker compose down
