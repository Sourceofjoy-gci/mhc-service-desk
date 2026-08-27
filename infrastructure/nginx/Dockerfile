# syntax=docker/dockerfile:1.7
FROM nginx:1.28.3-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
RUN mkdir -p /etc/nginx/snippets
COPY snippets/proxy-headers.conf /etc/nginx/snippets/proxy-headers.conf
COPY conf.d/app.conf /etc/nginx/templates/app.conf.template
