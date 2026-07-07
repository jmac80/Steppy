FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js /usr/share/nginx/html/
RUN chmod -R a+rX /usr/share/nginx/html /etc/nginx/conf.d
EXPOSE 80
