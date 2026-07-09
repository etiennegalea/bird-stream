# Use a Node.js image for building
FROM node:18 AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ARG VITE_API_URL
ARG VITE_NODE_ENV=production
ARG VITE_HLS_FALLBACK=true
ENV VITE_API_URL=$VITE_API_URL \
    VITE_NODE_ENV=$VITE_NODE_ENV \
    VITE_HLS_FALLBACK=$VITE_HLS_FALLBACK

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
# Static SPA config; traefik in front handles TLS and /api routing.
COPY nginx.default.conf.template /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
