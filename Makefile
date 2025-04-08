APP_NAME="media_streamer"
PATH_LOCAL=$(CURDIR)
PORT=5000

run_local:
	python webplayer.py

lint:
	pip install ruff==0.11.2
	ruff check --fix .
	ruff format .

test:
	pip install pytest==8.3.5 pytest-html==4.1.1
	PYTHONPATH=. pytest tests -v --html=report.html

deploy_headless:
	docker build --no-cache -t ${APP_NAME} .
	docker run --network=host --name ${APP_NAME} -dit -p ${PORT}:${PORT} -v ${PATH_LOCAL}/downloads:/app/downloads ${APP_NAME}

restart_docker:
	docker stop ${APP_NAME} || true
	docker rm ${APP_NAME} || true
	docker system prune -f
	git pull
	make deploy_headless
