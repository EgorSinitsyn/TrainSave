# TrainSafe
TrainSafe — это система, обеспечивающая безопасность данных и предотвращение несанкционированного доступа к базе данных, с поддержкой двухфакторной аутентификации (2FA). Проект реализован с использованием Python, Flask, MySQL, Docker и Kubernetes. Разработка предназначена для развертывания в облачной инфраструктуре Yandex Cloud.


## Описание

### Основные задачи ПО
1.  Игнорирование запросов к БД, исходящих от устройств, которые не принадлежат внутренней корпоративной сети.
2.	Перехват запросов к базе данных — модуль должен перехватывать все SQL-запросы, направляемые от сотрудников заказчика к базе данных MySQL, для их последующей проверки.
3.	Проверка прав доступа — после перехвата запросов происходит идентификация сотрудника и одновременно с этим проверяется, имеет ли он, соответствующие права доступа для выполнения данной операции (чтение, запись, изменение или удаление данных). Проверка основана на политике безопасности, заранее определенной заказчиком, с учетом уровня доступа конкретного пользователя.
4.	Решение о передаче запроса — в случае успешного прохождения авторизации,проверки прав доступа, и 2FA запрос передается в MySQL для исполнения. Если проверка неуспешна, запрос блокируется, а сотрудник получает сообщение об отказе в выполнении операции с указанием причины.
5.	Логирование событий — модуль должен обеспечивать подробное логирование всех действий, связанных с обращениями к базе данных. 


### Создание docker-образов
```bash
docker build -t server_module ./server
docker build -t request_service_module ./request_service
docker build -t two_factor_service_module ./two_factor_service
```
### Применение 
```bash
docker-compose up --build
```

### Применение манифестов Kubernetes
1. Старт Minikube
```bash
minikube start --cpus=4 --memory=5192
```
2. Проверяем запуск кластера
```bash
kubectl cluster-info
```
3. Применение ConfigMap
```bash
kubectl apply -f app-config.yaml
```
4. Применение деплойментов
```bash
kubectl apply -f ./server/server-deployment.yaml
kubectl apply -f ./request_service/request-service-deployment.yaml
kubectl apply -f ./two_factor_service/two-factor-service-deployment.yaml
```
5. Применение сервисов
```bash
kubectl apply -f ./server/server-service.yaml
kubectl apply -f ./request_service/request-service-service.yaml
kubectl apply -f ./two_factor_service/two-factor-service-service.yaml
```
6. Связываем локальный Docker с Minikube
```bash
eval $(minikube docker-env)
```
7. Создаем образы (обязательно выполнить пред команду)
```bash
docker build -t server_module ./server
docker build -t request_service_module ./request_service
docker build -t two_factor_service_module ./two_factor_service
```
8. Они обязательно должны отобразиться в Minikube
```bash
eval $(minikube docker-env)
docker images
```
9. Стягиваем образы в Minikube
```bash
minikube image load server_module:latest                                              
minikube image load request_service_module:latest
minikube image load two_factor_service_module:latest
```
10. Проверяем статус подов (должно быть running) и сервисов
```bash
kubectl get pods
kubectl get svc
```
11. Проброс локального хоста в Minikube
```bash
kubectl port-forward service/server-service 6000:6000
```
12. Делаем запросы на localhost:6000
