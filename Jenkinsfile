pipeline {
    agent any

    environment {
        WORKSPACE_DIR = "${WORKSPACE}"
    }

    stages {

        stage("Determine Environment") {
            steps {
                script {

                    echo "Branch: ${env.BRANCH_NAME}"

                    if (env.BRANCH_NAME == "main") {

                        env.DEPLOY_ENV = "production"

                        env.SERVER_ROOT = "/var/www/ay-lms-python-L"
                        env.PROJECT_DIR = "/var/www/ay-lms-python-L/Aryu"

                        env.VENV_PY  = "/var/www/ay-lms-python-L/venv/bin/python"
                        env.VENV_PIP = "/var/www/ay-lms-python-L/venv/bin/pip"

                        env.SERVICE_NAME = "aylms.service"

                    } else if (env.BRANCH_NAME == "staging") {

                        env.DEPLOY_ENV = "staging"

                        env.SERVER_ROOT = "/var/www/python-staging"
                        env.PROJECT_DIR = "/var/www/python-staging/Aryu"

                        env.VENV_PY  = "/var/www/python-staging/venv/bin/python"
                        env.VENV_PIP = "/var/www/python-staging/venv/bin/pip"

                        env.SERVICE_NAME = "gunicorn-aryu-staging.service"

                    } else {

                        error "Unsupported branch '${env.BRANCH_NAME}'. Deployment stopped."

                    }

                    echo "=========================================="
                    echo "Environment : ${env.DEPLOY_ENV}"
                    echo "Branch      : ${env.BRANCH_NAME}"
                    echo "Server root : ${env.SERVER_ROOT}"
                    echo "Project dir : ${env.PROJECT_DIR}"
                    echo "Python      : ${env.VENV_PY}"
                    echo "Service     : ${env.SERVICE_NAME}"
                    echo "=========================================="
                }
            }
        }

        stage("Sync Code") {
            steps {
                sh '''
                    rsync -rlvz --delete \
                        --exclude "media/" \
                        --exclude "static/" \
                        --exclude "*.log" \
                        --exclude "__pycache__/" \
                        "${WORKSPACE_DIR}/Aryu/" \
                        "${PROJECT_DIR}/"
                '''
            }
        }

        stage("Install Dependencies") {
            steps {
                sh '''
                    "${VENV_PIP}" install \
                        -r "${WORKSPACE_DIR}/Aryu/requirements.txt"
                '''
            }
        }

        stage("Django Check") {
            steps {
                sh '''
                    "${VENV_PY}" \
                        "${PROJECT_DIR}/manage.py" check
                '''
            }
        }

        stage("Migrate DB") {
            steps {
                sh '''
                    "${VENV_PY}" \
                        "${PROJECT_DIR}/manage.py" migrate --noinput
                '''
            }
        }

        stage("Collect Static") {
            steps {
                sh '''
                    "${VENV_PY}" \
                        "${PROJECT_DIR}/manage.py" collectstatic --noinput
                '''
            }
        }

        stage("Restart Service") {
            steps {
                sh '''
                    sudo systemctl restart "${SERVICE_NAME}"
                    sudo systemctl is-active --quiet "${SERVICE_NAME}"
                '''
            }
        }
    }

    post {
        success {
            echo "=========================================="
            echo " ${DEPLOY_ENV} deployment successful"
            echo " Directory: ${SERVER_ROOT}"
            echo " Service:   ${SERVICE_NAME}"
            echo "=========================================="
        }

        failure {
            echo "=========================================="
            echo " ${DEPLOY_ENV ?: 'UNKNOWN'} deployment FAILED"
            echo "=========================================="
        }
    }
}
