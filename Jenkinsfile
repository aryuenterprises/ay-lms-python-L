pipeline {
    agent any

    environment {
        WORKSPACE_DIR = "${WORKSPACE}"
        SERVER_ROOT   = "/var/www/ay-lms-python-L"
        SERVER_DIR    = "/var/www/ay-lms-python-L/Aryu"
        VENV_PIP      = "/var/www/ay-lms-python-L/venv/bin/pip"
        VENV_PY       = "/var/www/ay-lms-python-L/venv/bin/python"
        SERVICE_NAME  = "aylms.service"
    }

    stages {

        stage("Sync code to LIVE (rsync)") {
            steps {
                sh '''
                rsync -rlDvz --delete \
                --exclude "media/" \
                --exclude "static/" \
                --exclude "*.log" \
                --exclude "__pycache__/" \
                ${WORKSPACE_DIR}/Aryu/ ${SERVER_DIR}/
                '''
            }
        }

        stage("Install dependencies") {
            steps {
                sh "${VENV_PIP} install -r ${SERVER_ROOT}/requirements.txt"
            }
        }

        stage("Django check") {
            steps {
                sh "${VENV_PY} ${SERVER_DIR}/manage.py check"
            }
        }

        stage("Migrate DB") {
            steps {
                sh "${VENV_PY} ${SERVER_DIR}/manage.py migrate --noinput"
            }
        }

        stage("Collect static") {
            steps {
                sh "${VENV_PY} ${SERVER_DIR}/manage.py collectstatic --noinput"
            }
        }

        stage("Restart LIVE service") {
            steps {
                sh "sudo systemctl restart ${SERVICE_NAME}"
            }
        }
    }
}

