# Use a Node.js image for building
FROM node:18 AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ARG VITE_API_URL
ARG VITE_NODE_ENV=production
ARG VITE_OPENRELAY_TURN_USERNAME
ARG VITE_OPENRELAY_TURN_CREDENTIAL
ENV VITE_API_URL=$VITE_API_URL \
    VITE_NODE_ENV=$VITE_NODE_ENV \
    VITE_OPENRELAY_TURN_USERNAME=$VITE_OPENRELAY_TURN_USERNAME \
    VITE_OPENRELAY_TURN_CREDENTIAL=$VITE_OPENRELAY_TURN_CREDENTIAL

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
