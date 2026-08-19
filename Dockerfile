FROM node:22

WORKDIR /app

COPY frontend/package*.json ./

RUN npm ci
EXPOSE 5500

CMD ["npx", "serve", ".", "-l", "5500"]