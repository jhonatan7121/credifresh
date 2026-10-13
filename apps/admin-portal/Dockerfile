FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js
COPY favicon.svg /usr/share/nginx/html/favicon.svg
COPY reset-password.html /usr/share/nginx/html/reset-password.html
COPY config.template.js /etc/nginx/templates/config.js.template
COPY nginx-default.conf.template /etc/nginx/templates/default.conf.template
RUN rm -f /etc/nginx/conf.d/default.conf

ENV API_BASE_URL=http://localhost:8000 \
    PORT=10000 \
    NGINX_ENVSUBST_FILTER=^(PORT|API_BASE_URL)$

EXPOSE 80
