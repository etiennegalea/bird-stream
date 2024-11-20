# Use a Node.js image for building
FROM node:18 as build

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install dependencies and build the React app
RUN npm install && npm run build

# Use a lightweight server to serve the built files
FROM nginx:alpine

# Copy the React build to the nginx web server
COPY --from=build /app/build /usr/share/nginx/html

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
