FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css app.js /usr/share/nginx/html/

RUN apk add --no-cache curl \
 && mkdir -p /usr/share/nginx/html/vendor \
 && curl -fsSL -o /usr/share/nginx/html/vendor/three.min.js \
      https://unpkg.com/three@0.128.0/build/three.min.js \
 && curl -fsSL -o /usr/share/nginx/html/vendor/STLLoader.js \
      https://unpkg.com/three@0.128.0/examples/js/loaders/STLLoader.js \
 && curl -fsSL -o /usr/share/nginx/html/vendor/OrbitControls.js \
      https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js \
 && chmod -R a+rX /usr/share/nginx/html /etc/nginx/conf.d

EXPOSE 80
