# Use the official lightweight Nginx image
FROM nginx:alpine

COPY ./infrastructure/documentation/nginx.conf.template /tmp/nginx.conf.template
COPY ./infrastructure/documentation/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]